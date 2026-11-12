"""Confirmation gates and model controls, with no real scientific decisions."""

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from agents.writing_agent import WRITER_VERSION
from methodology import runtime
from methodology.protocol import approve_protocol, draft_protocol, save_protocol
from storage import review_manager
from storage.human_review import read_json
from storage.review_manager import write_json
from workflow.confirmations import confirm_step
from workflow.graph import run_review


class GuidedWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.review = self.root / "fixture"
        (self.review / "outputs").mkdir(parents=True)
        (self.review / "papers").mkdir()
        (self.review / "topic.txt").write_text("Temporary protocol for testing")
        mocked = patch.object(review_manager, "REVIEW_ROOT", self.root)
        mocked.start()
        self.addCleanup(mocked.stop)
        document = save_protocol(
            "fixture", draft_protocol("fixture").model_dump(mode="json"), "Test fixture"
        )
        approve_protocol("fixture", document["fingerprint"], "Test fixture", "")

    def test_each_phase_stops_until_confirmed_and_report_does_not_loop(self):
        calls = []
        updates = {
            "search_strategy": {},
            "retrieval": {"papers": []},
            "screening": {"papers": []},
            "download": {"full_text": []},
            "full_text_screening": {},
            "ingestion": {},
            "extraction": {"evidence": []},
            "appraisal": {},
            "synthesis": {
                "report": "Test draft",
                "scientific_writer_version": WRITER_VERSION,
            },
            "quality": {
                "quality_review": {"passed": True, "issues": [], "recommendations": []}
            },
        }

        def fake(name):
            def stage(state):
                calls.append(name)
                if name == "synthesis":
                    (self.review / "outputs/literature_review.md").write_text(
                        "Synthetic test draft"
                    )
                return updates[name]

            return stage

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "workflow.confirmations.writing_status",
                    return_value={"ready": True},
                )
            )
            stack.enter_context(
                patch("workflow.graph.writing_status", return_value={"ready": True})
            )
            for name in updates:
                stack.enter_context(
                    patch("workflow.nodes." + name, side_effect=fake(name))
                )
            for expected in [
                "retrieval",
                "save",
                "full_text_screening",
                "extraction",
                "appraisal",
                "quality",
            ]:
                state = run_review("fixture")
                self.assertEqual(state["status"], "awaiting_step_confirmation")
                self.assertEqual(state["awaiting_confirmation"]["stage"], expected)
                before = list(calls)
                same = run_review("fixture")
                self.assertEqual(
                    same["awaiting_confirmation"]["token"],
                    state["awaiting_confirmation"]["token"],
                )
                self.assertEqual(calls, before)
                token = state["awaiting_confirmation"]["token"]
                with self.assertRaises(ValueError):
                    confirm_step("fixture", "stale-token", "Test reviewer")
                if expected == "quality":
                    with (
                        patch(
                            "workflow.confirmations.writing_status",
                            return_value={"ready": False},
                        ),
                        self.assertRaisesRegex(
                            ValueError, "Scientific writing is incomplete"
                        ),
                    ):
                        confirm_step("fixture", token, "Test reviewer")
                confirm_step("fixture", token, "Test reviewer")
                with self.assertRaises(ValueError):
                    confirm_step("fixture", token, "Test reviewer")
            result = run_review("fixture")
        self.assertEqual(result["status"], "completed_preliminary")
        self.assertEqual(calls.count("quality"), 1)
        self.assertEqual(calls.count("synthesis"), 1)
        self.assertEqual(
            len(read_json(self.review / "outputs/step_confirmations.json", [])), 6
        )

    def test_incomplete_writing_can_resume_from_the_report_confirmation(self):
        from agents.grounding import EVIDENCE_VERSION
        from workflow.graph import STAGES

        document = read_json(self.review / "protocol.json", {})
        write_json(self.review / "papers.json", [])
        write_json(
            self.review / "workflow_state.json",
            {
                "review_id": "fixture",
                "topic": "Synthetic question",
                "completed": STAGES,
                "protocol_fingerprint": document["fingerprint"],
                "model_config": {"extraction_version": EVIDENCE_VERSION},
                "scientific_writer_version": WRITER_VERSION,
                "status": "awaiting_step_confirmation",
                "awaiting_confirmation": {
                    "stage": "quality",
                    "token": "old-report-token",
                },
            },
        )
        with (
            patch("workflow.graph.writing_status", return_value={"ready": False}),
            patch(
                "workflow.nodes.synthesis",
                side_effect=RuntimeError("Reached scientific writing retry"),
            ),
            self.assertRaisesRegex(RuntimeError, "Reached scientific writing retry"),
        ):
            run_review("fixture")
        state = read_json(self.review / "workflow_state.json", {})
        self.assertIsNone(state.get("awaiting_confirmation"))

    def test_phase_confirmation_cannot_bypass_pending_screening(self):
        from workflow.confirmations import ConfirmationRequired, await_confirmation

        document = read_json(self.review / "protocol.json", {})
        write_json(
            self.review / "papers.json",
            [
                {
                    "id": "https://openalex.org/W1",
                    "title": "Uncertain test paper",
                    "screening": {"decision": "uncertain"},
                }
            ],
        )
        with self.assertRaises(ConfirmationRequired):
            await_confirmation(
                {
                    "review_id": "fixture",
                    "protocol_fingerprint": document["fingerprint"],
                    "completed": ["save"],
                },
                "save",
            )
        state = read_json(self.review / "workflow_state.json", {})
        with self.assertRaisesRegex(ValueError, "pending decisions"):
            confirm_step(
                "fixture", state["awaiting_confirmation"]["token"], "Test reviewer"
            )


class ThinkingControlsTests(unittest.TestCase):
    def setUp(self):
        runtime._cache.clear()
        self.addCleanup(runtime._cache.clear)

    def response(self, data):
        response = Mock()
        response.json.return_value = data
        return patch("methodology.runtime.requests.post", return_value=response)

    def test_boolean_switch_and_named_level_models(self):
        for metadata, expected in [
            ({"thinking": {"values": [False, True]}}, ["default", "off", "on"]),
            ({"thinking": {"values": ["low", "high"]}}, ["default", "low", "high"]),
            (
                {"capabilities": ["thinking"], "details": {"family": "qwen3"}},
                ["default", "off", "on"],
            ),
            ({"thinking": {"values": [False]}}, ["default", "off"]),
        ]:
            with self.subTest(metadata=metadata), self.response(metadata):
                runtime._cache.clear()
                result = runtime.model_controls()
                self.assertEqual([o["value"] for o in result["options"]], expected)

    def test_controls_unavailable_does_not_guess_support(self):
        import requests

        with patch(
            "methodology.runtime.requests.post", side_effect=requests.ConnectionError
        ):
            result = runtime.model_controls()
            self.assertFalse(result["available"])
            self.assertIsNotNone(result["error"])

    def test_saved_setting_is_carried_to_worker_and_unknown_modes_rejected(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(review_manager, "REVIEW_ROOT", Path(tmp)),
            self.response({"thinking": {"values": [False, True]}}),
        ):
            (Path(tmp) / "fixture").mkdir()
            (Path(tmp) / "fixture/topic.txt").write_text("Test")
            runtime.save_thinking("fixture", "on")
            self.assertEqual(
                runtime.worker_environment("fixture")["OLLAMA_REASONING"], "true"
            )
            runtime.save_thinking("fixture", "off")
            self.assertEqual(
                runtime.worker_environment("fixture")["OLLAMA_REASONING"], "false"
            )
            with self.assertRaises(ValueError):
                runtime.save_thinking("fixture", "unsupported")


class ConversationApiTests(unittest.TestCase):
    setUp = GuidedWorkflowTests.setUp

    def test_settings_and_confirmation_endpoints_enforce_worker_boundaries(self):
        from fastapi.testclient import TestClient

        from api.app import create_app
        from api.jobs import JobManager
        from workflow.confirmations import ConfirmationRequired, await_confirmation

        manager = JobManager()
        with TestClient(create_app(manager)) as client:
            with patch(
                "methodology.runtime.model_controls",
                return_value={
                    "options": [{"value": "default"}, {"value": "on"}, {"value": "off"}]
                },
            ):
                response = client.put(
                    "/api/reviews/fixture/settings", json={"thinking": "off"}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    runtime.worker_environment("fixture")["OLLAMA_REASONING"], "false"
                )
                self.assertEqual(
                    client.put(
                        "/api/reviews/fixture/settings", json={"thinking": "invalid"}
                    ).status_code,
                    409,
                )
            manager.active["fixture"] = {"status": "running"}
            self.assertEqual(
                client.put(
                    "/api/reviews/fixture/settings", json={"thinking": "default"}
                ).status_code,
                409,
            )
            manager.active.clear()
            document = read_json(self.review / "protocol.json", {})
            with self.assertRaises(ConfirmationRequired):
                await_confirmation(
                    {
                        "review_id": "fixture",
                        "completed": ["retrieval"],
                        "protocol_fingerprint": document["fingerprint"],
                    },
                    "retrieval",
                )
            detail = client.get("/api/reviews/fixture").json()
            token = detail["awaiting_confirmation"]["token"]
            self.assertEqual(client.post("/api/reviews/fixture/run").status_code, 409)
            confirmed = client.post(
                "/api/reviews/fixture/confirm-step",
                json={"token": token, "reviewer": "Test reviewer"},
            )
            self.assertEqual(confirmed.status_code, 200)
            self.assertEqual(
                client.post(
                    "/api/reviews/fixture/confirm-step",
                    json={"token": token, "reviewer": "Test reviewer"},
                ).status_code,
                409,
            )
            self.assertIsNone(
                client.get("/api/reviews/fixture").json()["awaiting_confirmation"]
            )

    def test_planner_receives_review_specific_thinking_setting(self):
        from fastapi.testclient import TestClient

        from api.app import create_app
        from api.jobs import JobManager

        with (
            TestClient(create_app(JobManager())) as client,
            patch("api.app.reasoning_value", return_value=True),
            patch(
                "agents.planner_agent.propose_protocol",
                return_value=draft_protocol("fixture"),
            ) as planner,
        ):
            response = client.post("/api/reviews/fixture/protocol/suggest")
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()["approval"])
            self.assertTrue(planner.call_args.kwargs["reasoning"])


class ChatApiTests(unittest.TestCase):
    setUp = GuidedWorkflowTests.setUp

    def test_chat_is_persistent_idempotent_and_cannot_approve_a_phase(self):
        from fastapi.testclient import TestClient

        from api.app import create_app
        from api.jobs import JobManager
        from workflow.confirmations import ConfirmationRequired, await_confirmation

        doc = read_json(self.review / "protocol.json", {})
        with self.assertRaises(ConfirmationRequired):
            await_confirmation(
                {
                    "review_id": "fixture",
                    "protocol_fingerprint": doc["fingerprint"],
                    "completed": ["retrieval"],
                },
                "retrieval",
            )
        token = read_json(self.review / "workflow_state.json", {})[
            "awaiting_confirmation"
        ]["token"]
        with (
            TestClient(create_app(JobManager())) as client,
            patch(
                "agents.chat_agent.reply",
                return_value="Use the validation button to continue.",
            ) as reply,
        ):
            body = {
                "text": "Approve this phase for me",
                "request_id": "test-message-001",
            }
            result = client.post("/api/reviews/fixture/messages", json=body)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["role"], "assistant")
            self.assertEqual(
                client.post("/api/reviews/fixture/messages", json=body).status_code, 200
            )
            reply.assert_called_once()
            detail = client.get("/api/reviews/fixture").json()
            self.assertEqual(len(detail["chat_messages"]), 2)
            self.assertEqual(detail["awaiting_confirmation"]["token"], token)
            self.assertFalse((self.review / "outputs/step_confirmations.json").exists())
            self.assertEqual(
                client.post(
                    "/api/reviews/fixture/messages",
                    json={**body, "text": "different message"},
                ).status_code,
                409,
            )

    def test_failed_chat_keeps_the_transcript_unchanged_and_active_work_is_locked(self):
        from fastapi.testclient import TestClient

        from api.app import create_app
        from api.jobs import JobManager

        manager = JobManager()
        with TestClient(create_app(manager)) as client:
            body = {"text": "Explain this step", "request_id": "test-message-002"}
            with patch(
                "agents.chat_agent.reply", side_effect=ValueError("Model unavailable")
            ):
                self.assertEqual(
                    client.post("/api/reviews/fixture/messages", json=body).status_code,
                    409,
                )
            self.assertFalse((self.review / "outputs/chat_messages.json").exists())
            manager.active["fixture"] = {"status": "running"}
            with patch("agents.chat_agent.reply") as reply:
                self.assertEqual(
                    client.post("/api/reviews/fixture/messages", json=body).status_code,
                    409,
                )
                reply.assert_not_called()
            manager.active.clear()
            self.assertEqual(
                client.post("/api/reviews/missing/messages", json=body).status_code, 404
            )
            self.assertEqual(
                client.post(
                    "/api/reviews/fixture/messages", json={**body, "text": "   "}
                ).status_code,
                422,
            )


class ThinkingDefaultTests(unittest.TestCase):
    setUp = GuidedWorkflowTests.setUp

    def test_new_and_legacy_default_settings_start_off(self):
        controls = {"available": True, "options": [{"value": "off"}, {"value": "on"}]}
        with patch("methodology.runtime.model_controls", return_value=controls):
            self.assertEqual(runtime.settings("fixture")["thinking"], "off")
            self.assertEqual(
                runtime.worker_environment("fixture")["OLLAMA_REASONING"], "false"
            )
            write_json(
                self.review / "outputs/runtime_settings.json", {"thinking": "default"}
            )
            self.assertEqual(runtime.settings("fixture")["thinking"], "off")
            self.assertFalse(runtime.reasoning_value("fixture"))
            runtime.save_thinking("fixture", "on")
            self.assertEqual(runtime.settings("fixture")["thinking"], "on")
            self.assertTrue(runtime.reasoning_value("fixture"))

    def test_non_boolean_model_requires_explicit_enabling_instead_of_silent_thinking(
        self,
    ):
        controls = {
            "available": True,
            "options": [{"value": "default"}, {"value": "low"}],
        }
        with patch("methodology.runtime.model_controls", return_value=controls):
            with self.assertRaisesRegex(ValueError, "cannot disable"):
                runtime.reasoning_value("fixture")
            runtime.save_thinking("fixture", "low")
            self.assertEqual(runtime.reasoning_value("fixture"), "low")


class OriginalPdfTests(unittest.TestCase):
    setUp = GuidedWorkflowTests.setUp

    def test_original_bytes_download_and_responsive_page_render(self):
        import pymupdf
        from fastapi.testclient import TestClient

        from api.app import create_app
        from api.jobs import JobManager

        pdf = self.review / "papers/W1.pdf"
        with pymupdf.open() as document:
            first = document.new_page()
            first.insert_text((72, 72), "Original page with a figure and columns")
            first.draw_rect(
                pymupdf.Rect(80, 100, 220, 180), color=(1, 0, 0), fill=(0.9, 0.9, 0.9)
            )
            second = document.new_page()
            second.insert_text((72, 72), "Second original page")
            document.save(pdf)
        original = pdf.read_bytes()
        with TestClient(create_app(JobManager())) as client:
            base = "/api/reviews/fixture/papers/W1"
            info = client.get(base + "/pdf-info")
            self.assertEqual(info.status_code, 200)
            self.assertEqual(info.json()["pages"], 2)
            self.assertEqual(client.get(base + "/file").content, original)
            download = client.get(base + "/file?download=true")
            self.assertEqual(download.content, original)
            self.assertIn("attachment", download.headers["content-disposition"])
            page = client.get(base + "/page/1")
            self.assertEqual(page.status_code, 200)
            self.assertTrue(page.content.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertIn("image/png", page.headers["content-type"])
            self.assertEqual(client.get(base + "/page/0").status_code, 404)
            self.assertEqual(client.get(base + "/page/3").status_code, 404)
            self.assertEqual(client.get(base + "/page/1?scale=99").status_code, 422)
            self.assertEqual(
                client.get("/api/reviews/fixture/papers/unknown/pdf-info").status_code,
                404,
            )
        self.assertEqual(pdf.read_bytes(), original)
