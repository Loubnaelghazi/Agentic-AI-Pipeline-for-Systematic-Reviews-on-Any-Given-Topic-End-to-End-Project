"""Reader-facing review summaries; raw audit data stays in separate artifacts."""

import math
from xml.sax.saxutils import escape


def count(value):
    return (
        str(value)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else "Not recorded"
    )


def markdown_table(headers, rows):
    def cell(value):
        return (
            str(value if value is not None else "Not reported")
            .replace("|", "\\|")
            .replace("\n", " ")
        )

    return "\n".join(
        [
            "| " + " | ".join(map(cell, headers)) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *["| " + " | ".join(map(cell, row)) + " |" for row in rows],
        ]
    )


def selection_summary(values):
    rows = [
        (label, count(values.get(key)))
        for key, label in [
            ("records_identified", "Records identified"),
            ("duplicates_removed", "Duplicates removed"),
            ("records_screened", "Titles and abstracts screened"),
            ("records_excluded", "Records excluded at screening"),
            ("reports_sought", "Full texts sought"),
            ("reports_retrieved", "Full texts retrieved"),
            ("reports_not_retrieved", "Full texts unavailable"),
            ("reports_assessed", "Full texts assessed"),
            ("reports_excluded", "Full texts excluded"),
            (
                "reports_included",
                "Include recommendations"
                if values.get("mode") == "automatic"
                else "Reports included",
            ),
            ("eligibility_uncertain", "Eligibility decisions pending"),
            ("reports_in_synthesis", "Reports with extracted evidence"),
        ]
        if key in values
    ]
    parts = [markdown_table(["Selection stage", "Reports / records"], rows)]
    pending = values.get("eligibility_uncertain")
    if isinstance(pending, int) and pending > 0:
        parts.append(
            f"**{pending} reports still await an eligibility decision.** Their extracted evidence remains provisional and does not support the primary comparative interpretation."
        )
    if values.get("reports_not_retrieved"):
        parts.append(
            "Unavailable full texts are access gaps; they are not classified as scientific exclusions."
        )
    parts.append(
        "Counts describe publication reports. The number of independent studies is "
        + (
            str(values["studies_included"]) + "."
            if values.get("studies_included") is not None
            else "not yet confirmed."
        )
    )
    checks = list(values.get("count_checks", {}).values())
    if checks:
        status = (
            "All recorded selection totals balance."
            if all(v is True for v in checks)
            else "Some selection totals require reconciliation or additional records."
        )
        parts.append("**Count reconciliation:** " + status)
    reasons = values.get("exclusion_reasons", {})
    if reasons:
        parts.append(
            "#### Reasons for full-text exclusion\n\n"
            + "\n".join(f"- {reason}: {number}" for reason, number in reasons.items())
        )
    return "\n\n".join(parts)


def appraisal_summary(notes, papers):
    titles = {p["id"].rsplit("/", 1)[-1]: p.get("title") or "Article" for p in papers}
    parts = [
        "## Appraisal questions for scientific review",
        "These questions are automated suggestions for the reviewer, not validated risk-of-bias ratings.",
    ]
    for pid, entry in notes.items():
        parts.append("### " + titles.get(pid, "Article awaiting metadata"))
        if entry.get("notes"):
            parts.append("\n".join("- " + str(note) for note in entry["notes"]))
        if entry.get("error"):
            parts.append(
                "Appraisal suggestions could not be generated. Review this article manually; technical details are retained in the audit files."
            )
    if not notes:
        parts.append("No appraisal suggestions are available yet.")
    return "\n\n".join(parts) + "\n\n"


def table_results(table, row_indices):
    """Resolve a merged label only when its PDF geometry spans the current row."""
    rows, boxes = table["cells"], table["cell_bboxes"]
    displayed = []
    for index in row_indices:
        values = list(rows[index])
        cells = [box for box in boxes[index] if box]
        shortest = min(cells, key=lambda box: box[3] - box[1]) if cells else None
        center = (shortest[1] + shortest[3]) / 2 if shortest else None
        for column, value in enumerate(values):
            if value is not None or center is None:
                continue
            for earlier in range(index - 1, 0, -1):
                box = boxes[earlier][column]
                if box and box[1] <= center < box[3]:
                    values[column] = rows[earlier][column]
                    break
        displayed.append(values)
    headers = [
        value or ("Group / model" if i == 0 else f"Value {i + 1}")
        for i, value in enumerate(rows[0])
    ]
    return markdown_table(headers, displayed)


def render_selection_flow(path, values):
    """Accessible SVG with explicit branches for pending and include decisions."""
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1190" viewBox="0 0 1000 1190" role="img" aria-labelledby="title desc">',
        '<title id="title">PRISMA-oriented search and selection flow</title>',
        '<desc id="desc">Search, screening, retrieval and eligibility counts. Pending decisions and unavailable reports are distinct from exclusions.</desc>',
        '<rect width="1000" height="1190" rx="22" fill="#f6f8fc"/>',
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L0,8 L8,4z" fill="#94a3b8"/></marker></defs>',
        '<text x="45" y="50" fill="#172b4d" font-family="sans-serif" font-size="28" font-weight="700">Search &amp; selection</text>',
        '<text x="45" y="78" fill="#64748b" font-family="sans-serif" font-size="15">PRISMA-oriented reporting · '
        + (
            "Automated draft"
            if values.get("mode") == "automatic"
            else "Review reporting draft"
        )
        + "</text>",
    ]
    palette = {
        "blue": ("#eff6ff", "#2563eb"),
        "violet": ("#f5f3ff", "#7c3aed"),
        "teal": ("#f0fdfa", "#0f766e"),
        "amber": ("#fffbeb", "#b45309"),
        "green": ("#f0fdf4", "#15803d"),
        "slate": ("#f1f5f9", "#475569"),
    }

    def box(x, y, width, title, value, subtitle, tone, height=110):
        bg, color = palette[tone]
        svg.extend(
            [
                f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="14" fill="{bg}" stroke="{color}" stroke-opacity="0.35"/>',
                f'<rect x="{x}" y="{y + 17}" width="5" height="{height - 34}" rx="2" fill="{color}"/>',
                f'<text x="{x + 20}" y="{y + 29}" font-family="sans-serif" font-size="16" font-weight="700" fill="{color}">{escape(title)}</text>',
                f'<text x="{x + 20}" y="{y + 69}" font-family="sans-serif" font-size="{32 if isinstance(value, int) else 20}" font-weight="700" fill="#172b4d">{escape(count(value))}</text>',
            ]
        )
        # Wrap the explanation, including unusually large count values.
        import textwrap

        for index, line in enumerate(
            textwrap.wrap(subtitle, max(20, int((width - 40) / 7.5)))
        ):
            svg.append(
                f'<text x="{x + 20}" y="{y + 93 + index * 17}" font-family="sans-serif" font-size="13" fill="#475569">{escape(line)}</text>'
            )

    def arrow(x1, y1, x2, y2):
        svg.append(
            f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="#94a3b8" stroke-width="2"/>'
        )
        angle = math.atan2(y2 - y1, x2 - x1)
        base_x, base_y = x2 - 9 * math.cos(angle), y2 - 9 * math.sin(angle)
        points = [
            (x2, y2),
            (base_x + 4 * math.sin(angle), base_y - 4 * math.cos(angle)),
            (base_x - 4 * math.sin(angle), base_y + 4 * math.cos(angle)),
        ]
        svg.append(
            '<polygon points="'
            + " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
            + '" fill="#94a3b8"/>'
        )

    main_x, side_x = 45, 655
    stages = [
        (
            115,
            "Identification",
            "records_identified",
            "Records found across the searched sources",
            "blue",
            "Duplicates removed",
            "duplicates_removed",
            "Removed before screening",
            "slate",
        ),
        (
            280,
            "Titles & abstracts",
            "records_screened",
            "Records examined for relevance",
            "violet",
            "Screening exclusions",
            "records_excluded",
            "Excluded at title / abstract review",
            "slate",
        ),
        (
            445,
            "Full-text retrieval",
            "reports_retrieved",
            f"Full texts available · {count(values.get('reports_sought'))} sought",
            "teal",
            "Full texts unavailable",
            "reports_not_retrieved",
            "Access gaps, not scientific exclusions",
            "amber",
        ),
        (
            610,
            "Eligibility assessment",
            "reports_assessed",
            "Reports checked against the review criteria",
            "violet",
            "Full-text exclusions",
            "reports_excluded",
            "Exclusion reasons recorded separately",
            "slate",
        ),
    ]
    for (
        y,
        title,
        key,
        subtitle,
        tone,
        side_title,
        side_key,
        side_subtitle,
        side_tone,
    ) in stages:
        box(main_x, y, 510, title, values.get(key), subtitle, tone)
        box(
            side_x,
            y,
            300,
            side_title,
            values.get(side_key),
            side_subtitle,
            side_tone,
            height=125,
        )
        arrow(560, y + 54, 645, y + 54)
    for y in (225, 390, 555):
        arrow(300, y + 5, 300, y + 45)
    box(
        45,
        795,
        245,
        "Include recommendations"
        if values.get("mode") == "automatic"
        else "Included reports",
        values.get("reports_included"),
        "Eligibility supported",
        "green",
        125,
    )
    box(
        310,
        795,
        245,
        "Decision pending",
        values.get("eligibility_uncertain"),
        "Retained provisionally",
        "amber",
        125,
    )
    arrow(300, 725, 167, 785)
    arrow(300, 725, 432, 785)
    arrow(167, 925, 280, 970)
    arrow(432, 925, 320, 970)
    box(
        45,
        985,
        510,
        "Evidence extracted",
        values.get("reports_in_synthesis"),
        "Reports with usable source evidence",
        "teal",
        110,
    )
    svg.extend(
        [
            '<text x="655" y="834" font-family="sans-serif" font-size="16" font-weight="700" fill="#172b4d">How to read this diagram</text>',
            '<text x="655" y="866" font-family="sans-serif" font-size="14" fill="#475569">Amber means a decision or access</text>',
            '<text x="655" y="888" font-family="sans-serif" font-size="14" fill="#475569">gap remains. It is not an exclusion.</text>',
            '<text x="655" y="928" font-family="sans-serif" font-size="14" fill="#475569">Extracted evidence can remain</text>',
            '<text x="655" y="950" font-family="sans-serif" font-size="14" fill="#475569">provisional pending eligibility.</text>',
            '<text x="45" y="1135" font-family="sans-serif" font-size="13" fill="#475569">Counts describe reports; independent study counts require confirmation. Reporting does not certify PRISMA compliance.</text>',
            '<text x="45" y="1160" font-family="sans-serif" font-size="12" fill="#64748b">Adapted from the PRISMA 2020 flow diagram · prisma-statement.org · CC BY 4.0</text>',
            "</svg>",
        ]
    )
    path.write_text("".join(svg), encoding="utf-8")
    import pymupdf

    with pymupdf.open(stream="".join(svg).encode(), filetype="svg") as document:
        document[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(
            path.with_suffix(".png")
        )
