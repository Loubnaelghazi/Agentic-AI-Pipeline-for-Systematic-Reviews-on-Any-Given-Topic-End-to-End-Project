"""Transient Ollama faults must not become accepted empty scientific drafts."""

import unittest
from unittest.mock import Mock, patch

import httpx
import test_automatic_mode as fixtures
from langchain_core.documents import Document

from agents.extraction_agent import select_source_statements
from agents.grounding import SelectedEvidence, SentenceSelection
from agents.semantic_validation import SCIENTIFIC_VERSION
from agents.transport import retry_ollama
from rag.retrieval import hybrid_search
from storage.human_review import read_json
from storage.review_manager import write_json
from workflow.automatic import (
    completed_without_quotes,
    decide_final,
    extraction_failures,
    result,
    result_fingerprint,
)


class ExtractionRecoveryTests(unittest.TestCase):
    def test_audited_empty_extraction_is_a_gap_but_transport_failure_is_not(self):
        case = self.prepare()
        write_json(case.review / "workflow_state.json", {"eligible_paper_ids": ["W1"]})
        record = {
            "paper_id": "W1",
            "claims": [],
            "extraction_complete": True,
            "scientific_version": SCIENTIFIC_VERSION,
            "grounding_status": "no_verified_quotes",
            "supporting_passages": [{"text": "Source text was assessed."}],
        }
        write_json(case.review / "outputs/evidence.json", [record])
        self.assertEqual(extraction_failures("fixture"), [])
        self.assertTrue(completed_without_quotes(record))
        for change in (
            {"error": "Provider timeout"},
            {"extraction_complete": False},
            {"supporting_passages": []},
        ):
            changed = {**record, **change}
            write_json(case.review / "outputs/evidence.json", [changed])
            self.assertEqual(extraction_failures("fixture"), ["W1"])

    def test_cached_invented_sentence_id_is_repaired_without_retrieval(self):
        valid = SelectedEvidence(
            selections=[SentenceSelection(kind="methodology", statement_id="P1-S1")]
        )
        model = Mock()
        model.invoke.return_value = valid
        with patch("agents.extraction_agent.structured_llm", model):
            selections = select_source_statements(
                "Source",
                {"P1-S1"},
                [{"kind": "methodology", "statement_id": "INVENTED", "field": None}],
            )
        self.assertEqual(selections, valid.model_dump()["selections"])
        self.assertEqual(model.invoke.call_count, 1)

    def test_repeated_invented_ids_remain_an_error(self):
        invalid = SelectedEvidence(
            selections=[SentenceSelection(kind="methodology", statement_id="INVENTED")]
        )
        model = Mock()
        model.invoke.return_value = invalid
        with (
            patch("agents.extraction_agent.structured_llm", model),
            self.assertRaisesRegex(ValueError, "unknown sentence IDs"),
        ):
            select_source_statements("Source", {"P1-S1"})
        self.assertEqual(model.invoke.call_count, 2)

    def test_transient_calls_retry_but_validation_errors_do_not(self):
        operation = Mock(side_effect=[httpx.ConnectError("offline"), "ok"])
        with patch("agents.transport.time.sleep"):
            self.assertEqual(retry_ollama(operation, attempts=2), "ok")
        self.assertEqual(operation.call_count, 2)
        invalid = Mock(side_effect=ValueError("invalid source selection"))
        with self.assertRaises(ValueError):
            retry_ollama(invalid, attempts=2)
        self.assertEqual(invalid.call_count, 1)

    def test_retry_budget_is_bounded(self):
        operation = Mock(side_effect=TimeoutError("slow provider"))
        with patch("agents.transport.time.sleep"), self.assertRaises(TimeoutError):
            retry_ollama(operation, attempts=2)
        self.assertEqual(operation.call_count, 2)

    def test_optional_rerank_failure_preserves_hybrid_results_and_records_fallback(
        self,
    ):
        docs = [
            Document(
                page_content="Study methods and results.", metadata={"source": "W1.txt"}
            ),
            Document(
                page_content="Reported limitations.", metadata={"source": "W1.txt"}
            ),
        ]
        store = Mock()
        store.similarity_search.return_value = docs
        store.get.return_value = {
            "documents": [d.page_content for d in docs],
            "metadatas": [d.metadata for d in docs],
        }
        trace = []
        with patch("rag.rerank.rerank", side_effect=TimeoutError("slow reranker")):
            returned = hybrid_search(
                store, "study methods", "W1.txt", trace=trace, use_reranker=True
            )
        self.assertEqual(len(returned), 2)
        self.assertFalse(trace[0]["reranked"])
        self.assertTrue(trace[0]["rerank_requested"])
        self.assertIn("TimeoutError", trace[0]["rerank_error"])

    def prepare(self):
        case = fixtures.AutomaticModeTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_failed_extraction_is_not_completed_and_resume_reuses_search(self):
        case = self.prepare()
        with self.assertRaisesRegex(RuntimeError, "Extraction incomplete"):
            case.run_automatic(
                extraction_error=TimeoutError("synthetic provider fault")
            )
        state = read_json(case.review / "workflow_state.json", {})
        self.assertNotIn("extraction", state["completed"])
        self.assertIn("ingestion", state["completed"])
        self.assertEqual(state["status"], "failed")
        self.assertIsNone(result("fixture"))
        case.run_automatic()
        value = result("fixture")
        self.assertTrue(value["ready"])
        self.assertEqual(value["failed_paper_ids"], [])
        trace = read_json(case.review / "outputs/execution_trace.json", [])
        self.assertEqual(sum(t["stage"] == "retrieval" for t in trace), 1)
        self.assertEqual(sum(t["stage"] == "extraction" for t in trace), 2)

    def test_legacy_empty_result_cannot_be_accepted_and_can_be_repaired(self):
        case = self.prepare()
        case.run_automatic()
        path = case.review / "outputs/evidence.json"
        write_json(path, [{"paper_id": "W1", "error": "timed out"}])
        metadata_path = case.review / "outputs/automatic_result.json"
        metadata = read_json(metadata_path, {})
        metadata["fingerprint"] = result_fingerprint("fixture")
        write_json(metadata_path, metadata)
        value = result("fixture")
        self.assertTrue(value["current"])
        self.assertFalse(value["ready"])
        self.assertEqual(value["failed_paper_ids"], ["W1"])
        with self.assertRaisesRegex(
            ValueError, "Extraction or scientific writing is incomplete"
        ):
            decide_final(
                "fixture", value["fingerprint"], "accept", "Synthetic reviewer"
            )
        case.run_automatic()
        self.assertTrue(result("fixture")["ready"])
        trace = read_json(case.review / "outputs/execution_trace.json", [])
        self.assertEqual(sum(t["stage"] == "retrieval" for t in trace), 1)

    def test_pause_during_extraction_is_preserved_as_a_pause_not_a_failed_record(self):
        from workflow.progress import WorkflowPaused

        case = self.prepare()
        state = case.run_automatic(extraction_error=WorkflowPaused("Requested pause"))
        self.assertEqual(state["status"], "paused")
        self.assertNotIn("extraction", state["completed"])
        self.assertFalse((case.review / "outputs/evidence.json").exists())
        case.run_automatic()
        self.assertTrue(result("fixture")["ready"])
