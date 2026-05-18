import unittest

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


if __name__ == "__main__":
    unittest.main()
