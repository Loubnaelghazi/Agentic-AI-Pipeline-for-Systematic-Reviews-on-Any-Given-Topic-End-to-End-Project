"""Model upgrades must preserve sources and actual human decisions."""

import hashlib
import unittest
from unittest.mock import patch

from methodology.runtime import settings, upgrade_generation_model
from storage.human_review import read_json
from workflow.automatic import result


class ModelUpgradeTests(unittest.TestCase):
    def test_explicit_upgrade_archives_and_invalidates_model_dependent_outputs(self):
        from test_automatic_mode import AutomaticModeTests

        case = AutomaticModeTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.run_automatic()
        original = (case.review / "papers/W1.pdf").read_bytes()
        self.assertTrue(result("fixture")["ready"])
        with patch("methodology.runtime.validate_configuration_choices"):
            event = upgrade_generation_model("fixture", "synthetic:9b")
        self.assertTrue(event["changed"])
        self.assertEqual(settings("fixture")["model"], "synthetic:9b")
        self.assertEqual(
            hashlib.sha256(original).hexdigest(),
            hashlib.sha256((case.review / "papers/W1.pdf").read_bytes()).hexdigest(),
        )
        state = read_json(case.review / "workflow_state.json", {})
        self.assertIn("retrieval", state["completed"])
        self.assertIn("extraction", state["completed"])
        self.assertNotIn("full_text_screening", state["completed"])
        self.assertNotIn("synthesis", state["completed"])
        self.assertFalse(result("fixture")["current"])
        self.assertTrue(list((case.review / "outputs/history").iterdir()))
        self.assertEqual(
            len(read_json(case.review / "outputs/model_migrations.json", [])), 1
        )
        for filename in [
            "human_decisions.json",
            "protocol_approvals.json",
            "appraisals.json",
        ]:
            self.assertFalse((case.review / "outputs" / filename).exists())

    def test_all_generation_roles_use_the_shared_context_budget(self):
        from agents import critic_agent, screening_agent, search_agent
        from agents.client import chat_model
        from config import OLLAMA_NUM_CTX

        for client in [
            screening_agent.llm,
            search_agent.llm,
            critic_agent.llm,
            chat_model(400, model="synthetic:9b", reasoning=False, temperature=0.1),
        ]:
            self.assertEqual(client.num_ctx, OLLAMA_NUM_CTX)
        selected = chat_model(
            400, model="synthetic:9b", reasoning=False, temperature=0.1
        )
        self.assertEqual(selected.model, "synthetic:9b")
        self.assertEqual(selected.num_predict, 400)
        self.assertFalse(selected.reasoning)

    def test_upgrade_rejects_regressions_on_critical_source_cases_or_cpu_spill(self):
        from scripts.complete_model_upgrade import adoption_check

        keys = [
            "missing_split",
            "cited_work_not_this_study",
            "missing_detail_not_absence",
            "table_wrong_dataset",
            "crossvalidation_not_annotation",
        ]
        candidate = {
            "passed": 10,
            "embedding_coexistence_ok": True,
            "cases": [{"id": key, "correct": True} for key in keys],
            "loaded_model": {"size": 1000, "size_vram": 1000},
            "median_tokens_per_second": 25,
        }
        self.assertTrue(adoption_check(candidate, {"passed": 7})[0])
        candidate["cases"][0]["correct"] = False
        self.assertFalse(adoption_check(candidate, {"passed": 7})[0])
        candidate["cases"][0]["correct"] = True
        candidate["loaded_model"]["size_vram"] = 500
        self.assertFalse(adoption_check(candidate, {"passed": 7})[0])

    def test_default_model_update_preserves_other_environment_values(self):
        import tempfile
        from pathlib import Path

        from scripts import complete_model_upgrade as upgrade

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(upgrade, "PROJECT", Path(folder)),
        ):
            path = Path(folder) / ".env"
            path.write_text("OLLAMA_MODEL=old:4b\nOTHER_SETTING=keep\n")
            self.assertEqual(upgrade.update_default("new:9b"), "old:4b")
            self.assertIn("OTHER_SETTING=keep", path.read_text())
            self.assertEqual(path.read_text().count("OLLAMA_MODEL="), 1)

    def test_explicit_revalidation_reuses_sources_but_clears_machine_proposals(self):
        from test_automatic_mode import AutomaticModeTests

        case = AutomaticModeTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.run_automatic()
        current = settings("fixture")["model"]
        self.assertFalse(upgrade_generation_model("fixture", current)["changed"])
        with patch("methodology.runtime.validate_configuration_choices"):
            event = upgrade_generation_model("fixture", current, revalidate=True)
        self.assertEqual(event["action"], "generation_profile_revalidation")
        self.assertEqual(
            read_json(case.review / "outputs/automatic_eligibility.json", None), {}
        )
        self.assertTrue(read_json(case.review / "outputs/evidence.json", []))
