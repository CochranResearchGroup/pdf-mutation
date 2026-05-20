"""Importable mutation engine API.

This module is the stable boundary for callers that want to generate plans,
audit QDF content, or apply reviewed plans without parsing CLI output.
"""

from __future__ import annotations

from pdf_glyph_replace import (
    analyze_qdf,
    apply_plan_to_qdf,
    audit_qdf,
    plan_qdf,
    replace_qdf,
)

__all__ = [
    "analyze_qdf",
    "apply_plan_to_qdf",
    "audit_qdf",
    "plan_qdf",
    "replace_qdf",
]
