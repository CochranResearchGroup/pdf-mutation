#!/usr/bin/env python3
"""Non-mutating PDF inventory for pdf-mutation dogfood corpora."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pdf_glyph_replace as glyph


__version__ = glyph.__version__


FAIL_ON_CHOICES = (
    "error",
    "unsupported",
    "skipped",
    "qpdf-check-failed",
    "qdf-conversion-failed",
    "probe-unsupported",
    "probe-no-match",
    "probe-infeasible",
    "probe-feasible",
    "probe-match",
)


def run_command(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def classify_qdf(qdf: bytes) -> dict[str, Any]:
    """Return structural inventory for a QDF byte stream without decoded text."""
    objects = glyph.parse_objects(qdf)
    decode_maps, _ = glyph.build_font_maps(objects)
    streams = [glyph.stream_of(body) for body in objects.values()]
    text_object_count = sum(
        len(glyph.BT_ET_RE.findall(stream)) for stream in streams if stream is not None
    )
    type0_font_count = sum(1 for body in objects.values() if b"/Subtype /Type0" in body)
    to_unicode_ref_count = len(glyph.TO_UNICODE_RE.findall(qdf))
    decoded_font_resource_count = len(decode_maps)

    if decoded_font_resource_count:
        status = "supported"
        reason = "decoded Type0 ToUnicode font resources found"
    elif type0_font_count or to_unicode_ref_count:
        status = "unsupported"
        reason = "Type0 or ToUnicode objects found, but no decodable page font resources"
    else:
        status = "unsupported"
        reason = "no Type0 fonts with ToUnicode CMaps found"

    return {
        "qdf_size_bytes": len(qdf),
        "object_count": len(objects),
        "stream_count": sum(1 for stream in streams if stream is not None),
        "type0_font_count": type0_font_count,
        "to_unicode_ref_count": to_unicode_ref_count,
        "decoded_font_resource_count": decoded_font_resource_count,
        "decoded_glyph_count_total": sum(len(mapping) for mapping in decode_maps.values()),
        "font_resources": [
            {"font": font, "decoded_glyphs": len(decode_maps[font])}
            for font in sorted(decode_maps)
        ],
        "text_object_count": text_object_count,
        "status": status,
        "reason": reason,
    }


def probe_qdf(
    qdf: bytes,
    *,
    search: str,
    replacement: str,
    align: str,
) -> dict[str, Any]:
    """Return non-sensitive search feasibility signals for a QDF byte stream."""
    try:
        reports, decode_maps = glyph.analyze_qdf(qdf, search, replacement, align=align)
    except SystemExit as exc:
        return {
            "search_length": len(search),
            "replacement_length": len(replacement),
            "search_sha256_12": hashlib.sha256(search.encode("utf-8")).hexdigest()[:12],
            "replacement_sha256_12": hashlib.sha256(replacement.encode("utf-8")).hexdigest()[:12],
            "align": align,
            "status": "unsupported",
            "reason": str(exc),
            "total_matches": 0,
            "feasible": False,
            "match_count_by_font": [],
        }

    total = sum(report.match_count for report in reports)
    feasible = total > 0 and all(report.feasible for report in reports)
    if feasible:
        status = "feasible"
        reason = "all probe matches are feasible"
    elif total:
        status = "infeasible"
        reason = "one or more probe matches are not feasible"
    else:
        status = "no_match"
        reason = "probe text not found"

    by_font: dict[str, int] = {}
    reasons: list[str] = []
    for report in reports:
        by_font[report.font] = by_font.get(report.font, 0) + report.match_count
        if report.reason and report.reason not in reasons:
            reasons.append(report.reason)

    return {
        "search_length": len(search),
        "replacement_length": len(replacement),
        "search_sha256_12": hashlib.sha256(search.encode("utf-8")).hexdigest()[:12],
        "replacement_sha256_12": hashlib.sha256(replacement.encode("utf-8")).hexdigest()[:12],
        "align": align,
        "status": status,
        "reason": reason,
        "total_matches": total,
        "feasible": feasible,
        "font_resource_count": len(decode_maps),
        "match_count_by_font": [
            {"font": font, "match_count": by_font[font]} for font in sorted(by_font)
        ],
        "infeasible_reasons": reasons,
    }


def inventory_pdf(
    path: Path,
    *,
    keep_qdf_dir: Path | None = None,
    probe: tuple[str, str] | None = None,
    align: str = "exact",
    max_input_bytes: int | None = None,
) -> dict[str, Any]:
    """Classify a PDF without mutating it or extracting text content."""
    started = time.time()
    result: dict[str, Any] = {
        "input_pdf": str(path),
        "size_bytes": path.stat().st_size if path.exists() else None,
        "qpdf_check": False,
        "qdf_conversion": False,
        "qdf_path": None,
        "status": "error",
        "reason": "",
        "duration_seconds": None,
    }
    if not path.exists():
        result["reason"] = "input file does not exist"
        result["duration_seconds"] = round(time.time() - started, 3)
        return result
    if max_input_bytes is not None and result["size_bytes"] is not None:
        if int(result["size_bytes"]) > max_input_bytes:
            result.update(
                {
                    "status": "skipped",
                    "reason": f"input size exceeds --max-input-bytes ({max_input_bytes})",
                    "max_input_bytes": max_input_bytes,
                    "duration_seconds": round(time.time() - started, 3),
                }
            )
            if probe:
                result["probe"] = {
                    "search_length": len(probe[0]),
                    "replacement_length": len(probe[1]),
                    "search_sha256_12": hashlib.sha256(probe[0].encode("utf-8")).hexdigest()[:12],
                    "replacement_sha256_12": hashlib.sha256(
                        probe[1].encode("utf-8")
                    ).hexdigest()[:12],
                    "align": align,
                    "status": "skipped",
                    "reason": "inventory skipped before QDF conversion",
                    "total_matches": 0,
                    "feasible": False,
                    "match_count_by_font": [],
                }
            return result

    check = run_command(["qpdf", "--check", str(path)])
    if check.returncode != 0:
        result["reason"] = "qpdf --check failed"
        result["stderr_tail"] = check.stderr.decode("utf-8", "replace")[-500:]
        result["duration_seconds"] = round(time.time() - started, 3)
        return result
    result["qpdf_check"] = True

    with tempfile.TemporaryDirectory(prefix="pdf-inventory-") as tmp:
        qdf_path = Path(tmp) / "input.qdf.pdf"
        conversion = run_command(
            ["qpdf", "--qdf", "--object-streams=disable", str(path), str(qdf_path)]
        )
        if conversion.returncode != 0:
            result["reason"] = "qpdf QDF conversion failed"
            result["stderr_tail"] = conversion.stderr.decode("utf-8", "replace")[-500:]
            result["duration_seconds"] = round(time.time() - started, 3)
            return result
        result["qdf_conversion"] = True

        qdf = qdf_path.read_bytes()
        if keep_qdf_dir:
            keep_qdf_dir.mkdir(parents=True, exist_ok=True)
            kept = keep_qdf_dir / f"{path.stem}.qdf.pdf"
            kept.write_bytes(qdf)
            result["qdf_path"] = str(kept)

    result.update(classify_qdf(qdf))
    if probe:
        result["probe"] = probe_qdf(qdf, search=probe[0], replacement=probe[1], align=align)
    result["duration_seconds"] = round(time.time() - started, 3)
    return result


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return aggregate non-sensitive inventory counts."""
    status_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    probe_status_counts: dict[str, int] = {}
    total_size = 0
    total_matches = 0
    supported_with_text_objects = 0
    for row in rows:
        status = str(row.get("status", ""))
        status_counts[status] = status_counts.get(status, 0) + 1
        reason = str(row.get("reason", ""))
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if isinstance(row.get("size_bytes"), int):
            total_size += int(row["size_bytes"])
        if row.get("status") == "supported" and int(row.get("text_object_count") or 0) > 0:
            supported_with_text_objects += 1
        probe = row.get("probe")
        if isinstance(probe, dict):
            probe_status = str(probe.get("status", ""))
            probe_status_counts[probe_status] = probe_status_counts.get(probe_status, 0) + 1
            total_matches += int(probe.get("total_matches") or 0)

    summary: dict[str, Any] = {
        "total_pdfs": len(rows),
        "total_size_bytes": total_size,
        "status_counts": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "qpdf_check_failed": sum(1 for row in rows if row.get("qpdf_check") is False),
        "qdf_conversion_failed": sum(1 for row in rows if row.get("qdf_conversion") is False),
        "supported_with_text_objects": supported_with_text_objects,
        "total_type0_fonts": sum(int(row.get("type0_font_count") or 0) for row in rows),
        "total_decoded_font_resources": sum(
            int(row.get("decoded_font_resource_count") or 0) for row in rows
        ),
        "total_text_objects": sum(int(row.get("text_object_count") or 0) for row in rows),
    }
    if probe_status_counts:
        summary["probe_status_counts"] = dict(sorted(probe_status_counts.items()))
        summary["probe_total_matches"] = total_matches
        summary["probe_feasible_pdfs"] = sum(
            1 for row in rows if isinstance(row.get("probe"), dict) and row["probe"].get("feasible")
        )
    return summary


def write_outputs(
    rows: list[dict[str, Any]],
    *,
    json_path: Path | None,
    tsv_path: Path | None,
    summary: dict[str, Any] | None = None,
) -> None:
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        payload: Any = {"rows": rows, "summary": summary} if summary is not None else rows
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if tsv_path:
        tsv_path.parent.mkdir(parents=True, exist_ok=True)
        headers = [
            "input_pdf",
            "size_bytes",
            "qpdf_check",
            "qdf_conversion",
            "status",
            "reason",
            "object_count",
            "stream_count",
            "type0_font_count",
            "to_unicode_ref_count",
            "decoded_font_resource_count",
            "text_object_count",
            "probe_status",
            "probe_total_matches",
            "probe_feasible",
            "max_input_bytes",
            "duration_seconds",
        ]
        with tsv_path.open("w", encoding="utf-8") as handle:
            handle.write("\t".join(headers) + "\n")
            for row in rows:
                flat = dict(row)
                probe = row.get("probe")
                if isinstance(probe, dict):
                    flat["probe_status"] = probe.get("status", "")
                    flat["probe_total_matches"] = probe.get("total_matches", "")
                    flat["probe_feasible"] = probe.get("feasible", "")
                handle.write("\t".join(str(flat.get(header, "")) for header in headers) + "\n")


def print_table(rows: list[dict[str, Any]]) -> None:
    has_probe = any("probe" in row for row in rows)
    headers = ["input_pdf", "status", "type0", "decoded_fonts", "text_objects"]
    if has_probe:
        headers.extend(["probe_status", "probe_matches", "probe_feasible"])
    headers.append("reason")
    print("\t".join(headers))
    for row in rows:
        values = [
            str(row.get("input_pdf", "")),
            str(row.get("status", "")),
            str(row.get("type0_font_count", "")),
            str(row.get("decoded_font_resource_count", "")),
            str(row.get("text_object_count", "")),
        ]
        if has_probe:
            probe = row.get("probe") if isinstance(row.get("probe"), dict) else {}
            values.extend(
                [
                    str(probe.get("status", "")),
                    str(probe.get("total_matches", "")),
                    str(probe.get("feasible", "")),
                ]
            )
        values.append(str(row.get("reason", "")))
        print("\t".join(values))


def print_summary(summary: dict[str, Any]) -> None:
    print("summary")
    print(f"total_pdfs\t{summary['total_pdfs']}")
    print(f"total_size_bytes\t{summary['total_size_bytes']}")
    print(f"status_counts\t{json.dumps(summary['status_counts'], sort_keys=True)}")
    print(f"reason_counts\t{json.dumps(summary['reason_counts'], sort_keys=True)}")
    print(f"total_type0_fonts\t{summary['total_type0_fonts']}")
    print(f"total_decoded_font_resources\t{summary['total_decoded_font_resources']}")
    print(f"total_text_objects\t{summary['total_text_objects']}")
    if "probe_status_counts" in summary:
        print(f"probe_status_counts\t{json.dumps(summary['probe_status_counts'], sort_keys=True)}")
        print(f"probe_total_matches\t{summary['probe_total_matches']}")
        print(f"probe_feasible_pdfs\t{summary['probe_feasible_pdfs']}")


def fail_on_matches(rows: list[dict[str, Any]], fail_on: list[str]) -> list[dict[str, Any]]:
    """Return row/rule matches for caller-selected inventory gates."""
    matches: list[dict[str, Any]] = []
    selected = set(fail_on)
    for row in rows:
        row_rules: list[str] = []
        status = row.get("status")
        if "error" in selected and status == "error":
            row_rules.append("error")
        if "unsupported" in selected and status == "unsupported":
            row_rules.append("unsupported")
        if "skipped" in selected and status == "skipped":
            row_rules.append("skipped")
        if (
            "qpdf-check-failed" in selected
            and row.get("qpdf_check") is False
            and row.get("reason") == "qpdf --check failed"
        ):
            row_rules.append("qpdf-check-failed")
        if (
            "qdf-conversion-failed" in selected
            and row.get("qdf_conversion") is False
            and row.get("reason") == "qpdf QDF conversion failed"
        ):
            row_rules.append("qdf-conversion-failed")

        probe = row.get("probe")
        if isinstance(probe, dict):
            probe_status = probe.get("status")
            if "probe-unsupported" in selected and probe_status == "unsupported":
                row_rules.append("probe-unsupported")
            if "probe-no-match" in selected and probe_status == "no_match":
                row_rules.append("probe-no-match")
            if "probe-infeasible" in selected and probe_status == "infeasible":
                row_rules.append("probe-infeasible")
            if "probe-feasible" in selected and probe_status == "feasible":
                row_rules.append("probe-feasible")
            if "probe-match" in selected and int(probe.get("total_matches") or 0) > 0:
                row_rules.append("probe-match")

        if row_rules:
            matches.append(
                {
                    "input_pdf": row.get("input_pdf", ""),
                    "status": status,
                    "probe_status": probe.get("status", "") if isinstance(probe, dict) else "",
                    "rules": row_rules,
                }
            )
    return matches


def print_fail_on_matches(matches: list[dict[str, Any]]) -> None:
    print("fail_on_matches", file=sys.stderr)
    print("input_pdf\tstatus\tprobe_status\trules", file=sys.stderr)
    for match in matches:
        print(
            "\t".join(
                [
                    str(match.get("input_pdf", "")),
                    str(match.get("status", "")),
                    str(match.get("probe_status", "")),
                    ",".join(str(rule) for rule in match.get("rules", [])),
                ]
            ),
            file=sys.stderr,
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory PDFs for pdf-mutation support without extracting text content."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("pdfs", nargs="+", type=Path, help="PDF files to classify")
    parser.add_argument("--json", type=Path, help="write JSON inventory to this path")
    parser.add_argument("--tsv", type=Path, help="write TSV inventory to this path")
    parser.add_argument("--keep-qdf-dir", type=Path, help="write generated QDF files here")
    parser.add_argument(
        "--probe",
        nargs=2,
        metavar=("SEARCH", "REPLACEMENT"),
        help="include non-sensitive match feasibility for this search/replacement pair",
    )
    parser.add_argument(
        "--align",
        choices=("exact", "left", "right"),
        default="exact",
        help="alignment policy used by --probe for length-changing replacements",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="include aggregate counts by inventory status and probe status",
    )
    parser.add_argument(
        "--max-input-bytes",
        type=int,
        help="skip QDF conversion for PDFs larger than this many bytes",
    )
    parser.add_argument(
        "--fail-on",
        nargs="+",
        choices=FAIL_ON_CHOICES,
        default=[],
        metavar="RULE",
        help="exit non-zero when any selected inventory rule matches",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    glyph.require_tool("qpdf")
    rows = [
        inventory_pdf(
            pdf,
            keep_qdf_dir=args.keep_qdf_dir,
            probe=tuple(args.probe) if args.probe else None,
            align=args.align,
            max_input_bytes=args.max_input_bytes,
        )
        for pdf in args.pdfs
    ]
    summary = build_summary(rows) if args.summary else None
    write_outputs(rows, json_path=args.json, tsv_path=args.tsv, summary=summary)
    if not args.json:
        print_table(rows)
        if summary is not None:
            print_summary(summary)
    matches = fail_on_matches(rows, args.fail_on)
    if matches:
        print_fail_on_matches(matches)
        return 2
    return 1 if any(row["status"] == "error" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
