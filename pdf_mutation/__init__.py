"""Public Python API for deterministic glyph-preserving PDF mutation."""

from __future__ import annotations

from pdf_glyph_replace import __version__
from pdf_mutation.engine import apply_plan_to_qdf, audit_qdf, plan_qdf, replace_qdf

__all__ = [
    "__version__",
    "apply_plan_to_qdf",
    "audit_qdf",
    "plan_qdf",
    "replace_qdf",
]
