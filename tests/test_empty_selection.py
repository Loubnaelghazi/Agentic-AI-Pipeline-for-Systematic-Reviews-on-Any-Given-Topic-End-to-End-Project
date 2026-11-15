"""Empty selections stop without inference, fake manuscripts, or lost decisions."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.jobs import JobManager
from methodology.protocol import approve_protocol, draft_protocol, save_protocol
from storage import review_manager
from storage.human_review import read_json, record_decision
from storage.review_manager import write_json
from workflow.confirmations import (
    ConfirmationRequired,
    await_confirmation,
    confirm_step,
)
from workflow.graph import run_review
from workflow.selection_outcome import EmptySelection, selection_reason, stop_if_empty


class EmptySelectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        mocked = patch.object(review_manager, "REVIEW_ROOT", Path(temporary.name))
        mocked.start()
        self.addCleanup(mocked.stop)
        self.rid, self.root = review_manager.create_review(
            "Synthetic solar forecasting study"
        )
        doc = save_protocol(
            self.rid, draft_protocol(self.rid).model_dump(mode="json"), "Test fixture"
        )
        approve_protocol(self.rid, doc["fingerprint"], "Test fixture", "")
        self.state = {
            "review_id": self.rid,
            "review_path": str(self.root),
            "topic": "Synthetic solar forecasting study",
            "protocol_fingerprint": doc["fingerprint"],
            "completed": ["search_strategy", "retrieval", "screening", "save"],
        }
        self.papers = [
            {
                "id": "https://openalex.org/W1",
                "title": "Synthetic study",
                "abstract": "Synthetic abstract",
                "screening": {
                    "decision": "include",
                    "protocol_fingerprint": doc["fingerprint"],
                    "reviews": [{"decision": "include"}, {"decision": "include"}],
                },
            }
        ]
        write_json(self.root / "papers.json", self.papers)
        write_json(self.root / "workflow_state.json", self.state)

    def test_all_human_exclusions_stop_before_download_without_model_calls(self):
        record_decision(
            self.rid,
            "screening:W1",
            "exclude",
            "Test fixture",
            "Outside synthetic scope",
        )
        decisions = (self.root / "outputs/human_decisions.json").read_bytes()
        with patch(
            "workflow.graph.graph.invoke",
            side_effect=AssertionError("Must not run downstream stages"),
        ):
            result = run_review(self.rid)
        self.assertEqual(result["status"], "no_evidence")
        self.assertEqual(result["selection_outcome"]["reason"], "all_screened_out")
        self.assertEqual(
            (self.root / "outputs/human_decisions.json").read_bytes(), decisions
        )
        self.assertFalse((self.root / "outputs/literature_review.md").exists())
        self.assertTrue((self.root / "outputs/selection_report.docx").exists())
        count = len(list((self.root / "outputs/history").iterdir()))
        self.assertEqual(run_review(self.rid)["status"], "no_evidence")
        self.assertEqual(len(list((self.root / "outputs/history").iterdir())), count)

    def test_unavailable_full_text_is_distinct_from_exclusion(self):
        self.state["completed"].append("download")
        write_json(
            self.root / "outputs/full_text.json",
            [{"paper_id": "W1", "status": "unavailable"}],
        )
        self.assertEqual(selection_reason(self.state), "full_texts_unavailable")
        with self.assertRaises(EmptySelection):
            stop_if_empty(self.state)
        text = (self.root / "outputs/selection_report.md").read_text()
        self.assertIn("access gap", text)
        self.assertNotIn("## Abstract", text)

    def test_unfinished_acquisition_does_not_become_an_empty_terminal_result(self):
        self.state["completed"].append("download")
        self.assertIsNone(selection_reason(self.state))

    def test_all_full_text_exclusions_stop_before_ingestion(self):
        self.state["completed"] += ["download", "full_text_screening"]
        write_json(
            self.root / "outputs/full_text.json",
            [{"paper_id": "W1", "status": "retrieved"}],
        )
        (self.root / "papers/W1.txt").write_text(
            "This synthetic study concerns an unrelated outcome."
        )
        record_decision(
            self.rid,
            "eligibility:W1",
            "exclude",
            "Test fixture",
            "Outcome does not match the protocol",
        )
        self.assertEqual(selection_reason(self.state), "no_eligible_reports")
        with self.assertRaises(EmptySelection):
            stop_if_empty(self.state)
        self.assertNotIn("ingestion", self.state["completed"])
        self.assertFalse((self.root / "outputs/scientific_manuscript.json").exists())

    def test_uncertain_screening_waits_for_a_human_in_guided_mode(self):
        self.papers[0]["screening"]["decision"] = "uncertain"
        write_json(self.root / "papers.json", self.papers)
        self.assertIsNone(selection_reason(self.state))

    def test_automatic_uncertain_eligibility_stops_without_a_fake_final_draft(self):
        self.state["completed"] += ["download", "full_text_screening"]
        write_json(
            self.root / "outputs/full_text.json",
            [{"paper_id": "W1", "status": "retrieved"}],
        )
        (self.root / "papers/W1.txt").write_text(
            "Synthetic full text for control-flow testing."
        )
        write_json(
            self.root / "outputs/automatic_eligibility.json",
            {"W1": {"recommendation": "uncertain"}},
        )
        self.assertEqual(
            selection_reason(self.state, "automatic"), "eligibility_unresolved"
        )
        with self.assertRaises(EmptySelection):
            stop_if_empty(self.state, "automatic")
        self.assertFalse((self.root / "outputs/automatic_result.json").exists())

    def test_confirmation_stops_empty_selection_and_api_hides_old_manuscript(self):
        record_decision(
            self.rid,
            "screening:W1",
            "exclude",
            "Test fixture",
            "Outside synthetic scope",
        )
        (self.root / "outputs/literature_review.md").write_text(
            "Old empty report must not appear current"
        )
        with self.assertRaises(ConfirmationRequired):
            await_confirmation(self.state, "save")
        token = read_json(self.root / "workflow_state.json", {})[
            "awaiting_confirmation"
        ]["token"]
        result = confirm_step(self.rid, token, "Test fixture")
        self.assertEqual(result["status"], "no_evidence")
        with TestClient(create_app(JobManager())) as client:
            detail = client.get(f"/api/reviews/{self.rid}").json()
            self.assertIsNone(detail["report"])
            self.assertFalse(detail["report_current"])
            self.assertIsNone(detail["awaiting_confirmation"])
            self.assertEqual(detail["selection_outcome"]["reason"], "all_screened_out")

    def test_revised_approved_protocol_can_start_a_new_search(self):
        record_decision(
            self.rid,
            "screening:W1",
            "exclude",
            "Test fixture",
            "Outside synthetic scope",
        )
        run_review(self.rid)
        p = draft_protocol(self.rid).model_dump(mode="json")
        p["concepts"] = [["solar"], ["forecasting"]]
        doc = save_protocol(self.rid, p, "Test fixture")
        approve_protocol(self.rid, doc["fingerprint"], "Test fixture", "")
        with (
            patch(
                "workflow.nodes.retrieval",
                side_effect=RuntimeError("New search reached"),
            ),
            self.assertRaisesRegex(RuntimeError, "New search reached"),
        ):
            run_review(self.rid)
