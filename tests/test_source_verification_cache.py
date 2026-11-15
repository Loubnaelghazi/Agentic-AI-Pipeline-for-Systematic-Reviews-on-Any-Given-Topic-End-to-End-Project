"""Source checks are reusable only while both evidence and file bytes are unchanged."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from agents.grounding import EVIDENCE_VERSION
from rag.provenance import PaperSource
from storage import review_manager
from storage.human_review import validate_record_source


class SourceVerificationCacheTests(unittest.TestCase):
    def test_reuses_checks_and_invalidates_when_pdf_bytes_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "fixture/papers"
            folder.mkdir(parents=True)
            quote = "We evaluated twelve samples in this study."
            path = folder / "W1.pdf"

            def save(text):
                with pymupdf.open() as doc:
                    page = doc.new_page()
                    page.insert_text((72, 72), text)
                    doc.save(path)

            save(quote)
            passage = {**PaperSource(path).passage(quote), "passage_id": "P1"}
            record = {
                "paper_id": "W1",
                "review_id": "fixture",
                "evidence_version": EVIDENCE_VERSION,
                "claims": [{"kind": "methodology", "quote": quote, "passage_id": "P1"}],
                "supporting_passages": [passage],
            }
            with (
                patch.object(review_manager, "REVIEW_ROOT", root),
                patch("storage.human_review.PaperSource", wraps=PaperSource) as source,
            ):
                validate_record_source("fixture", record)
                validate_record_source("fixture", record)
                self.assertEqual(source.call_count, 1)
                save("The source file now contains different information.")
                with self.assertRaisesRegex(ValueError, "no longer matches"):
                    validate_record_source("fixture", record)
                self.assertEqual(source.call_count, 2)
