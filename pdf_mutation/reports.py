"""Importable reporting and layout-evidence helpers."""

from __future__ import annotations

from pdf_mutation.engine import (
    apply_plan_report_payload,
    bbox_alignment_assertions,
    collect_bbox_evidence,
    report_payload,
    write_report,
)

__all__ = [
    "apply_plan_report_payload",
    "bbox_alignment_assertions",
    "collect_bbox_evidence",
    "report_payload",
    "write_report",
]
