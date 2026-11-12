import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from methodology.docx import write_document
from methodology.presentation import (
    render_selection_flow,
    selection_summary,
    table_results,
)


class ReportPresentationTests(unittest.TestCase):
    def test_counts_are_readable_and_unknown_is_not_zero(self):
        text = selection_summary(
            {
                "mode": "automatic",
                "records_identified": None,
                "duplicates_removed": 0,
                "reports_included": 0,
                "eligibility_uncertain": 2,
                "reports_not_retrieved": 1,
                "studies_included": None,
            }
        )
        self.assertIn("Records identified | Not recorded", text)
        self.assertIn("Duplicates removed | 0", text)
        self.assertIn("Include recommendations | 0", text)
        self.assertIn("2 reports still await", text)
        self.assertNotIn('"mode"', text)
        self.assertNotIn("```", text)

    def test_merged_group_requires_geometry_and_does_not_modify_raw_data(self):
        table = {
            "cells": [
                ["Dataset", "F1 (%)"],
                ["A", "98.79"],
                [None, "97.00"],
                [None, "86.95"],
            ],
            "cell_bboxes": [
                [[0, 0, 10, 10], [10, 0, 20, 10]],
                [[0, 10, 10, 30], [10, 10, 20, 20]],
                [None, [10, 20, 20, 30]],
                [None, [10, 30, 20, 40]],
            ],
        }
        before = json.dumps(table)
        result = table_results(table, [2, 3])
        self.assertIn("| A | 97.00 |", result)
        self.assertIn("| Not reported | 86.95 |", result)
        self.assertEqual(json.dumps(table), before)

    def test_colored_svg_and_word_contain_real_table_and_embedded_diagram(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            render_selection_flow(
                root / "prisma.svg",
                {
                    "mode": "automatic",
                    "records_identified": 3,
                    "reports_included": 0,
                    "eligibility_uncertain": 2,
                },
            )
            svg = (root / "prisma.svg").read_text()
            ET.fromstring(svg)
            self.assertIn("Decision pending", svg)
            self.assertIn("Include recommendations", svg)
            self.assertIn("#fffbeb", svg)
            self.assertIn("#eff6ff", svg)
            self.assertIn("<polygon", svg)
            write_document(
                root / "report.docx",
                "# Review\n\n| Stage | Reports |\n| --- | --- |\n| Pending | 2 |\n\n### PRISMA selection diagram\n",
                root / "prisma.png",
            )
            with zipfile.ZipFile(root / "report.docx") as doc:
                for name in [
                    "word/document.xml",
                    "word/styles.xml",
                    "word/_rels/document.xml.rels",
                    "[Content_Types].xml",
                ]:
                    ET.fromstring(doc.read(name))
                xml = doc.read("word/document.xml").decode()
                self.assertIn("<w:tbl>", xml)
                self.assertIn("<w:drawing>", xml)
                self.assertNotIn("| --- |", xml)
                self.assertIn("word/media/prisma.png", doc.namelist())

    def test_scientific_word_uses_captions_and_three_line_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "paper.docx"
            write_document(
                path,
                "# Review\n\n**Table 1. Included study findings.**\n\n| Study | F1 |\n| --- | --- |\n| A | 0.80 |\n\n*Note.* F1 is reported without unit conversion.\n",
                scientific=True,
            )
            with zipfile.ZipFile(path) as archive:
                document = archive.read("word/document.xml").decode()
                styles = archive.read("word/styles.xml").decode()
            self.assertIn('w:val="TableCaption"', document)
            self.assertIn('w:val="TableNote"', document)
            self.assertIn("Times New Roman", styles)
            borders = document.split("<w:tblBorders>", 1)[1].split(
                "</w:tblBorders>", 1
            )[0]
            self.assertNotIn("insideV", borders)
            self.assertNotIn("w:left", borders)
            self.assertIn("<w:bottom", borders)
