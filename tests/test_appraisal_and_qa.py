"""Failures, invented support and ambiguous assessments must not pass as evidence."""

import unittest
from unittest.mock import MagicMock, patch

from agents.appraisal_agent import (
    DomainProposal,
    domain_sources,
    propose_appraisal,
    validate_proposal,
)
from agents.scientific_qa import (
    SourceReview,
    bind_review,
    locate_findings,
    review_manuscript,
    study_excerpt,
)
from evaluation.benchmark import evaluate
from methodology.appraisal_profiles import apply_profile
from methodology.protocol import Protocol, strategies


def protocol():
    return Protocol(
        research_question="Does the model generalize to independent participants?",
        rationale="Examine independent validation in model evaluation studies.",
        inclusion_criteria=["Reports validation"],
        exclusion_criteria=["No primary results"],
        concepts=[["model"], ["validation"]],
        appraisal_domains=[
            {
                "id": "validation",
                "question": "Are independent participants used for validation?",
            }
        ],
    )


class SourceAppraisalTests(unittest.TestCase):
    def test_search_synonyms_are_alternatives_not_required_simultaneously(self):
        p = protocol()
        p.concepts = [["Transformer", "self attention"], ["translation", "NMT"]]
        query = strategies(p)["openalex"][1]
        self.assertEqual(
            query, '("Transformer" OR "self attention") AND ("translation" OR "NMT")'
        )

    def test_invalid_or_missing_support_cannot_produce_low_risk(self):
        text = "We tested on independent participants."
        snippets = [{"id": "S1", "text": text}]
        for ids in [[], ["invented"], ["S1", "invented"]]:
            with self.subTest(ids=ids):
                result = validate_proposal(
                    {
                        "judgement": "low",
                        "rationale": "Independent test set.",
                        "source_ids": ids,
                    },
                    snippets,
                    None,
                    text,
                )
                self.assertEqual(result["judgement"], "unclear")

    def test_disagreeing_machine_assessments_remain_unclear(self):
        quote = "We used independent participants for validation."
        client = MagicMock()
        client.with_structured_output.return_value.invoke.side_effect = [
            DomainProposal(
                judgement="low",
                rationale="Independent participants were used.",
                source_ids=["S1"],
            ),
            DomainProposal(
                judgement="unclear",
                rationale="Overlap is not explicitly excluded.",
                source_ids=["S1"],
            ),
        ]
        with patch("agents.appraisal_agent.chat_model", return_value=client):
            value = propose_appraisal(
                protocol(), {"paper_id": "W1", "supporting_passages": [{"text": quote}]}
            )
        self.assertEqual(value["domains"][0]["judgement"], "unclear")
        self.assertEqual(value["domains"][0]["validation"], "disagreement")
        self.assertFalse(value["human_reviewed"])
        self.assertFalse(value["validated_instrument"])

    def test_model_failure_is_reported_as_unclear_not_low(self):
        client = MagicMock()
        client.with_structured_output.return_value.invoke.side_effect = TimeoutError(
            "offline"
        )
        with patch("agents.appraisal_agent.chat_model", return_value=client):
            result = propose_appraisal(
                protocol(),
                {
                    "paper_id": "W1",
                    "supporting_passages": [
                        {"text": "Validation used independent participants."}
                    ],
                },
            )
        self.assertEqual(result["domains"][0]["validation"], "failed")
        self.assertEqual(result["domains"][0]["judgement"], "unclear")

    def test_windows_are_exact_and_bounded_and_profile_is_explicit(self):
        text = ("Validation involved independent participants. " * 700).strip()
        windows = domain_sources("Independent validation participants", text, None)
        self.assertLessEqual(len(windows), 8)
        self.assertTrue(all(w["text"] in text for w in windows))
        p = apply_profile(protocol(), "prediction")
        self.assertIn("not the full PROBAST", p.appraisal_name)
        self.assertIn("validation", [d.id for d in p.appraisal_domains])


class LocatedCriticTests(unittest.TestCase):
    def test_critic_quotes_are_copied_from_existing_identifiers(self):
        verdict = SourceReview(
            concern="contradiction",
            manuscript_id="M1",
            source_id="S1",
            reason="The numeric values differ",
        )
        value = bind_review(
            verdict,
            {"M1": "Accuracy was 90 percent."},
            {"S1": "Accuracy was 80 percent."},
        )
        self.assertEqual(value[0]["manuscript_quote"], "Accuracy was 90 percent.")
        self.assertEqual(value[0]["evidence_quote"], "Accuracy was 80 percent.")
        with self.assertRaisesRegex(ValueError, "unknown source"):
            bind_review(verdict, {"M1": "Accuracy was 90 percent."}, {})

    def test_uncertain_critic_never_becomes_a_clean_pass(self):
        with self.assertRaisesRegex(ValueError, "could not resolve"):
            bind_review(
                SourceReview(concern="uncertain", reason="Evidence is ambiguous"),
                {},
                {},
            )

    def test_study_excerpt_does_not_mix_publications_or_joint_paragraphs(self):
        writing = {
            "facts": {"W1:Q1": {"paper_id": "W1"}, "W2:Q1": {"paper_id": "W2"}},
            "sections": {
                "results": {
                    "paragraphs": [
                        {"text": "First study result.", "evidence_ids": ["W1:Q1"]},
                        {"text": "Second study result.", "evidence_ids": ["W2:Q1"]},
                        {"text": "Joint summary.", "evidence_ids": ["W1:Q1", "W2:Q1"]},
                    ]
                }
            },
        }
        self.assertEqual(study_excerpt(writing, "W1"), "First study result.")
        self.assertEqual(study_excerpt(writing, "W2"), "Second study result.")

    def test_critic_sends_only_source_mapped_paragraphs_to_each_study_audit(self):
        writing = {
            "facts": {
                "W1:Q1": {
                    "paper_id": "W1",
                    "kind": "main_findings",
                    "text": "First study result.",
                },
                "W2:Q1": {
                    "paper_id": "W2",
                    "kind": "main_findings",
                    "text": "Second study result.",
                },
            },
            "sections": {
                "results": {
                    "paragraphs": [
                        {"text": "First study result.", "evidence_ids": ["W1:Q1"]},
                        {"text": "Second study result.", "evidence_ids": ["W2:Q1"]},
                    ]
                }
            },
        }
        records = [
            {"paper_id": pid, "claims": [{"kind": "main_findings", "quote": text}]}
            for pid, text in [
                ("W1", "First study result."),
                ("W2", "Second study result."),
            ]
        ]
        client = MagicMock()
        client.with_structured_output.return_value.invoke.return_value = SourceReview(
            concern="none", reason="All supplied statements agree"
        )
        with patch("agents.scientific_qa.chat_model", return_value=client):
            value = review_manuscript(
                {}, records, "First study result. Second study result.", writing=writing
            )
        prompts = [
            call.args[0]
            for call in client.with_structured_output.return_value.invoke.call_args_list
        ]
        self.assertIn("First study result.", prompts[0])
        self.assertNotIn("Second study result.", prompts[0])
        self.assertNotIn("First study result.", prompts[1])
        self.assertTrue(value["completed"])

    def test_fabricated_manuscript_or_evidence_findings_are_quarantined(self):
        record = {"paper_id": "W1", "claims": [{"quote": "Accuracy was 80 percent."}]}
        finding = {
            "category": "contradiction",
            "manuscript_quote": "Accuracy was 90 percent.",
            "evidence_quote": "Accuracy was 80 percent.",
            "explanation": "The reported accuracy differs.",
        }
        ok, rejected = locate_findings([finding], "Accuracy was 90 percent.", record)
        self.assertEqual(len(ok), 1)
        self.assertFalse(rejected)
        for changes in [
            {"manuscript_quote": "Invented manuscript sentence."},
            {"evidence_quote": "Accuracy was 70 percent."},
        ]:
            ok, rejected = locate_findings(
                [{**finding, **changes}], "Accuracy was 90 percent.", record
            )
            self.assertFalse(ok)
            self.assertEqual(len(rejected), 1)

    def test_failed_critic_is_incomplete_and_never_passes(self):
        client = MagicMock()
        client.with_structured_output.return_value.invoke.side_effect = TimeoutError(
            "offline"
        )
        with patch("agents.scientific_qa.chat_model", return_value=client):
            result = review_manuscript(
                {},
                [
                    {
                        "paper_id": "W1",
                        "claims": [
                            {"kind": "main_findings", "quote": "Source result."}
                        ],
                    }
                ],
                "Draft",
            )
        self.assertFalse(result["completed"])
        self.assertFalse(result["passed"])
        self.assertTrue(result["failures"])


class EvaluationIntegrityTests(unittest.TestCase):
    def test_all_wrong_predictions_have_zero_f1_and_no_fake_timing(self):
        labels = [
            {
                "paper_id": "a",
                "reviewer": "Named reader",
                "decision": "include",
                "manual_seconds": True,
            }
        ]
        result = evaluate(
            labels, [{"paper_id": "a", "decision": "exclude", "automated_seconds": 1}]
        )
        self.assertEqual(result["f1"], 0)
        self.assertIsNone(result["time_savings_fraction"])

    def test_abstention_is_distinct_from_exclusion_and_human_labels_required(self):
        labels = [{"paper_id": "a", "reviewer": "Named reader", "decision": "include"}]
        result = evaluate(labels, [{"paper_id": "a", "decision": "uncertain"}])
        self.assertEqual(result["accuracy"], 0)
        self.assertEqual(result["decision_coverage"], 0)
        self.assertEqual(result["retention_recall"], 1)
        with self.assertRaises(ValueError):
            evaluate(
                [{**labels[0], "reviewer": None}],
                [{"paper_id": "a", "decision": "include"}],
            )
