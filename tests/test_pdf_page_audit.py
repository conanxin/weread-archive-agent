"""Synthetic-only regression for PDF text/image/vector/blank classification."""
import unittest
from tools.pdf_page_audit import audit_pages, page_kind, PASS, REVIEW


class FakePage:
    def __init__(self, *, text="", images=0, drawings=0):
        self.text = text
        self.images = images
        self.drawings = drawings

    def get_text(self, mode):
        assert mode == "text"
        return self.text

    def get_images(self, full=False):
        assert full is True
        return [("fake-xref",)] * self.images

    def get_drawings(self):
        return [{"type": "l"}] * self.drawings


class PDFPageAuditTests(unittest.TestCase):
    def test_distinguishes_text_image_vector_and_true_blank(self):
        pages = [
            FakePage(text="一段正文"),
            FakePage(text="图片图注", images=1),
            FakePage(images=1),
            FakePage(drawings=4),
            FakePage(),
        ]
        report = audit_pages(pages)
        self.assertEqual(report["status"], REVIEW)
        self.assertEqual(report["page_class_counts"],
                         {"IMAGE_ONLY": 1, "TEXT": 1, "TEXT_WITH_IMAGES": 1,
                          "TRUE_BLANK": 1, "VECTOR_ONLY": 1})
        self.assertEqual(report["true_blank_pages"], [5])
        self.assertEqual(report["vector_only_pending_visual_review"], [4])
        self.assertFalse(report["full_book_confirmed"])

    def test_reviewed_visual_separators_from_synthetic_seventh_case(self):
        pages = [FakePage(text="普通页面") for _ in range(198)]
        pages[20] = FakePage(images=1)
        pages[21] = FakePage(drawings=4)
        pages[22] = FakePage(text="下一章")
        pages[148] = FakePage(images=1)
        pages[149] = FakePage(drawings=4)
        pages[150] = FakePage(text="又一章")
        unreviewed = audit_pages(pages)
        self.assertEqual(unreviewed["status"], REVIEW)
        self.assertEqual(unreviewed["vector_only_pending_visual_review"], [22, 150])
        approved = audit_pages(pages, reviewed_separator_pages=[22, 150])
        self.assertEqual(approved["status"], PASS)
        self.assertEqual(approved["explicitly_reviewed_separator_pages"], [22, 150])
        self.assertEqual(approved["true_blank_pages"], [])
        self.assertEqual(approved["vector_only_pending_visual_review"], [])
        self.assertEqual(approved["source_reader_visual_fidelity"], "UNVERIFIED")
        self.assertFalse(approved["full_book_confirmed"])

    def test_true_blank_blocks_pass_even_with_reviewed_vectors(self):
        report = audit_pages([FakePage(), FakePage(drawings=1)],
                             reviewed_separator_pages=[2])
        self.assertEqual(report["status"], REVIEW)
        self.assertEqual(report["true_blank_pages"], [1])

    def test_vector_without_explicit_review_is_not_auto_approved(self):
        report = audit_pages([FakePage(drawings=1)])
        self.assertEqual(report["status"], REVIEW)
        self.assertEqual(report["vector_only_pages"], [1])
        self.assertEqual(report["explicitly_reviewed_separator_pages"], [])

    def test_non_vector_claim_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "REVIEWED_SEPARATOR_NOT_VECTOR_ONLY"):
            audit_pages([FakePage(text="不可冒称分隔页")],
                        reviewed_separator_pages=[1])
        with self.assertRaisesRegex(ValueError, "REVIEWED_SEPARATOR_NOT_VECTOR_ONLY"):
            audit_pages([FakePage()],
                        reviewed_separator_pages=[1])

    def test_invalid_approved_pages_and_empty_pdf(self):
        for values in ([0], [-1], [1, 1], [True], [1.5]):
            with self.subTest(values=values), self.assertRaisesRegex(
                    ValueError, "INVALID_REVIEWED_SEPARATOR_PAGES"):
                audit_pages([FakePage(drawings=1)], reviewed_separator_pages=values)
        with self.assertRaisesRegex(ValueError, "EMPTY_PDF"):
            audit_pages([])

    def test_missing_pymupdf_not_required_for_synthetic_tests(self):
        self.assertEqual(page_kind(FakePage(text="文字")), "TEXT")

    def test_any_unrecognized_page_operation_failure_does_not_claim_pass(self):
        class BrokenPage:
            def get_text(self, mode):
                return ""
            def get_images(self, full=False):
                return []
            def get_drawings(self):
                raise RuntimeError("PDF_LAYER_PARSE_ERROR")
        with self.assertRaisesRegex(RuntimeError, "PDF_LAYER_PARSE_ERROR"):
            audit_pages([BrokenPage()])


if __name__ == "__main__":
    unittest.main()
