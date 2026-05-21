#!/usr/bin/env python3
"""Synthetic PDF/QDF fixture helpers for pdf-mutation tests and public repros."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


__version__ = "0.1.7"

DEFAULT_CIDS: dict[str, str] = {
    " ": "0003",
    ".": "0004",
    "$": "0093",
    "A": "00FF",
    "0": "002A",
    "1": "002B",
    "2": "002C",
    "3": "002D",
    "4": "002E",
    "5": "002F",
    "6": "0030",
    "7": "0031",
    "8": "0032",
    "9": "0033",
    "a": "0119",
    "b": "011A",
    "c": "011B",
}


def _utf16_hex(char: str) -> str:
    return char.encode("utf-16-be").hex().upper()


def cmap_stream(cid_map: dict[str, str] | None = None) -> bytes:
    """Return a minimal ToUnicode CMap for a synthetic Type0 font."""
    cid_map = cid_map or DEFAULT_CIDS
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo",
        "<< /Registry (Adobe)",
        "/Ordering (UCS)",
        "/Supplement 0",
        ">> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
        f"{len(cid_map)} beginbfchar",
    ]
    for char, cid in sorted(cid_map.items(), key=lambda item: item[1]):
        lines.append(f"<{cid}> <{_utf16_hex(char)}>")
    lines.extend(
        [
            "endbfchar",
            "endcmap",
            "CMapName currentdict /CMap defineresource pop",
            "end",
            "end",
            "",
        ]
    )
    return "\n".join(lines).encode("ascii")


def cid_hex(text: str, cid_map: dict[str, str] | None = None) -> str:
    """Encode text as concatenated four-hex-digit CIDs."""
    cid_map = cid_map or DEFAULT_CIDS
    missing = sorted({char for char in text if char not in cid_map})
    if missing:
        escaped = ", ".join(repr(char) for char in missing)
        raise ValueError(f"character(s) not present in synthetic font: {escaped}")
    return "".join(cid_map[char] for char in text)


def text_object(
    text: str,
    *,
    font: str = "F4",
    font_size: str = "16",
    x: str = "100",
    y: str = "10",
    one_glyph_per_line: bool = False,
    advance: str = "9.6",
    punctuation_advance: str = "3.6",
    cid_map: dict[str, str] | None = None,
) -> bytes:
    """Return a synthetic text object body for one decoded text string."""
    cid_map = cid_map or DEFAULT_CIDS
    lines = [f"/{font} {font_size} Tf", f"1 0 0 -1 {x} {y} Tm"]
    if not one_glyph_per_line:
        lines.append(f"<{cid_hex(text, cid_map)}> Tj")
        return "\n".join(lines).encode("ascii")

    previous_char: str | None = None
    for char in text:
        cid = cid_hex(char, cid_map)
        if previous_char is None:
            lines.append(f"<{cid}> Tj")
        else:
            td = punctuation_advance if previous_char == "." else advance
            lines.append(f"{td} 0 Td <{cid}> Tj")
        previous_char = char
    return "\n".join(lines).encode("ascii")


def qdf_document(*text_objects: bytes, cid_map: dict[str, str] | None = None) -> bytes:
    """Return a complete synthetic QDF byte stream for one or more text objects."""
    cid_map = cid_map or DEFAULT_CIDS
    body = b"\nET\nBT\n".join(text_objects)
    return (
        b"""1 0 obj
<<
  /Resources <<
    /Font <<
      /F4 25 0 R
    >>
  >>
>>
endobj
25 0 obj
<<
  /BaseFont /AAAAAA+SyntheticFixture
  /DescendantFonts [48 0 R]
  /Encoding /Identity-H
  /Subtype /Type0
  /ToUnicode 49 0 R
  /Type /Font
>>
endobj
49 0 obj
<<
  /Length 50 0 R
>>
stream
"""
        + cmap_stream(cid_map)
        + b"""endstream
endobj
51 0 obj
<<
  /Length 52 0 R
>>
stream
BT
"""
        + body
        + b"""
ET
endstream
endobj
"""
    )


def synthetic_qdf(
    text: str,
    *,
    one_glyph_per_line: bool = False,
    x: str = "100",
    y: str = "10",
) -> bytes:
    """Build a complete synthetic QDF document containing one text object."""
    return qdf_document(text_object(text, one_glyph_per_line=one_glyph_per_line, x=x, y=y))


def _pdf_stream_dict(payload: bytes) -> bytes:
    return b"<<\n  /Length " + str(len(payload)).encode("ascii") + b"\n>>\nstream\n" + payload + b"endstream"


def synthetic_pdf(
    text: str,
    *,
    one_glyph_per_line: bool = False,
    x: str = "100",
    y: str = "10",
) -> bytes:
    """Build a standalone PDF containing one synthetic Type0-font text object."""
    content = b"BT\n" + text_object(text, one_glyph_per_line=one_glyph_per_line, x=x, y=y) + b"\nET\n"
    cmap = cmap_stream()
    objects = [
        (1, b"<<\n  /Type /Catalog\n  /Pages 2 0 R\n>>"),
        (2, b"<<\n  /Type /Pages\n  /Kids [3 0 R]\n  /Count 1\n>>"),
        (
            3,
            b"<<\n"
            b"  /Type /Page\n"
            b"  /Parent 2 0 R\n"
            b"  /MediaBox [0 0 800 1600]\n"
            b"  /Resources << /Font << /F4 5 0 R >> >>\n"
            b"  /Contents 4 0 R\n"
            b">>",
        ),
        (4, _pdf_stream_dict(content)),
        (
            5,
            b"<<\n"
            b"  /Type /Font\n"
            b"  /Subtype /Type0\n"
            b"  /BaseFont /AAAAAA+SyntheticFixture\n"
            b"  /Encoding /Identity-H\n"
            b"  /DescendantFonts [6 0 R]\n"
            b"  /ToUnicode 7 0 R\n"
            b">>",
        ),
        (
            6,
            b"<<\n"
            b"  /Type /Font\n"
            b"  /Subtype /CIDFontType2\n"
            b"  /BaseFont /AAAAAA+SyntheticFixture\n"
            b"  /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >>\n"
            b"  /DW 600\n"
            b">>",
        ),
        (7, _pdf_stream_dict(cmap)),
    ]

    chunks = [b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n"]
    offsets: dict[int, int] = {}
    for object_id, payload in objects:
        offsets[object_id] = sum(len(chunk) for chunk in chunks)
        chunks.append(str(object_id).encode("ascii") + b" 0 obj\n" + payload + b"\nendobj\n")
    xref_offset = sum(len(chunk) for chunk in chunks)
    chunks.append(b"xref\n0 8\n0000000000 65535 f \n")
    for object_id in range(1, 8):
        chunks.append(f"{offsets[object_id]:010d} 00000 n \n".encode("ascii"))
    chunks.append(
        b"trailer\n<<\n  /Size 8\n  /Root 1 0 R\n>>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    return b"".join(chunks)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic PDF or QDF fixture for pdf-mutation repros."
    )
    parser.add_argument("text", help="decoded text to encode into the fixture")
    parser.add_argument("-o", "--output", type=Path, help="write fixture to this path")
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="write a standalone PDF instead of the default QDF-like fixture",
    )
    parser.add_argument(
        "--one-glyph-per-line",
        action="store_true",
        help="emit each glyph as a separate hexadecimal Tj line with Td advances",
    )
    parser.add_argument("--x", default="100", help="text matrix x coordinate")
    parser.add_argument("--y", default="10", help="text matrix y coordinate")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        fixture = (
            synthetic_pdf(
                args.text,
                one_glyph_per_line=args.one_glyph_per_line,
                x=args.x,
                y=args.y,
            )
            if args.pdf
            else synthetic_qdf(
                args.text,
                one_glyph_per_line=args.one_glyph_per_line,
                x=args.x,
                y=args.y,
            )
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.output:
        args.output.write_bytes(fixture)
    else:
        sys.stdout.buffer.write(fixture)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
