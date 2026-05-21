"""Layout evidence helpers for optional bbox validation artifacts."""

from __future__ import annotations

import hashlib
import html
import re
import shutil
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pdf_mutation.adapters import run_status


BBOX_WORD_RE = re.compile(r"<word\b(?P<attrs>[^>]*)>(?P<text>.*?)</word>", re.S)
BBOX_ATTR_RE = re.compile(r'([A-Za-z]+)="([^"]+)"')
BBOX_ASSERTION_TOLERANCE = Decimal("0.75")


def artifact_fingerprint(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": str(path),
        "size": len(data),
        "sha256_12": hashlib.sha256(data).hexdigest()[:12],
    }


def write_bbox_artifact(pdf_path: Path, bbox_path: Path) -> dict[str, object]:
    bbox_path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("pdftotext") is None:
        return {
            "status": "unavailable",
            "path": str(bbox_path),
            "reason": "pdftotext not found on PATH",
        }
    returncode, _stdout, stderr = run_status(
        ["pdftotext", "-bbox", str(pdf_path), str(bbox_path)]
    )
    if returncode:
        return {
            "status": "error",
            "path": str(bbox_path),
            "reason": stderr.decode("utf-8", "replace").strip() or "pdftotext -bbox failed",
        }
    return {
        "status": "ok",
        **artifact_fingerprint(bbox_path),
    }


def parse_bbox_words(path: Path) -> list[dict[str, object]]:
    words: list[dict[str, object]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for match in BBOX_WORD_RE.finditer(text):
        attrs = dict(BBOX_ATTR_RE.findall(match.group("attrs")))
        try:
            words.append(
                {
                    "text": html.unescape(re.sub(r"<[^>]+>", "", match.group("text"))),
                    "x_min": Decimal(attrs["xMin"]),
                    "y_min": Decimal(attrs["yMin"]),
                    "x_max": Decimal(attrs["xMax"]),
                    "y_max": Decimal(attrs["yMax"]),
                }
            )
        except (KeyError, InvalidOperation):
            continue
    return words


def bbox_words_matching(path: Path, target: str) -> list[dict[str, object]]:
    return [word for word in parse_bbox_words(path) if target in str(word["text"])]


def decimal_report(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return text


def bbox_alignment_assertions(
    *,
    before_path: Path,
    after_path: Path,
    search: str,
    replacement: str,
    align: str,
) -> dict[str, object]:
    before_words = bbox_words_matching(before_path, search)
    after_words = bbox_words_matching(after_path, replacement)
    warnings: list[str] = []
    if not before_words:
        warnings.append("search text not found in before bbox artifact")
    if not after_words:
        warnings.append("replacement text not found in after bbox artifact")
    pair_count = min(len(before_words), len(after_words))
    if pair_count == 0:
        return {
            "status": "warning",
            "align": align,
            "checked_pairs": 0,
            "before_match_count": len(before_words),
            "after_match_count": len(after_words),
            "warnings": warnings,
            "privacy": {"literal_text_included": False},
        }

    if align == "exact":
        if len(before_words) != len(after_words):
            warnings.append(
                f"bbox match count differs: before={len(before_words)} after={len(after_words)}"
            )
        return {
            "status": "ok" if not warnings else "warning",
            "align": align,
            "contract": "text_extraction_changed",
            "checked_pairs": pair_count,
            "before_match_count": len(before_words),
            "after_match_count": len(after_words),
            "assertions": [],
            "warnings": warnings,
            "privacy": {"literal_text_included": False},
        }

    assertions: list[dict[str, object]] = []
    tolerance = BBOX_ASSERTION_TOLERANCE
    for index, (before, after) in enumerate(zip(before_words, after_words), 1):
        left_delta = Decimal(after["x_min"]) - Decimal(before["x_min"])
        right_delta = Decimal(after["x_max"]) - Decimal(before["x_max"])
        if align == "right":
            passed = abs(right_delta) <= tolerance
            contract = "right_edge"
            checked_edge = "x_max"
            checked_delta = right_delta
        else:
            passed = abs(left_delta) <= tolerance
            contract = "left_edge"
            checked_edge = "x_min"
            checked_delta = left_delta
        assertions.append(
            {
                "index": index,
                "contract": contract,
                "passed": passed,
                "checked_edge": checked_edge,
                "checked_delta": decimal_report(checked_delta),
                "left_delta": decimal_report(left_delta),
                "right_delta": decimal_report(right_delta),
                "before": {
                    "x_min": decimal_report(Decimal(before["x_min"])),
                    "x_max": decimal_report(Decimal(before["x_max"])),
                },
                "after": {
                    "x_min": decimal_report(Decimal(after["x_min"])),
                    "x_max": decimal_report(Decimal(after["x_max"])),
                },
            }
        )
    if len(before_words) != len(after_words):
        warnings.append(
            f"bbox match count differs: before={len(before_words)} after={len(after_words)}"
        )
    failed = sum(1 for assertion in assertions if not assertion["passed"])
    if failed:
        warnings.append(f"{failed} bbox alignment assertion(s) failed")
    return {
        "status": "ok" if not warnings else "warning",
        "align": align,
        "checked_pairs": pair_count,
        "before_match_count": len(before_words),
        "after_match_count": len(after_words),
        "tolerance": decimal_report(tolerance),
        "assertions": assertions,
        "warnings": warnings,
        "privacy": {"literal_text_included": False},
    }


def collect_bbox_evidence(
    *,
    input_pdf: Path,
    output_pdf: Path,
    bbox_dir: Path | None,
    stem: str,
    search: str | None = None,
    replacement: str | None = None,
    align: str | None = None,
) -> dict[str, object] | None:
    if bbox_dir is None:
        return None
    before = write_bbox_artifact(input_pdf, bbox_dir / f"{stem}.before.bbox.html")
    after = write_bbox_artifact(output_pdf, bbox_dir / f"{stem}.after.bbox.html")
    warnings: list[str] = []
    for label, artifact in (("before", before), ("after", after)):
        if artifact["status"] != "ok":
            warnings.append(f"{label} bbox extraction {artifact['status']}: {artifact['reason']}")
    assertions: dict[str, object] | None = None
    if before["status"] == "ok" and after["status"] == "ok" and search and replacement and align:
        assertions = bbox_alignment_assertions(
            before_path=Path(str(before["path"])),
            after_path=Path(str(after["path"])),
            search=search,
            replacement=replacement,
            align=align,
        )
        warnings.extend(str(warning) for warning in assertions["warnings"])
    return {
        "tool": "pdftotext -bbox",
        "status": "ok" if not warnings else "warning",
        "before": before,
        "after": after,
        "alignment_assertions": assertions,
        "warnings": warnings,
        "privacy": {
            "bbox_html_may_include_extracted_text": True,
            "report_includes_bbox_text": False,
        },
    }
