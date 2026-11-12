"""PDF tables with cell geometry and unchanged decimal text.

Do not use Table.extract(): some PDFs emit decimal points after the digits.
Read each detected cell from its original PDF bounding box instead.
"""

import re

import pymupdf

from rag.provenance import normalize


def extract_tables(path):
    tables, issues = [], []
    if not path.exists():
        return tables, ["No PDF available for table extraction"]
    with pymupdf.open(path) as document:
        for page_number, page in enumerate(document, 1):
            text = page.get_text()
            if not re.search(r"(?im)^\s*(?:table|tab\.)\s*\d+[.:]", text):
                continue
            try:
                detected = page.find_tables().tables
                textpage = page.get_textpage()
                for index, table in enumerate(detected, 1):
                    cells = [
                        [
                            normalize(page.get_textbox(cell, textpage=textpage))
                            if cell
                            else None
                            for cell in row.cells
                        ]
                        for row in table.rows
                    ]
                    if len(cells) < 2:
                        continue
                    # Keep merged cells as null. No automatic fill of an
                    # ambiguous dataset/group label across row boundaries.
                    tables.append(
                        {
                            "table_id": f"T{page_number}-{index}",
                            "page": page_number,
                            "bbox": list(table.bbox),
                            "cells": cells,
                            "cell_bboxes": [
                                [list(cell) if cell else None for cell in row.cells]
                                for row in table.rows
                            ],
                            "page_context": normalize(text),
                            "status": "source_cells_unreviewed",
                        }
                    )
                if not detected:
                    issues.append(
                        f"PDF p. {page_number}: table mentioned but no grid detected; inspect page"
                    )
            except (ValueError, RuntimeError) as error:
                issues.append(f"PDF p. {page_number}: table extraction failed: {error}")
    return tables, issues


def table_statement(table, row_index):
    """Attach headers and group context without inventing a normalized metric."""
    rows = table["cells"]
    return (
        f"PDF p. {table['page']}, table {table['table_id']}, row {row_index}. "
        f"Headers: {rows[0]}. "
        f"Preceding group rows: {[r[:2] for r in rows[1:row_index]]}. "
        f"Cells: {rows[row_index]}. "
        "Null cells are merged/empty; interpretation requires checking the source."
    )
