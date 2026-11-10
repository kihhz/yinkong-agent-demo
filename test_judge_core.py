import io
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from judge_catalog import answer, catalog_response, conversation_summary, read_pdf, report, select_evidence
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
        with patch("judge_catalog.judge_answer", return_value={"status": "CONNECTED", "answer": "你好！"}) as model:
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
        with patch("judge_catalog.judge_answer", return_value={
            "status": "CONNECTED", "answer": "附件要求两个备用降落点。[1]"
        }) as model:
            result = answer("test", "Project Willow 有什么要求？", [], pages, "synthetic.pdf")
        evidence = model.call_args.args[2]["evidence"]
        self.assertIn("Project Willow", evidence[0]["text"])
        self.assertEqual(result["cited"][0]["locator"], "第 1 页")
        markdown = report(*conversation_summary([result]))
        self.assertIn("synthetic.pdf", markdown)
        with ZipFile(io.BytesIO(word_report(markdown))) as doc:
            self.assertIn("synthetic.pdf", doc.read("word/document.xml").decode())

    def test_pdf_isolation_and_model_error(self):
        with patch("judge_catalog.judge_answer", return_value={"status": "HTTP_ERROR", "http_code": 401}) as model:
            result = answer("test", "附件呢？", [{
                "question": "上次有附件", "regions": (), "uses_pdf": True,
                "result": {"status": "CONNECTED", "answer": "私有附件内容"},
            }])
        self.assertEqual(model.call_args.args[2]["history"], [])
        self.assertEqual(result["result"], {"status": "HTTP_ERROR", "http_code": 401})

    def test_invalid_source_or_formal_score_is_not_shown(self):
        for text in ("参考政策[9]", "S=0.88。[1]", "承载得分为 90。[1]", "省级政策结论。"):
            with self.subTest(text=text), patch("judge_catalog.judge_answer", return_value={
                "status": "CONNECTED", "answer": text,
            }):
                result = answer("test", "黑龙江低空政策", [])
                self.assertEqual(result["result"]["status"], "EVIDENCE_VALIDATION_FAILED")
                self.assertNotIn("answer", result["result"])

    def test_invalid_upload(self):
        with self.assertRaises(ValueError):
            read_pdf(b"not a pdf", "invalid.pdf")

    def test_session_summary_includes_prior_questions_and_remaps_references(self):
        replies = [
            {"status": "CONNECTED", "answer": "您好"},
            {"status": "CONNECTED", "answer": "本次查到肇东植保资料。[3]\n\n### 本题要点\n核实当地植保作业条件。[3]"},
            {"status": "CONNECTED", "answer": "福建有低空文旅案例。[2]\n\n### 本题要点\n可参考福建文旅案例。[2]"},
            {"status": "HTTP_ERROR", "http_code": 503},
        ]
        turns = []
        with patch("judge_catalog.judge_answer", side_effect=replies):
            for question in ["你好", "黑龙江植保有什么依据？", "福建文旅有什么案例？", "后续怎么落地？"]:
                turns.append(answer("test", question, turns))
        findings, pending, sources = conversation_summary(turns)
        self.assertEqual([f["note"] for f in findings],
                         ["核实当地植保作业条件。[1]", "可参考福建文旅案例。[2]"])
        self.assertEqual([s["region"] for s in sources], ["黑龙江", "福建"])
        self.assertEqual(pending, ["后续怎么落地？"])
        self.assertNotIn("本题要点", turns[1]["result"]["answer"])
        content = report(findings, pending, sources)
        for item in ["黑龙江植保", "福建文旅", "后续怎么落地", "来源与定位"]:
            self.assertIn(item, content)
        self.assertNotIn("您好", content)

    def test_catalog_lists_public_provinces_and_separates_uploads(self):
        result = catalog_response("整个数据资料库你有哪些省份的信息", has_attachment=True)
        self.assertEqual(result["result"]["status"], "CATALOG")
        self.assertEqual(
            {s["region"] for s in result["cited"]},
            {"全国", "黑龙江", "福建", "安徽", "云南", "吉林", "广东", "四川"},
        )
        self.assertIn("31 个省级地区", result["result"]["answer"])
        self.assertIn("PDF 单独列", result["result"]["answer"])
        self.assertIn("黑龙江", conversation_summary([result])[0][0]["note"])
        self.assertIsNone(catalog_response("黑龙江有哪些低空经济政策？"))
        self.assertIsNone(catalog_response("根据公开资料分析上海地区的低空政策"))

    def test_region_statistics_are_separate_from_policy_evidence(self):
        _, sources = select_evidence("上海的人口和城镇化率")
        self.assertIn("2480 万人", sources[-1]["text"])
        self.assertEqual(sources[-1]["region"], "上海")
        _, sources = select_evidence("四川有哪些低空经济政策")
        self.assertTrue(any(row["region"] == "四川" for row in sources))


if __name__ == "__main__":
    unittest.main()
