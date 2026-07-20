"""Handler code fingerprints for Derivation Resume invalidation."""

from __future__ import annotations

import importlib
import inspect
from hashlib import sha256


def _source_or_error(obj: object, label: str) -> str:
    try:
        return inspect.getsource(obj)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 - fingerprint must still hash
        return f"{label}:error:{type(exc).__name__}:{exc}"


def handler_source_fingerprint(handler_ref: str | None) -> str:
    """Hash handler ref + callable source (+ unwrapped executor when using handler_refs)."""
    if not handler_ref:
        return sha256(b"handler:none").hexdigest()
    module_name, separator, attribute_name = handler_ref.partition(":")
    if not separator or not attribute_name:
        return sha256(f"handler:invalid:{handler_ref}".encode("utf-8")).hexdigest()
    chunks = [handler_ref]
    try:
        module = importlib.import_module(module_name)
        target = module
        for part in attribute_name.split("."):
            target = getattr(target, part)
        chunks.append(_source_or_error(target, "handler"))
    except Exception as exc:  # noqa: BLE001
        chunks.append(f"resolve_error:{type(exc).__name__}:{exc}")
    # Thin Stage5 factories in handler_refs do not contain executor bodies.
    if module_name.endswith("handler_refs"):
        attr = attribute_name.split(".")[-1]
        for mod_name in (
            "video_agent.derivation.v4.executors",
            "video_agent.derivation.v4.e1_compositor",
        ):
            try:
                impl_mod = importlib.import_module(mod_name)
                chunks.append(f"module:{mod_name}")
                chunks.append(_source_or_error(impl_mod, mod_name))
                if mod_name.endswith("executors"):
                    impl = getattr(impl_mod, attr, None)
                    if impl is not None:
                        chunks.append(_source_or_error(impl, attr))
            except Exception as exc:  # noqa: BLE001
                chunks.append(f"module_error:{mod_name}:{type(exc).__name__}")
    return sha256("\n".join(chunks).encode("utf-8")).hexdigest()
