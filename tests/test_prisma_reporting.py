"""Automatic PRISMA counts, manuscript binding and publication-year regressions."""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree

import test_automatic_mode as fixtures
from pydantic import ValidationError

from api.app import RunConfiguration
from methodology.automatic_reporting import MARKER, automatic_flow
from methodology.protocol import draft_protocol, load_protocol
from methodology.reporting import review_checklist_item
from methodology.runtime import save_configuration, settings, year_bounds
from storage.human_review import digest, read_json
from storage.review_manager import write_json
from workflow.automatic import result, result_fingerprint, upgrade_reporting


class PrismaReportingTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.AutomaticModeTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.root = self.case.review
        self.out = self.root / "outputs"

    def test_year_defaults_and_one_sided_bounds(self):
        self.assertEqual(year_bounds(settings("fixture")), (None, None))
        self.assertEqual(
            year_bounds({"year_from": 2020, "year_to": None}), (date(2020, 1, 1), None)
        )
        self.assertEqual(
            year_bounds({"year_from": None, "year_to": 2025}),
            (None, date(2025, 12, 31)),
        )
        for start, end in [(2025, 2020), (0, None), (2020.5, None), (True, None)]:
            with self.assertRaises((ValueError, ValidationError)):
                year_bounds({"year_from": start, "year_to": end})
        with self.assertRaises(ValidationError):
            RunConfiguration(year_from=2025, year_to=2020)
        with self.assertRaises(ValidationError):
            RunConfiguration(year_from=2020.5)

    def test_years_are_saved_to_protocol_and_can_be_cleared_before_run(self):
        save_configuration("fixture", {"year_from": 2020, "year_to": 2025})
        self.case.run_automatic()
        protocol = load_protocol("fixture")["protocol"]
        self.assertEqual(protocol["date_from"], "2020-01-01")
        self.assertEqual(protocol["date_to"], "2025-12-31")
        with self.assertRaises(ValueError):
            save_configuration("fixture", {"year_from": 2021})
        (self.root / "workflow_state.json").unlink()
        save_configuration("fixture", {"year_from": None, "year_to": None})
        self.assertEqual(year_bounds(settings("fixture")), (None, None))

    def test_date_bounds_reach_each_search_provider(self):
        from tools.search import arxiv, openalex, pubmed

        save_configuration("fixture", {"year_from": 2020, "year_to": 2025})
        protocol = draft_protocol("fixture")
        response = MagicMock()
        response.json.return_value = {"results": [], "meta": {"next_cursor": None}}
        with patch("tools.search.fetch", return_value=response) as fetch:
            openalex(MagicMock(), "query", protocol)
            params = fetch.call_args.args[2]
            self.assertIn("from_publication_date:2020-01-01", params["filter"])
            self.assertIn("to_publication_date:2025-12-31", params["filter"])
        response.json.return_value = {"esearchresult": {"idlist": [], "count": "0"}}
        with patch("tools.search.fetch", return_value=response) as fetch:
            pubmed(MagicMock(), "query", protocol)
            self.assertEqual(fetch.call_args.args[2]["mindate"], "2020/01/01")
            self.assertEqual(fetch.call_args.args[2]["maxdate"], "2025/12/31")
        response.text = '<feed xmlns="http://www.w3.org/2005/Atom" />'
        client = MagicMock()
        client.get.return_value = response
        arxiv(client, "all:query", protocol)
        self.assertIn(
            "submittedDate:[202001010000 TO 202512312359]",
            client.get.call_args.kwargs["params"]["search_query"],
        )

    def test_automatic_run_exports_real_counts_and_unreviewed_checklist(self):
        self.case.run_automatic()
        flow = read_json(self.out / "prisma_flow.json", {})
        self.assertEqual(flow["records_identified"], 1)
        self.assertEqual(flow["reports_included"], 1)
        self.assertEqual(flow["reports_in_synthesis"], 1)
        self.assertIsNone(flow["studies_included"])
        self.assertTrue(all(flow["count_checks"].values()))
        ElementTree.fromstring((self.out / "prisma_flow.svg").read_text())
        report = (self.out / "automatic_review.md").read_text()
        checklist = read_json(self.out / "prisma_checklist.json", {})
        self.assertEqual(checklist["report_fingerprint"], digest(report))
        self.assertFalse(checklist["compliance_claimed"])
        self.assertTrue(
            all(
                i["status"] == "requires_human_review" and not i["reviewer"]
                for i in checklist["items"]
            )
        )
        for name in (
            "evidence_table.csv",
            "references.bib",
            "full_text_decisions.csv",
            "automatic_review.docx",
        ):
            self.assertTrue((self.out / name).is_file())
        before = result("fixture")["fingerprint"]
        item = checklist["items"][0]
        review_checklist_item(
            "fixture",
            item["id"],
            "reported",
            "Title",
            "",
            "Synthetic reviewer",
            checklist["report_fingerprint"],
        )
        self.assertTrue(result("fixture")["current"])
        self.assertEqual(result("fixture")["fingerprint"], before)
        (self.out / "automatic_review.md").write_text(report + "\nRevised manuscript")
        with self.assertRaises(ValueError):
            review_checklist_item(
                "fixture",
                item["id"],
                "reported",
                "Title",
                "",
                "Synthetic reviewer",
                checklist["report_fingerprint"],
            )

    def test_counts_separate_provisional_reports_and_acquisition_failures(self):
        self.case.run_automatic()
        papers = read_json(self.root / "papers.json", [])
        original = papers[0]
        for pid, decision in [
            ("W2", "uncertain"),
            ("W3", "exclude"),
            ("W4", "include"),
        ]:
            papers.append({**original, "id": pid, "screening": {"decision": decision}})
        write_json(self.root / "papers.json", papers)
        write_json(self.out / "retrieved_records.json", papers + [original])
        write_json(
            self.out / "duplicates.json", [{"duplicate": "W1-copy", "retained": "W1"}]
        )
        write_json(
            self.out / "full_text.json",
            [
                {"paper_id": "W1", "status": "retrieved"},
                {"paper_id": "W2", "status": "retrieved"},
                {"paper_id": "W4", "status": "unavailable"},
            ],
        )
        write_json(
            self.out / "automatic_eligibility.json",
            {
                "W1": {"recommendation": "include", "reason": "Eligible"},
                "W2": {
                    "recommendation": "uncertain",
                    "reason": "Incomplete study detail",
                },
            },
        )
        flow, _ = automatic_flow("fixture")
        self.assertEqual(flow["records_identified"], 5)
        self.assertEqual(flow["duplicates_removed"], 1)
        self.assertEqual(flow["records_excluded"], 1)
        self.assertEqual(flow["reports_sought"], 3)
        self.assertEqual(flow["reports_not_retrieved"], 1)
        self.assertEqual(flow["reports_excluded"], 0)
        self.assertEqual(flow["eligibility_uncertain"], 1)
        self.assertEqual(flow["reports_retained_without_usable_extraction"], 1)
        self.assertTrue(all(flow["count_checks"].values()))
        proposals = read_json(self.out / "automatic_eligibility.json", {})
        proposals["W2"] = {"recommendation": "exclude", "reason": "Wrong population"}
        write_json(self.out / "automatic_eligibility.json", proposals)
        flow, _ = automatic_flow("fixture")
        self.assertEqual(flow["exclusion_reasons"], {"Wrong population": 1})
        self.assertEqual(flow["reports_not_retrieved"], 1)
        self.assertEqual(flow["reports_excluded"], 1)

    def test_missing_provenance_is_unknown_and_flow_tampering_invalidates_result(self):
        self.case.run_automatic()
        flow = read_json(self.out / "prisma_flow.json", {})
        flow["records_identified"] = 999
        write_json(self.out / "prisma_flow.json", flow)
        self.assertFalse(result("fixture")["current"])
        (self.out / "retrieved_records.json").unlink()
        (self.out / "duplicates.json").unlink()
        flow, _ = automatic_flow("fixture")
        self.assertIsNone(flow["records_identified"])
        self.assertIsNone(flow["duplicates_removed"])
        self.assertIsNone(flow["count_checks"]["deduplication_balances"])

    def test_old_completed_report_is_upgraded_without_model_or_search_calls(self):
        self.case.run_automatic()
        path = self.out / "automatic_review.md"
        path.write_text(path.read_text().split(MARKER)[0])
        for name in ("prisma_flow.json", "prisma_flow.svg", "prisma_checklist.json"):
            (self.out / name).unlink()
        metadata = read_json(self.out / "automatic_result.json", {})
        metadata.pop("reporting_version", None)
        metadata["fingerprint"] = result_fingerprint("fixture")
        write_json(self.out / "automatic_result.json", metadata)
        self.assertTrue(result("fixture")["current"])
        with (
            patch(
                "tools.search.retrieve",
                side_effect=AssertionError("Search must not rerun"),
            ),
            patch(
                "agents.client.chat_model",
                side_effect=AssertionError("Models must not rerun"),
            ),
        ):
            updated = upgrade_reporting("fixture")
        self.assertTrue(updated["current"])
        self.assertTrue((self.out / "prisma_flow.svg").exists())
        self.assertFalse((self.out / "human_decisions.json").exists())
        self.assertIsNone(load_protocol("fixture")["approval"])
        self.assertEqual(
            (self.out / "technical_report.md").read_text().count(MARKER), 1
        )
