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
HEALTH_POLICIES = ["readiness", "complete"]
TABLE_HEADERS = [
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


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def matches_filters(
    record: dict[str, Any],
    *,
    policies: list[str],
    fail_only: bool,
    exit_codes: list[int],
) -> bool:
    if policies:
        policy = str(record_value(record, ("policy", "policy")))
        selected_policy = str(record_value(record, ("policy", "selected_policy")))
        if policy not in policies and selected_policy not in policies:
            return False
    if fail_only and int_value(record.get("fail_on_match_count")) <= 0:
        return False
    if exit_codes and int_value(record.get("exit_code"), default=-1) not in exit_codes:
        return False
    return True


def filter_records(
    records: list[dict[str, Any]],
    *,
    policies: list[str],
    fail_only: bool,
    exit_codes: list[int],
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if matches_filters(record, policies=policies, fail_only=fail_only, exit_codes=exit_codes)
    ]


def latest_by_policy(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        policy = str(record_value(record, ("policy", "policy")))
        if not policy:
            policy = str(record_value(record, ("policy", "selected_policy")))
        if policy:
            latest[policy] = record
    return [latest[policy] for policy in sorted(latest)]


def health_record(records: list[dict[str, Any]], health_policies: list[str] | None = None) -> dict[str, Any] | None:
    policies = health_policies or HEALTH_POLICIES
    candidates = filter_records(records, policies=policies, fail_only=False, exit_codes=[])
    if not candidates:
        return None
    return candidates[-1]


def health_status(record: dict[str, Any] | None) -> tuple[int, str]:
    if record is None:
        return 2, "missing\tno readiness or complete policy records found"
    policy = str(record_value(record, ("policy", "policy")))
    selected_policy = str(record_value(record, ("policy", "selected_policy")))
    exit_code = int_value(record.get("exit_code"), default=2)
    fail_count = int_value(record.get("fail_on_match_count"))
    status = "ok" if exit_code == 0 and fail_count == 0 else "fail"
    fields = [
        status,
        f"policy={policy}",
        f"selected={selected_policy}",
        f"exit={exit_code}",
        f"fail_matches={fail_count}",
        f"fail_rules={format_rules(record.get('fail_on_rules', []))}",
        f"json_path={record_value(record, ('policy', 'json_path'))}",
    ]
    return (0 if status == "ok" else 2), "\t".join(fields)


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


def render_table(records: list[dict[str, Any]]) -> str:
    lines = ["\t".join(TABLE_HEADERS)]
    for row in rows_for_records(records):
        lines.append("\t".join(row))
    return "\n".join(lines) + "\n"


def print_table(records: list[dict[str, Any]]) -> None:
    print(render_table(records), end="")


def markdown_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def render_markdown(records: list[dict[str, Any]]) -> str:
    lines = [
        "| " + " | ".join(markdown_cell(header) for header in TABLE_HEADERS) + " |",
        "| " + " | ".join("---" for _ in TABLE_HEADERS) + " |",
    ]
    for row in rows_for_records(records):
        lines.append("| " + " | ".join(markdown_cell(cell) for cell in row) + " |")
    return "\n".join(lines) + "\n"


def print_markdown(records: list[dict[str, Any]]) -> None:
    print(render_markdown(records), end="")


def write_output(text: str, output_path: Path | None) -> None:
    if output_path is None:
        print(text, end="")
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")


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
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="write selected manifest records as a Markdown table instead of a TSV table",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write summary output to this path instead of stdout; parent directories are created",
    )
    parser.add_argument(
        "--policy",
        action="append",
        default=[],
        help="show only records whose effective or selected policy matches this value; repeatable",
    )
    parser.add_argument(
        "--fail-only",
        action="store_true",
        help="show only records with one or more fail-on matches",
    )
    parser.add_argument(
        "--exit-code",
        action="append",
        type=int,
        default=[],
        help="show only records with this process exit code; repeatable",
    )
    parser.add_argument(
        "--latest-by-policy",
        action="store_true",
        help="show only the latest matching manifest record for each policy",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="exit 0 only when the latest readiness or complete policy record passed",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.json and args.markdown:
        raise SystemExit("--json and --markdown are mutually exclusive")
    if args.limit < 0:
        raise SystemExit("--limit must be non-negative")
    if not args.manifest.exists():
        raise SystemExit(f"manifest does not exist: {args.manifest}")
    records = filter_records(
        load_manifest(args.manifest),
        policies=args.policy,
        fail_only=args.fail_only,
        exit_codes=args.exit_code,
    )
    if args.health:
        status, line = health_status(health_record(records))
        write_output(line + "\n", args.output)
        return status
    if args.latest_by_policy:
        records = latest_by_policy(records)
    elif args.limit:
        records = records[-args.limit :]
    if args.json:
        text = json.dumps(records, indent=2, sort_keys=True) + "\n"
    elif args.markdown:
        text = render_markdown(records)
    else:
        text = render_table(records)
    write_output(text, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
