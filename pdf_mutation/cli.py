"""Console entrypoint for pdf-glyph-replace."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from pdf_mutation.adapters import require_tool, run
from pdf_mutation.engine import (
    __version__,
    analyze_qdf,
    apply_plan_report_payload,
    apply_plan_to_qdf,
    audit_exit_status,
    audit_qdf,
    plan_exit_status,
    plan_qdf,
    print_dry_run_report,
    replace_qdf,
    report_payload,
    write_report,
)
from pdf_mutation.layout import collect_bbox_evidence


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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report decoded matches and feasibility without writing a PDF",
    )
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


__all__ = [
    "enforce_expect_count",
    "load_json_file",
    "main",
    "non_negative_int",
    "print_audit_report",
    "print_plan_report",
]
