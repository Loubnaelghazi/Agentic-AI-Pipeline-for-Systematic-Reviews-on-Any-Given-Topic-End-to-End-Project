import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from methodology.appraisal import appraisal_source, check_appraisal_quote
from storage import review_manager


class AppraisalQuotesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.paper_dir = self.root / "fixture" / "papers"
        self.paper_dir.mkdir(parents=True)
        (self.paper_dir.parent / "topic.txt").write_text("Temporary test review")
        mocked = patch.object(review_manager, "REVIEW_ROOT", self.root)
        mocked.start()
        self.addCleanup(mocked.stop)

    def test_viewed_text_and_validation_agree_for_text_only_source(self):
        (self.paper_dir / "W1.txt").write_text(
            "Methods\nWe measured   twelve samples.\n"
        )
        _, text = appraisal_source("fixture", "W1")
        self.assertIn("We measured twelve samples.", text)
        support = check_appraisal_quote("fixture", "W1", "We measured\ntwelve samples.")
        self.assertEqual(support["text"], "We measured twelve samples.")
        self.assertIsNone(support["page_start"])
        with self.assertRaisesRegex(ValueError, "continuous passage"):
            check_appraisal_quote("fixture", "W1", "The design was excellent.")

    def test_pdf_references_and_boundary_crossing_quotes_are_rejected(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((72, 72), "Methods\nWe measured twelve samples.")
            page = pdf.new_page()
            page.insert_text((72, 72), "References\nA cited study found a benefit.")
            pdf.save(self.paper_dir / "W1.pdf")
        _, text = appraisal_source("fixture", "W1")
        self.assertNotIn("A cited study", text)
        result = check_appraisal_quote("fixture", "W1", "We measured twelve samples.")
        self.assertEqual(result["page_start"], 1)
        for quote in [
            "A cited study found a benefit.",
            "We measured twelve samples. References",
        ]:
            with self.subTest(quote=quote), self.assertRaises(ValueError):
                check_appraisal_quote("fixture", "W1", quote)

    def test_source_paths_cannot_escape_paper_folder(self):
        with self.assertRaises(ValueError):
            appraisal_source("fixture", "../outside")
        outside = self.root / "outside.txt"
        outside.write_text("Private unrelated text")
        (self.paper_dir / "W1.txt").symlink_to(outside)
        with self.assertRaises(ValueError):
            appraisal_source("fixture", "W1")

    def test_empty_source_never_accepts_a_quote(self):
        with self.assertRaises(ValueError):
            check_appraisal_quote("fixture", "W1", "anything")
