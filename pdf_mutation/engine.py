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
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

from pdf_mutation.adapters import require_tool, run, run_status
from pdf_mutation.cmap import (
    BFCHAR_LINE_RE,
    BFRANGE_ARRAY_LINE_RE,
    BFRANGE_BASE_LINE_RE,
    FONT_RESOURCE_RE,
    OBJ_RE,
    STREAM_RE,
    TO_UNICODE_RE,
    build_font_maps,
    hex_to_text,
    int_hex,
    parse_cmap,
    parse_objects,
    stream_of,
    width_for,
)
from pdf_mutation.layout import (
    bbox_alignment_assertions,
    bbox_words_matching,
    collect_bbox_evidence,
    decimal_report,
    parse_bbox_words,
    write_bbox_artifact,
)


__version__ = "0.1.3"

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


@dataclasses.dataclass
class AuditTextObject:
    text_object_index: int
    stream_object: int | None
    font: str
    decoded_length: int
    glyph_count: int
    cmap_glyphs: int
    decoded_sha256_12: str
    match_count: int
    patchable: bool
    reason: str
    alignment_contract: str = ""
    estimated_x_shift: str = ""
    replacement_missing_chars: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class AuditSplitMatch:
    text_object_indexes: list[int]
    stream_objects: list[int | None]
    fonts: list[str]
    match_count: int
    patchable: bool
    reason: str
    split_kind: str = ""
    segments: list[dict[str, object]] = dataclasses.field(default_factory=list)
    blockers: list[dict[str, object]] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class PlanMatch:
    id: str
    kind: str
    patchable: bool
    reason: str
    text_object_index: int
    stream_object: int | None
    font: str
    match_index: int
    glyph_start: int
    glyph_end: int
    glyph_cids: list[str]
    replacement_cids: list[str]
    chunk_spans: list[dict[str, object]]
    alignment_contract: str = ""
    estimated_x_shift: str = ""


@dataclasses.dataclass
class PlanSplitCandidate:
    id: str
    kind: str
    patchable: bool
    reason: str
    text_object_indexes: list[int]
    stream_objects: list[int | None]
    fonts: list[str]
    match_index: int
    split_kind: str = ""
    segments: list[dict[str, object]] = dataclasses.field(default_factory=list)
    blockers: list[dict[str, object]] = dataclasses.field(default_factory=list)


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


def text_object_feasibility(
    body: bytes,
    *,
    search: str,
    replacement: str,
    decoded: str,
    encode: dict[str, str],
    align: str,
) -> tuple[bool, str, str, str, list[str]]:
    missing = sorted({char for char in replacement if char not in encode})
    if missing:
        escaped = ", ".join(repr(char) for char in missing)
        return False, f"replacement character(s) not present in active font: {escaped}", "", "", missing
    if len(search) != len(replacement):
        if align not in {"left", "right"}:
            return (
                False,
                "replacement changes glyph count; use --align left or --align right for supported text",
                "",
                "",
                [],
            )
        feasible, reason, contract, x_shift = alignment_diagnostics(
            body, search, replacement, decoded, align=align
        )
        return feasible, reason, contract if feasible else "", x_shift if feasible else "", []
    return True, "ok", "exact glyph-count replacement preserves existing layout operators", "0", []


def find_occurrences(decoded: str, search: str) -> list[int]:
    positions: list[int] = []
    start = 0
    while search:
        index = decoded.find(search, start)
        if index < 0:
            break
        positions.append(index)
        start = index + len(search)
    return positions


def input_fingerprint(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": str(path),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def artifact_fingerprint(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": str(path),
        "size_bytes": len(data),
        "sha256_12": hashlib.sha256(data).hexdigest()[:12],
    }


def plan_id_for(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def replacement_cids_or_empty(replacement: str, encode: dict[str, str]) -> list[str]:
    if any(char not in encode for char in replacement):
        return []
    return [encode[char] for char in replacement]


def chunk_spans_for_match(glyphs: list[Glyph], start: int, replacement_codes: list[str]) -> list[dict[str, object]]:
    spans: list[dict[str, object]] = []
    for offset, new_cid in enumerate(replacement_codes):
        glyph = glyphs[start + offset]
        spans.append(
            {
                "glyph_index": start + offset,
                "chunk_start": glyph.chunk_start,
                "chunk_end": glyph.chunk_end,
                "old_cid": glyph.cid,
                "new_cid": new_cid,
            }
        )
    return spans


def split_kind_for_segments(segments: list[dict[str, object]]) -> str:
    fonts = {str(segment["font"]) for segment in segments}
    objects = {int(segment["text_object_index"]) for segment in segments}
    if len(fonts) > 1 and len(objects) > 1:
        return "cross_text_object_and_font"
    if len(fonts) > 1:
        return "cross_font"
    return "cross_text_object"


def split_segments_for_match(
    *,
    ranges: list[tuple[int, int, dict[str, object]]],
    start: int,
    end: int,
    search_length: int,
    replacement: str,
    encode_maps: dict[str, dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    segments: list[dict[str, object]] = []
    blockers: list[dict[str, object]] = []
    same_length = len(replacement) == search_length
    for range_start, range_end, meta in ranges:
        if range_start >= end or range_end <= start:
            continue
        font = str(meta["font"])
        glyph_start = max(start, range_start) - range_start
        glyph_end = min(end, range_end) - range_start
        replacement_available = False
        missing_count = 0
        if same_length:
            replacement_part = replacement[
                max(start, range_start) - start : min(end, range_end) - start
            ]
            encode = encode_maps.get(font, {})
            missing_count = sum(1 for char in replacement_part if char not in encode)
            replacement_available = missing_count == 0
        segment = {
            "text_object_index": int(meta["text_object_index"]),
            "stream_object": meta["stream_object"],
            "font": font,
            "glyph_start": glyph_start,
            "glyph_end": glyph_end,
            "replacement_glyphs_available": replacement_available,
            "missing_replacement_glyph_count": missing_count,
        }
        segments.append(segment)
        if same_length and not replacement_available:
            blockers.append(
                {
                    "font": font,
                    "text_object_index": int(meta["text_object_index"]),
                    "reason": "replacement character(s) not present in active font",
                    "missing_replacement_glyph_count": missing_count,
                }
            )
        elif not same_length:
            blockers.append(
                {
                    "font": font,
                    "text_object_index": int(meta["text_object_index"]),
                    "reason": "segmented length-changing replacement is not designed",
                    "missing_replacement_glyph_count": 0,
                }
            )
    return segments, blockers


def plan_qdf(
    qdf: bytes,
    search: str,
    replacement: str,
    *,
    align: str,
    input_pdf: Path | None = None,
) -> dict[str, object]:
    objects = parse_objects(qdf)
    decode_maps, encode_maps = build_font_maps(objects)
    if not decode_maps:
        raise SystemExit("no Type0 fonts with ToUnicode CMaps found")

    matches: list[PlanMatch] = []
    split_candidates: list[PlanSplitCandidate] = []
    decoded_ranges: list[tuple[int, int, dict[str, object]]] = []
    joined_parts: list[str] = []
    text_object_index = 0
    cursor = 0

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
            joined_parts.append(decoded)
            decoded_ranges.append(
                (
                    cursor,
                    cursor + len(decoded),
                    {
                        "text_object_index": text_object_index,
                        "stream_object": stream_object,
                        "font": font_name,
                    },
                )
            )
            cursor += len(decoded)

            replacement_codes = replacement_cids_or_empty(replacement, encode)
            for match_index, start in enumerate(find_occurrences(decoded, search), 1):
                feasible, reason, contract, x_shift, _missing = text_object_feasibility(
                    body,
                    search=search,
                    replacement=replacement,
                    decoded=decoded,
                    encode=encode,
                    align=align,
                )
                if not replacement_codes and "replacement character" in reason:
                    reason = "replacement character(s) not present in active font"
                same_glyph_count = len(search) == len(replacement)
                patchable = feasible and same_glyph_count and bool(replacement_codes)
                if feasible and not same_glyph_count:
                    reason = "length-changing matches require a later plan schema before plan apply"
                    patchable = False
                    contract = ""
                    x_shift = ""
                glyph_end = start + len(search)
                spans = (
                    chunk_spans_for_match(glyphs, start, replacement_codes)
                    if patchable
                    else []
                )
                matches.append(
                    PlanMatch(
                        id=f"m{len(matches) + 1}",
                        kind="text_object",
                        patchable=patchable,
                        reason=reason,
                        text_object_index=text_object_index,
                        stream_object=stream_object,
                        font=font_name,
                        match_index=match_index,
                        glyph_start=start,
                        glyph_end=glyph_end,
                        glyph_cids=[glyph.cid for glyph in glyphs[start:glyph_end]],
                        replacement_cids=replacement_codes if patchable else [],
                        chunk_spans=spans,
                        alignment_contract=contract if patchable else "",
                        estimated_x_shift=x_shift if patchable else "",
                    )
                )

    joined = "".join(joined_parts)
    for match_index, start in enumerate(find_occurrences(joined, search), 1):
        end = start + len(search)
        overlapped = [
            meta
            for range_start, range_end, meta in decoded_ranges
            if range_start < end and range_end > start
        ]
        if len(overlapped) > 1:
            segments, blockers = split_segments_for_match(
                ranges=decoded_ranges,
                start=start,
                end=end,
                search_length=len(search),
                replacement=replacement,
                encode_maps=encode_maps,
            )
            split_candidates.append(
                PlanSplitCandidate(
                    id=f"s{len(split_candidates) + 1}",
                    kind="split",
                    patchable=False,
                    reason="match spans multiple text objects or font resources",
                    text_object_indexes=[int(meta["text_object_index"]) for meta in overlapped],
                    stream_objects=[meta["stream_object"] for meta in overlapped],
                    fonts=[str(meta["font"]) for meta in overlapped],
                    match_index=match_index,
                    split_kind=split_kind_for_segments(segments),
                    segments=segments,
                    blockers=blockers,
                )
            )

    patchable_matches = sum(1 for match in matches if match.patchable)
    unpatchable_matches = sum(1 for match in matches if not match.patchable) + len(split_candidates)
    payload: dict[str, object] = {
        "schema": "pdf-mutation-plan",
        "schema_version": 1,
        "version": __version__,
        "mode": "plan",
        "input_pdf": input_fingerprint(input_pdf) if input_pdf else None,
        "align": align,
        "search_length": len(search),
        "replacement_length": len(replacement),
        "search_sha256_12": hashlib.sha256(search.encode("utf-8")).hexdigest()[:12],
        "replacement_sha256_12": hashlib.sha256(replacement.encode("utf-8")).hexdigest()[:12],
        "font_resources": [
            {"font": font, "decoded_glyphs": len(decode_maps[font])}
            for font in sorted(decode_maps)
        ],
        "expected": {
            "total_candidates": len(matches) + len(split_candidates),
            "patchable_matches": patchable_matches,
            "unpatchable_candidates": unpatchable_matches,
            "split_candidates": len(split_candidates),
        },
        "matches": [dataclasses.asdict(match) for match in matches],
        "split_candidates": [dataclasses.asdict(candidate) for candidate in split_candidates],
        "privacy": {
            "decoded_text_included": False,
            "literal_search_replacement_included": False,
        },
    }
    payload["plan_id"] = plan_id_for(payload)
    return payload


def audit_qdf(qdf: bytes, search: str, replacement: str, *, align: str) -> dict[str, object]:
    objects = parse_objects(qdf)
    decode_maps, encode_maps = build_font_maps(objects)
    if not decode_maps:
        raise SystemExit("no Type0 fonts with ToUnicode CMaps found")

    text_objects: list[AuditTextObject] = []
    decoded_ranges: list[tuple[int, int, AuditTextObject]] = []
    split_ranges: list[tuple[int, int, dict[str, object]]] = []
    text_object_index = 0
    joined_parts: list[str] = []
    cursor = 0

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
            match_count = decoded.count(search)
            patchable = False
            reason = "search not present in text object"
            alignment_contract = ""
            estimated_x_shift = ""
            missing_chars: list[str] = []
            if match_count:
                patchable, reason, alignment_contract, estimated_x_shift, missing_chars = text_object_feasibility(
                    body,
                    search=search,
                    replacement=replacement,
                    decoded=decoded,
                    encode=encode,
                    align=align,
                )

            audit_object = AuditTextObject(
                text_object_index=text_object_index,
                stream_object=stream_object,
                font=font_name,
                decoded_length=len(decoded),
                glyph_count=len(glyphs),
                cmap_glyphs=len(decode),
                decoded_sha256_12=hashlib.sha256(decoded.encode("utf-8")).hexdigest()[:12],
                match_count=match_count,
                patchable=patchable,
                reason=reason,
                alignment_contract=alignment_contract,
                estimated_x_shift=estimated_x_shift,
                replacement_missing_chars=missing_chars,
            )
            text_objects.append(audit_object)
            joined_parts.append(decoded)
            decoded_ranges.append((cursor, cursor + len(decoded), audit_object))
            split_ranges.append(
                (
                    cursor,
                    cursor + len(decoded),
                    {
                        "text_object_index": text_object_index,
                        "stream_object": stream_object,
                        "font": font_name,
                    },
                )
            )
            cursor += len(decoded)

    split_matches: list[AuditSplitMatch] = []
    joined = "".join(joined_parts)
    start = 0
    while search:
        index = joined.find(search, start)
        if index < 0:
            break
        end = index + len(search)
        overlapped = [
            audit_object
            for range_start, range_end, audit_object in decoded_ranges
            if range_start < end and range_end > index
        ]
        if len(overlapped) > 1:
            segments, blockers = split_segments_for_match(
                ranges=split_ranges,
                start=index,
                end=end,
                search_length=len(search),
                replacement=replacement,
                encode_maps=encode_maps,
            )
            split_matches.append(
                AuditSplitMatch(
                    text_object_indexes=[obj.text_object_index for obj in overlapped],
                    stream_objects=[obj.stream_object for obj in overlapped],
                    fonts=[obj.font for obj in overlapped],
                    match_count=1,
                    patchable=False,
                    reason="match spans multiple text objects or font resources",
                    split_kind=split_kind_for_segments(segments),
                    segments=segments,
                    blockers=blockers,
                )
            )
        start = index + len(search)

    total_matches = sum(obj.match_count for obj in text_objects) + sum(match.match_count for match in split_matches)
    patchable_matches = sum(obj.match_count for obj in text_objects if obj.patchable)
    unpatchable_matches = total_matches - patchable_matches
    return {
        "version": __version__,
        "mode": "audit",
        "align": align,
        "search_length": len(search),
        "replacement_length": len(replacement),
        "search_sha256_12": hashlib.sha256(search.encode("utf-8")).hexdigest()[:12],
        "replacement_sha256_12": hashlib.sha256(replacement.encode("utf-8")).hexdigest()[:12],
        "font_resources": [
            {"font": font, "decoded_glyphs": len(decode_maps[font])}
            for font in sorted(decode_maps)
        ],
        "total_text_objects": len(text_objects),
        "total_matches": total_matches,
        "patchable_matches": patchable_matches,
        "unpatchable_matches": unpatchable_matches,
        "split_match_count": sum(match.match_count for match in split_matches),
        "text_objects": [dataclasses.asdict(obj) for obj in text_objects],
        "split_matches": [dataclasses.asdict(match) for match in split_matches],
        "privacy": {
            "decoded_text_included": False,
            "literal_search_replacement_included": False,
        },
    }


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


def audit_exit_status(payload: dict[str, object]) -> int:
    total_matches = int(payload["total_matches"])
    unpatchable_matches = int(payload["unpatchable_matches"])
    if total_matches == 0:
        return 1
    return 2 if unpatchable_matches else 0


def plan_exit_status(payload: dict[str, object]) -> int:
    expected = payload["expected"]
    if not isinstance(expected, dict):
        return 2
    if int(expected["total_candidates"]) == 0:
        return 1
    return 2 if int(expected["unpatchable_candidates"]) else 0


def non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--expect-count must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("--expect-count must be non-negative")
    return parsed


def enforce_expect_count(expected_count: int | None, actual_count: int, *, label: str) -> None:
    if expected_count is None:
        return
    if actual_count != expected_count:
        raise SystemExit(
            f"--expect-count mismatch: expected {expected_count} {label}, found {actual_count}"
        )


def load_json_file(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in plan {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"plan {path} must contain a JSON object")
    return payload


def validate_plan_for_apply(plan: dict[str, object], input_pdf: Path) -> list[dict[str, object]]:
    if plan.get("schema") != "pdf-mutation-plan":
        raise SystemExit("plan schema is not pdf-mutation-plan")
    if plan.get("schema_version") != 1:
        raise SystemExit("unsupported plan schema_version")
    if plan.get("mode") != "plan":
        raise SystemExit("plan mode must be 'plan'")

    expected_input = plan.get("input_pdf")
    if not isinstance(expected_input, dict):
        raise SystemExit("plan is missing input_pdf fingerprint metadata")
    actual_input = input_fingerprint(input_pdf)
    for key in ("size_bytes", "sha256"):
        if expected_input.get(key) != actual_input[key]:
            raise SystemExit("input PDF fingerprint does not match plan")

    expected = plan.get("expected")
    if not isinstance(expected, dict):
        raise SystemExit("plan is missing expected match counts")
    if int(expected.get("total_candidates", 0)) == 0:
        raise SystemExit("plan contains no candidates to apply")
    if int(expected.get("unpatchable_candidates", 0)) != 0:
        raise SystemExit("plan contains unpatchable candidates; refusing to apply")
    if int(expected.get("split_candidates", 0)) != 0:
        raise SystemExit("plan contains split candidates; refusing to apply")

    if plan.get("search_length") != plan.get("replacement_length"):
        raise SystemExit("only same-glyph-count plans can be applied")

    matches = plan.get("matches")
    if not isinstance(matches, list):
        raise SystemExit("plan matches must be a list")
    if len(matches) != int(expected.get("patchable_matches", -1)):
        raise SystemExit("plan patchable match count does not match matches list")

    seen_ids: set[str] = set()
    for match in matches:
        if not isinstance(match, dict):
            raise SystemExit("plan match entries must be objects")
        match_id = match.get("id")
        if not isinstance(match_id, str) or not match_id:
            raise SystemExit("plan match is missing an id")
        if match_id in seen_ids:
            raise SystemExit(f"duplicate plan match id: {match_id}")
        seen_ids.add(match_id)
        if match.get("kind") != "text_object" or match.get("patchable") is not True:
            raise SystemExit(f"plan match {match_id} is not patchable text_object")
        glyph_cids = match.get("glyph_cids")
        replacement_cids_value = match.get("replacement_cids")
        spans = match.get("chunk_spans")
        if not isinstance(glyph_cids, list) or not isinstance(replacement_cids_value, list):
            raise SystemExit(f"plan match {match_id} is missing glyph CID data")
        if not isinstance(spans, list) or not spans:
            raise SystemExit(f"plan match {match_id} is missing chunk spans")
        if len(glyph_cids) != len(replacement_cids_value) or len(spans) != len(glyph_cids):
            raise SystemExit(f"plan match {match_id} has inconsistent glyph span counts")
        for span in spans:
            if not isinstance(span, dict):
                raise SystemExit(f"plan match {match_id} has invalid chunk span")
            for key in ("chunk_start", "chunk_end", "old_cid", "new_cid"):
                if key not in span:
                    raise SystemExit(f"plan match {match_id} chunk span is missing {key}")
    return matches


def apply_plan_to_text_object(body: bytes, matches: list[dict[str, object]]) -> tuple[bytes, int, int, list[str]]:
    if not matches:
        return body, 0, 0, []

    font_match = FONT_SET_RE.search(body)
    if not font_match:
        ids = ", ".join(str(match["id"]) for match in matches)
        raise SystemExit(f"planned text object is missing active font for match(es): {ids}")
    font_name = font_match.group(1).decode("ascii")

    replacements: list[tuple[int, int, bytes, bytes, str]] = []
    applied_ids: list[str] = []
    for match in matches:
        match_id = str(match["id"])
        if match.get("font") != font_name:
            raise SystemExit(f"plan match {match_id} font does not match regenerated QDF")
        spans = match["chunk_spans"]
        if not isinstance(spans, list):
            raise SystemExit(f"plan match {match_id} has invalid chunk spans")
        for span in spans:
            if not isinstance(span, dict):
                raise SystemExit(f"plan match {match_id} has invalid chunk span")
            start = int(span["chunk_start"])
            end = int(span["chunk_end"])
            old_cid = str(span["old_cid"]).upper().encode("ascii")
            new_cid = str(span["new_cid"]).upper().encode("ascii")
            if start < 0 or end <= start or end > len(body):
                raise SystemExit(f"plan match {match_id} chunk span is outside regenerated text object")
            if body[start:end].upper() != old_cid:
                raise SystemExit(f"plan match {match_id} chunk span does not match regenerated QDF")
            replacements.append((start, end, old_cid, new_cid, match_id))
        applied_ids.append(match_id)

    last_end = -1
    for start, end, _old_cid, _new_cid, match_id in sorted(replacements):
        if start < last_end:
            raise SystemExit(f"plan match {match_id} overlaps another planned glyph span")
        last_end = end

    rebuilt = bytearray()
    pos = 0
    for start, end, _old_cid, new_cid, _match_id in sorted(replacements):
        rebuilt.extend(body[pos:start])
        rebuilt.extend(new_cid)
        pos = end
    rebuilt.extend(body[pos:])
    return bytes(rebuilt), len(applied_ids), len(replacements), applied_ids


def apply_plan_to_qdf(qdf: bytes, plan: dict[str, object], *, input_pdf: Path) -> tuple[bytes, int, int, list[str]]:
    matches = validate_plan_for_apply(plan, input_pdf)
    planned_by_text_object: dict[int, list[dict[str, object]]] = {}
    for match in matches:
        planned_by_text_object.setdefault(int(match["text_object_index"]), []).append(match)

    total_matches = 0
    total_glyphs = 0
    applied_ids: list[str] = []
    text_object_index = 0
    touched_text_objects: set[int] = set()

    def replace_object(obj_match: re.Match[bytes]) -> bytes:
        nonlocal text_object_index, total_matches, total_glyphs, applied_ids
        obj_num = int(obj_match.group(1))
        body = obj_match.group(2)

        def replace_stream(stream_match: re.Match[bytes]) -> bytes:
            prefix, stream, suffix = stream_match.groups()

            def replace_text_object(text_match: re.Match[bytes]) -> bytes:
                nonlocal text_object_index, total_matches, total_glyphs, applied_ids
                text_object_index += 1
                planned = planned_by_text_object.get(text_object_index, [])
                if not planned:
                    return text_match.group(0)
                for match in planned:
                    if match.get("stream_object") != obj_num:
                        raise SystemExit(
                            f"plan match {match['id']} stream object does not match regenerated QDF"
                        )
                new_body, match_count, glyph_count, ids = apply_plan_to_text_object(
                    text_match.group(1),
                    planned,
                )
                touched_text_objects.add(text_object_index)
                total_matches += match_count
                total_glyphs += glyph_count
                applied_ids.extend(ids)
                return b"BT\n" + new_body + b"\nET"

            return prefix + BT_ET_RE.sub(replace_text_object, stream) + suffix

        new_body = STREAM_RE.sub(replace_stream, body)
        return obj_match.group(1) + b" 0 obj\n" + new_body + b"\nendobj"

    edited = OBJ_RE.sub(replace_object, qdf)
    missing = sorted(set(planned_by_text_object) - touched_text_objects)
    if missing:
        missing_text = ", ".join(str(index) for index in missing)
        raise SystemExit(f"planned text object(s) not found in regenerated QDF: {missing_text}")
    if total_matches != len(matches):
        raise SystemExit("applied match count does not match plan")
    return edited, total_matches, total_glyphs, applied_ids


def apply_plan_report_payload(
    *,
    plan: dict[str, object],
    input_pdf: Path,
    output_pdf: Path,
    changed_matches: int,
    changed_glyphs: int,
    applied_match_ids: list[str],
    layout_evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": __version__,
        "mode": "apply-plan",
        "plan_id": plan.get("plan_id"),
        "input_pdf": input_fingerprint(input_pdf),
        "output_pdf": str(output_pdf),
        "changed_matches": changed_matches,
        "changed_glyphs": changed_glyphs,
        "applied_match_ids": applied_match_ids,
        "skipped_unapplied_count": 0,
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
    if layout_evidence is not None:
        payload["layout_evidence"] = layout_evidence
    return payload


def print_plan_report(payload: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    expected = payload["expected"]
    if not isinstance(expected, dict):
        raise SystemExit("internal error: invalid plan summary")
    print(
        "plan: "
        f"id={payload['plan_id']} "
        f"align={payload['align']} "
        f"candidates={expected['total_candidates']} "
        f"patchable={expected['patchable_matches']} "
        f"unpatchable={expected['unpatchable_candidates']} "
        f"split={expected['split_candidates']}"
    )


def print_audit_report(payload: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    print(
        "audit: "
        f"search_length={payload['search_length']} "
        f"replacement_length={payload['replacement_length']} "
        f"align={payload['align']}"
    )
    print("font resources:")
    for font in payload["font_resources"]:
        print(f"- /{font['font']}: decoded_glyphs={font['decoded_glyphs']}")
    print(f"text objects: {payload['total_text_objects']}")
    print(f"total matches: {payload['total_matches']}")
    print(f"patchable matches: {payload['patchable_matches']}")
    print(f"unpatchable matches: {payload['unpatchable_matches']}")
    if payload["text_objects"]:
        print("text object audit:")
    for obj in payload["text_objects"]:
        print(
            f"- text_object={obj['text_object_index']} stream={obj['stream_object']} "
            f"font=/{obj['font']} decoded_length={obj['decoded_length']} "
            f"glyphs={obj['glyph_count']} matches={obj['match_count']} "
            f"patchable={'yes' if obj['patchable'] else 'no'} reason={obj['reason']}"
        )
    if payload["split_matches"]:
        print("split matches:")
    for match in payload["split_matches"]:
        objects = ",".join(str(index) for index in match["text_object_indexes"])
        fonts = ",".join(f"/{font}" for font in match["fonts"])
        print(
            f"- text_objects={objects} fonts={fonts} "
            f"patchable=no reason={match['reason']}"
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
    layout_evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    total = sum(report.match_count for report in reports)
    feasible = total > 0 and all(report.feasible for report in reports)
    payload: dict[str, object] = {
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
    if layout_evidence is not None:
        payload["layout_evidence"] = layout_evidence
    return payload


def write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Glyph-preserving PDF search/replace using qpdf QDF and ToUnicode CMaps."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("search", nargs="?")
    parser.add_argument("replacement", nargs="?")
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
    parser.add_argument(
        "--audit",
        action="store_true",
        help=(
            "audit every decoded text object and split match without writing a PDF; "
            "implies --dry-run and omits decoded document text from JSON"
        ),
    )
    parser.add_argument(
        "--plan",
        type=Path,
        help=(
            "write a reviewable mutation plan JSON without writing a PDF; "
            "implies --dry-run and omits decoded document text"
        ),
    )
    parser.add_argument(
        "--apply-plan",
        type=Path,
        help="apply a reviewed mutation plan JSON and fail closed if the source PDF no longer matches",
    )
    parser.add_argument(
        "--expect-count",
        type=non_negative_int,
        help="require exactly N patchable or applied matches before considering the operation successful",
    )
    parser.add_argument("--json", action="store_true", help="emit dry-run report as JSON")
    parser.add_argument("--keep-qdf", type=Path, help="write the edited QDF for inspection")
    parser.add_argument("--report", type=Path, help="write a non-sensitive JSON mutation report")
    parser.add_argument(
        "--bbox-dir",
        type=Path,
        help=(
            "write optional before/after pdftotext -bbox HTML artifacts under PATH "
            "and reference them from --report"
        ),
    )
    args = parser.parse_args()

    if args.apply_plan:
        if args.plan or args.audit or args.dry_run:
            parser.error("--apply-plan cannot be combined with --plan, --audit, or --dry-run")
        if args.json:
            parser.error("--json is only supported with --dry-run, --audit, or --plan")
        if args.search is not None or args.replacement is not None:
            parser.error("search and replacement are not used with --apply-plan")
        if not args.output:
            parser.error("-o/--output is required with --apply-plan")
    elif args.search is None or args.replacement is None:
        parser.error("search and replacement are required unless --apply-plan is used")

    if args.audit or args.plan:
        args.dry_run = True
    if not args.dry_run and not args.output:
        parser.error("-o/--output is required unless --dry-run is used")
    if args.json and not args.dry_run:
        parser.error("--json is only supported with --dry-run")
    if args.bbox_dir and (args.dry_run or not args.report):
        parser.error("--bbox-dir is only supported for write/apply modes with --report")

    require_tool("qpdf")
    if not args.dry_run:
        require_tool("fix-qdf")

    with tempfile.TemporaryDirectory(prefix="pdf-glyph-replace-") as tmp:
        qdf_path = Path(tmp) / "input.qdf.pdf"
        fixed_path = Path(tmp) / "fixed.qdf.pdf"
        run(["qpdf", "--qdf", "--object-streams=disable", str(args.input_pdf), str(qdf_path)])
        qdf = qdf_path.read_bytes()
        if args.apply_plan:
            plan = load_json_file(args.apply_plan)
            edited, changed_matches, changed_glyphs, applied_match_ids = apply_plan_to_qdf(
                qdf,
                plan,
                input_pdf=args.input_pdf,
            )
            enforce_expect_count(args.expect_count, changed_matches, label="applied match(es)")
            if args.keep_qdf:
                args.keep_qdf.write_bytes(edited)
            fixed = run(["fix-qdf"], stdin=edited)
            fixed_path.write_bytes(fixed)
            run(["qpdf", str(fixed_path), str(args.output)])
            layout_evidence = collect_bbox_evidence(
                input_pdf=args.input_pdf,
                output_pdf=args.output,
                bbox_dir=args.bbox_dir,
                stem=args.output.stem,
            )
            if args.report:
                write_report(
                    args.report,
                    apply_plan_report_payload(
                        plan=plan,
                        input_pdf=args.input_pdf,
                        output_pdf=args.output,
                        changed_matches=changed_matches,
                        changed_glyphs=changed_glyphs,
                        applied_match_ids=applied_match_ids,
                        layout_evidence=layout_evidence,
                    ),
                )
            print(f"applied plan {plan.get('plan_id')}: changed {changed_matches} match(es)")
            return 0

        search = str(args.search)
        replacement = str(args.replacement)
        if args.plan:
            payload = plan_qdf(
                qdf,
                search,
                replacement,
                align=args.align,
                input_pdf=args.input_pdf,
            )
            expected = payload["expected"]
            if isinstance(expected, dict):
                enforce_expect_count(
                    args.expect_count,
                    int(expected["patchable_matches"]),
                    label="patchable match(es)",
                )
            write_report(args.plan, payload)
            print_plan_report(payload, as_json=args.json)
            if args.report:
                write_report(args.report, payload)
            return plan_exit_status(payload)

        if args.audit:
            payload = audit_qdf(qdf, search, replacement, align=args.align)
            enforce_expect_count(
                args.expect_count,
                int(payload["patchable_matches"]),
                label="patchable match(es)",
            )
            print_audit_report(payload, as_json=args.json)
            if args.report:
                write_report(args.report, payload)
            return audit_exit_status(payload)

        reports, decode_maps = analyze_qdf(qdf, search, replacement, align=args.align)
        patchable_matches = (
            sum(report.match_count for report in reports)
            if reports and all(report.feasible for report in reports)
            else 0
        )
        if args.dry_run:
            enforce_expect_count(args.expect_count, patchable_matches, label="patchable match(es)")
            print_dry_run_report(
                reports,
                decode_maps,
                search=search,
                replacement=replacement,
                align=args.align,
                as_json=args.json,
            )
            if args.report:
                write_report(
                    args.report,
                    report_payload(
                        input_pdf=args.input_pdf,
                        output_pdf=args.output,
                        search=search,
                        replacement=replacement,
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

        edited, count = replace_qdf(qdf, search, replacement, align=args.align)
        enforce_expect_count(args.expect_count, count, label="replaced match(es)")
        if count == 0:
            raise SystemExit(f"no decoded matches found for {search!r}")
        if args.keep_qdf:
            args.keep_qdf.write_bytes(edited)
        fixed = run(["fix-qdf"], stdin=edited)
        fixed_path.write_bytes(fixed)
        run(["qpdf", str(fixed_path), str(args.output)])
        layout_evidence = collect_bbox_evidence(
            input_pdf=args.input_pdf,
            output_pdf=args.output,
            bbox_dir=args.bbox_dir,
            stem=args.output.stem,
            search=search,
            replacement=replacement,
            align=args.align,
        )
        if args.report:
            write_report(
                args.report,
                report_payload(
                    input_pdf=args.input_pdf,
                    output_pdf=args.output,
                    search=search,
                    replacement=replacement,
                    align=args.align,
                    reports=reports,
                    decode_maps=decode_maps,
                    layout_evidence=layout_evidence,
                    dry_run=False,
                ),
            )

    print(f"replaced {count} occurrence(s): {search} -> {replacement}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
