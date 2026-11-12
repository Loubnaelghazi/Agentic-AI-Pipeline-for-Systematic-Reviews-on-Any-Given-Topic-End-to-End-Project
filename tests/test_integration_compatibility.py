"""Keep local retrieval guarantees when importing the conversation frontend."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_ollama import OllamaEmbeddings

from agents.full_text_agent import WindowAssessment, assess_full_text
from agents.narrative_agent import build_facts, validate_themes
from agents.runtime import inspect_runtime
from methodology.protocol import draft_protocol
from rag.vector_store import RetrievalEmbeddings, index_identity
from storage import review_manager


class IntegrationCompatibilityTests(unittest.TestCase):
    def test_queries_never_receive_document_prefixes(self):
        with patch.object(
            OllamaEmbeddings, "embed_documents", return_value=[[0.1]]
        ) as parent:
            RetrievalEmbeddings(model="nomic-embed-text").embed_query("methods")
            self.assertEqual(parent.call_args.args[0], ["search_query: methods"])
            RetrievalEmbeddings(model="qwen3-embedding:0.6b").embed_query("methods")
            self.assertIn("Instruct:", parent.call_args.args[0][0])

    def test_embedding_spaces_and_revisions_remain_separate(self):
        self.assertNotEqual(index_identity("nomic"), index_identity("qwen"))
        self.assertNotEqual(
            index_identity("qwen", "old"), index_identity("qwen", "new")
        )

    def test_machine_evidence_is_never_labelled_human_confirmed(self):
        facts = build_facts(
            [
                {
                    "paper_id": "W1",
                    "claims": [
                        {"quote": "Synthetic source text.", "kind": "methodology"}
                    ],
                }
            ],
            {},
        )
        self.assertEqual(facts["W1:Q1"]["origin"], "source_checked_ai_proposal")

    def test_comparative_narrative_rejects_invented_numbers(self):
        facts = {"W1:Q1": {"paper_id": "W1", "text": "We evaluated 20 samples."}}
        with self.assertRaises(ValueError):
            validate_themes(
                [
                    {
                        "title": "Results",
                        "analysis": "We evaluated 99 samples.",
                        "limitations": "No external validation.",
                        "evidence_ids": ["W1:Q1"],
                    }
                ],
                facts,
            )

    def test_full_text_resumes_saved_windows_without_model_calls(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(review_manager, "REVIEW_ROOT", Path(tmp)),
        ):
            rid, root = review_manager.create_review("Synthetic software verification")
            (root / "papers/W1.txt").write_text(
                "Readable original source sentence. " * 330
            )
            client = MagicMock()
            client.with_structured_output.return_value.invoke.return_value = (
                WindowAssessment(findings=[])
            )
            with (
                patch("agents.full_text_agent.chat_model", return_value=client),
                patch(
                    "agents.full_text_agent.adjudicate_criterion",
                    return_value={
                        "status": "unknown",
                        "quote": "",
                        "reason": "Synthetic missing evidence",
                    },
                ),
            ):
                result = assess_full_text(draft_protocol(rid), "W1", root / "papers")
                calls = client.with_structured_output.return_value.invoke.call_count
                self.assertGreater(calls, 1)
                self.assertEqual(result["coverage_details"]["assessed_windows"], calls)
                assess_full_text(draft_protocol(rid), "W1", root / "papers")
                self.assertEqual(
                    client.with_structured_output.return_value.invoke.call_count, calls
                )

    def test_diagnostics_resolve_the_configured_models(self):
        from config import model_config

        cfg = model_config()
        response = MagicMock()
        response.json.return_value = {
            "models": [{"name": cfg[k], "digest": k} for k in ("llm", "embedding")]
        }
        with patch("agents.runtime.requests.get", return_value=response):
            self.assertTrue(inspect_runtime()["ready"])
