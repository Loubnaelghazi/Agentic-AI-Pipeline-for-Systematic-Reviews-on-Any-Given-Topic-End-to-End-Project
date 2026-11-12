"""Render an extractive evidence report without introducing model-generated claims."""

import html

from agents.grounding import validate_record
from methodology.presentation import table_results


def synthesize_evidence(topic: str, evidence: list[dict]) -> str:
    if not evidence:
        raise ValueError("No evidence available for synthesis.")
    lines = [
        "## Research question",
        html.escape(topic),
        "## Evidence scope",
        (
            f"This evidence digest covers {len(evidence)} full-text reports. "
            "Study eligibility and relevance require human assessment. "
            "The excerpts below are source quotations; quotation matching does not "
            "verify scientific accuracy or correct attribution of cited work. "
            "Only human-approved excerpts may support an approved review; raw extractions remain unreviewed."
        ),
    ]
    for record in evidence:
        claims = validate_record(record)
        passages = {p["passage_id"]: p for p in record["supporting_passages"]}
        lines.append(f"## {record['paper_id']}")
        reviewed = record.get("human_reviewed", False)
        if record.get("eligibility_status"):
            lines.append(
                f"Eligibility: {record['eligibility_status']} (machine proposal)."
            )
        for kind, heading in [
            ("research_objective", "Candidate objective excerpts — unreviewed"),
            ("methodology", "Candidate methodology excerpts — unreviewed"),
            ("main_findings", "Candidate finding excerpts — unreviewed"),
            ("limitations", "Candidate limitation excerpts — attribution unverified"),
        ]:
            if reviewed:
                heading = {
                    "research_objective": "Human-reviewed research objective",
                    "methodology": "Human-reviewed methodology",
                    "main_findings": "Human-reviewed findings",
                    "limitations": "Human-reviewed author-reported limitations",
                }[kind]
            lines.append(f"### {heading}")
            numeric_quotes = {
                r.get("quote") for r in record.get("numerical_results", [])
            }
            selected = [
                c
                for c in claims
                if c["kind"] == kind
                and not (kind == "main_findings" and c["quote"] in numeric_quotes)
            ]
            if not selected:
                lines.append(
                    "No human-approved excerpt is available for this field. This is a gap in approved evidence, not an author-reported limitation."
                    if reviewed
                    else "Not found in the retrieved excerpts. This is a gap in extraction, not an author-reported limitation."
                )
            for claim in selected:
                passage = passages[claim["passage_id"]]
                start, end = passage.get("page_start"), passage.get("page_end")
                location = f"PDF p. {start}" if start else "page unavailable"
                if start and end != start:
                    location += f"–{end}"
                lines.append(
                    f"> {html.escape(claim['quote'])}\n\n[{record['paper_id']}:{claim['passage_id']}; {location}]"
                )
        if record.get("rejected_claims"):
            lines.append(
                f"{len(record['rejected_claims'])} proposed quotations were rejected by source matching; see evidence.json."
            )
        tables = {t["table_id"]: t for t in record.get("source_tables", [])}
        if record.get("numerical_results"):
            lines.append(
                "### Numerical table results — source cells, AI audited; human review required"
            )
            for table_id, table in tables.items():
                rows = [
                    r["row_index"]
                    for r in record["numerical_results"]
                    if r["table_id"] == table_id
                ]
                if rows:
                    lines.append(f"#### Results — PDF page {table['page']}")
                    lines.append(table_results(table, rows))
        if record.get("table_extraction_issues"):
            lines.append(
                "### Table extraction gaps\n\n"
                + "\n".join(
                    "- " + html.escape(issue)
                    for issue in record["table_extraction_issues"]
                )
                + "\n\nThese are extraction gaps, not evidence that results are absent."
            )
    lines += [
        "## Synthesis boundary",
        (
            "No cross-study effectiveness ranking, pooled estimate, or generalization is made. "
            "Those conclusions require human-verified study eligibility, comparable outcomes, and evidence appraisal."
        ),
    ]
    return "\n\n".join(lines) + "\n"
