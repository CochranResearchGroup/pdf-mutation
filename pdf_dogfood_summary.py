#!/usr/bin/env python3
"""Summarize pdf-dogfood JSONL run manifests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pdf_dogfood


__version__ = pdf_dogfood.__version__


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Load JSONL manifest records from path."""
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_number}: invalid JSONL record: {exc}") from exc
            if not isinstance(record, dict):
                raise SystemExit(f"{path}:{line_number}: manifest record must be an object")
            records.append(record)
    return records


def record_value(record: dict[str, Any], path: tuple[str, ...], default: Any = "") -> Any:
    value: Any = record
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def format_counts(counts: Any) -> str:
    if not isinstance(counts, dict) or not counts:
        return ""
    return ",".join(f"{key}={counts[key]}" for key in sorted(counts))


def format_rules(rules: Any) -> str:
    if not isinstance(rules, list) or not rules:
        return ""
    return ",".join(str(rule) for rule in rules)


def rows_for_records(records: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for record in records:
        rows.append(
            [
                str(record.get("timestamp_unix", "")),
                str(record.get("exit_code", "")),
                str(record_value(record, ("policy", "policy"))),
                str(record_value(record, ("policy", "selected_policy"))),
                str(record_value(record, ("summary", "total_pdfs"))),
                format_counts(record_value(record, ("summary", "status_counts"), {})),
                format_counts(record_value(record, ("summary", "probe_status_counts"), {})),
                str(record.get("fail_on_match_count", "")),
                format_rules(record.get("fail_on_rules", [])),
                str(record_value(record, ("policy", "json_path"))),
            ]
        )
    return rows


def print_table(records: list[dict[str, Any]]) -> None:
    headers = [
        "timestamp_unix",
        "exit",
        "policy",
        "selected",
        "pdfs",
        "status_counts",
        "probe_status_counts",
        "fail_matches",
        "fail_rules",
        "json_path",
    ]
    print("\t".join(headers))
    for row in rows_for_records(records):
        print("\t".join(row))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize pdf-dogfood JSONL manifests.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=pdf_dogfood.DEFAULT_MANIFEST,
        help=f"manifest JSONL path; default: {pdf_dogfood.DEFAULT_MANIFEST}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="show only the last N records; default: 20",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="write selected manifest records as JSON instead of a TSV table",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.limit < 0:
        raise SystemExit("--limit must be non-negative")
    if not args.manifest.exists():
        raise SystemExit(f"manifest does not exist: {args.manifest}")
    records = load_manifest(args.manifest)
    if args.limit:
        records = records[-args.limit :]
    if args.json:
        print(json.dumps(records, indent=2, sort_keys=True))
    else:
        print_table(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
