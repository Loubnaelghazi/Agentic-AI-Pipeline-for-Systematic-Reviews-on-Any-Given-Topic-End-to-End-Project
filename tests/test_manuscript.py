import unittest

from methodology.manuscript import build_manuscript


class ManuscriptTests(unittest.TestCase):
    def render(self, records=None, narrative=None):
        records = (
            records
            if records is not None
            else [
                {
                    "paper_id": "W1",
                    "eligibility_status": "uncertain",
                    "claims": [
                        {
                            "kind": "main_findings",
                            "quote": "The model achieved an F1 of 0.80.",
                            "passage_id": "P1",
                        }
                    ],
                    "supporting_passages": [{"passage_id": "P1", "page_start": 2}],
                }
            ]
        )
        return build_manuscript(
            "Synthetic review topic",
            {
                "research_question": "What do the studies report?",
                "sources": ["openalex"],
                "max_records_per_query": 3,
                "inclusion_criteria": ["Original studies"],
                "exclusion_criteria": ["Reviews"],
                "appraisal_name": "Project-defined rubric",
            },
            [{"id": "W1", "title": "Synthetic source article", "year": 2021}],
            records,
            {
                "records_identified": 3,
                "reports_retrieved": 1,
                "reports_included": 0,
                "eligibility_uncertain": 1,
            },
            {},
            "- [W1] Synthetic source article.",
            narrative,
        )

    def test_real_article_sections_and_source_citations_are_present(self):
        text = self.render()
        for heading in [
            "Abstract",
            "Introduction",
            "Methods",
            "Results",
            "Discussion",
            "Limitations",
            "Conclusion",
            "References",
        ]:
            self.assertIn("## " + heading + "\n", text)
        self.assertIn("**Objective:**", text)
        self.assertIn("**Methods:**", text)
        self.assertNotIn("The model achieved an F1 of 0.80.", text)
        self.assertIn("verified abstract narrative is not yet available", text)

    def test_unresolved_eligibility_cannot_become_a_positive_conclusion(self):
        text = self.render(
            narrative={
                "themes": [
                    {"title": "Unsupported", "analysis": "This proves superiority."}
                ]
            }
        )
        self.assertIn("0 reports contributed to the primary synthesis", text)
        self.assertIn("1 reports remained provisional", text)
        self.assertIn("No report currently has an include recommendation", text)
        self.assertNotIn("This proves superiority", text)
        self.assertIn("No source-audited comparative narrative", text)

    def test_excluded_reports_do_not_enter_results(self):
        text = self.render(
            [{"paper_id": "W1", "eligibility_status": "exclude", "claims": []}]
        )
        self.assertIn("No eligible source evidence is available", text)
        self.assertNotIn("#### Synthetic source article", text)

    def test_scientific_limitations_do_not_describe_runtime_or_model_failures(self):
        text = self.render()
        limitations = text.split("## Limitations", 1)[1].split("## Conclusion", 1)[0]
        self.assertNotIn("small local model", limitations)
        self.assertNotIn("misattribute", limitations)
        self.assertIn("risk-of-bias", limitations)
        self.assertIn("retrieval limit", limitations)
        self.assertIn("Figure 1.", text)
        self.assertIn("![Study selection flow](prisma_flow.png)", text)

    def test_numeric_table_includes_only_rows_cited_in_audited_writing(self):
        from agents.writing_agent import section_fingerprint
        from methodology.manuscript import scientific_tables

        key = "W1:T1:R1"
        facts = {
            key: {
                "paper_id": "W1",
                "kind": "main_findings",
                "scope": "primary",
                "text": "The reported F1 score was 0.80.",
                "page": 2,
            }
        }
        paragraphs = [
            {
                "text": facts[key]["text"],
                "evidence_ids": [key],
                "audit": {
                    "supported": True,
                    "citations_complete": True,
                    "correct_scope": True,
                },
            }
        ]
        writing = {
            "facts": facts,
            "sections": {
                "results": {
                    "verified": True,
                    "paragraphs": paragraphs,
                    "content_fingerprint": section_fingerprint(paragraphs, facts),
                }
            },
        }
        table = {
            "table_id": "T1",
            "page": 2,
            "cells": [["Model", "F1"], ["Selected", "0.80"], ["Uncited", "0.99"]],
            "cell_bboxes": [[None, None], [None, None], [None, None]],
        }
        record = {
            "paper_id": "W1",
            "source_tables": [table],
            "numerical_results": [
                {"table_id": "T1", "row_index": 1},
                {"table_id": "T1", "row_index": 2},
            ],
        }
        tables = scientific_tables([{"id": "W1", "title": "Study"}], [record], writing)
        self.assertIn("Table 3.", tables[2])
        self.assertIn("Selected | 0.80", tables[2])
        self.assertNotIn("Uncited", tables[2])
