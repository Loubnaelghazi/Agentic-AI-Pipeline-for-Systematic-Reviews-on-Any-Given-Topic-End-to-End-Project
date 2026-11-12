"""Fail-closed scientific prose and resumability, using synthetic evidence only."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from writer_fixtures import audited_writing

from agents.grounding import EVIDENCE_VERSION
from agents.writing_agent import (
    SECTIONS,
    SectionDraft,
    audit_section,
    saved_section_valid,
    section_prose,
    validate_paragraph,
    write_manuscript,
    writing_packet,
    writing_status,
)
from storage import review_manager
from storage.review_manager import write_json


class ScientificWritingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.review = self.root / "fixture"
        (self.review / "outputs").mkdir(parents=True)
        (self.review / "papers").mkdir()
        (self.review / "topic.txt").write_text("Synthetic review question")
        patcher = patch.object(review_manager, "REVIEW_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.protocol = {"research_question": "What does the model achieve?"}
        quote = "The model achieved an F1 of 0.80 on the test dataset."
        self.record = {
            "paper_id": "W1",
            "review_id": "fixture",
            "evidence_version": EVIDENCE_VERSION,
            "eligibility_status": "include",
            "claims": [{"kind": "main_findings", "quote": quote, "passage_id": "P1"}],
            "supporting_passages": [
                {"source": "W1.txt", "passage_id": "P1", "text": quote, "page_start": 2}
            ],
            "numerical_results": [],
            "source_tables": [],
        }
        self.packet = writing_packet("fixture", self.protocol, [self.record])
        self.key = next(iter(self.packet["facts"]))

    def test_provisional_evidence_never_enters_primary_writing(self):
        packet = writing_packet(
            "fixture",
            self.protocol,
            [{**self.record, "eligibility_status": "uncertain"}],
        )
        self.assertEqual(packet["facts"], {})
        with patch("agents.writing_agent.chat_model") as model:
            value = write_manuscript(
                "fixture",
                self.protocol,
                [{**self.record, "eligibility_status": "uncertain"}],
            )
        self.assertFalse(value["ready"])
        model.assert_not_called()

    def test_guided_mode_requires_approved_evidence(self):
        with self.assertRaisesRegex(ValueError, "human-approved"):
            writing_packet("fixture", self.protocol, [self.record], mode="guided")
        packet = writing_packet(
            "fixture",
            self.protocol,
            [{**self.record, "human_reviewed": True}],
            mode="guided",
        )
        self.assertTrue(
            all(f["origin"] == "human_approved" for f in packet["facts"].values())
        )

    def test_unknown_citations_values_and_background_fail(self):
        for text, ids in [
            ("This model achieved an F1 of 0.99.", [self.key]),
            ("This model achieved an F1 of 0.80.", ["unknown"]),
        ]:
            with self.assertRaises(ValueError):
                validate_paragraph(
                    {"text": text, "evidence_ids": ids}, self.packet["facts"], "results"
                )
        background = {
            self.key: {**self.packet["facts"][self.key], "scope": "background_only"}
        }
        with self.assertRaises(ValueError):
            validate_paragraph(
                {"text": self.record["claims"][0]["quote"], "evidence_ids": [self.key]},
                background,
                "conclusion",
            )

    def test_internal_ids_cannot_leak_into_scientific_prose(self):
        paragraph = {
            "text": f"The reported model achieved an F1 of 0.80 ({self.key}).",
            "evidence_ids": [self.key],
        }
        row = validate_paragraph(paragraph, self.packet["facts"], "results")
        self.assertNotIn(self.key, row["text"])
        self.assertEqual(row["text"], "The reported model achieved an F1 of 0.80.")
        with self.assertRaisesRegex(ValueError, "only in evidence_ids"):
            validate_paragraph(
                {
                    **paragraph,
                    "text": "The reported model achieved an F1 of 0.80 (W1:Q99).",
                },
                self.packet["facts"],
                "results",
            )

    def test_equivalent_numeric_notation_does_not_create_a_false_rejection(self):
        facts = {
            self.key: {
                **self.packet["facts"][self.key],
                "text": "The F1 score was .80 in this experiment.",
            }
        }
        row = validate_paragraph(
            {
                "text": "The F1 score was 0.80 in this experiment.",
                "evidence_ids": [self.key],
            },
            facts,
            "results",
        )
        self.assertIn("0.80", row["text"])

    def test_ready_requires_all_audits_and_unchanged_inputs(self):
        value = audited_writing("fixture", self.protocol, [self.record])
        path = self.review / "outputs/scientific_manuscript.json"
        write_json(path, value)
        self.assertTrue(writing_status("fixture", self.packet)["ready"])
        self.assertIn("[W1; PDF p. 2]", section_prose(value, "results"))
        value["sections"]["results"]["paragraphs"][0]["text"] = (
            "Altered and unsupported prose."
        )
        self.assertFalse(
            saved_section_valid(value["sections"]["results"], value["facts"], "results")
        )
        self.assertEqual(section_prose(value, "results"), "")
        write_json(path, value)
        self.assertFalse(writing_status("fixture", self.packet)["ready"])
        changed = writing_packet(
            "fixture", {"research_question": "A new question"}, [self.record]
        )
        self.assertEqual(writing_status("fixture", changed)["status"], "stale")

    def test_rejected_metric_association_is_quarantined_then_resume_reuses_sections(
        self,
    ):
        paragraph = {
            "text": self.record["claims"][0]["quote"],
            "evidence_ids": [self.key],
        }
        model = Mock()
        model.with_structured_output.return_value.invoke.return_value = SectionDraft(
            paragraphs=[paragraph]
        )
        with (
            patch("agents.writing_agent.chat_model", return_value=model),
            patch(
                "agents.writing_agent.model_signature", return_value="fixture-digest"
            ),
            patch("agents.writing_agent.validate_record_source"),
            patch("agents.writing_agent.progress"),
            patch(
                "agents.writing_agent.audit_section",
                return_value={
                    "0": {
                        "supported": False,
                        "citations_complete": True,
                        "correct_scope": True,
                        "reason": "Metric is assigned to the wrong dataset",
                    }
                },
            ),
        ):
            rejected = write_manuscript("fixture", self.protocol, [self.record])
        self.assertFalse(rejected["ready"])
        self.assertEqual(section_prose(rejected, "results"), "")
        self.assertEqual(rejected["sections"]["results"]["attempts"], 2)
        self.assertTrue(rejected["sections"]["results"]["rejected_draft"])
        approved = audited_writing("fixture", self.protocol, [self.record])
        approved["sections"].pop("abstract")
        approved["ready"] = False
        approved["model_revision"] = "fixture-digest"
        write_json(self.review / "outputs/scientific_manuscript.json", approved)
        model.with_structured_output.return_value.invoke.side_effect = [
            ValueError("Malformed draft"),
            SectionDraft(paragraphs=[paragraph]),
        ]
        with (
            patch("agents.writing_agent.chat_model", return_value=model),
            patch(
                "agents.writing_agent.model_signature", return_value="fixture-digest"
            ),
            patch("agents.writing_agent.validate_record_source"),
            patch("agents.writing_agent.progress"),
            patch(
                "agents.writing_agent.audit_section",
                return_value={
                    "0": {
                        "supported": True,
                        "citations_complete": True,
                        "correct_scope": True,
                        "reason": "Supported",
                    }
                },
            ) as audit,
        ):
            complete = write_manuscript("fixture", self.protocol, [self.record])
        self.assertTrue(complete["ready"])
        self.assertEqual(audit.call_count, 1)
        self.assertEqual(complete["sections"]["abstract"]["attempts"], 2)
        self.assertEqual(len(complete["sections"]), len(SECTIONS))

    def test_rejected_paragraph_never_leaks_when_valid_paragraph_is_retained(self):
        good = {"text": self.record["claims"][0]["quote"], "evidence_ids": [self.key]}
        bad = {
            "text": "This model can replace all clinical readers.",
            "evidence_ids": [self.key],
        }
        self.record["claims"].append(
            {**self.record["claims"][0], "kind": "research_objective"}
        )

        def proposal(prompt):
            context = json.loads(prompt.rsplit("\n", 1)[-1])
            key = next(iter(context["facts"]))
            return SectionDraft(
                paragraphs=[{**row, "evidence_ids": [key]} for row in (good, bad)]
            )

        model = Mock()
        model.with_structured_output.return_value.invoke.side_effect = proposal
        reviews = {
            str(i): {
                "supported": i == 0,
                "citations_complete": i == 0,
                "correct_scope": True,
                "reason": "Supported"
                if i == 0
                else "Unsupported clinical recommendation",
            }
            for i in range(2)
        }
        with (
            patch("agents.writing_agent.chat_model", return_value=model),
            patch(
                "agents.writing_agent.model_signature", return_value="fixture-digest"
            ),
            patch("agents.writing_agent.validate_record_source"),
            patch("agents.writing_agent.progress"),
            patch("agents.writing_agent.audit_section", return_value=reviews),
        ):
            value = write_manuscript("fixture", self.protocol, [self.record])
        self.assertTrue(value["ready"])
        self.assertNotIn(bad["text"], section_prose(value, "results"))
        self.assertIn(good["text"], section_prose(value, "results"))
        self.assertIn("omitted", value["sections"]["results"]["issues"][0])
        self.assertEqual(len(value["sections"]["results"]["attempt_history"]), 2)

    def test_quarantined_proposal_requires_a_new_audit_before_reuse(self):
        value = audited_writing("fixture", self.protocol, [self.record])
        paragraph = {
            "text": self.record["claims"][0]["quote"],
            "evidence_ids": [self.key],
        }
        value["sections"]["abstract"] = {
            "verified": False,
            "paragraphs": [],
            "rejected_draft": {"paragraphs": [paragraph]},
            "issues": ["Needs another audit"],
        }
        value["ready"] = False
        value["model_revision"] = "fixture-digest"
        write_json(self.review / "outputs/scientific_manuscript.json", value)
        self.assertEqual(section_prose(value, "abstract"), "")
        with (
            patch("agents.writing_agent.chat_model") as model,
            patch(
                "agents.writing_agent.model_signature", return_value="fixture-digest"
            ),
            patch("agents.writing_agent.validate_record_source"),
            patch("agents.writing_agent.progress"),
            patch(
                "agents.writing_agent.audit_section",
                return_value={
                    "0": {
                        "supported": True,
                        "citations_complete": True,
                        "correct_scope": True,
                        "reason": "Supported",
                    }
                },
            ) as audit,
        ):
            checked = write_manuscript("fixture", self.protocol, [self.record])
        self.assertTrue(checked["ready"])
        audit.assert_called_once()
        model.assert_not_called()

    def test_malformed_editor_verdict_fails_closed_after_bounded_retry(self):
        model = Mock()
        model.with_structured_output.return_value.invoke.side_effect = ValueError(
            "Malformed verdict"
        )
        with (
            patch("agents.writing_agent.chat_model", return_value=model),
            patch(
                "agents.eligibility_audit.model_controls", return_value={"options": []}
            ),
        ):
            reviews = audit_section(
                "results",
                [
                    {
                        "text": self.record["claims"][0]["quote"],
                        "evidence_ids": [self.key],
                    }
                ],
                self.packet["facts"],
                "Question",
            )
        self.assertEqual(reviews, {})
        self.assertEqual(model.with_structured_output.return_value.invoke.call_count, 2)

    def test_source_local_draft_rejects_cross_study_citations(self):
        from agents.writing_agent import draft_section

        facts = {
            **self.packet["facts"],
            "W2:Q1": {**self.packet["facts"][self.key], "paper_id": "W2"},
        }
        model = Mock()
        model.with_structured_output.return_value.invoke.return_value = SectionDraft(
            paragraphs=[
                {
                    "text": "The other study reported an F1 of 0.80.",
                    "evidence_ids": ["W2:Q1"],
                }
            ]
        )
        with (
            patch("agents.writing_agent.chat_model", return_value=model),
            self.assertRaisesRegex(ValueError, "publication-specific"),
        ):
            draft_section(
                "results",
                facts,
                {**self.packet, "included_paper_ids": ["W1", "W2"]},
                [],
            )

    def test_editor_gets_only_the_paragraphs_own_sources(self):
        from agents.writing_agent import EditorialVerdict

        facts = {
            **self.packet["facts"],
            "W2:Q1": {
                **self.packet["facts"][self.key],
                "paper_id": "W2",
                "text": "Unrelated second study.",
            },
        }
        model = Mock()
        model.with_structured_output.return_value.invoke.return_value = (
            EditorialVerdict(
                entailed="yes",
                reason="Supported",
            )
        )
        with (
            patch("agents.writing_agent.chat_model", return_value=model),
            patch(
                "agents.eligibility_audit.model_controls", return_value={"options": []}
            ),
        ):
            verdicts = audit_section(
                "results",
                [
                    {
                        "text": self.record["claims"][0]["quote"],
                        "evidence_ids": [self.key],
                    }
                ],
                facts,
                "Question",
            )
        prompt = model.with_structured_output.return_value.invoke.call_args.args[0]
        self.assertNotIn("Unrelated second study", prompt)
        self.assertTrue(verdicts["0"]["supported"])

    def test_uncertain_entailment_never_authorizes_a_paragraph(self):
        from agents.writing_agent import EditorialVerdict

        model = Mock()
        model.with_structured_output.return_value.invoke.return_value = (
            EditorialVerdict(
                entailed="unknown", reason="The dataset attribution is not established"
            )
        )
        with (
            patch("agents.writing_agent.chat_model", return_value=model),
            patch(
                "agents.eligibility_audit.model_controls", return_value={"options": []}
            ),
        ):
            verdicts = audit_section(
                "results",
                [
                    {
                        "text": self.record["claims"][0]["quote"],
                        "evidence_ids": [self.key],
                    }
                ],
                self.packet["facts"],
                "Question",
            )
        self.assertFalse(verdicts["0"]["supported"])
        self.assertFalse(verdicts["0"]["citations_complete"])

    def test_known_coauthor_is_canonicalized_but_unrelated_author_is_rejected(self):
        facts = {
            self.key: {
                **self.packet["facts"][self.key],
                "publication": {
                    "authors": ["Pranav Rajpurkar", "Andrew Ng"],
                    "year": 2017,
                },
            }
        }
        row = validate_paragraph(
            {"text": "Ng et al. reported an F1 of 0.80.", "evidence_ids": [self.key]},
            facts,
            "abstract",
        )
        self.assertEqual(row["text"], "Rajpurkar et al. reported an F1 of 0.80.")
        with self.assertRaisesRegex(ValueError, "FIRST author"):
            validate_paragraph(
                {
                    "text": "Unrelated et al. reported an F1 of 0.80.",
                    "evidence_ids": [self.key],
                },
                facts,
                "abstract",
            )

    def test_results_cannot_silently_drop_a_study_with_primary_findings(self):
        value = audited_writing("fixture", self.protocol, [self.record])
        facts = {
            **value["facts"],
            "W2:Q1": {**value["facts"][self.key], "paper_id": "W2"},
        }
        self.assertFalse(
            saved_section_valid(value["sections"]["results"], facts, "results")
        )
