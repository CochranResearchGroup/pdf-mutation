#!/usr/bin/env python3
"""Glyph-preserving search/replace for simple encoded PDF text.

This tool rewrites hexadecimal ``Tj`` glyph operands in a qpdf QDF rendering.
It decodes text through each font's ToUnicode CMap, finds literal text
matches, and replaces only the glyph CIDs. Drawing operators, coordinates,
font resources, and spacing commands are left intact.

The first supported mode is deliberately narrow: search and replacement must
decode to the same number of glyphs inside a single PDF text object. That makes
card/account/token substitutions deterministic and layout-preserving.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path


__version__ = "0.1.1"

OBJ_RE = re.compile(rb"(?m)^(\d+) 0 obj\n(.*?)\nendobj", re.S)
STREAM_RE = re.compile(rb"(stream\n)(.*?)(\nendstream)", re.S)
FONT_RESOURCE_RE = re.compile(rb"/(F[^\s/<>\[\]()]+)\s+(\d+)\s+0\s+R")
TO_UNICODE_RE = re.compile(rb"/ToUnicode\s+(\d+)\s+0\s+R")
BFCHAR_LINE_RE = re.compile(rb"^\s*<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s*$")
BFRANGE_ARRAY_LINE_RE = re.compile(
    rb"^\s*<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s+\[(.*?)\]\s*$"
)
BFRANGE_BASE_LINE_RE = re.compile(
    rb"^\s*<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s*$"
)
BT_ET_RE = re.compile(rb"BT\n(.*?)\nET", re.S)
FONT_SET_RE = re.compile(rb"/(F[^\s/<>\[\]()]+)\s+[-+.0-9]+\s+Tf")
HEX_TJ_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*Tj")
TJ_ARRAY_RE = re.compile(rb"\[(.*?)\]\s*TJ", re.S)
HEX_STRING_RE = re.compile(rb"<([0-9A-Fa-f]+)>")
DRAW_LINE_RE = re.compile(rb"(?m)^(?:(?P<td>[-+.0-9]+) 0 Td )?<(?P<hex>[0-9A-Fa-f]+)> Tj$")
TEXT_MATRIX_RE = re.compile(rb"1 0 0 -1 ([-+.0-9]+) ([-+.0-9]+) Tm", re.M)


@dataclasses.dataclass
class Glyph:
    char: str
    cid: str
    match: re.Match[bytes]
    chunk_start: int
    chunk_end: int


@dataclasses.dataclass
class TextObjectReport:
    text_object_index: int
    stream_object: int | None
    font: str
    decoded_text: str
    match_count: int
    feasible: bool
    reason: str
    alignment_contract: str = ""
    estimated_x_shift: str = ""


def run(args: list[str], *, stdin: bytes | None = None) -> bytes:
    proc = subprocess.run(args, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        raise SystemExit(proc.returncode)
    return proc.stdout


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"required executable not found on PATH: {name}")


def hex_to_text(hex_value: bytes) -> str:
    raw = bytes.fromhex(hex_value.decode("ascii"))
    try:
        return raw.decode("utf-16-be")
    except UnicodeDecodeError:
        return "".join(chr(b) for b in raw)


def int_hex(value: bytes) -> int:
    return int(value.decode("ascii"), 16)


def width_for(start_hex: bytes) -> int:
    return len(start_hex.decode("ascii"))


def parse_cmap(stream: bytes) -> dict[str, str]:
    mapping: dict[str, str] = {}
    mode: str | None = None
    for line in stream.splitlines():
        if b"beginbfchar" in line:
            mode = "bfchar"
            continue
        if b"endbfchar" in line and mode == "bfchar":
            mode = None
            continue
        if b"beginbfrange" in line:
            mode = "bfrange"
            continue
        if b"endbfrange" in line and mode == "bfrange":
            mode = None
            continue

        if mode == "bfchar":
            match = BFCHAR_LINE_RE.match(line)
            if match:
                src, dst = match.groups()
                mapping[src.decode("ascii").upper()] = hex_to_text(dst)
        elif mode == "bfrange":
            array_match = BFRANGE_ARRAY_LINE_RE.match(line)
            if array_match:
                start, end, array_body = array_match.groups()
                width = width_for(start)
                cid = int_hex(start)
                end_cid = int_hex(end)
                values = re.findall(rb"<([0-9A-Fa-f]+)>", array_body)
                if len(values) == end_cid - cid + 1:
                    for offset, dst in enumerate(values):
                        mapping[f"{cid + offset:0{width}X}"] = hex_to_text(dst)
                continue

            base_match = BFRANGE_BASE_LINE_RE.match(line)
            if base_match:
                start, end, dst_start = base_match.groups()
                width = width_for(start)
                cid = int_hex(start)
                end_cid = int_hex(end)
                dst = int_hex(dst_start)
                dst_width = width_for(dst_start)
                for offset in range(end_cid - cid + 1):
                    mapping[f"{cid + offset:0{width}X}"] = hex_to_text(
                        f"{dst + offset:0{dst_width}X}".encode("ascii")
                    )
    return mapping


def parse_objects(qdf: bytes) -> dict[int, bytes]:
    return {int(num): body for num, body in OBJ_RE.findall(qdf)}


def stream_of(obj_body: bytes) -> bytes | None:
    match = STREAM_RE.search(obj_body)
    return match.group(2) if match else None


def build_font_maps(objects: dict[int, bytes]) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    to_unicode_by_font_obj: dict[int, int] = {}
    for obj_num, body in objects.items():
        match = TO_UNICODE_RE.search(body)
        if match:
            to_unicode_by_font_obj[obj_num] = int(match.group(1))

    resource_to_font_obj: dict[str, int] = {}
    for body in objects.values():
        for name, obj_num in FONT_RESOURCE_RE.findall(body):
            obj_int = int(obj_num)
            if obj_int in to_unicode_by_font_obj:
                resource_to_font_obj[name.decode("ascii")] = obj_int

    decode_maps: dict[str, dict[str, str]] = {}
    encode_maps: dict[str, dict[str, str]] = {}
    for resource, font_obj in resource_to_font_obj.items():
        cmap_obj = to_unicode_by_font_obj[font_obj]
        stream = stream_of(objects[cmap_obj])
        if not stream:
            continue
        decode = parse_cmap(stream)
        encode: dict[str, str] = {}
        for cid, char in decode.items():
            encode.setdefault(char, cid)
        decode_maps[resource] = decode
        encode_maps[resource] = encode
    return decode_maps, encode_maps


def iter_text_hex_strings(body: bytes) -> list[re.Match[bytes]]:
    matches: list[re.Match[bytes]] = list(HEX_TJ_RE.finditer(body))
    for array_match in TJ_ARRAY_RE.finditer(body):
        for hex_match in HEX_STRING_RE.finditer(array_match.group(1)):
            matches.append(
                _OffsetMatch(
                    hex_match,
                    group_offset=array_match.start(1),
                    full_start=array_match.start(1) + hex_match.start(),
                    full_end=array_match.start(1) + hex_match.end(),
                )
            )
    return sorted(matches, key=lambda match: match.start())


class _OffsetMatch:
    def __init__(self, match: re.Match[bytes], *, group_offset: int, full_start: int, full_end: int):
        self._match = match
        self._group_offset = group_offset
        self._full_start = full_start
        self._full_end = full_end

    def group(self, index: int = 0) -> bytes:
        return self._match.group(index)

    def start(self, index: int = 0) -> int:
        if index == 0:
            return self._full_start
        return self._group_offset + self._match.start(index)

    def end(self, index: int = 0) -> int:
        if index == 0:
            return self._full_end
        return self._group_offset + self._match.end(index)


def glyphs_for_text_object(body: bytes, decode: dict[str, str]) -> list[Glyph]:
    glyphs: list[Glyph] = []
    for match in iter_text_hex_strings(body):
        hex_operand = match.group(1).decode("ascii").upper()
        if len(hex_operand) % 4:
            continue
        for offset in range(0, len(hex_operand), 4):
            cid = hex_operand[offset : offset + 4]
            glyphs.append(
                Glyph(
                    decode.get(cid, ""),
                    cid,
                    match,
                    match.start(1) + offset,
                    match.start(1) + offset + 4,
                )
            )
    return glyphs


def replace_in_text_object(
    body: bytes,
    *,
    search: str,
    replacement: str,
    align: str,
    decode_maps: dict[str, dict[str, str]],
    encode_maps: dict[str, dict[str, str]],
) -> tuple[bytes, int]:
    font_match = FONT_SET_RE.search(body)
    if not font_match:
        return body, 0
    font_name = font_match.group(1).decode("ascii")
    decode = decode_maps.get(font_name)
    encode = encode_maps.get(font_name)
    if not decode or not encode:
        return body, 0

    glyphs = glyphs_for_text_object(body, decode)
    decoded = "".join(g.char for g in glyphs)
    if search not in decoded:
        return body, 0
    if len(search) != len(replacement):
        if align in {"left", "right"}:
            return replace_variable_width_aligned(
                body,
                search=search,
                replacement=replacement,
                align=align,
                decode=decode,
                encode=encode,
                font_name=font_name,
            )
        raise SystemExit(
            "replacement must have the same decoded glyph count as search "
            f"unless --align left or --align right is used: {search!r} -> {replacement!r}"
        )
    for char in replacement:
        if char not in encode:
            raise SystemExit(f"replacement character {char!r} is not present in font /{font_name}")

    replacements: dict[int, str] = {}
    count = 0
    start = 0
    while True:
        index = decoded.find(search, start)
        if index < 0:
            break
        for offset, char in enumerate(replacement):
            replacements[index + offset] = encode[char]
        count += 1
        start = index + len(search)
    if not replacements:
        return body, 0

    chunk_replacements: dict[tuple[int, int], str] = {}
    glyph_index = 0
    for match in iter_text_hex_strings(body):
        hex_operand = match.group(1).decode("ascii").upper()
        if len(hex_operand) % 4:
            glyph_index += 1
            continue
        for offset in range(0, len(hex_operand), 4):
            if glyph_index in replacements:
                chunk_replacements[
                    (match.start(1) + offset, match.start(1) + offset + 4)
                ] = replacements[glyph_index]
            glyph_index += 1

    rebuilt = bytearray()
    pos = 0
    for (start_pos, end_pos), cid in sorted(chunk_replacements.items()):
        rebuilt.extend(body[pos:start_pos])
        rebuilt.extend(cid.encode("ascii"))
        pos = end_pos
    rebuilt.extend(body[pos:])
    return bytes(rebuilt), count


def format_decimal(value: Decimal) -> bytes:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return text.encode("ascii")


def replacement_cids(replacement: str, encode: dict[str, str], font_name: str) -> list[str]:
    cids: list[str] = []
    for char in replacement:
        if char not in encode:
            raise SystemExit(f"replacement character {char!r} is not present in font /{font_name}")
        cids.append(encode[char])
    return cids


def infer_default_advance(draws: list[re.Match[bytes]]) -> bytes:
    advances = [m.group("td") for m in draws if m.group("td")]
    if not advances:
        raise SystemExit("--align right requires Td advances in the text object")
    # Ignore very narrow punctuation spacing when possible; the dominant advance
    # is the deterministic choice for inserted same-style glyphs in tabular text.
    wide = [a for a in advances if abs(Decimal(a.decode("ascii"))) >= Decimal("5")]
    return Counter(wide or advances).most_common(1)[0][0]


def infer_previous_char_advances(chars: list[str], draws: list[re.Match[bytes]]) -> dict[str, bytes]:
    by_previous: dict[str, list[bytes]] = {}
    for index in range(1, min(len(chars), len(draws))):
        td = draws[index].group("td")
        if td:
            by_previous.setdefault(chars[index - 1], []).append(td)
    return {char: Counter(values).most_common(1)[0][0] for char, values in by_previous.items()}


def replace_variable_width_aligned(
    body: bytes,
    *,
    search: str,
    replacement: str,
    align: str,
    decode: dict[str, str],
    encode: dict[str, str],
    font_name: str,
) -> tuple[bytes, int]:
    draws = list(DRAW_LINE_RE.finditer(body))
    if not draws:
        raise SystemExit(f"--align {align} requires one-glyph-per-line hexadecimal Tj text")

    chars: list[str] = []
    for draw in draws:
        hex_operand = draw.group("hex").decode("ascii").upper()
        if len(hex_operand) != 4:
            raise SystemExit(f"--align {align} currently requires one CID per Tj operand")
        chars.append(decode.get(hex_operand, ""))
    decoded = "".join(chars)
    match_positions: list[int] = []
    start = 0
    while True:
        index = decoded.find(search, start)
        if index < 0:
            break
        match_positions.append(index)
        start = index + len(search)
    if not match_positions:
        return body, 0
    if len(match_positions) > 1:
        raise SystemExit(f"--align {align} currently supports one match per text object")

    tm_match = TEXT_MATRIX_RE.search(body)
    if not tm_match:
        raise SystemExit(f"--align {align} requires a simple '1 0 0 -1 x y Tm' text matrix")

    replacement_codes = replacement_cids(replacement, encode, font_name)
    default_advance = infer_default_advance(draws)
    previous_char_advances = infer_previous_char_advances(chars, draws)
    delta_count = len(replacement) - len(search)
    shift = Decimal(default_advance.decode("ascii")) * Decimal(delta_count)
    old_x = Decimal(tm_match.group(1).decode("ascii"))
    new_x = old_x if align == "left" else old_x - shift

    index = match_positions[0]
    old_len = len(search)
    old_draws = draws[index : index + old_len]
    if len(old_draws) != old_len:
        raise SystemExit("internal error: match extends beyond parsed glyph draws")

    replacement_lines: list[bytes] = []
    for offset, cid in enumerate(replacement_codes):
        if offset == 0 and old_draws[0].group("td"):
            td = old_draws[offset].group("td")
        else:
            td = previous_char_advances.get(replacement[offset - 1], default_advance)
        if td:
            replacement_lines.append(td + b" 0 Td <" + cid.encode("ascii") + b"> Tj")
        else:
            replacement_lines.append(b"<" + cid.encode("ascii") + b"> Tj")

    rebuilt = bytearray()
    rebuilt.extend(body[: tm_match.start(1)])
    rebuilt.extend(format_decimal(new_x))
    rebuilt.extend(body[tm_match.end(1) : old_draws[0].start()])
    rebuilt.extend(b"\n".join(replacement_lines))
    rebuilt.extend(body[old_draws[-1].end() :])
    return bytes(rebuilt), 1


def replace_qdf(qdf: bytes, search: str, replacement: str, *, align: str) -> tuple[bytes, int]:
    objects = parse_objects(qdf)
    decode_maps, encode_maps = build_font_maps(objects)
    if not decode_maps:
        raise SystemExit("no Type0 fonts with ToUnicode CMaps found")

    total = 0

    def replace_stream(match: re.Match[bytes]) -> bytes:
        nonlocal total
        prefix, stream, suffix = match.groups()

        def replace_text_object(text_match: re.Match[bytes]) -> bytes:
            nonlocal total
            new_body, count = replace_in_text_object(
                text_match.group(1),
                search=search,
                replacement=replacement,
                align=align,
                decode_maps=decode_maps,
                encode_maps=encode_maps,
            )
            total += count
            return b"BT\n" + new_body + b"\nET"

        new_stream = BT_ET_RE.sub(replace_text_object, stream)
        return prefix + new_stream + suffix

    return STREAM_RE.sub(replace_stream, qdf), total


def replacement_chars_available(replacement: str, encode: dict[str, str]) -> tuple[bool, str]:
    missing = sorted({char for char in replacement if char not in encode})
    if missing:
        escaped = ", ".join(repr(char) for char in missing)
        return False, f"replacement character(s) not present in active font: {escaped}"
    return True, "ok"


def alignment_diagnostics(
    body: bytes, search: str, replacement: str, decoded: str, *, align: str
) -> tuple[bool, str, str, str]:
    draws = list(DRAW_LINE_RE.finditer(body))
    if not draws:
        return False, f"{align} align requires one-glyph-per-line hexadecimal Tj text", "", ""
    for draw in draws:
        if len(draw.group("hex")) != 4:
            return False, f"{align} align requires exactly one CID per Tj operand", "", ""
    match_count = decoded.count(search)
    if match_count != 1:
        return False, f"{align} align requires exactly one match per text object", "", ""
    if not TEXT_MATRIX_RE.search(body):
        return False, f"{align} align requires a simple '1 0 0 -1 x y Tm' text matrix", "", ""
    if not any(draw.group("td") for draw in draws):
        return False, f"{align} align requires Td advances in the text object", "", ""
    try:
        default_advance = Decimal(infer_default_advance(draws).decode("ascii"))
    except Exception:
        return False, f"{align} align could not infer a deterministic glyph advance", "", ""
    delta_count = len(replacement) - len(search)
    x_shift = Decimal("0") if align == "left" else -(default_advance * Decimal(delta_count))
    contract = (
        "preserve left edge and original text matrix"
        if align == "left"
        else "preserve right edge by shifting text matrix left for inserted glyph advance"
    )
    return True, "ok", contract, format_decimal(x_shift).decode("ascii")


def analyze_qdf(
    qdf: bytes, search: str, replacement: str, *, align: str
) -> tuple[list[TextObjectReport], dict[str, dict[str, str]]]:
    objects = parse_objects(qdf)
    decode_maps, encode_maps = build_font_maps(objects)
    if not decode_maps:
        raise SystemExit("no Type0 fonts with ToUnicode CMaps found")

    reports: list[TextObjectReport] = []
    decoded_objects: list[tuple[int, str, str]] = []
    text_object_index = 0
    for stream_object, object_body in objects.items():
        stream = stream_of(object_body)
        if stream is None:
            continue
        for text_match in BT_ET_RE.finditer(stream):
            text_object_index += 1
            body = text_match.group(1)
            font_match = FONT_SET_RE.search(body)
            if not font_match:
                continue
            font_name = font_match.group(1).decode("ascii")
            decode = decode_maps.get(font_name)
            encode = encode_maps.get(font_name)
            if not decode or not encode:
                continue

            glyphs = glyphs_for_text_object(body, decode)
            decoded = "".join(g.char for g in glyphs)
            decoded_objects.append((text_object_index, font_name, decoded))
            match_count = decoded.count(search)
            if not match_count:
                continue

            feasible, reason = replacement_chars_available(replacement, encode)
            alignment_contract = ""
            estimated_x_shift = ""
            if feasible and len(search) != len(replacement):
                if align not in {"left", "right"}:
                    feasible = False
                    reason = "replacement changes glyph count; use --align left or --align right for supported text"
                else:
                    feasible, reason, contract, x_shift = alignment_diagnostics(
                        body, search, replacement, decoded, align=align
                    )
                    if feasible:
                        alignment_contract = contract
                        estimated_x_shift = x_shift
                    else:
                        alignment_contract = ""
                        estimated_x_shift = ""
            else:
                alignment_contract = "exact glyph-count replacement preserves existing layout operators"
                estimated_x_shift = "0"

            reports.append(
                TextObjectReport(
                    text_object_index=text_object_index,
                    stream_object=stream_object,
                    font=font_name,
                    decoded_text=decoded,
                    match_count=match_count,
                    feasible=feasible,
                    reason=reason,
                    alignment_contract=alignment_contract,
                    estimated_x_shift=estimated_x_shift,
                )
            )
    if not reports:
        joined = "".join(decoded for _, _, decoded in decoded_objects)
        if search in joined:
            reports.append(
                TextObjectReport(
                    text_object_index=0,
                    stream_object=None,
                    font="multiple",
                    decoded_text=search,
                    match_count=1,
                    feasible=False,
                    reason="match appears split across text objects or font changes",
                )
            )
    return reports, decode_maps


def print_dry_run_report(
    reports: list[TextObjectReport],
    decode_maps: dict[str, dict[str, str]],
    *,
    search: str,
    replacement: str,
    align: str,
    as_json: bool,
) -> None:
    total = sum(report.match_count for report in reports)
    feasible = total > 0 and all(report.feasible for report in reports)
    if as_json:
        payload = {
            "align": align,
            "search": search,
            "replacement": replacement,
            "font_resources": [
                {"font": font, "decoded_glyphs": len(decode_maps[font])}
                for font in sorted(decode_maps)
            ],
            "total_matches": total,
            "feasible": feasible,
            "matches": [dataclasses.asdict(report) for report in reports],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    print(f"dry-run: {search!r} -> {replacement!r} align={align}")
    print("font resources:")
    for font in sorted(decode_maps):
        print(f"- /{font}: decoded_glyphs={len(decode_maps[font])}")
    print(f"total matches: {total}")
    print(f"feasible: {'yes' if feasible else 'no'}")
    if reports:
        print("matches:")
    for report in reports:
        preview = report.decoded_text.replace("\n", "\\n")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        print(
            f"- text_object={report.text_object_index} font=/{report.font} "
            f"count={report.match_count} feasible={'yes' if report.feasible else 'no'} "
            f"reason={report.reason} text={preview!r}"
        )


def report_payload(
    *,
    input_pdf: Path,
    output_pdf: Path | None,
    search: str,
    replacement: str,
    align: str,
    reports: list[TextObjectReport],
    decode_maps: dict[str, dict[str, str]],
    dry_run: bool,
) -> dict[str, object]:
    total = sum(report.match_count for report in reports)
    feasible = total > 0 and all(report.feasible for report in reports)
    return {
        "version": __version__,
        "mode": "dry-run" if dry_run else "write",
        "input_pdf": str(input_pdf),
        "output_pdf": str(output_pdf) if output_pdf else None,
        "align": align,
        "search_length": len(search),
        "replacement_length": len(replacement),
        "search_sha256_12": hashlib.sha256(search.encode("utf-8")).hexdigest()[:12],
        "replacement_sha256_12": hashlib.sha256(replacement.encode("utf-8")).hexdigest()[:12],
        "font_resources": [
            {"font": font, "decoded_glyphs": len(decode_maps[font])}
            for font in sorted(decode_maps)
        ],
        "total_matches": total,
        "feasible": feasible,
        "matches": [
            {
                "text_object_index": report.text_object_index,
                "stream_object": report.stream_object,
                "font": report.font,
                "match_count": report.match_count,
                "feasible": report.feasible,
                "reason": report.reason,
                "alignment_contract": report.alignment_contract,
                "estimated_x_shift": report.estimated_x_shift,
            }
            for report in reports
        ],
        "validation_hints": [
            "qpdf --check <output.pdf>",
            "pdftotext <output.pdf> - | rg '<expected-or-old-text>'",
            "pdftotext -bbox <output.pdf> <report>.bbox.html  # when layout preservation matters",
        ],
        "privacy": {
            "decoded_text_included": False,
            "literal_search_replacement_included": False,
        },
    }


def write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Glyph-preserving PDF search/replace using qpdf QDF and ToUnicode CMaps."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("search")
    parser.add_argument("replacement")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument(
        "--align",
        choices=("exact", "left", "right"),
        default="exact",
        help=(
            "alignment policy for length-changing replacements. "
            "'exact' requires equal glyph counts; 'left' preserves the text matrix; "
            "'right' preserves the right edge for simple one-glyph-per-line text objects."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="report decoded matches and feasibility without writing a PDF")
    parser.add_argument("--json", action="store_true", help="emit dry-run report as JSON")
    parser.add_argument("--keep-qdf", type=Path, help="write the edited QDF for inspection")
    parser.add_argument("--report", type=Path, help="write a non-sensitive JSON mutation report")
    args = parser.parse_args()

    if not args.dry_run and not args.output:
        parser.error("-o/--output is required unless --dry-run is used")
    if args.json and not args.dry_run:
        parser.error("--json is only supported with --dry-run")

    require_tool("qpdf")
    if not args.dry_run:
        require_tool("fix-qdf")

    with tempfile.TemporaryDirectory(prefix="pdf-glyph-replace-") as tmp:
        qdf_path = Path(tmp) / "input.qdf.pdf"
        fixed_path = Path(tmp) / "fixed.qdf.pdf"
        run(["qpdf", "--qdf", "--object-streams=disable", str(args.input_pdf), str(qdf_path)])
        qdf = qdf_path.read_bytes()
        reports, decode_maps = analyze_qdf(qdf, args.search, args.replacement, align=args.align)
        if args.dry_run:
            print_dry_run_report(
                reports,
                decode_maps,
                search=args.search,
                replacement=args.replacement,
                align=args.align,
                as_json=args.json,
            )
            if args.report:
                write_report(
                    args.report,
                    report_payload(
                        input_pdf=args.input_pdf,
                        output_pdf=args.output,
                        search=args.search,
                        replacement=args.replacement,
                        align=args.align,
                        reports=reports,
                        decode_maps=decode_maps,
                        dry_run=True,
                    ),
                )
            if not reports:
                return 1
            if any(not report.feasible for report in reports):
                return 2
            return 0

        edited, count = replace_qdf(qdf, args.search, args.replacement, align=args.align)
        if count == 0:
            raise SystemExit(f"no decoded matches found for {args.search!r}")
        if args.keep_qdf:
            args.keep_qdf.write_bytes(edited)
        fixed = run(["fix-qdf"], stdin=edited)
        fixed_path.write_bytes(fixed)
        run(["qpdf", str(fixed_path), str(args.output)])
        if args.report:
            write_report(
                args.report,
                report_payload(
                    input_pdf=args.input_pdf,
                    output_pdf=args.output,
                    search=args.search,
                    replacement=args.replacement,
                    align=args.align,
                    reports=reports,
                    decode_maps=decode_maps,
                    dry_run=False,
                ),
            )

    print(f"replaced {count} occurrence(s): {args.search} -> {args.replacement}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
