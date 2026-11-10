import io
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from judge_core import answer, read_pdf, report, select_evidence
from report_docx import build as word_report


def sample_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    })
    text = DecodedStreamObject()
    text.set_data(b"BT /F1 16 Tf 72 748 Td (Synthetic evidence: Project Willow requires two backup landing sites.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(text)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class JudgeTests(unittest.TestCase):
    def test_greeting_uses_model_without_evidence(self):
        with patch("judge_core.judge_answer", return_value={"status": "CONNECTED", "answer": "你好！"}) as model:
            result = answer("test", "你好", [])
        self.assertEqual(model.call_args.args[2]["evidence"], [])
        self.assertEqual(result["result"]["answer"], "你好！")

    def test_regions_follow_up_and_switch(self):
        regions, sources = select_evidence("黑龙江有哪些低空政策")
        self.assertEqual(regions, ("黑龙江",))
        self.assertTrue(any(x["id"] == "hlj-huma" for x in sources))
        self.assertEqual(select_evidence("进一步说说风险", regions)[0], regions)
        new_regions, new_sources = select_evidence("福建与安徽的试点场景", regions)
        self.assertEqual(new_regions, ("福建", "安徽"))
        self.assertEqual({x["region"] for x in new_sources}, {"全国", "福建", "安徽"})

    def test_pdf_location_and_report_export(self):
        pages = read_pdf(sample_pdf(), "synthetic.pdf")
        self.assertIn("Project Willow", pages[0][1])
        with patch("judge_core.judge_answer", return_value={
            "status": "CONNECTED", "answer": "附件要求两个备用降落点。[1]"
        }) as model:
            result = answer("test", "Project Willow 有什么要求？", [], pages, "synthetic.pdf")
        evidence = model.call_args.args[2]["evidence"]
        self.assertIn("Project Willow", evidence[0]["text"])
        self.assertEqual(result["cited"][0]["locator"], "第 1 页")
        markdown = report(result)
        self.assertIn("synthetic.pdf", markdown)
        with ZipFile(io.BytesIO(word_report(markdown))) as doc:
            self.assertIn("synthetic.pdf", doc.read("word/document.xml").decode())

    def test_pdf_isolation_and_model_error(self):
        with patch("judge_core.judge_answer", return_value={"status": "HTTP_ERROR", "http_code": 401}) as model:
            result = answer("test", "附件呢？", [{
                "question": "上次有附件", "regions": (), "uses_pdf": True,
                "result": {"status": "CONNECTED", "answer": "私有附件内容"},
            }])
        self.assertEqual(model.call_args.args[2]["history"], [])
        self.assertEqual(result["result"], {"status": "HTTP_ERROR", "http_code": 401})

    def test_invalid_source_or_formal_score_is_not_shown(self):
        for text in ("参考政策[9]", "S=0.88。[1]", "承载得分为 90。[1]", "省级政策结论。"):
            with self.subTest(text=text), patch("judge_core.judge_answer", return_value={
                "status": "CONNECTED", "answer": text,
            }):
                result = answer("test", "黑龙江低空政策", [])
                self.assertEqual(result["result"]["status"], "EVIDENCE_VALIDATION_FAILED")
                self.assertNotIn("answer", result["result"])

    def test_invalid_upload(self):
        with self.assertRaises(ValueError):
            read_pdf(b"not a pdf", "invalid.pdf")


if __name__ == "__main__":
    unittest.main()
