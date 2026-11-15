"""Protocol scope validation and bounded, source-audited screening decisions."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pydantic import ValidationError

from agents.full_text_agent import Finding, WindowAssessment, assess_full_text
from agents.planner_agent import ProtocolPlan, propose_protocol
from methodology.protocol import Protocol


class ScopeAndScreeningTests(unittest.TestCase):
    def test_planner_rejects_placeholder_and_retries_once(self):
        value = dict(
            research_question="How is XAI used for IDS?",
            rationale="Assess laboratory and operational evidence.",
            inclusion_criteria=[
                "English between [Insert Start Year] and [Insert End Year]"
            ],
            exclusion_criteria=["Unrelated research"],
            concepts=[["XAI"], ["IDS"]],
        )
        with self.assertRaises(ValidationError):
            ProtocolPlan(**value)
        value["inclusion_criteria"] = ["Empirical XAI applied to IDS"]
        client = Mock()
        client.with_structured_output.return_value.invoke.side_effect = [
            ValueError("Invalid criteria"),
            ProtocolPlan(**value),
        ]
        with patch("agents.planner_agent.chat_model", return_value=client):
            result = propose_protocol("XAI for IDS")
        self.assertEqual(result.inclusion_criteria, value["inclusion_criteria"])
        self.assertEqual(
            client.with_structured_output.return_value.invoke.call_count, 2
        )

    def assess(self, verdicts):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "papers"
            folder.mkdir()
            text = "We evaluated a classifier using a laboratory dataset."
            (folder / "W1.txt").write_text(text)
            model = Mock()
            model.with_structured_output.return_value.invoke.return_value = (
                WindowAssessment(
                    findings=[
                        Finding(
                            criterion_id=cid,
                            status="supported",
                            reason="Discovery",
                            quote=text,
                        )
                        for cid in ("E1", "E2")
                    ]
                )
            )
            with (
                patch("agents.full_text_agent.chat_model", return_value=model),
                patch("agents.full_text_agent.progress"),
                patch(
                    "agents.full_text_agent.verify_items",
                    return_value={
                        str(i): {
                            "subject": "this_study",
                            "verdict": "supported",
                            "reason": "Source",
                        }
                        for i in range(2)
                    },
                ),
                patch(
                    "agents.full_text_agent.adjudicate_criterion",
                    side_effect=[
                        {"status": v, "reason": "Independent source audit"}
                        for v in verdicts
                    ],
                ) as audit,
            ):
                result = assess_full_text(
                    Protocol(
                        research_question="XAI for IDS?",
                        rationale="Laboratory studies are eligible.",
                        inclusion_criteria=["Relevant empirical study"],
                        exclusion_criteria=["Unrelated task", "No XAI application"],
                        concepts=[["IDS"]],
                    ),
                    "W1",
                    folder,
                )
                return result, audit.call_count

    def test_confirmed_exclusion_skips_remaining_audits(self):
        result, calls = self.assess(["supported"])
        self.assertEqual(result["recommendation"], "exclude")
        self.assertEqual(calls, 1)
        self.assertEqual(result["skipped_criterion_audits"], ["E2", "I1"])

    def test_unknown_other_exclusion_cannot_cancel_confirmed_exclusion(self):
        result, calls = self.assess(["unknown", "supported"])
        self.assertEqual(result["recommendation"], "exclude")
        self.assertEqual(calls, 2)

    def test_unknown_criteria_never_force_a_decision(self):
        result, calls = self.assess(["unknown", "unknown", "unknown"])
        self.assertEqual(result["recommendation"], "uncertain")
        self.assertEqual(calls, 3)
