"""PDF CMap and object parsing helpers for glyph-preserving mutation."""

from __future__ import annotations

import re


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
    return {int(obj_num): body for obj_num, body in OBJ_RE.findall(qdf)}


def stream_of(obj_body: bytes) -> bytes | None:
    match = STREAM_RE.search(obj_body)
    if match:
        return match.group(2)
    return None


def build_font_maps(
    objects: dict[int, bytes],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
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
