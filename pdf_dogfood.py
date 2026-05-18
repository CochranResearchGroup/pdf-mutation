#!/usr/bin/env python3
"""Run the canonical local dogfood inventory gate."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import pdf_glyph_replace as glyph
import pdf_inventory


__version__ = glyph.__version__

DEFAULT_CORPUS = Path("work/dogfood-pdfs/sample-*.pdf")
DEFAULT_OUTPUT_DIR = Path("work/dogfood-pdfs/inventory")
DEFAULT_MANIFEST = DEFAULT_OUTPUT_DIR / "dogfood-manifest.jsonl"
DEFAULT_MAX_INPUT_BYTES = 50_000_000
POLICY_FAIL_ON = {
    "complete": (
        "error",
        "qpdf-check-failed",
        "qdf-conversion-failed",
        "skipped",
    ),
    "readiness": (
        "error",
        "unsupported",
        "skipped",
        "probe-unsupported",
        "probe-no-match",
        "probe-infeasible",
    ),
    "routine": (
        "error",
        "qpdf-check-failed",
        "qdf-conversion-failed",
        "probe-feasible",
    ),
}
DEFAULT_POLICY = "routine"
POLICY_HELP = "; ".join(
    f"{name}: {', '.join(rules)}" for name, rules in sorted(POLICY_FAIL_ON.items())
)


def selected_fail_on(args: argparse.Namespace) -> list[str]:
    """Return the effective fail-on rules for the selected policy flags."""
    if args.no_fail_on:
        return []
    if args.fail_on is not None:
        return list(args.fail_on)
    return list(POLICY_FAIL_ON[args.policy])


def output_name(args: argparse.Namespace) -> str:
    """Return the report filename stem for this run."""
    if args.name:
        return args.name
    return "dogfood" if args.policy == DEFAULT_POLICY else f"dogfood-{args.policy}"


def build_inventory_argv(args: argparse.Namespace) -> list[str]:
    """Build the pdf-inventory argv for the selected dogfood policy."""
    output_dir = args.output_dir
    stem = output_name(args)
    inventory_args = [str(pdf) for pdf in args.pdfs]
    inventory_args.append("--summary")
    inventory_args.extend(["--max-input-bytes", str(args.max_input_bytes)])
    inventory_args.extend(["--json", str(output_dir / f"{stem}.json")])
    inventory_args.extend(["--tsv", str(output_dir / f"{stem}.tsv")])
    if args.probe:
        inventory_args.extend(["--probe", args.probe[0], args.probe[1]])
        inventory_args.extend(["--align", args.align])
    fail_on = selected_fail_on(args)
    if fail_on:
        inventory_args.append("--fail-on")
        inventory_args.extend(fail_on)
    return inventory_args


def policy_name(args: argparse.Namespace) -> str:
    """Return the effective policy label for report metadata."""
    if args.no_fail_on:
        return "none"
    if args.fail_on is not None:
        return "custom"
    return args.policy


def report_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    stem = output_name(args)
    return args.output_dir / f"{stem}.json", args.output_dir / f"{stem}.tsv"


def policy_metadata(args: argparse.Namespace) -> dict[str, Any]:
    """Return non-sensitive metadata for a dogfood report."""
    metadata: dict[str, Any] = {
        "tool": "pdf-dogfood",
        "version": __version__,
        "policy": policy_name(args),
        "selected_policy": args.policy,
        "fail_on": selected_fail_on(args),
        "max_input_bytes": args.max_input_bytes,
        "align": args.align,
        "output_name": output_name(args),
        "input_globs": [str(pdf) for pdf in args.original_pdfs],
        "input_count": len(args.pdfs),
        "json_path": str(report_paths(args)[0]),
        "tsv_path": str(report_paths(args)[1]),
    }
    if args.probe:
        metadata["probe"] = {
            "search_length": len(args.probe[0]),
            "replacement_length": len(args.probe[1]),
            "search_sha256_12": hashlib.sha256(args.probe[0].encode("utf-8")).hexdigest()[:12],
            "replacement_sha256_12": hashlib.sha256(
                args.probe[1].encode("utf-8")
            ).hexdigest()[:12],
        }
    return metadata


def write_outputs(
    rows: list[dict[str, Any]],
    *,
    json_path: Path,
    tsv_path: Path,
    summary: dict[str, Any],
    policy: dict[str, Any],
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"policy": policy, "rows": rows, "summary": summary}
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pdf_inventory.write_outputs(rows, json_path=None, tsv_path=tsv_path, summary=summary)


def manifest_record(
    *,
    policy: dict[str, Any],
    summary: dict[str, Any],
    matches: list[dict[str, Any]],
    exit_code: int,
) -> dict[str, Any]:
    """Return a compact non-sensitive dogfood run manifest record."""
    return {
        "timestamp_unix": int(time.time()),
        "tool": "pdf-dogfood",
        "version": __version__,
        "exit_code": exit_code,
        "policy": policy,
        "summary": {
            "total_pdfs": summary.get("total_pdfs"),
            "status_counts": summary.get("status_counts", {}),
            "reason_counts": summary.get("reason_counts", {}),
            "probe_status_counts": summary.get("probe_status_counts", {}),
            "probe_total_matches": summary.get("probe_total_matches", 0),
            "probe_feasible_pdfs": summary.get("probe_feasible_pdfs", 0),
            "qpdf_check_failed": summary.get("qpdf_check_failed", 0),
            "qdf_conversion_failed": summary.get("qdf_conversion_failed", 0),
        },
        "fail_on_match_count": len(matches),
        "fail_on_rules": sorted({rule for match in matches for rule in match.get("rules", [])}),
    }


def append_manifest(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the canonical pdf-mutation dogfood inventory gate."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "pdfs",
        nargs="*",
        type=Path,
        default=[DEFAULT_CORPUS],
        help=f"PDF glob(s) to inventory; default: {DEFAULT_CORPUS}",
    )
    parser.add_argument(
        "--policy",
        choices=tuple(sorted(POLICY_FAIL_ON)),
        default=DEFAULT_POLICY,
        help=f"named fail-on policy; default: {DEFAULT_POLICY}. Policies: {POLICY_HELP}",
    )
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
        help="alignment policy used by --probe",
    )
    parser.add_argument(
        "--max-input-bytes",
        type=int,
        default=DEFAULT_MAX_INPUT_BYTES,
        help=f"skip QDF conversion for PDFs larger than this many bytes; default: {DEFAULT_MAX_INPUT_BYTES}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"write JSON and TSV reports here; default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--name",
        help="output report filename stem; default: dogfood or dogfood-<policy>",
    )
    parser.add_argument(
        "--manifest",
        nargs="?",
        const=DEFAULT_MANIFEST,
        type=Path,
        help=f"append a compact JSONL run record; default path when omitted: {DEFAULT_MANIFEST}",
    )
    parser.add_argument(
        "--fail-on",
        nargs="+",
        choices=pdf_inventory.FAIL_ON_CHOICES,
        default=None,
        metavar="RULE",
        help="override --policy with explicit inventory rules that make the command exit 2",
    )
    parser.add_argument(
        "--no-fail-on",
        action="store_true",
        help="disable fail-on policy and run report-only inventory",
    )
    args = parser.parse_args(argv)
    args.original_pdfs = list(args.pdfs)
    return args


def expand_pdf_args(pdfs: list[Path]) -> list[Path]:
    expanded: list[Path] = []
    for pdf in pdfs:
        text = str(pdf)
        if any(char in text for char in "*?[]"):
            matches = [Path(match) for match in sorted(glob.glob(text))]
            expanded.extend(matches if matches else [pdf])
        else:
            expanded.append(pdf)
    return expanded


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    args.pdfs = expand_pdf_args(args.pdfs)
    glyph.require_tool("qpdf")
    rows = [
        pdf_inventory.inventory_pdf(
            pdf,
            probe=tuple(args.probe) if args.probe else None,
            align=args.align,
            max_input_bytes=args.max_input_bytes,
        )
        for pdf in args.pdfs
    ]
    summary = pdf_inventory.build_summary(rows)
    json_path, tsv_path = report_paths(args)
    policy = policy_metadata(args)
    write_outputs(
        rows,
        json_path=json_path,
        tsv_path=tsv_path,
        summary=summary,
        policy=policy,
    )
    matches = pdf_inventory.fail_on_matches(rows, selected_fail_on(args))
    exit_code = 2 if matches else 1 if any(row["status"] == "error" for row in rows) else 0
    if args.manifest:
        append_manifest(
            args.manifest,
            manifest_record(policy=policy, summary=summary, matches=matches, exit_code=exit_code),
        )
    if matches:
        pdf_inventory.print_fail_on_matches(matches)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
