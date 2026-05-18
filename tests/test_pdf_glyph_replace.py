import unittest

import pdf_glyph_replace as p


CMAP_STREAM = b"""/CIDInit /ProcSet findresource begin
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


def qdf_with_text(text_body: bytes) -> bytes:
    return b"""1 0 obj
<<
  /Resources <<
    /Font <<
      /F4 25 0 R
    >>
  >>
>>
endobj
25 0 obj
<<
  /BaseFont /AAAAAA+Fixture
  /DescendantFonts [48 0 R]
  /Encoding /Identity-H
  /Subtype /Type0
  /ToUnicode 49 0 R
  /Type /Font
>>
endobj
49 0 obj
<<
  /Length 50 0 R
>>
stream
""" + CMAP_STREAM + b"""endstream
endobj
51 0 obj
<<
  /Length 52 0 R
>>
stream
BT
""" + text_body + b"""
ET
endstream
endobj
"""


def qdf_with_two_text_objects(first_body: bytes, second_body: bytes) -> bytes:
    return b"""1 0 obj
<<
  /Resources <<
    /Font <<
      /F4 25 0 R
    >>
  >>
>>
endobj
25 0 obj
<<
  /BaseFont /AAAAAA+Fixture
  /DescendantFonts [48 0 R]
  /Encoding /Identity-H
  /Subtype /Type0
  /ToUnicode 49 0 R
  /Type /Font
>>
endobj
49 0 obj
<<
  /Length 50 0 R
>>
stream
""" + CMAP_STREAM + b"""endstream
endobj
51 0 obj
<<
  /Length 52 0 R
>>
stream
BT
""" + first_body + b"""
ET
BT
""" + second_body + b"""
ET
endstream
endobj
"""


class PdfGlyphReplaceTests(unittest.TestCase):
    def test_parse_cmap_ignores_codespace_range_and_decodes_ranges(self):
        cmap = p.parse_cmap(CMAP_STREAM)

        self.assertEqual(cmap["0003"], " ")
        self.assertEqual(cmap["0004"], ".")
        self.assertEqual(cmap["002A"], "0")
        self.assertEqual(cmap["0032"], "8")
        self.assertEqual(cmap["0119"], "a")
        self.assertNotIn("0000", cmap)

    def test_exact_replacement_rewrites_only_matching_cids(self):
        qdf = qdf_with_text(
            b"""/F4 16 Tf
1 0 0 -1 100 10 Tm
<002D> Tj
9.6 0 Td <0032> Tj
9.6 0 Td <002A> Tj
9.6 0 Td <0031> Tj"""
        )

        edited, count = p.replace_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(count, 1)
        self.assertIn(b"<0032> Tj", edited)
        self.assertIn(b"9.6 0 Td <002E> Tj", edited)
        self.assertNotIn(b"9.6 0 Td <0031> Tj", edited)

    def test_exact_replacement_handles_multiple_cids_in_one_tj_operand(self):
        qdf = qdf_with_text(
            b"""/F4 16 Tf
1 0 0 -1 100 10 Tm
<002D0032002A0031> Tj"""
        )

        edited, count = p.replace_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(count, 1)
        self.assertIn(b"<0032002D002A002E> Tj", edited)

    def test_exact_replacement_handles_simple_tj_array(self):
        qdf = qdf_with_text(
            b"""/F4 16 Tf
1 0 0 -1 100 10 Tm
[<002D0032> 25 <002A0031>] TJ"""
        )

        edited, count = p.replace_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(count, 1)
        self.assertIn(b"[<0032002D> 25 <002A002E>] TJ", edited)

    def test_right_aligned_replacement_shifts_text_matrix_and_inserts_glyph(self):
        qdf = qdf_with_text(
            b"""/F4 16 Tf
1 0 0 -1 653.375 1370 Tm
<0093> Tj
9.6 0 Td <002D> Tj
9.6 0 Td <0031> Tj
9.6 0 Td <0004> Tj
3.6 0 Td <002D> Tj
9.6 0 Td <002E> Tj"""
        )

        edited, count = p.replace_qdf(qdf, "37.34", "138.46", align="right")

        self.assertEqual(count, 1)
        self.assertIn(b"1 0 0 -1 643.775 1370 Tm", edited)
        self.assertIn(b"9.6 0 Td <002B> Tj", edited)
        self.assertIn(b"9.6 0 Td <0032> Tj", edited)
        self.assertIn(b"3.6 0 Td <002E> Tj", edited)
        self.assertIn(b"9.6 0 Td <0030> Tj", edited)

    def test_left_aligned_replacement_preserves_text_matrix_and_inserts_glyph(self):
        qdf = qdf_with_text(
            b"""/F4 16 Tf
1 0 0 -1 653.375 1370 Tm
<0093> Tj
9.6 0 Td <002D> Tj
9.6 0 Td <0031> Tj
9.6 0 Td <0004> Tj
3.6 0 Td <002D> Tj
9.6 0 Td <002E> Tj"""
        )

        edited, count = p.replace_qdf(qdf, "37.34", "138.46", align="left")

        self.assertEqual(count, 1)
        self.assertIn(b"1 0 0 -1 653.375 1370 Tm", edited)
        self.assertIn(b"9.6 0 Td <002B> Tj", edited)
        self.assertIn(b"9.6 0 Td <0032> Tj", edited)
        self.assertIn(b"3.6 0 Td <002E> Tj", edited)
        self.assertIn(b"9.6 0 Td <0030> Tj", edited)

    def test_analyze_qdf_reports_feasibility(self):
        qdf = qdf_with_text(
            b"""/F4 16 Tf
1 0 0 -1 100 10 Tm
<002D> Tj
9.6 0 Td <0032> Tj
9.6 0 Td <002A> Tj
9.6 0 Td <0031> Tj"""
        )

        reports, decode_maps = p.analyze_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(sorted(decode_maps), ["F4"])
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].stream_object, 51)
        self.assertEqual(reports[0].match_count, 1)
        self.assertTrue(reports[0].feasible)
        self.assertEqual(reports[0].alignment_contract, "exact glyph-count replacement preserves existing layout operators")
        self.assertEqual(reports[0].estimated_x_shift, "0")

    def test_report_payload_omits_literal_text_and_keeps_locations(self):
        qdf = qdf_with_text(
            b"""/F4 16 Tf
1 0 0 -1 100 10 Tm
<002D0032002A0031> Tj"""
        )
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
        qdf = qdf_with_text(
            b"""/F4 16 Tf
1 0 0 -1 653.375 1370 Tm
<0093> Tj
9.6 0 Td <002D> Tj
9.6 0 Td <0031> Tj
9.6 0 Td <0004> Tj
3.6 0 Td <002D> Tj
9.6 0 Td <002E> Tj"""
        )

        reports, _ = p.analyze_qdf(qdf, "37.34", "138.46", align="left")

        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0].feasible)
        self.assertIn("left edge", reports[0].alignment_contract)
        self.assertEqual(reports[0].estimated_x_shift, "0")

    def test_analyze_qdf_reports_right_alignment_shift(self):
        qdf = qdf_with_text(
            b"""/F4 16 Tf
1 0 0 -1 653.375 1370 Tm
<0093> Tj
9.6 0 Td <002D> Tj
9.6 0 Td <0031> Tj
9.6 0 Td <0004> Tj
3.6 0 Td <002D> Tj
9.6 0 Td <002E> Tj"""
        )

        reports, _ = p.analyze_qdf(qdf, "37.34", "138.46", align="right")

        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0].feasible)
        self.assertIn("right edge", reports[0].alignment_contract)
        self.assertEqual(reports[0].estimated_x_shift, "-9.6")

    def test_analyze_qdf_reports_split_match_as_infeasible(self):
        qdf = qdf_with_two_text_objects(
            b"""/F4 16 Tf
1 0 0 -1 100 10 Tm
<002D0032> Tj""",
            b"""/F4 16 Tf
1 0 0 -1 140 10 Tm
<002A0031> Tj""",
        )

        reports, _ = p.analyze_qdf(qdf, "3807", "8304", align="exact")

        self.assertEqual(len(reports), 1)
        self.assertFalse(reports[0].feasible)
        self.assertIn("split", reports[0].reason)


if __name__ == "__main__":
    unittest.main()
