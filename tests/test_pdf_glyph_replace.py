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


def mixed_font_qdf(
    *text_objects: bytes,
    f4_cid_map: dict[str, str] | None = None,
    f5_cid_map: dict[str, str] | None = None,
) -> bytes:
    body = b"\nET\nBT\n".join(text_objects)
    f4_cmap = f.cmap_stream(f4_cid_map)
    f5_cmap = f.cmap_stream(f5_cid_map)
    return (
        b"""1 0 obj
<<
  /Resources <<
    /Font <<
      /F4 25 0 R
      /F5 26 0 R
    >>
  >>
>>
endobj
25 0 obj
<<
  /BaseFont /AAAAAA+SyntheticFixtureA
  /DescendantFonts [48 0 R]
  /Encoding /Identity-H
  /Subtype /Type0
  /ToUnicode 49 0 R
  /Type /Font
>>
endobj
26 0 obj
<<
  /BaseFont /BBBBBB+SyntheticFixtureB
  /DescendantFonts [58 0 R]
  /Encoding /Identity-H
  /Subtype /Type0
  /ToUnicode 59 0 R
  /Type /Font
>>
endobj
49 0 obj
<<
  /Length 50 0 R
>>
stream
"""
        + f4_cmap
        + b"""endstream
endobj
59 0 obj
<<
  /Length 60 0 R
>>
stream
"""
        + f5_cmap
        + b"""endstream
endobj
51 0 obj
<<
  /Length 52 0 R
>>
stream
BT
"""
        + body
        + b"""
ET
endstream
endobj
"""
    )


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
            layout_evidence={"status": "ok"},
        )

        self.assertEqual(payload["total_matches"], 1)
        self.assertFalse(payload["privacy"]["decoded_text_included"])
        self.assertFalse(payload["privacy"]["literal_search_replacement_included"])
        self.assertNotIn("decoded_text", payload["matches"][0])
        self.assertEqual(payload["matches"][0]["stream_object"], 51)
        self.assertEqual(payload["layout_evidence"], {"status": "ok"})

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

    def test_audit_qdf_reports_all_text_objects_and_split_font_match_without_text(self):
        qdf = mixed_font_qdf(
            f.text_object("38", font="F4", x="100", y="10"),
            f.text_object("07", font="F5", x="140", y="10"),
            f.text_object("9999", font="F5", x="200", y="10"),
        )

        payload = p.audit_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(payload["mode"], "audit")
        self.assertEqual(payload["total_text_objects"], 3)
        self.assertEqual(payload["total_matches"], 1)
        self.assertEqual(payload["patchable_matches"], 0)
        self.assertEqual(payload["unpatchable_matches"], 1)
        self.assertEqual(payload["split_match_count"], 1)
        self.assertEqual(
            payload["split_matches"][0]["text_object_indexes"],
            [1, 2],
        )
        self.assertEqual(payload["split_matches"][0]["fonts"], ["F4", "F5"])
        self.assertFalse(payload["split_matches"][0]["patchable"])
        self.assertEqual(payload["split_matches"][0]["split_kind"], "cross_text_object_and_font")
        self.assertEqual(
            [
                (segment["text_object_index"], segment["font"], segment["glyph_start"], segment["glyph_end"])
                for segment in payload["split_matches"][0]["segments"]
            ],
            [(1, "F4", 0, 2), (2, "F5", 0, 2)],
        )
        self.assertEqual(payload["split_matches"][0]["blockers"], [])
        self.assertEqual([obj["font"] for obj in payload["text_objects"]], ["F4", "F5", "F5"])
        self.assertEqual([obj["match_count"] for obj in payload["text_objects"]], [0, 0, 0])
        self.assertFalse(payload["privacy"]["decoded_text_included"])
        self.assertNotIn("3807", str(payload))
        self.assertNotIn("8304", str(payload))

    def test_audit_qdf_reports_patchable_mixed_font_object_match(self):
        qdf = mixed_font_qdf(
            f.text_object("9999", font="F4", x="100", y="10"),
            f.text_object("3807", font="F5", x="140", y="10"),
        )

        payload = p.audit_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(payload["total_text_objects"], 2)
        self.assertEqual(payload["total_matches"], 1)
        self.assertEqual(payload["patchable_matches"], 1)
        self.assertEqual(payload["unpatchable_matches"], 0)
        self.assertEqual(payload["split_match_count"], 0)
        self.assertEqual(payload["text_objects"][1]["font"], "F5")
        self.assertTrue(payload["text_objects"][1]["patchable"])
        self.assertEqual(payload["text_objects"][1]["alignment_contract"], "exact glyph-count replacement preserves existing layout operators")

    def test_audit_exit_status_distinguishes_patchable_missing_and_unpatchable(self):
        patchable = {
            "total_matches": 1,
            "unpatchable_matches": 0,
        }
        missing = {
            "total_matches": 0,
            "unpatchable_matches": 0,
        }
        unpatchable = {
            "total_matches": 1,
            "unpatchable_matches": 1,
        }

        self.assertEqual(p.audit_exit_status(patchable), 0)
        self.assertEqual(p.audit_exit_status(missing), 1)
        self.assertEqual(p.audit_exit_status(unpatchable), 2)

    def test_plan_qdf_records_patchable_exact_match_without_literal_text(self):
        qdf = f.synthetic_qdf("3807")

        payload = p.plan_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(payload["schema"], "pdf-mutation-plan")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["expected"]["total_candidates"], 1)
        self.assertEqual(payload["expected"]["patchable_matches"], 1)
        self.assertEqual(payload["expected"]["unpatchable_candidates"], 0)
        self.assertEqual(payload["expected"]["split_candidates"], 0)
        self.assertRegex(payload["plan_id"], r"^[0-9a-f]{16}$")
        self.assertFalse(payload["privacy"]["decoded_text_included"])
        self.assertFalse(payload["privacy"]["literal_search_replacement_included"])
        self.assertNotIn("3807", str(payload))
        self.assertNotIn("8304", str(payload))

        match = payload["matches"][0]
        self.assertEqual(match["id"], "m1")
        self.assertEqual(match["kind"], "text_object")
        self.assertTrue(match["patchable"])
        self.assertEqual(match["stream_object"], 51)
        self.assertEqual(match["font"], "F4")
        self.assertEqual(match["glyph_start"], 0)
        self.assertEqual(match["glyph_end"], 4)
        self.assertEqual(match["glyph_cids"], ["002D", "0032", "002A", "0031"])
        self.assertEqual(match["replacement_cids"], ["0032", "002D", "002A", "002E"])
        self.assertEqual(len(match["chunk_spans"]), 4)
        self.assertEqual(match["chunk_spans"][0]["old_cid"], "002D")
        self.assertEqual(match["chunk_spans"][0]["new_cid"], "0032")

    def test_plan_qdf_records_split_candidate_as_unpatchable(self):
        qdf = mixed_font_qdf(
            f.text_object("38", font="F4", x="100", y="10"),
            f.text_object("07", font="F5", x="140", y="10"),
        )

        payload = p.plan_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(payload["expected"]["total_candidates"], 1)
        self.assertEqual(payload["expected"]["patchable_matches"], 0)
        self.assertEqual(payload["expected"]["unpatchable_candidates"], 1)
        self.assertEqual(payload["expected"]["split_candidates"], 1)
        self.assertEqual(payload["matches"], [])
        self.assertEqual(payload["split_candidates"][0]["id"], "s1")
        self.assertEqual(payload["split_candidates"][0]["text_object_indexes"], [1, 2])
        self.assertEqual(payload["split_candidates"][0]["fonts"], ["F4", "F5"])
        self.assertFalse(payload["split_candidates"][0]["patchable"])
        self.assertEqual(payload["split_candidates"][0]["split_kind"], "cross_text_object_and_font")
        self.assertEqual(
            [
                (segment["text_object_index"], segment["font"], segment["glyph_start"], segment["glyph_end"])
                for segment in payload["split_candidates"][0]["segments"]
            ],
            [(1, "F4", 0, 2), (2, "F5", 0, 2)],
        )
        self.assertEqual(payload["split_candidates"][0]["blockers"], [])

    def test_plan_qdf_records_adjacent_same_font_split_as_unpatchable_segmented_candidate(self):
        qdf = f.qdf_document(
            f.text_object("38", font="F4", x="100", y="10"),
            f.text_object("07", font="F4", x="140", y="10"),
        )

        payload = p.plan_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(payload["expected"]["total_candidates"], 1)
        self.assertEqual(payload["expected"]["patchable_matches"], 0)
        self.assertEqual(payload["expected"]["split_candidates"], 1)
        split = payload["split_candidates"][0]
        self.assertEqual(split["split_kind"], "cross_text_object")
        self.assertEqual(split["fonts"], ["F4", "F4"])
        self.assertEqual(split["blockers"], [])
        self.assertTrue(all(segment["replacement_glyphs_available"] for segment in split["segments"]))

    def test_plan_qdf_records_missing_replacement_glyph_without_literal_replacement(self):
        qdf = f.synthetic_qdf("3807")

        payload = p.plan_qdf(qdf, "3807", "ZZZZ", align="exact")

        self.assertEqual(payload["expected"]["total_candidates"], 1)
        self.assertEqual(payload["expected"]["patchable_matches"], 0)
        self.assertEqual(payload["expected"]["unpatchable_candidates"], 1)
        match = payload["matches"][0]
        self.assertFalse(match["patchable"])
        self.assertEqual(match["reason"], "replacement character(s) not present in active font")
        self.assertEqual(match["replacement_cids"], [])
        self.assertNotIn("3807", str(payload))
        self.assertNotIn("ZZZZ", str(payload))

    def test_plan_qdf_records_split_blocker_when_replacement_glyph_missing_in_one_font(self):
        f5_map = dict(f.DEFAULT_CIDS)
        del f5_map["4"]
        qdf = mixed_font_qdf(
            f.text_object("38", font="F4", x="100", y="10"),
            f.text_object("07", font="F5", x="140", y="10", cid_map=f5_map),
            f5_cid_map=f5_map,
        )

        payload = p.plan_qdf(qdf, "3807", "8304", align="exact")

        split = payload["split_candidates"][0]
        self.assertEqual(split["split_kind"], "cross_text_object_and_font")
        self.assertEqual(
            [(segment["font"], segment["replacement_glyphs_available"]) for segment in split["segments"]],
            [("F4", True), ("F5", False)],
        )
        self.assertEqual(
            split["blockers"],
            [
                {
                    "font": "F5",
                    "text_object_index": 2,
                    "reason": "replacement character(s) not present in active font",
                    "missing_replacement_glyph_count": 1,
                }
            ],
        )
        self.assertNotIn("3807", str(payload))
        self.assertNotIn("8304", str(payload))

    def test_plan_exit_status_distinguishes_patchable_missing_and_unpatchable(self):
        patchable = {
            "expected": {"total_candidates": 1, "unpatchable_candidates": 0},
        }
        missing = {
            "expected": {"total_candidates": 0, "unpatchable_candidates": 0},
        }
        unpatchable = {
            "expected": {"total_candidates": 1, "unpatchable_candidates": 1},
        }

        self.assertEqual(p.plan_exit_status(patchable), 0)
        self.assertEqual(p.plan_exit_status(missing), 1)
        self.assertEqual(p.plan_exit_status(unpatchable), 2)

    def test_expect_count_helper_accepts_matching_count(self):
        self.assertEqual(p.non_negative_int("2"), 2)

        p.enforce_expect_count(2, 2, label="patchable match(es)")
        p.enforce_expect_count(None, 5, label="patchable match(es)")

    def test_expect_count_helper_rejects_invalid_or_mismatched_count(self):
        with self.assertRaises(p.argparse.ArgumentTypeError):
            p.non_negative_int("-1")
        with self.assertRaisesRegex(SystemExit, "expected 2 patchable match"):
            p.enforce_expect_count(2, 1, label="patchable match(es)")

    def test_apply_plan_to_qdf_rewrites_only_planned_exact_match(self):
        qdf = f.synthetic_qdf("3807")
        with p.tempfile.TemporaryDirectory() as tmp:
            input_pdf = p.Path(tmp) / "input.pdf"
            input_pdf.write_bytes(b"%PDF-fixture\n")
            plan = p.plan_qdf(qdf, "3807", "8304", align="exact", input_pdf=input_pdf)

            edited, changed_matches, changed_glyphs, applied_ids = p.apply_plan_to_qdf(
                qdf,
                plan,
                input_pdf=input_pdf,
            )

        self.assertEqual(changed_matches, 1)
        self.assertEqual(changed_glyphs, 4)
        self.assertEqual(applied_ids, ["m1"])
        self.assertIn(b"<0032002D002A002E> Tj", edited)
        self.assertNotIn(b"<002D0032002A0031> Tj", edited)

    def test_apply_plan_to_qdf_rejects_stale_input_fingerprint(self):
        qdf = f.synthetic_qdf("3807")
        with p.tempfile.TemporaryDirectory() as tmp:
            input_pdf = p.Path(tmp) / "input.pdf"
            input_pdf.write_bytes(b"%PDF-fixture\n")
            plan = p.plan_qdf(qdf, "3807", "8304", align="exact", input_pdf=input_pdf)
            input_pdf.write_bytes(b"%PDF-changed\n")

            with self.assertRaisesRegex(SystemExit, "input PDF fingerprint does not match plan"):
                p.apply_plan_to_qdf(qdf, plan, input_pdf=input_pdf)

    def test_apply_plan_to_qdf_rejects_stale_qdf_span(self):
        qdf = f.synthetic_qdf("3807")
        with p.tempfile.TemporaryDirectory() as tmp:
            input_pdf = p.Path(tmp) / "input.pdf"
            input_pdf.write_bytes(b"%PDF-fixture\n")
            plan = p.plan_qdf(qdf, "3807", "8304", align="exact", input_pdf=input_pdf)
            plan["matches"][0]["chunk_spans"][0]["old_cid"] = "FFFF"

            with self.assertRaisesRegex(SystemExit, "chunk span does not match"):
                p.apply_plan_to_qdf(qdf, plan, input_pdf=input_pdf)

    def test_apply_plan_to_qdf_rejects_unpatchable_plan(self):
        qdf = f.synthetic_qdf("3807")
        with p.tempfile.TemporaryDirectory() as tmp:
            input_pdf = p.Path(tmp) / "input.pdf"
            input_pdf.write_bytes(b"%PDF-fixture\n")
            plan = p.plan_qdf(qdf, "3807", "ZZZZ", align="exact", input_pdf=input_pdf)

            with self.assertRaisesRegex(SystemExit, "unpatchable candidates"):
                p.apply_plan_to_qdf(qdf, plan, input_pdf=input_pdf)

    def test_apply_plan_report_payload_omits_literal_text(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            input_pdf = p.Path(tmp) / "input.pdf"
            output_pdf = p.Path(tmp) / "output.pdf"
            input_pdf.write_bytes(b"%PDF-fixture\n")
            plan = p.plan_qdf(
                f.synthetic_qdf("3807"),
                "3807",
                "8304",
                align="exact",
                input_pdf=input_pdf,
            )

            payload = p.apply_plan_report_payload(
                plan=plan,
                input_pdf=input_pdf,
                output_pdf=output_pdf,
                changed_matches=1,
                changed_glyphs=4,
                applied_match_ids=["m1"],
                layout_evidence={"status": "ok"},
            )

        self.assertEqual(payload["mode"], "apply-plan")
        self.assertEqual(payload["plan_id"], plan["plan_id"])
        self.assertEqual(payload["changed_matches"], 1)
        self.assertEqual(payload["skipped_unapplied_count"], 0)
        self.assertEqual(payload["layout_evidence"], {"status": "ok"})
        self.assertFalse(payload["privacy"]["decoded_text_included"])
        self.assertNotIn("3807", str(payload))
        self.assertNotIn("8304", str(payload))

    def test_collect_bbox_evidence_records_artifact_hashes_without_report_text(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            root = p.Path(tmp)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            bbox_dir = root / "bbox"
            input_pdf.write_bytes(b"%PDF-before\n")
            output_pdf.write_bytes(b"%PDF-after\n")

            def fake_run_status(args):
                output = p.Path(args[-1])
                text = "8304" if "after" in output.name else "3807"
                output.write_text(
                    f'<html><word xMin="10" yMin="20" xMax="40" yMax="30">{text}</word></html>\n',
                    encoding="utf-8",
                )
                return 0, b"", b""

            with (
                unittest.mock.patch.object(p.shutil, "which", return_value="/usr/bin/pdftotext"),
                unittest.mock.patch.object(p, "run_status", side_effect=fake_run_status),
            ):
                payload = p.collect_bbox_evidence(
                    input_pdf=input_pdf,
                    output_pdf=output_pdf,
                    bbox_dir=bbox_dir,
                    stem="output",
                    search="3807",
                    replacement="8304",
                    align="exact",
                )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["before"]["status"], "ok")
        self.assertEqual(payload["after"]["status"], "ok")
        self.assertIn("sha256_12", payload["before"])
        self.assertEqual(payload["alignment_assertions"]["status"], "ok")
        self.assertEqual(payload["alignment_assertions"]["checked_pairs"], 1)
        self.assertEqual(payload["alignment_assertions"]["contract"], "text_extraction_changed")
        self.assertEqual(payload["alignment_assertions"]["before_match_count"], 1)
        self.assertEqual(payload["alignment_assertions"]["after_match_count"], 1)
        self.assertEqual(payload["alignment_assertions"]["assertions"], [])
        self.assertFalse(payload["privacy"]["report_includes_bbox_text"])
        self.assertTrue(payload["privacy"]["bbox_html_may_include_extracted_text"])
        self.assertNotIn("3807", str(payload))
        self.assertNotIn("8304", str(payload))

    def test_bbox_alignment_assertions_check_left_and_right_edges_without_literal_text(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            root = p.Path(tmp)
            before = root / "before.html"
            after_left = root / "after-left.html"
            after_right = root / "after-right.html"
            before.write_text(
                '<word xMin="100" yMin="20" xMax="150" yMax="30">37.34</word>',
                encoding="utf-8",
            )
            after_left.write_text(
                '<word xMin="100.2" yMin="20" xMax="165" yMax="30">138.46</word>',
                encoding="utf-8",
            )
            after_right.write_text(
                '<word xMin="85" yMin="20" xMax="150.3" yMax="30">138.46</word>',
                encoding="utf-8",
            )

            left = p.bbox_alignment_assertions(
                before_path=before,
                after_path=after_left,
                search="37.34",
                replacement="138.46",
                align="left",
            )
            right = p.bbox_alignment_assertions(
                before_path=before,
                after_path=after_right,
                search="37.34",
                replacement="138.46",
                align="right",
            )

        self.assertEqual(left["status"], "ok")
        self.assertEqual(left["assertions"][0]["contract"], "left_edge")
        self.assertEqual(left["assertions"][0]["left_delta"], "0.2")
        self.assertTrue(left["assertions"][0]["passed"])
        self.assertEqual(right["status"], "ok")
        self.assertEqual(right["assertions"][0]["contract"], "right_edge")
        self.assertEqual(right["assertions"][0]["right_delta"], "0.3")
        self.assertTrue(right["assertions"][0]["passed"])
        self.assertNotIn("37.34", str(left))
        self.assertNotIn("138.46", str(right))

    def test_bbox_alignment_assertions_warn_on_failed_contract(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            root = p.Path(tmp)
            before = root / "before.html"
            after = root / "after.html"
            before.write_text(
                '<word xMin="100" yMin="20" xMax="150" yMax="30">37.34</word>',
                encoding="utf-8",
            )
            after.write_text(
                '<word xMin="112" yMin="20" xMax="170" yMax="30">138.46</word>',
                encoding="utf-8",
            )

            payload = p.bbox_alignment_assertions(
                before_path=before,
                after_path=after,
                search="37.34",
                replacement="138.46",
                align="left",
            )

        self.assertEqual(payload["status"], "warning")
        self.assertFalse(payload["assertions"][0]["passed"])
        self.assertIn("failed", payload["warnings"][0])

    def test_collect_bbox_evidence_warns_when_pdftotext_is_missing(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            root = p.Path(tmp)
            input_pdf = root / "input.pdf"
            output_pdf = root / "output.pdf"
            input_pdf.write_bytes(b"%PDF-before\n")
            output_pdf.write_bytes(b"%PDF-after\n")

            with unittest.mock.patch.object(p.shutil, "which", return_value=None):
                payload = p.collect_bbox_evidence(
                    input_pdf=input_pdf,
                    output_pdf=output_pdf,
                    bbox_dir=root / "bbox",
                    stem="output",
                )

        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["before"]["status"], "unavailable")
        self.assertEqual(payload["after"]["status"], "unavailable")
        self.assertEqual(len(payload["warnings"]), 2)


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

    def test_main_prints_latest_by_policy_markdown(self):
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            status = ds.main([str(self.FIXTURE_MANIFEST), "--latest-by-policy", "--markdown"])

        output = stdout.getvalue()
        lines = output.splitlines()
        self.assertEqual(status, 0)
        self.assertEqual(
            lines[0],
            "| timestamp_unix | exit | policy | selected | pdfs | status_counts | "
            "probe_status_counts | fail_matches | fail_rules | json_path |",
        )
        self.assertEqual(lines[1], "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        self.assertEqual(len(lines), 4)
        self.assertIn("| 1700000060 | 2 | readiness | readiness | 3 |", lines[2])
        self.assertIn("probe-no-match,unsupported", lines[2])
        self.assertIn("routine-latest.json", lines[3])
        self.assertNotIn("3807", output)
        self.assertNotIn("8304", output)

    def test_main_writes_markdown_output_file(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            output_path = p.Path(tmp) / "summaries" / "latest.md"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                status = ds.main(
                    [
                        str(self.FIXTURE_MANIFEST),
                        "--latest-by-policy",
                        "--markdown",
                        "--output",
                        str(output_path),
                    ]
                )

            content = output_path.read_text(encoding="utf-8")
            self.assertEqual(status, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("| timestamp_unix | exit | policy |", content)
            self.assertIn("routine-latest.json", content)
            self.assertTrue(content.endswith("\n"))
            self.assertNotIn("3807", content)
            self.assertNotIn("8304", content)

    def test_main_writes_json_output_file(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            output_path = p.Path(tmp) / "summary.json"

            status = ds.main([str(self.FIXTURE_MANIFEST), "--limit", "1", "--json", "--output", str(output_path)])

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(status, 0)
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["policy"]["json_path"], "work/dogfood-pdfs/inventory/routine-latest.json")

    def test_main_writes_health_output_file_and_preserves_status(self):
        with p.tempfile.TemporaryDirectory() as tmp:
            output_path = p.Path(tmp) / "health.txt"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                status = ds.main([str(self.FIXTURE_MANIFEST), "--health", "--output", str(output_path)])

            self.assertEqual(status, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("policy=readiness", output_path.read_text(encoding="utf-8"))

    def test_markdown_cell_escapes_table_delimiters_and_newlines(self):
        self.assertEqual(ds.markdown_cell(r"a\b|c\nd"), r"a\\b\|c\\nd")
        self.assertEqual(ds.markdown_cell("a|b\nc"), r"a\|b<br>c")

    def test_main_rejects_json_and_markdown(self):
        with self.assertRaises(SystemExit) as raised:
            ds.main([str(self.FIXTURE_MANIFEST), "--json", "--markdown"])

        self.assertEqual(str(raised.exception), "--json and --markdown are mutually exclusive")

    def test_main_prints_latest_by_policy_json_after_filters(self):
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            status = ds.main([str(self.FIXTURE_MANIFEST), "--latest-by-policy", "--exit-code", "0", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["policy"]["policy"], "routine")
        self.assertEqual(payload[0]["policy"]["json_path"], "work/dogfood-pdfs/inventory/routine-latest.json")

    def test_health_status_reports_failed_gate_record(self):
        records = ds.load_manifest(self.FIXTURE_MANIFEST)

        status, line = ds.health_status(ds.health_record(records))

        self.assertEqual(status, 2)
        self.assertIn("fail", line)
        self.assertIn("policy=readiness", line)
        self.assertIn("fail_matches=2", line)
        self.assertIn("probe-no-match,unsupported", line)

    def test_health_status_reports_passed_gate_record(self):
        record = {
            "exit_code": 0,
            "fail_on_match_count": 0,
            "fail_on_rules": [],
            "policy": {
                "policy": "complete",
                "selected_policy": "complete",
                "json_path": "work/dogfood-pdfs/inventory/complete.json",
            },
        }

        status, line = ds.health_status(record)

        self.assertEqual(status, 0)
        self.assertIn("ok", line)
        self.assertIn("policy=complete", line)
        self.assertIn("exit=0", line)

    def test_health_status_reports_missing_gate_record(self):
        status, line = ds.health_status(None)

        self.assertEqual(status, 2)
        self.assertIn("missing", line)

    def test_main_health_returns_nonzero_for_failed_fixture_gate(self):
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            status = ds.main([str(self.FIXTURE_MANIFEST), "--health"])

        self.assertEqual(status, 2)
        self.assertIn("policy=readiness", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
