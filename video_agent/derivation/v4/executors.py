from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from video_agent.ai.gpt_image import edit_image
from video_agent.assets.v4.derivation_orchestrator import (
    DerivationCapabilityBinding,
    DerivationResultDraft,
    PreparedDerivation,
    build_derivation_signature,
)
from video_agent.assets.v4.repository import AssetDraft, AssetResolutionSession
from video_agent.assets.v4.stage4_errors import Stage4Error
from video_agent.contracts.v4 import (
    AssetLineage,
    DerivationEntry,
    EvidenceClass,
    RelationPatternEntry,
    SourceKind,
)
from video_agent.contracts.v4.resolved_assets import DerivationRequest
from video_agent.derivation.v4.prompt_composer import compose_derivation_prompt
from video_agent.derivation.v4.sizing import target_size_for_orientation
from video_agent.io import write_json_atomic
from video_agent.registries import CapabilityRegistryHub

_CANVAS = (1080, 1920)


def _evidence_from_class(value: str) -> EvidenceClass:
    if value.startswith("E1"):
        return EvidenceClass.FAITHFUL
    if value.startswith("E0"):
        return EvidenceClass.SOURCE
    if value.startswith("E3"):
        return EvidenceClass.DECORATIVE
    return EvidenceClass.SEMANTIC


def _resolve_object_path(session: AssetResolutionSession, asset_ref: str, *, scene_id: str, slot_id: str) -> Path:
    asset = session.get_asset(asset_ref)
    if asset is None:
        raise Stage4Error("derivation_failed", f"asset missing: {asset_ref}", scene_id=scene_id, slot_id=slot_id)
    object_store = getattr(session.repository, "object_store", None)
    if object_store is None:
        raise Stage4Error("derivation_failed", "repository has no object_store", scene_id=scene_id, slot_id=slot_id)
    return object_store.resolve(asset.object_key)


def _fit_paste(source: Path, output: Path, *, canvas: tuple[int, int] = _CANVAS) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        frame = Image.new("RGB", canvas, (7, 10, 14))
        scale = min((canvas[0] - 80) / image.width, (canvas[1] - 220) / image.height)
        resized = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
        x = (canvas[0] - resized.width) // 2
        y = 160 + ((canvas[1] - 220) - resized.height) // 2
        frame.paste(resized, (x, y))
        frame.save(output, format="PNG")


def _normalize_orientation(source: Path, output: Path, orientation: str | None) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        if orientation == "portrait" and image.width > image.height:
            image = ImageOps.contain(image, (1080, 1920), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (1080, 1920), (7, 10, 14))
            canvas.paste(image, ((1080 - image.width) // 2, (1920 - image.height) // 2))
            canvas.save(output, format="PNG")
            return
        if orientation == "landscape" and image.height > image.width:
            image = ImageOps.contain(image, (1920, 1080), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (1920, 1080), (7, 10, 14))
            canvas.paste(image, ((1920 - image.width) // 2, (1080 - image.height) // 2))
            canvas.save(output, format="PNG")
            return
        image.save(output, format="PNG")


def _sequence_variant(source: Path, output: Path, stage: str) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        if stage == "base":
            image.save(output, format="PNG")
            return
        if stage == "stage":
            enhanced = ImageEnhance.Contrast(image).enhance(1.08)
            enhanced = ImageEnhance.Color(enhanced).enhance(1.05)
            enhanced.save(output, format="PNG")
            return
        # final: slight sharpen settle
        settled = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=80, threshold=2))
        settled.save(output, format="PNG")


def _combined_panels(paths: list[Path], output: Path) -> Path:
    if len(paths) == 1:
        return paths[0]
    panel_w, panel_h = 1024, 1024
    canvas = Image.new("RGB", (panel_w * len(paths), panel_h), (12, 15, 20))
    for index, path in enumerate(paths):
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            image.thumbnail((panel_w - 32, panel_h - 56), Image.Resampling.LANCZOS)
            x = index * panel_w + (panel_w - image.width) // 2
            y = 40 + (panel_h - 40 - image.height) // 2
            canvas.paste(image, (x, y))
    canvas.save(output, format="PNG")
    return output


def _write_run_artifacts(
    *,
    run_dir: Path | None,
    request: DerivationRequest,
    prepared: PreparedDerivation,
    prompt_text: str | None,
    provider_response: dict | None,
    result_summary: dict,
) -> None:
    if run_dir is None:
        return
    target = run_dir / "derivations" / request.request_id.replace("://", "_")
    target.mkdir(parents=True, exist_ok=True)
    write_json_atomic(target / "request.json", request)
    write_json_atomic(target / "prepared.json", prepared.__dict__)
    if prompt_text is not None:
        (target / "prompt.md").write_text(prompt_text, encoding="utf-8")
    if provider_response is not None:
        write_json_atomic(target / "provider.response.json", provider_response)
    write_json_atomic(target / "result.json", result_summary)
    write_json_atomic(
        target / "manifest.json",
        {
            "request_id": request.request_id,
            "capability_id": prepared.capability_id,
            "derivation_signature": prepared.derivation_signature,
        },
    )


class DeterministicDerivationExecutor:
    """Pixel-preserving compositor for E1 / deterministic derivation capabilities."""

    def __init__(self, repo_root: Path, registry: CapabilityRegistryHub, *, run_dir: Path | None = None) -> None:
        self.repo_root = repo_root
        self.registry = registry
        self.run_dir = run_dir

    def execute(
        self,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
    ) -> DerivationResultDraft:
        entry = self.registry.require_entry("derivation", binding.capability_id)
        if not isinstance(entry, DerivationEntry):
            raise Stage4Error("missing_derivation_capability", binding.capability_id)
        if request.required_group is not None:
            return self._execute_group(request, binding, prepared, session, entry)
        return DerivationResultDraft(
            drafts=[
                self._draft_from_bytes(
                    request=request,
                    binding=binding,
                    prepared=prepared,
                    session=session,
                    entry=entry,
                    role=request.target_asset_role,
                    member_key=request.slot_id,
                    signature=prepared.derivation_signature,
                    image_bytes=self._render_single(request, prepared, session, entry),
                    provider="deterministic",
                    model="pil",
                    prompt_sha256=prepared.prompt_template_sha256,
                )
            ],
            draft_member_keys=[request.slot_id],
        )

    def _render_single(
        self,
        request: DerivationRequest,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
        entry: DerivationEntry,
    ) -> bytes:
        if not request.parent_asset_refs:
            raise Stage4Error(
                "website_truth_violation",
                f"{entry.id} requires a real parent screenshot",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        source = _resolve_object_path(
            session,
            request.parent_asset_refs[0],
            scene_id=request.scene_id,
            slot_id=request.slot_id,
        )
        with NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            if entry.id in {"site_faithful_reframe", "site_feature_entry_callout_keyframe"}:
                _fit_paste(source, temporary)
            elif entry.id == "normalize_gallery_asset":
                _normalize_orientation(source, temporary, request.target_orientation)
            else:
                _fit_paste(source, temporary)
            return temporary.read_bytes()
        finally:
            temporary.unlink(missing_ok=True)

    def _execute_group(
        self,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
        entry: DerivationEntry,
    ) -> DerivationResultDraft:
        assert request.required_group is not None
        pattern = self.registry.entry("relation_pattern", request.required_group.pattern_id)
        if not isinstance(pattern, RelationPatternEntry):
            raise Stage4Error(
                "derivation_failed",
                f"unknown relation pattern: {request.required_group.pattern_id}",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        parent = session.get_asset(request.parent_asset_refs[0])
        if parent is None:
            raise Stage4Error("derivation_failed", "parent missing", scene_id=request.scene_id, slot_id=request.slot_id)
        source = _resolve_object_path(
            session,
            parent.asset_ref,
            scene_id=request.scene_id,
            slot_id=request.slot_id,
        )
        reuse: dict[str, str] = {}
        drafts: list[AssetDraft] = []
        draft_keys: list[str] = []
        for member in sorted(pattern.members, key=lambda item: item.order):
            if entry.id == "site_params_flower_text_frame_sequence" and member.member_key == "base":
                reuse[member.member_key] = parent.asset_ref
                continue
            signature = build_derivation_signature(
                parent_refs=list(request.parent_asset_refs),
                parent_hashes=[parent.content_sha256],
                context_refs=list(request.context_asset_refs),
                context_hashes=[],
                category_id=request.category_id,
                role=member.asset_role,
                pattern_id=request.required_group.pattern_id,
                member_key=member.member_key,
                capability_id=binding.capability_id,
                capability_version=binding.capability_version,
                execution_fingerprint=binding.execution_fingerprint,
                narrative_fingerprint=sha256(f"{request.scene_id}|{member.member_key}".encode("utf-8")).hexdigest(),
                target_orientation=request.target_orientation or "",
            )
            existing = session.find_by_derivation_signature(signature)
            if existing is not None:
                reuse[member.member_key] = existing.asset_ref
                continue
            with NamedTemporaryFile(suffix=".png", delete=False) as handle:
                temporary = Path(handle.name)
            try:
                if entry.id == "site_params_flower_text_frame_sequence":
                    _sequence_variant(source, temporary, member.member_key)
                else:
                    _fit_paste(source, temporary)
                drafts.append(
                    self._draft_from_bytes(
                        request=request,
                        binding=binding,
                        prepared=prepared,
                        session=session,
                        entry=entry,
                        role=member.asset_role,
                        member_key=member.member_key,
                        signature=signature,
                        image_bytes=temporary.read_bytes(),
                        provider="deterministic",
                        model="pil",
                        prompt_sha256=prepared.prompt_template_sha256,
                    )
                )
                draft_keys.append(member.member_key)
            finally:
                temporary.unlink(missing_ok=True)
        _write_run_artifacts(
            run_dir=self.run_dir,
            request=request,
            prepared=prepared,
            prompt_text=None,
            provider_response=None,
            result_summary={"executor": "deterministic", "members": draft_keys, "reuse": reuse},
        )
        return DerivationResultDraft(
            drafts=drafts,
            draft_member_keys=draft_keys,
            reuse_member_refs=reuse,
            group_type=request.required_group.group_type,
            pattern_id=request.required_group.pattern_id,
            category_id=request.category_id or parent.category_id,
        )

    def _draft_from_bytes(
        self,
        *,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
        entry: DerivationEntry,
        role: str,
        member_key: str,
        signature: str,
        image_bytes: bytes,
        provider: str,
        model: str,
        prompt_sha256: str,
    ) -> AssetDraft:
        object_store = getattr(session.repository, "object_store", None)
        if object_store is None:
            raise Stage4Error("derivation_failed", "repository has no object_store")
        object_key = f"derived/stage5/{signature}_{member_key}.png"
        with NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            temporary.write_bytes(image_bytes)
            info = object_store.put_file(temporary, object_key)
        finally:
            temporary.unlink(missing_ok=True)
        parent = session.get_asset(request.parent_asset_refs[0]) if request.parent_asset_refs else None
        evidence = _evidence_from_class(entry.capabilities.output_evidence_class)
        now = datetime.now(timezone.utc)
        return AssetDraft(
            filename=Path(info.object_key).name,
            object_key=info.object_key,
            content_sha256=info.content_sha256,
            media_type=info.media_type,
            module=parent.module if parent else ((request.category_id or "").split("/")[0] or None),
            category_id=request.category_id or (parent.category_id if parent else None),
            category_path=list(parent.category_path) if parent else [],
            asset_role=role,
            case_label=parent.case_label if parent else None,
            industry=parent.industry if parent else None,
            description=f"stage5 {binding.capability_id}:{member_key}",
            width=info.width,
            height=info.height,
            orientation=info.orientation,
            animated=False,
            source_kind=SourceKind.DERIVED,
            origin_type="stage5_derivation",
            evidence_class=evidence,
            claims=list(parent.claims) if parent and evidence == EvidenceClass.FAITHFUL else [],
            lineage=AssetLineage(
                parent_asset_refs=list(request.parent_asset_refs),
                derivation_type=request.derivation_type,
                executor_id=binding.capability_id,
                provider=provider,
                model=model,
                prompt_template_version=binding.capability_version,
                prompt_sha256=prompt_sha256,
                parameters_sha256=sha256(signature.encode("utf-8")).hexdigest(),
                derivation_signature=signature,
                created_at=now,
            ),
        )


class GptImageDerivationExecutor:
    """GPT Image executor for E2 semantic derivation capabilities."""

    def __init__(
        self,
        repo_root: Path,
        registry: CapabilityRegistryHub,
        *,
        run_dir: Path | None = None,
        image_editor=edit_image,
    ) -> None:
        self.repo_root = repo_root
        self.registry = registry
        self.run_dir = run_dir
        self.image_editor = image_editor

    def execute(
        self,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
    ) -> DerivationResultDraft:
        entry = self.registry.require_entry("derivation", binding.capability_id)
        if not isinstance(entry, DerivationEntry):
            raise Stage4Error("missing_derivation_capability", binding.capability_id)
        if entry.capabilities.website_truth_policy == "forbidden" and request.target_asset_role in {
            "site_home",
            "feature_entry",
            "parameter_panel",
        }:
            raise Stage4Error(
                "website_truth_violation",
                "GPT Image cannot fabricate website screenshots",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        if request.required_group is not None:
            return self._execute_group(request, binding, prepared, session, entry)
        parent_roles = []
        for ref in request.parent_asset_refs:
            asset = session.get_asset(ref)
            if asset is not None:
                parent_roles.append(asset.asset_role)
        prompt = compose_derivation_prompt(
            repo_root=self.repo_root,
            hub=self.registry,
            request=request,
            binding=binding,
            parent_roles=parent_roles,
        )
        image_bytes, provider_meta = self._generate(request, binding, session, prompt.text)
        draft = DeterministicDerivationExecutor(self.repo_root, self.registry)._draft_from_bytes(
            request=request,
            binding=binding,
            prepared=prepared,
            session=session,
            entry=entry,
            role=request.target_asset_role,
            member_key=request.slot_id,
            signature=prepared.derivation_signature,
            image_bytes=image_bytes,
            provider=provider_meta["provider"],
            model=provider_meta["model"],
            prompt_sha256=prompt.template_sha256,
        )
        _write_run_artifacts(
            run_dir=self.run_dir,
            request=request,
            prepared=prepared,
            prompt_text=prompt.text,
            provider_response=provider_meta,
            result_summary={"executor": "gpt_image", "asset_role": request.target_asset_role},
        )
        return DerivationResultDraft(drafts=[draft], draft_member_keys=[request.slot_id])

    def _execute_group(
        self,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
        entry: DerivationEntry,
    ) -> DerivationResultDraft:
        assert request.required_group is not None
        pattern = self.registry.entry("relation_pattern", request.required_group.pattern_id)
        if not isinstance(pattern, RelationPatternEntry):
            raise Stage4Error("derivation_failed", f"unknown pattern {request.required_group.pattern_id}")
        parent = session.get_asset(request.parent_asset_refs[0])
        if parent is None:
            raise Stage4Error("derivation_failed", "parent missing")
        reuse: dict[str, str] = {}
        drafts: list[AssetDraft] = []
        draft_keys: list[str] = []
        helper = DeterministicDerivationExecutor(self.repo_root, self.registry)
        for member in sorted(pattern.members, key=lambda item: item.order):
            if (
                request.required_group.pattern_id == "editor_sequence"
                and member.member_key == "source_result"
                and parent.asset_role == "result_image"
            ):
                reuse[member.member_key] = parent.asset_ref
                continue
            if (
                request.required_group.pattern_id == "reference_result_plan"
                and member.member_key == "result_image"
                and parent.asset_role == "result_image"
                and member.asset_role == "result_image"
            ):
                reuse[member.member_key] = parent.asset_ref
                continue
            signature = build_derivation_signature(
                parent_refs=list(request.parent_asset_refs),
                parent_hashes=[parent.content_sha256],
                context_refs=list(request.context_asset_refs),
                context_hashes=[],
                category_id=request.category_id,
                role=member.asset_role,
                pattern_id=request.required_group.pattern_id,
                member_key=member.member_key,
                capability_id=binding.capability_id,
                capability_version=binding.capability_version,
                execution_fingerprint=binding.execution_fingerprint,
                narrative_fingerprint=sha256(f"{request.scene_id}|{member.member_key}".encode("utf-8")).hexdigest(),
                target_orientation=request.target_orientation or "",
            )
            existing = session.find_by_derivation_signature(signature)
            if existing is not None:
                reuse[member.member_key] = existing.asset_ref
                continue
            prompt = compose_derivation_prompt(
                repo_root=self.repo_root,
                hub=self.registry,
                request=request,
                binding=binding,
                parent_roles=[parent.asset_role],
                member_key=member.member_key,
            )
            image_bytes, provider_meta = self._generate(
                request,
                binding,
                session,
                prompt.text,
                member_role=member.asset_role,
            )
            drafts.append(
                helper._draft_from_bytes(
                    request=request,
                    binding=binding,
                    prepared=prepared,
                    session=session,
                    entry=entry,
                    role=member.asset_role,
                    member_key=member.member_key,
                    signature=signature,
                    image_bytes=image_bytes,
                    provider=provider_meta["provider"],
                    model=provider_meta["model"],
                    prompt_sha256=prompt.template_sha256,
                )
            )
            draft_keys.append(member.member_key)
        return DerivationResultDraft(
            drafts=drafts,
            draft_member_keys=draft_keys,
            reuse_member_refs=reuse,
            group_type=request.required_group.group_type,
            pattern_id=request.required_group.pattern_id,
            category_id=request.category_id or parent.category_id,
        )

    def _generate(
        self,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        session: AssetResolutionSession,
        prompt: str,
        *,
        member_role: str | None = None,
    ) -> tuple[bytes, dict]:
        size = target_size_for_orientation(request.target_orientation, binding.target_size)
        with TemporaryDirectory(prefix="v4-derivation-") as temp_dir:
            temp_root = Path(temp_dir)
            source_paths: list[Path] = []
            for ref in request.parent_asset_refs:
                source_paths.append(
                    _resolve_object_path(session, ref, scene_id=request.scene_id, slot_id=request.slot_id)
                )
            for ref in request.context_asset_refs:
                source_paths.append(
                    _resolve_object_path(session, ref, scene_id=request.scene_id, slot_id=request.slot_id)
                )
            if not source_paths:
                blank = temp_root / "blank.png"
                width, height = (16, 9) if (request.target_orientation or "").startswith("land") else (9, 16)
                Image.new("RGB", (width * 64, height * 64), (24, 28, 34)).save(blank)
                source_paths = [blank]
            combined = temp_root / "combined.png"
            source = _combined_panels(source_paths, combined)
            try:
                result = self.image_editor(self.repo_root, source, prompt, size=size)
            except Exception as exc:  # noqa: BLE001
                raise Stage4Error(
                    "derivation_provider_failed",
                    f"GPT Image failed for {binding.capability_id}: {exc}",
                    scene_id=request.scene_id,
                    slot_id=request.slot_id,
                ) from exc
            if not result.content:
                raise Stage4Error(
                    "derivation_output_invalid",
                    "GPT Image returned empty content",
                    scene_id=request.scene_id,
                    slot_id=request.slot_id,
                )
            return result.content, {
                "provider": result.provider,
                "model": result.model,
                "response_id": result.response_id,
                "size": size,
                "member_role": member_role or request.target_asset_role,
            }


class Stage5DerivationExecutor:
    """Dispatch by Derivation Registry executor_kind. Production default for Stage4."""

    def __init__(
        self,
        repo_root: Path,
        registry: CapabilityRegistryHub,
        *,
        run_dir: Path | None = None,
        image_editor=edit_image,
    ) -> None:
        self.repo_root = repo_root
        self.registry = registry
        self.deterministic = DeterministicDerivationExecutor(repo_root, registry, run_dir=run_dir)
        self.gpt_image = GptImageDerivationExecutor(
            repo_root,
            registry,
            run_dir=run_dir,
            image_editor=image_editor,
        )

    def execute(
        self,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
    ) -> DerivationResultDraft:
        entry = self.registry.require_entry("derivation", binding.capability_id)
        if not isinstance(entry, DerivationEntry):
            raise Stage4Error("missing_derivation_capability", binding.capability_id)
        kind = entry.capabilities.executor_kind
        if kind == "deterministic":
            return self.deterministic.execute(request, binding, prepared, session)
        if kind in {"gpt_image", "composite"}:
            return self.gpt_image.execute(request, binding, prepared, session)
        raise Stage4Error(
            "capability_not_applicable",
            f"unsupported executor_kind: {kind}",
            scene_id=request.scene_id,
            slot_id=request.slot_id,
        )
