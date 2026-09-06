"""Explicit native runtime options; no model, preprocessing or acceptance changes."""

from __future__ import annotations

from typing import Any


def enable_cpu_arena(backend: Any) -> None:
    """Configure the three pooled RapidOCR sessions before their first invocation.

    RapidOCR 1.x hardcodes arenas off. Rebuild only its native sessions with
    identical models/providers/options, changing this one allocation flag.
    Fail closed on an unsupported backend instead of silently claiming a profile.
    """
    from onnxruntime import InferenceSession

    wrappers = (backend.text_det.infer, backend.text_cls.infer, backend.text_rec.session)
    replacements = []
    for wrapper in wrappers:
        previous = wrapper.session
        model = getattr(previous, "_model_path", None)
        if not model or previous.get_providers() != ["CPUExecutionProvider"]:
            raise ValueError("CPU_ARENA_PROFILE_REQUIRES_SUPPORTED_CPU_MODEL_SESSION")
        options = previous.get_session_options()
        options.enable_cpu_mem_arena = True
        replacements.append(
            InferenceSession(
                model,
                sess_options=options,
                providers=previous.get_providers(),
                provider_options=[previous.get_provider_options()["CPUExecutionProvider"]],
            )
        )
    # Publish only after every session has loaded successfully.
    for wrapper, replacement in zip(wrappers, replacements, strict=True):
        wrapper.session = replacement
