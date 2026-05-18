#!/usr/bin/env python3
"""Run the canonical local dogfood inventory gate."""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import pdf_glyph_replace as glyph
import pdf_inventory


__version__ = glyph.__version__

DEFAULT_CORPUS = Path("work/dogfood-pdfs/sample-*.pdf")
DEFAULT_OUTPUT_DIR = Path("work/dogfood-pdfs/inventory")
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
    return parser.parse_args(argv)


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
    return pdf_inventory.main(build_inventory_argv(args))


if __name__ == "__main__":
    raise SystemExit(main())
