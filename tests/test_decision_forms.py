"""Conditional requirements remain enforced beneath the streamlined UI."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from api.app import ProtocolApproval, ReviewDecision
from methodology.appraisal import AppraisalSubmission, DomainJudgement
from methodology.protocol import approve_protocol, draft_protocol, save_protocol
from methodology.reporting import checklist, review_checklist_item
from storage import review_manager
from storage.human_review import Decision


class DecisionFormsTests(unittest.TestCase):
    def decision(self, stage, action, **extra):
        return Decision(
            item_id="fixture",
            stage=stage,
            fingerprint="fixture",
            decision=action,
            reviewer=extra.pop("reviewer", "Test reviewer"),
            timestamp="2026-01-01T00:00:00Z",
            **extra,
        )

    def test_routine_decisions_allow_empty_notes(self):
        for stage, action in [
            ("screening", "include"),
            ("screening", "exclude"),
            ("eligibility", "include"),
            ("evidence", "approve"),
            ("evidence", "reject"),
        ]:
            with self.subTest(stage=stage, action=action):
                self.assertEqual(self.decision(stage, action).reason, "")
        self.assertEqual(
            ReviewDecision(
                item_id="x", fingerprint="x", decision="include", reviewer="Test"
            ).reason,
            "",
        )

    def test_full_text_exclusion_still_requires_a_reason(self):
        for reason in ["", "   "]:
            with self.assertRaises(ValidationError):
                self.decision("eligibility", "exclude", reason=reason)
        self.assertEqual(
            self.decision("eligibility", "exclude", reason="Wrong population").reason,
            "Wrong population",
        )

    def test_unclear_appraisal_notes_optional_but_other_judgements_require_reason(self):
        self.assertEqual(
            DomainJudgement(domain_id="selection", judgement="unclear").rationale, ""
        )
        for judgement in ["low", "some_concerns", "high", "not_applicable"]:
            with self.assertRaises(ValidationError):
                DomainJudgement(domain_id="selection", judgement=judgement)
        AppraisalSubmission(
            fingerprint="x", reviewer="Test", overall="unclear", domains=[]
        )
        with self.assertRaises(ValidationError):
            AppraisalSubmission(
                fingerprint="x", reviewer="Test", overall="low", domains=[]
            )

    def test_reviewer_remains_required(self):
        with self.assertRaises(ValidationError):
            self.decision("screening", "include", reviewer="")
        with self.assertRaises(ValidationError):
            DomainJudgement(domain_id="selection", judgement="not_a_judgement")

    def test_protocol_approval_notes_are_optional_and_recorded_without_invented_text(
        self,
    ):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(review_manager, "REVIEW_ROOT", Path(tmp)),
        ):
            root = Path(tmp) / "fixture"
            root.mkdir()
            (root / "topic.txt").write_text("Research on software verification")
            body = draft_protocol("fixture").model_dump(mode="json")
            doc = save_protocol("fixture", body, "Test reviewer")
            request = ProtocolApproval(
                fingerprint=doc["fingerprint"], reviewer="Test reviewer"
            )
            approved = approve_protocol(
                "fixture", request.fingerprint, request.reviewer, request.reason
            )
            self.assertEqual(approved["approval"]["reason"], "")

    def test_reported_checklist_item_uses_location_while_other_states_need_explanation(
        self,
    ):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(review_manager, "REVIEW_ROOT", Path(tmp)),
        ):
            root = Path(tmp) / "fixture" / "outputs"
            root.mkdir(parents=True)
            (root / "literature_review.md").write_text("# Review manuscript\n")
            fp = checklist("fixture")["report_fingerprint"]
            review_checklist_item(
                "fixture", "1", "reported", "Title", "", "Test reviewer", fp
            )
            for status, location in [
                ("reported", ""),
                ("not_applicable", ""),
                ("missing", ""),
            ]:
                with self.assertRaises(ValueError):
                    review_checklist_item(
                        "fixture", "1", status, location, "", "Test reviewer", fp
                    )
