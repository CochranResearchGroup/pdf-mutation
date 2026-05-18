#!/usr/bin/env python3
"""Non-mutating PDF inventory for pdf-mutation dogfood corpora."""

from __future__ import annotations

import argparse
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


def inventory_pdf(path: Path, *, keep_qdf_dir: Path | None = None) -> dict[str, Any]:
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
            "duration_seconds",
        ]
        with tsv_path.open("w", encoding="utf-8") as handle:
            handle.write("\t".join(headers) + "\n")
            for row in rows:
                handle.write("\t".join(str(row.get(header, "")) for header in headers) + "\n")


def print_table(rows: list[dict[str, Any]]) -> None:
    headers = ("input_pdf", "status", "type0", "decoded_fonts", "text_objects", "reason")
    print("\t".join(headers))
    for row in rows:
        print(
            "\t".join(
                [
                    str(row.get("input_pdf", "")),
                    str(row.get("status", "")),
                    str(row.get("type0_font_count", "")),
                    str(row.get("decoded_font_resource_count", "")),
                    str(row.get("text_object_count", "")),
                    str(row.get("reason", "")),
                ]
            )
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    glyph.require_tool("qpdf")
    rows = [inventory_pdf(pdf, keep_qdf_dir=args.keep_qdf_dir) for pdf in args.pdfs]
    write_outputs(rows, json_path=args.json, tsv_path=args.tsv)
    if not args.json:
        print_table(rows)
    return 1 if any(row["status"] == "error" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
