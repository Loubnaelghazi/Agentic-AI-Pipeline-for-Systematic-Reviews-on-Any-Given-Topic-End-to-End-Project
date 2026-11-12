"""Regression checks for attribution, polarity, table numbers and entailment."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf

from agents.full_text_agent import Finding, WindowAssessment, assess_full_text
from agents.grounding import EVIDENCE_VERSION
from agents.narrative_agent import Narrative, Theme, propose_narrative
from agents.semantic_validation import Verdict, Verification, verify_items
from methodology.protocol import Protocol
from rag.tables import extract_tables
from storage import review_manager
from storage.human_review import approved_evidence, validate_record_source


class ScientificValidationTests(unittest.TestCase):
    def test_guided_results_require_approval_of_the_specific_row(self):
        quote = "Proposed ensemble F1 98.79 percent."
        record = {
            "paper_id": "W1",
            "review_id": "fixture",
            "evidence_version": EVIDENCE_VERSION,
            "claims": [{"kind": "main_findings", "quote": quote, "passage_id": "P1"}],
            "supporting_passages": [
                {"source": "W1.txt", "passage_id": "P1", "text": quote}
            ],
            "numerical_results": [
                {"table_id": "T1", "row_index": 1, "quote": quote, "passage_id": "P1"},
                {"table_id": "T2", "row_index": 1, "quote": quote, "passage_id": "P2"},
            ],
        }
        item = {
            "stage": "evidence",
            "paper_id": "W1",
            "quote": quote,
            "passage": record["supporting_passages"][0],
            "proposed_kind": "main_findings",
            "decision": {"decision": "approve", "kind": None},
        }
        queue = {"review_id": "fixture", "included_papers": ["W1"], "items": [item]}
        self.assertEqual(
            len(approved_evidence(queue, [record])[0]["numerical_results"]), 1
        )
        item["decision"]["decision"] = "reject"
        self.assertFalse(approved_evidence(queue, [record])[0]["numerical_results"])

    def test_missing_and_duplicate_verdicts_do_not_authorize_claims(self):
        model = MagicMock()
        model.with_structured_output.return_value.invoke.return_value = Verification(
            verdicts=[
                Verdict(
                    item_id="a", subject="this_study", verdict="supported", reason="x"
                )
            ]
            * 2
        )
        with patch("agents.semantic_validation.chat_model", return_value=model):
            self.assertEqual(verify_items({"a": {}, "b": {}}, "source", "audit"), {})

    def full_text(self, check, exclusion_audit=None):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "papers"
            folder.mkdir()
            (folder.parent / "outputs").mkdir()
            (folder / "W1.txt").write_text(
                "We evaluate chest radiographs with five-fold cross-validation."
            )
            proposal = WindowAssessment(
                findings=[
                    Finding(
                        criterion_id="E1",
                        status="supported",
                        reason="bad proposal",
                        quote="We evaluate chest radiographs with five-fold cross-validation.",
                    )
                ]
            )
            client = MagicMock()
            client.with_structured_output.return_value.invoke.return_value = proposal
            with (
                patch("agents.full_text_agent.chat_model", return_value=client),
                patch("agents.full_text_agent.verify_items", return_value={"0": check}),
                patch(
                    "agents.full_text_agent.adjudicate_criterion",
                    side_effect=lambda criterion, body, findings, source: {
                        "status": (
                            "supported"
                            if exclusion_audit
                            and exclusion_audit.get("applies", {}).get("verdict")
                            == "supported"
                            and exclusion_audit.get("does_not_apply", {}).get("verdict")
                            == "contradicted"
                            else "contradicted"
                            if exclusion_audit
                            and exclusion_audit.get("applies", {}).get("verdict")
                            == "contradicted"
                            and exclusion_audit.get("does_not_apply", {}).get("verdict")
                            == "supported"
                            else "unknown"
                        )
                        if criterion.startswith("Studies lacking")
                        else "unknown",
                        "quote": "",
                        "reason": "Synthetic criterion adjudication",
                    },
                ),
                patch("agents.full_text_agent.progress"),
            ):
                return assess_full_text(
                    Protocol(
                        research_question="Methods?",
                        rationale="Synthetic test protocol",
                        inclusion_criteria=["Original study"],
                        exclusion_criteria=[
                            "Studies lacking a training/testing split."
                        ],
                        concepts=[["test"]],
                    ),
                    "W1",
                    folder,
                )

    def test_inconsistent_opposite_verdicts_cannot_exclude(self):
        value = {"subject": "this_study", "verdict": "supported", "reason": "Ambiguous"}
        result = self.full_text(value, {"applies": value, "does_not_apply": value})
        self.assertEqual(result["recommendation"], "uncertain")
        self.assertEqual(result["unresolved_exclusions"], ["E1"])

    def test_exclusion_requires_support_and_refutation_of_opposite(self):
        yes = {
            "subject": "this_study",
            "verdict": "supported",
            "reason": "Explicit absence",
        }
        no = {
            "subject": "this_study",
            "verdict": "contradicted",
            "reason": "Opposite refuted",
        }
        result = self.full_text(yes, {"applies": yes, "does_not_apply": no})
        self.assertEqual(result["recommendation"], "exclude")

    def test_refuted_exclusion_is_corrected_after_two_sided_audit(self):
        yes = {
            "subject": "this_study",
            "verdict": "supported",
            "reason": "A split exists",
        }
        no = {
            "subject": "this_study",
            "verdict": "contradicted",
            "reason": "No absence",
        }
        result = self.full_text(yes, {"applies": no, "does_not_apply": yes})
        self.assertEqual(result["criterion_decisions"]["E1"]["status"], "contradicted")
        self.assertEqual(result["findings"][0]["status"], "supported")
        self.assertNotEqual(result["recommendation"], "exclude")

    def test_split_evidence_cannot_support_no_split_exclusion(self):
        result = self.full_text(
            {
                "subject": "this_study",
                "verdict": "contradicted",
                "reason": "A split is described",
            }
        )
        self.assertEqual(result["findings"][0]["status"], "contradicted")
        self.assertNotEqual(result["recommendation"], "exclude")

    def test_cited_work_cannot_exclude_evaluated_study(self):
        result = self.full_text(
            {"subject": "cited_work", "verdict": "supported", "reason": "Other author"}
        )
        self.assertEqual(result["findings"][0]["status"], "unknown")
        self.assertNotEqual(result["recommendation"], "exclude")

    def test_unverified_verdict_cannot_exclude(self):
        result = self.full_text(
            {"subject": "unclear", "verdict": "insufficient", "reason": "Insufficient"}
        )
        self.assertNotEqual(result["recommendation"], "exclude")

    def test_semantically_unsupported_annotation_theme_is_removed(self):
        theme = Theme(
            title="Annotation",
            analysis="Both studies use expert annotators.",
            evidence_ids=["W1:Q1"],
            limitations="Panel details are unavailable.",
        )
        client = MagicMock()
        client.with_structured_output.return_value.invoke.return_value = Narrative(
            themes=[theme]
        )
        with (
            patch("agents.narrative_agent.chat_model", return_value=client),
            patch(
                "agents.narrative_agent.verify_items",
                return_value={
                    "theme": {
                        "subject": "this_study",
                        "verdict": "insufficient",
                        "reason": "Cross-validation is not annotation",
                    }
                },
            ),
        ):
            result = propose_narrative(
                MagicMock(),
                [
                    {
                        "paper_id": "W1",
                        "claims": [
                            {
                                "kind": "methodology",
                                "quote": "We used five-fold cross-validation.",
                            }
                        ],
                    }
                ],
                {},
            )
        self.assertFalse(result["themes"])
        self.assertEqual(len(result["rejected_themes"]), 1)

    def test_decimal_cells_preserved_and_tampering_rejected(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(review_manager, "REVIEW_ROOT", Path(tmp)),
        ):
            folder = Path(tmp) / "fixture/papers"
            folder.mkdir(parents=True)
            with pymupdf.open() as doc:
                page = doc.new_page()
                page.insert_text((50, 50), "Table 1. Performance")
                xs, ys = [50, 180, 280], [80, 110, 140]
                for x in xs:
                    page.draw_line((x, ys[0]), (x, ys[-1]))
                for y in ys:
                    page.draw_line((xs[0], y), (xs[-1], y))
                for x, y, text in [
                    (55, 100, "Model"),
                    (185, 100, "F1(%)"),
                    (55, 130, "Proposed"),
                    (185, 130, "98.79"),
                ]:
                    page.insert_text((x, y), text)
                doc.save(folder / "W1.pdf")
            tables, _ = extract_tables(folder / "W1.pdf")
            self.assertEqual(tables[0]["cells"][1][-1], "98.79")
            record = {
                "paper_id": "W1",
                "review_id": "fixture",
                "evidence_version": EVIDENCE_VERSION,
                "claims": [],
                "supporting_passages": [],
                "source_tables": tables,
                "numerical_results": [
                    {"table_id": tables[0]["table_id"], "row_index": 1}
                ],
            }
            validate_record_source("fixture", record)
            tables[0]["cells"][1][-1] = "99.99"
            with self.assertRaisesRegex(ValueError, "cells no longer match"):
                validate_record_source("fixture", record)

    def test_local_table9_regression_if_pdf_available(self):
        path = Path(
            "data/reviews/deep_learning_for_pneumonia_detection_in_26c073a4/papers/W3198276338.pdf"
        )
        if not path.exists():
            self.skipTest("Local audit PDF not distributed with repository")
        tables, _ = extract_tables(path)
        rows = next(t["cells"] for t in tables if t["page"] == 23)
        proposed = [r for r in rows if "Proposed Ensemble" in str(r)]
        self.assertEqual([r[5] for r in proposed], ["98.79", "86.95"])
