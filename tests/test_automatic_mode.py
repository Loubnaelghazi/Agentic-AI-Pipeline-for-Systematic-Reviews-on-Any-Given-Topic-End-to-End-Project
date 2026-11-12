import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pymupdf
from fastapi.testclient import TestClient
from writer_fixtures import audited_writing

from agents.grounding import EVIDENCE_VERSION
from api.app import create_app
from api.jobs import JobManager
from methodology.protocol import draft_protocol, load_protocol
from methodology.runtime import save_configuration, settings, worker_environment
from storage import review_manager
from workflow.automatic import decide_final, result, run_review


class AutomaticModeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.review = self.root / "fixture"
        (self.review / "papers").mkdir(parents=True)
        (self.review / "outputs").mkdir()
        (self.review / "topic.txt").write_text(
            "Temporary automatic software-review fixture"
        )
        mocked = patch.object(review_manager, "REVIEW_ROOT", self.root)
        mocked.start()
        self.addCleanup(mocked.stop)
        save_configuration(
            "fixture", {"mode": "automatic", "max_records": 2, "sources": ["openalex"]}
        )

    def run_automatic(self, extraction_error=None):
        paper = {
            "id": "https://openalex.org/W1",
            "title": "Synthetic test study",
            "year": 2025,
            "abstract": "We evaluated twelve samples.",
        }
        quote = "We evaluated twelve samples."

        def download(paper, folder):
            with pymupdf.open() as doc:
                page = doc.new_page()
                page.insert_text((72, 72), "Methods\n" + quote)
                doc.save(folder / "W1.pdf")
            (folder / "W1.txt").write_text("Methods\n" + quote)
            return str(folder / "W1.txt")

        record = {
            "paper_id": "W1",
            "review_id": "fixture",
            "evidence_version": EVIDENCE_VERSION,
            "claims": [{"kind": "main_findings", "passage_id": "P1", "quote": quote}],
            "supporting_passages": [
                {
                    "source": "W1.txt",
                    "passage_id": "P1",
                    "text": quote,
                    "page_start": 1,
                    "page_end": 1,
                }
            ],
        }
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "workflow.automatic.write_manuscript",
                    side_effect=audited_writing,
                )
            )
            stack.enter_context(
                patch(
                    "agents.planner_agent.propose_protocol",
                    return_value=draft_protocol("fixture"),
                )
            )
            stack.enter_context(
                patch(
                    "tools.search.retrieve",
                    return_value={
                        "papers": [paper],
                        "raw_records": [paper],
                        "duplicates": [],
                        "search_log": [
                            {"source": "openalex", "query": "test", "error": None}
                        ],
                    },
                )
            )
            stack.enter_context(
                patch(
                    "agents.screening_agent.dual_screen",
                    side_effect=lambda protocol, paper, fp: {
                        **paper,
                        "screening": {
                            "decision": "include",
                            "protocol_fingerprint": fp,
                            "reason": "Synthetic test proposal",
                        },
                    },
                )
            )
            stack.enter_context(
                patch("tools.pdf_downloader.download_paper", side_effect=download)
            )
            stack.enter_context(
                patch(
                    "agents.screening_agent.full_text_proposal",
                    return_value={
                        "recommendation": "include",
                        "reason": "Synthetic test eligibility proposal",
                    },
                )
            )
            stack.enter_context(patch("rag.ingest.ingest_papers"))
            stack.enter_context(
                patch(
                    "agents.extraction_agent.extract_evidence",
                    return_value=record,
                    side_effect=extraction_error,
                )
            )
            stack.enter_context(
                patch(
                    "agents.appraisal_agent.propose_appraisal",
                    return_value={"notes": ["Check the sample selection method."]},
                )
            )
            return run_review("fixture")

    def test_full_automatic_run_stops_only_for_final_decision_without_faking_human_approvals(
        self,
    ):
        state = self.run_automatic()
        self.assertEqual(state["status"], "awaiting_final_review")
        self.assertEqual(len(state["completed"]), 11)
        self.assertIsNone(load_protocol("fixture")["approval"])
        for filename in (
            "human_decisions.json",
            "appraisals.json",
            "protocol_approvals.json",
            "step_confirmations.json",
        ):
            self.assertFalse((self.review / "outputs" / filename).exists())
        draft = (self.review / "outputs/automatic_review.md").read_text()
        self.assertIn("AI-assisted manuscript", draft)
        self.assertNotIn("## Appendix A", draft)
        self.assertIn(
            "Technical limitations",
            (self.review / "outputs/technical_report.md").read_text(),
        )
        self.assertIn("We evaluated twelve samples.", draft)
        value = result("fixture")
        self.assertTrue(value["current"])
        self.assertIsNone(value["decision"])
        self.assertEqual(run_review("fixture")["status"], "awaiting_final_review")
        event = decide_final("fixture", value["fingerprint"], "accept", "Test reviewer")
        self.assertEqual(event["decision"], "accept")
        self.assertEqual(result("fixture")["decision"]["reviewer"], "Test reviewer")
        self.assertIn("does not certify", event["scope"])
        with self.assertRaises(ValueError):
            decide_final("fixture", value["fingerprint"], "reject", "Test reviewer")
        self.assertFalse((self.review / "outputs/human_decisions.json").exists())

    def test_rejection_endpoint_and_stale_result_protection(self):
        self.run_automatic()
        value = result("fixture")
        with TestClient(create_app(JobManager())) as client:
            detail = client.get("/api/reviews/fixture").json()
            self.assertIn("AI-assisted manuscript", detail["report"])
            self.assertEqual(detail["runtime_settings"]["mode"], "automatic")
            self.assertEqual(
                client.post(
                    "/api/reviews/fixture/final-decision",
                    json={
                        "fingerprint": "stale",
                        "decision": "accept",
                        "reviewer": "Test reviewer",
                    },
                ).status_code,
                409,
            )
            response = client.post(
                "/api/reviews/fixture/final-decision",
                json={
                    "fingerprint": value["fingerprint"],
                    "decision": "reject",
                    "reviewer": "Test reviewer",
                    "note": "Needs further source checks",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                client.get("/api/reviews/fixture").json()["automatic_result"][
                    "decision"
                ]["decision"],
                "reject",
            )
        with (self.review / "outputs/automatic_review.md").open("a") as file:
            file.write("\nChanged after final review.")
        self.assertFalse(result("fixture")["current"])
        with self.assertRaises(ValueError):
            decide_final("fixture", value["fingerprint"], "accept", "Test reviewer")

    def test_before_prompt_configuration_is_saved_and_carried_to_worker(self):
        models = {
            "models": [{"name": "test-local:1"}],
            "error": None,
            "default_model": "test-local:1",
        }
        controls = {
            "model": "test-local:1",
            "available": True,
            "options": [{"value": "off"}, {"value": "on"}],
        }
        with (
            patch("methodology.runtime.installed_models", return_value=models),
            patch("methodology.runtime.model_controls", return_value=controls),
            TestClient(create_app(JobManager())) as client,
        ):
            response = client.post(
                "/api/reviews",
                json={
                    "topic": "New configured fixture",
                    "configuration": {
                        "model": "test-local:1",
                        "mode": "automatic",
                        "thinking": "off",
                        "temperature": 0.2,
                        "max_records": 3,
                        "sources": ["pubmed"],
                    },
                },
            )
            self.assertEqual(response.status_code, 201)
            rid = response.json()["id"]
            value = settings(rid)
            self.assertEqual(value["model"], "test-local:1")
            self.assertEqual(value["mode"], "automatic")
            environment = worker_environment(rid)
            self.assertEqual(environment["OLLAMA_MODEL"], "test-local:1")
            self.assertEqual(environment["OLLAMA_REASONING"], "false")
            self.assertEqual(environment["OLLAMA_TEMPERATURE"], "0.2")
            client.post(f"/api/reviews/{rid}/protocol/draft")
            protocol = load_protocol(rid)["protocol"]
            self.assertEqual(protocol["sources"], ["pubmed"])
            self.assertEqual(protocol["max_records_per_query"], 3)
            self.assertEqual(
                client.post(
                    "/api/reviews",
                    json={"topic": "Bad sources", "configuration": {"sources": []}},
                ).status_code,
                422,
            )

    def test_browser_can_update_settings_across_frontend_and_backend_ports(self):
        with TestClient(create_app(JobManager())) as client:
            response = client.options(
                "/api/reviews/fixture/settings",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "PUT",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("PUT", response.headers["access-control-allow-methods"])
