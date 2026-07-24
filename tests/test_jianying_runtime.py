from __future__ import annotations

from pathlib import Path

import pytest

from video_agent.editors.jianying.runtime import JianyingSkillRuntime


def _fake_skill(root: Path, version: str = "1.5.0") -> Path:
    (root / "scripts" / "vendor" / "pyJianYingDraft").mkdir(parents=True)
    (root / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (root / "VERSION").write_text(version, encoding="utf-8")
    (root / "scripts" / "jy_wrapper.py").write_text("class JyProject: pass\n", encoding="utf-8")
    (root / "scripts" / "vendor" / "pyJianYingDraft" / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )
    return root


def test_discover_explicit_skill_root(tmp_path: Path) -> None:
    root = _fake_skill(tmp_path / "skill")
    runtime = JianyingSkillRuntime.discover(explicit_root=root)
    assert runtime.root == root.resolve()
    assert runtime.version == "1.5.0"


def test_discover_uses_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = _fake_skill(tmp_path / "skill")
    monkeypatch.setenv("JY_SKILL_ROOT", str(root))
    runtime = JianyingSkillRuntime.discover()
    assert runtime.root == root.resolve()


def test_rejects_old_skill_version(tmp_path: Path) -> None:
    root = _fake_skill(tmp_path / "skill", "1.4.9")
    with pytest.raises(RuntimeError, match="older than required"):
        JianyingSkillRuntime(root)


def test_probe_without_import_is_stable(tmp_path: Path) -> None:
    root = _fake_skill(tmp_path / "skill")
    runtime = JianyingSkillRuntime(root)
    first = runtime.probe(import_modules=False)
    second = runtime.probe(import_modules=False)
    assert first.version == "1.5.0"
    assert first.capability_sha256 == second.capability_sha256
    assert first.draft_creation is False
