import contextlib
import io
import json
import unittest
import unittest.mock

import pdf_dogfood as d
import pdf_dogfood_summary as ds
import pdf_fixture as f
import pdf_glyph_replace as p
import pdf_inventory as inv


CMAP_RANGE_STREAM = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo
<< /Registry (Adobe)
/Ordering (UCS)
/Supplement 0
>> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
4 beginbfchar
<0003> <0020>
<0004> <002E>
<0093> <0024>
<00FF> <0041>
endbfchar
10 beginbfchar
<002A> <0030>
<002B> <0031>
<002C> <0032>
<002D> <0033>
<002E> <0034>
<002F> <0035>
<0030> <0036>
<0031> <0037>
<0032> <0038>
<0033> <0039>
endbfchar
1 beginbfrange
<0119> <0121> <0061>
endbfrange
endcmap
CMapName currentdict /CMap defineresource pop
end
end
"""


class PdfGlyphReplaceTests(unittest.TestCase):
    def test_parse_cmap_ignores_codespace_range_and_decodes_ranges(self):
        cmap = p.parse_cmap(CMAP_RANGE_STREAM)

        self.assertEqual(cmap["0003"], " ")
        self.assertEqual(cmap["0004"], ".")
        self.assertEqual(cmap["002A"], "0")
        self.assertEqual(cmap["0032"], "8")
        self.assertEqual(cmap["0119"], "a")
        self.assertNotIn("0000", cmap)

    def test_exact_replacement_rewrites_only_matching_cids(self):
        qdf = f.synthetic_qdf("3807", one_glyph_per_line=True)

        edited, count = p.replace_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(count, 1)
        self.assertIn(b"<0032> Tj", edited)
        self.assertIn(b"9.6 0 Td <002E> Tj", edited)
        self.assertNotIn(b"9.6 0 Td <0031> Tj", edited)

    def test_exact_replacement_handles_multiple_cids_in_one_tj_operand(self):
        qdf = f.synthetic_qdf("3807")

        edited, count = p.replace_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(count, 1)
        self.assertIn(b"<0032002D002A002E> Tj", edited)

    def test_exact_replacement_handles_simple_tj_array(self):
        qdf = f.qdf_document(
            b"""/F4 16 Tf
1 0 0 -1 100 10 Tm
[<002D0032> 25 <002A0031>] TJ"""
        )

        edited, count = p.replace_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(count, 1)
        self.assertIn(b"[<0032002D> 25 <002A002E>] TJ", edited)

    def test_right_aligned_replacement_shifts_text_matrix_and_inserts_glyph(self):
        qdf = f.synthetic_qdf("$37.34", one_glyph_per_line=True, x="653.375", y="1370")

        edited, count = p.replace_qdf(qdf, "37.34", "138.46", align="right")

        self.assertEqual(count, 1)
        self.assertIn(b"1 0 0 -1 643.775 1370 Tm", edited)
        self.assertIn(b"9.6 0 Td <002B> Tj", edited)
        self.assertIn(b"9.6 0 Td <0032> Tj", edited)
        self.assertIn(b"3.6 0 Td <002E> Tj", edited)
        self.assertIn(b"9.6 0 Td <0030> Tj", edited)

    def test_left_aligned_replacement_preserves_text_matrix_and_inserts_glyph(self):
        qdf = f.synthetic_qdf("$37.34", one_glyph_per_line=True, x="653.375", y="1370")

        edited, count = p.replace_qdf(qdf, "37.34", "138.46", align="left")

        self.assertEqual(count, 1)
        self.assertIn(b"1 0 0 -1 653.375 1370 Tm", edited)
        self.assertIn(b"9.6 0 Td <002B> Tj", edited)
        self.assertIn(b"9.6 0 Td <0032> Tj", edited)
        self.assertIn(b"3.6 0 Td <002E> Tj", edited)
        self.assertIn(b"9.6 0 Td <0030> Tj", edited)

    def test_analyze_qdf_reports_feasibility(self):
        qdf = f.synthetic_qdf("3807", one_glyph_per_line=True)

        reports, decode_maps = p.analyze_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(sorted(decode_maps), ["F4"])
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].stream_object, 51)
        self.assertEqual(reports[0].match_count, 1)
        self.assertTrue(reports[0].feasible)
        self.assertEqual(reports[0].alignment_contract, "exact glyph-count replacement preserves existing layout operators")
        self.assertEqual(reports[0].estimated_x_shift, "0")

    def test_report_payload_omits_literal_text_and_keeps_locations(self):
        qdf = f.synthetic_qdf("3807")
        reports, decode_maps = p.analyze_qdf(qdf, "3807", "8304", align="exact")

        payload = p.report_payload(
            input_pdf=p.Path("input.pdf"),
            output_pdf=p.Path("output.pdf"),
            search="3807",
            replacement="8304",
            align="exact",
            reports=reports,
            decode_maps=decode_maps,
            dry_run=False,
        )

        self.assertEqual(payload["total_matches"], 1)
        self.assertFalse(payload["privacy"]["decoded_text_included"])
        self.assertFalse(payload["privacy"]["literal_search_replacement_included"])
        self.assertNotIn("decoded_text", payload["matches"][0])
        self.assertEqual(payload["matches"][0]["stream_object"], 51)

    def test_analyze_qdf_reports_left_alignment_contract(self):
        qdf = f.synthetic_qdf("$37.34", one_glyph_per_line=True, x="653.375", y="1370")

        reports, _ = p.analyze_qdf(qdf, "37.34", "138.46", align="left")

        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0].feasible)
        self.assertIn("left edge", reports[0].alignment_contract)
        self.assertEqual(reports[0].estimated_x_shift, "0")

    def test_analyze_qdf_reports_right_alignment_shift(self):
        qdf = f.synthetic_qdf("$37.34", one_glyph_per_line=True, x="653.375", y="1370")

        reports, _ = p.analyze_qdf(qdf, "37.34", "138.46", align="right")

        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0].feasible)
        self.assertIn("right edge", reports[0].alignment_contract)
        self.assertEqual(reports[0].estimated_x_shift, "-9.6")

    def test_analyze_qdf_reports_split_match_as_infeasible(self):
        qdf = f.qdf_document(
            f.text_object("38", x="100", y="10"),
            f.text_object("07", x="140", y="10"),
        )

        reports, _ = p.analyze_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(len(reports), 1)
        self.assertFalse(reports[0].feasible)
        self.assertIn("split", reports[0].reason)


class PdfFixtureTests(unittest.TestCase):
    def test_synthetic_qdf_decodes_through_replacement_analysis(self):
        qdf = f.synthetic_qdf("3807")

        reports, decode_maps = p.analyze_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(sorted(decode_maps), ["F4"])
        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0].feasible)

    def test_fixture_cli_writes_qdf(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            output = p.Path(tmp) / "fixture.qdf"

            status = f.main(["3807", "-o", str(output)])

            self.assertEqual(status, 0)
            qdf = output.read_bytes()
            self.assertIn(b"/BaseFont /AAAAAA+SyntheticFixture", qdf)
            self.assertIn(b"<002D0032002A0031> Tj", qdf)

    def test_fixture_rejects_missing_characters(self):
        with self.assertRaises(ValueError):
            f.synthetic_qdf("missing Z")


class PdfInventoryTests(unittest.TestCase):
    def test_classify_qdf_reports_supported_synthetic_fixture_without_text(self):
        qdf = f.synthetic_qdf("3807")

        row = inv.classify_qdf(qdf)

        self.assertEqual(row["status"], "supported")
        self.assertEqual(row["type0_font_count"], 1)
        self.assertEqual(row["decoded_font_resource_count"], 1)
        self.assertEqual(row["text_object_count"], 1)
        self.assertNotIn("decoded_text", row)

    def test_classify_qdf_reports_unsupported_non_type0_fixture(self):
        qdf = b"""1 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
2 0 obj
<< /Length 3 0 R >>
stream
BT
/F1 12 Tf
(hello) Tj
ET
endstream
endobj
"""

        row = inv.classify_qdf(qdf)

        self.assertEqual(row["status"], "unsupported")
        self.assertEqual(row["type0_font_count"], 0)
        self.assertEqual(row["decoded_font_resource_count"], 0)
        self.assertEqual(row["text_object_count"], 1)

    def test_probe_qdf_reports_feasible_match_without_literal_text(self):
        probe = inv.probe_qdf(f.synthetic_qdf("3807"), search="3807", replacement="8304", align="exact")

        self.assertEqual(probe["status"], "feasible")
        self.assertEqual(probe["total_matches"], 1)
        self.assertTrue(probe["feasible"])
        self.assertEqual(probe["match_count_by_font"], [{"font": "F4", "match_count": 1}])
        self.assertNotIn("3807", str(probe))
        self.assertNotIn("8304", str(probe))

    def test_probe_qdf_reports_no_match_without_failure(self):
        probe = inv.probe_qdf(f.synthetic_qdf("3807"), search="9999", replacement="8304", align="exact")

        self.assertEqual(probe["status"], "no_match")
        self.assertEqual(probe["total_matches"], 0)
        self.assertFalse(probe["feasible"])

    def test_probe_qdf_reports_unsupported_without_failure(self):
        probe = inv.probe_qdf(b"1 0 obj\n<<>>\nendobj\n", search="3807", replacement="8304", align="exact")

        self.assertEqual(probe["status"], "unsupported")
        self.assertEqual(probe["total_matches"], 0)
        self.assertFalse(probe["feasible"])

    def test_inventory_pdf_skips_oversized_input_before_qdf_conversion(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            pdf = p.Path(tmp) / "large.pdf"
            pdf.write_bytes(b"%PDF-1.7\n" + (b"0" * 32))

            row = inv.inventory_pdf(
                pdf,
                max_input_bytes=16,
                probe=("3807", "8304"),
            )

            self.assertEqual(row["status"], "skipped")
            self.assertFalse(row["qpdf_check"])
            self.assertFalse(row["qdf_conversion"])
            self.assertEqual(row["max_input_bytes"], 16)
            self.assertEqual(row["probe"]["status"], "skipped")
            self.assertNotIn("3807", str(row))
            self.assertNotIn("8304", str(row))

    def test_build_summary_aggregates_status_and_probe_counts(self):
        rows = [
            {
                "status": "supported",
                "reason": "decoded Type0 ToUnicode font resources found",
                "size_bytes": 100,
                "qpdf_check": True,
                "qdf_conversion": True,
                "type0_font_count": 1,
                "decoded_font_resource_count": 1,
                "text_object_count": 2,
                "probe": {"status": "feasible", "total_matches": 1, "feasible": True},
            },
            {
                "status": "unsupported",
                "reason": "no Type0 fonts with ToUnicode CMaps found",
                "size_bytes": 50,
                "qpdf_check": True,
                "qdf_conversion": True,
                "type0_font_count": 0,
                "decoded_font_resource_count": 0,
                "text_object_count": 1,
                "probe": {"status": "unsupported", "total_matches": 0, "feasible": False},
            },
            {
                "status": "skipped",
                "reason": "input size exceeds --max-input-bytes (16)",
                "size_bytes": 200,
                "qpdf_check": False,
                "qdf_conversion": False,
                "type0_font_count": 0,
                "decoded_font_resource_count": 0,
                "text_object_count": 0,
                "probe": {"status": "skipped", "total_matches": 0, "feasible": False},
            },
        ]

        summary = inv.build_summary(rows)

        self.assertEqual(summary["total_pdfs"], 3)
        self.assertEqual(summary["total_size_bytes"], 350)
        self.assertEqual(summary["status_counts"], {"skipped": 1, "supported": 1, "unsupported": 1})
        self.assertEqual(
            summary["probe_status_counts"],
            {"feasible": 1, "skipped": 1, "unsupported": 1},
        )
        self.assertEqual(summary["probe_total_matches"], 1)
        self.assertEqual(summary["probe_feasible_pdfs"], 1)

    def test_fail_on_matches_selected_inventory_and_probe_rules(self):
        rows = [
            {
                "input_pdf": "supported.pdf",
                "status": "supported",
                "qpdf_check": True,
                "qdf_conversion": True,
                "probe": {"status": "feasible", "total_matches": 1},
            },
            {
                "input_pdf": "unsupported.pdf",
                "status": "unsupported",
                "reason": "no Type0 fonts with ToUnicode CMaps found",
                "qpdf_check": True,
                "qdf_conversion": True,
                "probe": {"status": "unsupported", "total_matches": 0},
            },
            {
                "input_pdf": "skipped.pdf",
                "status": "skipped",
                "reason": "input size exceeds --max-input-bytes (16)",
                "qpdf_check": False,
                "qdf_conversion": False,
                "probe": {"status": "skipped", "total_matches": 0},
            },
            {
                "input_pdf": "broken.pdf",
                "status": "error",
                "reason": "qpdf QDF conversion failed",
                "qpdf_check": True,
                "qdf_conversion": False,
            },
        ]

        matches = inv.fail_on_matches(
            rows,
            ["unsupported", "qdf-conversion-failed", "probe-feasible", "probe-match"],
        )

        self.assertEqual([match["input_pdf"] for match in matches], [
            "supported.pdf",
            "unsupported.pdf",
            "broken.pdf",
        ])
        self.assertEqual(matches[0]["rules"], ["probe-feasible", "probe-match"])
        self.assertEqual(matches[1]["rules"], ["unsupported"])
        self.assertEqual(matches[2]["rules"], ["qdf-conversion-failed"])

    def test_main_returns_two_for_fail_on_match(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            pdf = p.Path(tmp) / "large.pdf"
            pdf.write_bytes(b"%PDF-1.7\n" + (b"0" * 32))

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                unittest.mock.patch.object(inv.glyph, "require_tool"),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                status = inv.main([
                    str(pdf),
                    "--max-input-bytes",
                    "16",
                    "--fail-on",
                    "skipped",
                ])

            self.assertEqual(status, 2)
            self.assertIn("fail_on_matches", stderr.getvalue())

    def test_write_outputs_writes_json_and_tsv(self):
        row = inv.classify_qdf(f.synthetic_qdf("3807"))
        row.update(
            {
                "input_pdf": "sample.pdf",
                "size_bytes": 123,
                "qpdf_check": True,
                "qdf_conversion": True,
                "duration_seconds": 0.1,
                "probe": inv.probe_qdf(
                    f.synthetic_qdf("3807"),
                    search="3807",
                    replacement="8304",
                    align="exact",
                ),
            }
        )
        with p.tempfile.TemporaryDirectory() as tmp:
            json_path = p.Path(tmp) / "inventory.json"
            tsv_path = p.Path(tmp) / "inventory.tsv"

            inv.write_outputs(
                [row],
                json_path=json_path,
                tsv_path=tsv_path,
                summary=inv.build_summary([row]),
            )

            self.assertIn('"summary"', json_path.read_text())
            self.assertIn('"status": "supported"', json_path.read_text())
            self.assertIn("sample.pdf", tsv_path.read_text())
            self.assertIn("probe_status", tsv_path.read_text())


class PdfDogfoodTests(unittest.TestCase):
    def test_build_inventory_argv_uses_canonical_defaults(self):
        args = d.parse_args(["--probe", "3807", "8304"])

        argv = d.build_inventory_argv(args)

        self.assertIn("work/dogfood-pdfs/sample-*.pdf", argv)
        self.assertIn("--summary", argv)
        self.assertIn("--probe", argv)
        self.assertEqual(
            argv[argv.index("--probe") + 1 : argv.index("--probe") + 3],
            ["3807", "8304"],
        )
        self.assertEqual(
            argv[argv.index("--fail-on") + 1 :],
            ["error", "qpdf-check-failed", "qdf-conversion-failed", "probe-feasible"],
        )
        self.assertIn("work/dogfood-pdfs/inventory/dogfood.json", argv)

    def test_build_inventory_argv_can_run_report_only(self):
        args = d.parse_args(["--no-fail-on", "--name", "baseline"])

        argv = d.build_inventory_argv(args)

        self.assertNotIn("--fail-on", argv)
        self.assertIn("work/dogfood-pdfs/inventory/baseline.json", argv)

    def test_build_inventory_argv_uses_named_policy(self):
        args = d.parse_args(["--policy", "complete"])

        argv = d.build_inventory_argv(args)

        self.assertEqual(
            argv[argv.index("--fail-on") + 1 :],
            ["error", "qpdf-check-failed", "qdf-conversion-failed", "skipped"],
        )
        self.assertIn("work/dogfood-pdfs/inventory/dogfood-complete.json", argv)

    def test_build_inventory_argv_explicit_fail_on_overrides_policy(self):
        args = d.parse_args(["--policy", "complete", "--fail-on", "error"])

        argv = d.build_inventory_argv(args)

        self.assertEqual(argv[argv.index("--fail-on") + 1 :], ["error"])

    def test_build_inventory_argv_uses_readiness_policy(self):
        args = d.parse_args(["--policy", "readiness", "--probe", "SEARCH", "REPLACEMENT"])

        argv = d.build_inventory_argv(args)

        self.assertEqual(
            argv[argv.index("--fail-on") + 1 :],
            [
                "error",
                "unsupported",
                "skipped",
                "probe-unsupported",
                "probe-no-match",
                "probe-infeasible",
            ],
        )
        self.assertIn("work/dogfood-pdfs/inventory/dogfood-readiness.json", argv)

    def test_policy_metadata_records_effective_policy_without_probe_literals(self):
        args = d.parse_args(["--policy", "readiness", "--probe", "3807", "8304"])
        args.pdfs = [p.Path("work/dogfood-pdfs/sample-01.pdf")]

        metadata = d.policy_metadata(args)

        self.assertEqual(metadata["tool"], "pdf-dogfood")
        self.assertEqual(metadata["policy"], "readiness")
        self.assertEqual(metadata["selected_policy"], "readiness")
        self.assertEqual(
            metadata["fail_on"],
            [
                "error",
                "unsupported",
                "skipped",
                "probe-unsupported",
                "probe-no-match",
                "probe-infeasible",
            ],
        )
        self.assertEqual(metadata["input_count"], 1)
        self.assertEqual(metadata["probe"]["search_length"], 4)
        self.assertNotIn("3807", str(metadata))
        self.assertNotIn("8304", str(metadata))

    def test_policy_metadata_marks_overrides(self):
        args = d.parse_args(["--policy", "complete", "--fail-on", "error"])

        metadata = d.policy_metadata(args)

        self.assertEqual(metadata["policy"], "custom")
        self.assertEqual(metadata["selected_policy"], "complete")
        self.assertEqual(metadata["fail_on"], ["error"])

    def test_manifest_record_is_compact_and_non_literal(self):
        args = d.parse_args(["--probe", "3807", "8304"])
        args.pdfs = [p.Path("work/dogfood-pdfs/sample-01.pdf")]
        policy = d.policy_metadata(args)
        summary = {
            "total_pdfs": 1,
            "status_counts": {"supported": 1},
            "reason_counts": {"decoded Type0 ToUnicode font resources found": 1},
            "probe_status_counts": {"no_match": 1},
            "probe_total_matches": 0,
            "probe_feasible_pdfs": 0,
            "qpdf_check_failed": 0,
            "qdf_conversion_failed": 0,
        }

        record = d.manifest_record(policy=policy, summary=summary, matches=[], exit_code=0)

        self.assertEqual(record["tool"], "pdf-dogfood")
        self.assertEqual(record["exit_code"], 0)
        self.assertEqual(record["summary"]["status_counts"], {"supported": 1})
        self.assertEqual(record["fail_on_match_count"], 0)
        self.assertNotIn("rows", record)
        self.assertNotIn("3807", str(record))
        self.assertNotIn("8304", str(record))

    def test_append_manifest_writes_jsonl(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            path = p.Path(tmp) / "manifest.jsonl"
            d.append_manifest(path, {"b": 2, "a": 1})
            d.append_manifest(path, {"c": 3})

            lines = path.read_text().splitlines()

            self.assertEqual(lines, ['{"a": 1, "b": 2}', '{"c": 3}'])

    def test_expand_pdf_args_expands_globs(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            root = p.Path(tmp)
            first = root / "a.pdf"
            second = root / "b.pdf"
            first.write_text("a")
            second.write_text("b")

            expanded = d.expand_pdf_args([root / "*.pdf"])

            self.assertEqual(expanded, [first, second])


class PdfDogfoodSummaryTests(unittest.TestCase):
    FIXTURE_MANIFEST = p.Path(__file__).parent / "fixtures" / "dogfood-manifest.jsonl"

    def test_rows_for_records_formats_manifest_counts(self):
        records = [
            {
                "timestamp_unix": 123,
                "exit_code": 2,
                "policy": {
                    "policy": "readiness",
                    "selected_policy": "readiness",
                    "json_path": "work/dogfood-pdfs/inventory/readiness.json",
                },
                "summary": {
                    "total_pdfs": 2,
                    "status_counts": {"supported": 1, "unsupported": 1},
                    "probe_status_counts": {"no_match": 1, "unsupported": 1},
                },
                "fail_on_match_count": 2,
                "fail_on_rules": ["probe-no-match", "unsupported"],
            }
        ]

        rows = ds.rows_for_records(records)

        self.assertEqual(
            rows,
            [
                [
                    "123",
                    "2",
                    "readiness",
                    "readiness",
                    "2",
                    "supported=1,unsupported=1",
                    "no_match=1,unsupported=1",
                    "2",
                    "probe-no-match,unsupported",
                    "work/dogfood-pdfs/inventory/readiness.json",
                ]
            ],
        )

    def test_load_manifest_reads_jsonl(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            manifest = p.Path(tmp) / "manifest.jsonl"
            manifest.write_text('{"a": 1}\n\n{"b": 2}\n', encoding="utf-8")

            records = ds.load_manifest(manifest)

            self.assertEqual(records, [{"a": 1}, {"b": 2}])

    def test_filter_records_combines_policy_fail_and_exit_filters(self):
        records = ds.load_manifest(self.FIXTURE_MANIFEST)

        filtered = ds.filter_records(
            records,
            policies=["readiness"],
            fail_only=True,
            exit_codes=[2],
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["policy"]["policy"], "readiness")
        self.assertEqual(filtered[0]["exit_code"], 2)

    def test_main_prints_fixture_manifest_table(self):
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            status = ds.main([str(self.FIXTURE_MANIFEST), "--limit", "2"])

        output = stdout.getvalue()
        lines = output.splitlines()
        self.assertEqual(status, 0)
        self.assertEqual(
            lines[0],
            "timestamp_unix\texit\tpolicy\tselected\tpdfs\tstatus_counts\t"
            "probe_status_counts\tfail_matches\tfail_rules\tjson_path",
        )
        self.assertEqual(len(lines), 3)
        self.assertIn("readiness", lines[1])
        self.assertIn("probe-no-match,unsupported", lines[1])
        self.assertIn("routine", lines[2])
        self.assertIn("routine-latest.json", lines[2])
        self.assertNotIn("3807", output)
        self.assertNotIn("8304", output)

    def test_main_prints_fixture_manifest_json(self):
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            status = ds.main([str(self.FIXTURE_MANIFEST), "--limit", "1", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["policy"]["policy"], "routine")
        self.assertEqual(payload[0]["policy"]["json_path"], "work/dogfood-pdfs/inventory/routine-latest.json")

    def test_main_filters_fixture_manifest_table(self):
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            status = ds.main([str(self.FIXTURE_MANIFEST), "--fail-only", "--policy", "readiness"])

        lines = stdout.getvalue().splitlines()
        self.assertEqual(status, 0)
        self.assertEqual(len(lines), 2)
        self.assertIn("readiness", lines[1])
        self.assertNotIn("routine", lines[1])

    def test_main_filters_fixture_manifest_json_by_exit_code(self):
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            status = ds.main([str(self.FIXTURE_MANIFEST), "--exit-code", "0", "--limit", "1", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["policy"]["policy"], "routine")
        self.assertEqual(payload[0]["policy"]["json_path"], "work/dogfood-pdfs/inventory/routine-latest.json")
        self.assertEqual(payload[0]["exit_code"], 0)

    def test_latest_by_policy_keeps_last_record_for_each_policy(self):
        records = ds.load_manifest(self.FIXTURE_MANIFEST)

        latest = ds.latest_by_policy(records)

        self.assertEqual([record["policy"]["policy"] for record in latest], ["readiness", "routine"])
        self.assertEqual(latest[0]["policy"]["json_path"], "work/dogfood-pdfs/inventory/readiness.json")
        self.assertEqual(latest[1]["policy"]["json_path"], "work/dogfood-pdfs/inventory/routine-latest.json")

    def test_main_prints_latest_by_policy_table(self):
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            status = ds.main([str(self.FIXTURE_MANIFEST), "--latest-by-policy"])

        lines = stdout.getvalue().splitlines()
        self.assertEqual(status, 0)
        self.assertEqual(len(lines), 3)
        self.assertIn("readiness", lines[1])
        self.assertIn("routine-latest.json", lines[2])

    def test_main_prints_latest_by_policy_json_after_filters(self):
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            status = ds.main([str(self.FIXTURE_MANIFEST), "--latest-by-policy", "--exit-code", "0", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["policy"]["policy"], "routine")
        self.assertEqual(payload[0]["policy"]["json_path"], "work/dogfood-pdfs/inventory/routine-latest.json")


if __name__ == "__main__":
    unittest.main()
