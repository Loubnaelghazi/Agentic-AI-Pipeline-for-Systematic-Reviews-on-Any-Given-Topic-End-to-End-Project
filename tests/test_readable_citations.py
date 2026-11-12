import unittest

from methodology.citations import readable_citations


class ReadableCitationTests(unittest.TestCase):
    papers = [
        {"id": "https://openalex.org/W12", "title": "Study title", "year": 2021},
        {"id": "https://openalex.org/W123", "title": "Second study", "year": 2022},
    ]

    def test_heading_page_and_evidence_citations_use_matching_numbers(self):
        text = "## W12\n[W12:P3; PDF p. 3]\n[W123:Q4]\n- [W12] Study title\n"
        rendered = readable_citations(text, self.papers)
        self.assertIn("## [1] Study title (2021)", rendered)
        self.assertIn("[1; PDF p. 3]", rendered)
        self.assertIn("[2]", rendered)
        self.assertNotIn("W12", rendered)
        self.assertEqual(readable_citations(rendered, self.papers), rendered)

    def test_source_quotations_urls_and_input_records_remain_unchanged(self):
        text = "> The source refers to W12.\nSource: https://openalex.org/W12\n"
        self.assertEqual(readable_citations(text, self.papers), text)
        self.assertEqual(self.papers[0]["id"], "https://openalex.org/W12")

    def test_bare_provisional_and_appraisal_references_are_readable(self):
        text = 'Provisional: W12, W123.\n"W123": {"notes": []}\n'
        self.assertEqual(
            readable_citations(text, self.papers),
            'Provisional: [1], [2].\n"[2]": {"notes": []}\n',
        )
