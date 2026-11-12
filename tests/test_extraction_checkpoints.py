"""Network failures must not discard completed within-paper extraction work."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf

from agents.extraction_agent import extract_evidence
from agents.grounding import SelectedEvidence
from storage import review_manager


class ExtractionCheckpointTests(unittest.TestCase):
    def test_retry_keeps_queries_and_invalidates_when_source_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "fixture/papers"
            folder.mkdir(parents=True)
            with pymupdf.open() as doc:
                page = doc.new_page()
                page.insert_text((72, 72), "We evaluated twelve samples in this study.")
                doc.save(folder / "W1.pdf")
            selector = MagicMock()
            selector.invoke.return_value = SelectedEvidence(selections=[])
            with (
                patch.object(review_manager, "REVIEW_ROOT", root),
                patch("agents.extraction_agent.get_vector_store"),
                patch("agents.extraction_agent.load_protocol", return_value=None),
                patch(
                    "agents.extraction_agent.model_config",
                    return_value={"model": "fixture"},
                ),
                patch("agents.extraction_agent.structured_llm", selector),
                patch("agents.extraction_agent.extract_tables", return_value=([], [])),
                patch("agents.extraction_agent.progress"),
            ):
                with (
                    patch(
                        "agents.extraction_agent.hybrid_search",
                        side_effect=[[], ConnectionError("offline")],
                    ),
                    self.assertRaises(ConnectionError),
                ):
                    extract_evidence("fixture", "W1")
                checkpoint = root / "fixture/outputs/extraction_progress/W1.json"
                self.assertEqual(
                    json.loads(checkpoint.read_text())["completed_queries"], [0]
                )
                with patch(
                    "agents.extraction_agent.hybrid_search", return_value=[]
                ) as search:
                    selector.invoke.side_effect = ConnectionError(
                        "offline during selection"
                    )
                    with self.assertRaises(ConnectionError):
                        extract_evidence("fixture", "W1")
                    self.assertEqual(search.call_count, 3)
                selector.invoke.side_effect = None
                with patch(
                    "agents.extraction_agent.hybrid_search", return_value=[]
                ) as search:
                    extract_evidence("fixture", "W1")
                    search.assert_not_called()
                    extract_evidence("fixture", "W1")
                    self.assertEqual(selector.invoke.call_count, 2)
                    (folder / "W1.txt").write_text(
                        "Source revision changes the identity."
                    )
                    extract_evidence("fixture", "W1")
                    self.assertEqual(search.call_count, 4)
                    self.assertEqual(selector.invoke.call_count, 3)
