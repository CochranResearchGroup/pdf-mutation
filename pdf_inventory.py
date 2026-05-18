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


__version__ = "0.1.1"


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


def write_outputs(rows: list[dict[str, Any]], *, json_path: Path | None, tsv_path: Path | None) -> None:
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
        )
        for pdf in args.pdfs
    ]
    write_outputs(rows, json_path=args.json, tsv_path=args.tsv)
    if not args.json:
        print_table(rows)
    return 1 if any(row["status"] == "error" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
