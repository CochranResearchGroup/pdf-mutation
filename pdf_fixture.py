#!/usr/bin/env python3
"""Synthetic QDF fixture helpers for pdf-mutation tests and public repros."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


__version__ = "0.1.3"

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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic QDF fixture for pdf-mutation repros."
    )
    parser.add_argument("text", help="decoded text to encode into the fixture")
    parser.add_argument("-o", "--output", type=Path, help="write fixture to this path")
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
        qdf = synthetic_qdf(
            args.text,
            one_glyph_per_line=args.one_glyph_per_line,
            x=args.x,
            y=args.y,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.output:
        args.output.write_bytes(qdf)
    else:
        sys.stdout.buffer.write(qdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
