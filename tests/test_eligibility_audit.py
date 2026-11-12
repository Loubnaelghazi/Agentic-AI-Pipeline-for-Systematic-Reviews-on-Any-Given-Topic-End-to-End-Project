"""Criterion identity, richer context, polarity and verifiable source quotations."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pymupdf

from agents.eligibility_audit import (
    CriterionJudgment,
    adjudicate_criterion,
    criterion_context,
)
from rag.provenance import PaperSource


class EligibilityAuditTests(unittest.TestCase):
    def test_context_contains_opening_and_relevant_methods_beyond_original_quote(self):
        body = (
            "We propose a new experimental classifier. "
            + "Background context. " * 180
            + "Training and validation sets were disjoint at patient level. "
            + "More background. " * 220
        )
        spans = criterion_context(
            body,
            "Studies lacking a training and validation split",
            [{"quote": "Background context."}],
        )
        text = " ".join(s["text"] for s in spans)
        self.assertIn("We propose", text)
        self.assertIn("disjoint at patient level", text)
        self.assertLessEqual(sum(s["end"] - s["start"] for s in spans), 9500)
        for span in spans:
            self.assertEqual(span["text"], body[span["start"] : span["end"]])

    def judge(self, quote, status="no", audit=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "W1.pdf"
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 70), "Our study used chest radiographs only.")
            page.insert_text(
                (50, 90), "We evaluated the proposed model on a held-out test set."
            )
            doc.save(path)
        source = PaperSource(path)
        model = Mock()
        model.with_structured_output.return_value.invoke.return_value = (
            CriterionJudgment(
                condition_met=status,
                evidence_ids=["S1"]
                if quote == "Our study used chest radiographs only."
                else ["INVENTED"],
                reason="Explicit methods",
            )
        )
        with (
            patch("agents.eligibility_audit.chat_model", return_value=model),
            patch(
                "agents.eligibility_audit.model_controls",
                return_value={
                    "available": True,
                    "options": [{"value": "on"}, {"value": "off"}],
                },
            ),
            patch(
                "agents.eligibility_audit.verify_criterion",
                return_value=audit or {},
            ) as verify,
        ):
            value = adjudicate_criterion(
                "Studies using modalities other than chest radiographs",
                source.text,
                [],
                source,
            )
        return value, verify

    def test_matching_literal_condition_and_independent_audit_resolve_negation(self):
        value, _ = self.judge(
            "Our study used chest radiographs only.",
            audit={
                "subject": "this_study",
                "verdict": "contradicted",
                "reason": "Uses radiographs only",
            },
        )
        self.assertEqual(value["status"], "contradicted")
        self.assertEqual(value["passage"]["page_start"], 1)
        self.assertTrue(value["audit_reasoning"])

    def test_unknown_sentence_identifier_cannot_authorize_a_decision(self):
        value, verify = self.judge("This study used computed tomography exclusively.")
        self.assertEqual(value["status"], "unknown")
        verify.assert_not_called()

    def test_wrong_subject_or_opposite_audit_remains_unknown(self):
        for audit in [
            {
                "subject": "cited_work",
                "verdict": "contradicted",
                "reason": "Other authors",
            },
            {
                "subject": "this_study",
                "verdict": "supported",
                "reason": "Contradicts proposal",
            },
        ]:
            value, _ = self.judge("Our study used chest radiographs only.", audit=audit)
            self.assertEqual(value["status"], "unknown")

    def test_repeated_malformed_audit_fails_closed_without_crashing_the_review(self):
        from agents.semantic_validation import verify_items

        model = Mock()
        model.with_structured_output.return_value.invoke.side_effect = ValueError(
            "Truncated JSON"
        )
        with patch("agents.semantic_validation.chat_model", return_value=model):
            value = verify_items(
                {"criterion": {"assertion": "A property"}},
                "Source text.",
                "Audit",
                reasoning=True,
            )
        self.assertEqual(value, {})
        self.assertEqual(model.with_structured_output.return_value.invoke.call_count, 2)

    def test_malformed_criterion_proposals_are_bounded_and_never_authorize_exclusion(
        self,
    ):
        model = Mock()
        model.with_structured_output.return_value.invoke.side_effect = ValueError(
            "No final JSON"
        )
        with (
            patch("agents.eligibility_audit.chat_model", return_value=model),
            patch(
                "agents.eligibility_audit.model_controls",
                return_value={"options": [{"value": "on"}, {"value": "off"}]},
            ),
            patch("agents.eligibility_audit.verify_criterion") as audit,
        ):
            value = adjudicate_criterion(
                "A criterion",
                "Our study describes a real experimental method.",
                [],
                Mock(),
            )
        self.assertEqual(value["status"], "unknown")
        self.assertEqual(model.with_structured_output.return_value.invoke.call_count, 2)
        audit.assert_not_called()
