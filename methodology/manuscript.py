"""Scientific manuscript presentation; execution diagnostics live in a separate report."""

from agents.writing_agent import saved_section_valid, section_prose
from methodology.presentation import count, markdown_table, table_results


def study_label(paper, pid):
    authors = paper.get("authors") or []
    name = (
        authors[0].split()[-1] + " et al." if authors else paper.get("title", "Study")
    )
    return f"{name} ({paper.get('year') or 'year not reported'}) [{pid}]"


def cited_facts(writing):
    """Only evidence referenced by intact, audited prose can enter summaries."""
    used = {
        key
        for name, section in (writing or {}).get("sections", {}).items()
        if saved_section_valid(section, (writing or {}).get("facts", {}), name)
        for paragraph in section.get("paragraphs", [])
        for key in paragraph["evidence_ids"]
    }
    return {
        key: value
        for key, value in (writing or {}).get("facts", {}).items()
        if key in used
    }


def scientific_tables(papers, included, writing):
    """Tables use only source facts cited by accepted prose; never guessed attributes."""
    metadata = {p["id"].rsplit("/", 1)[-1]: p for p in papers}
    facts = cited_facts(writing)
    used = set(facts)
    characteristics, outcomes = [], []
    for record in included:
        pid = record["paper_id"]
        selected = [
            f
            for f in facts.values()
            if f["paper_id"] == pid and f["scope"] == "primary"
        ]

        def excerpt(kinds, selected=selected):
            candidates = [
                f
                for f in selected
                if f["kind"] in kinds and not f["text"].lstrip().startswith("|")
            ]
            if not candidates:
                return "NR"
            fact = candidates[0]
            text = fact["text"]
            # Explicit ellipsis, no synthetic dataset or metric interpretation.
            if len(text) > 420:
                text = text[:417].rsplit(" ", 1)[0] + "…"
            return text + (f" (PDF p. {fact['page']})" if fact.get("page") else "")

        label = study_label(metadata.get(pid, {}), pid)
        characteristics.append(
            [label, excerpt(["research_objective"]), excerpt(["methodology"])]
        )
        outcomes.append([label, excerpt(["main_findings"])])
    tables = [
        "**Table 1. Characteristics and evaluation methods of the included reports.**\n\n"
        + markdown_table(
            ["Study", "Research objective", "Methods and evaluation context"],
            characteristics,
        )
        + "\n\n*Note.* Cells reproduce source-reported information cited in the manuscript. NR = not reported in the available cited evidence. An ellipsis indicates a shortened excerpt; PDF pages refer to the source article.",
        "**Table 2. Principal findings reported in the included studies.**\n\n"
        + markdown_table(["Study", "Reported outcome and evaluation context"], outcomes)
        + "\n\n*Note.* Values, units and confidence intervals are retained as reported. Outcomes from different evaluation settings are not head-to-head comparisons. No pooled estimate is presented.",
    ]
    for record in included:
        pid = record["paper_id"]
        for table in record.get("source_tables", []):
            rows = sorted(
                {
                    row["row_index"]
                    for row in record.get("numerical_results", [])
                    if row["table_id"] == table["table_id"]
                    and f"{pid}:{table['table_id']}:R{row['row_index']}" in used
                }
            )
            if rows:
                tables.append(
                    f"**Table {len(tables) + 1}. Numerical outcomes reported by {study_label(metadata.get(pid, {}), pid)}.**\n\n"
                    + table_results(table, rows)
                    + f"\n\n*Note.* Source column headings and units are retained without conversion. Only numerical rows cited by the verified manuscript are reproduced. Source: [{pid}], PDF p. {table['page']}."
                )
    return tables


def build_manuscript(
    topic,
    protocol,
    papers,
    evidence,
    flow,
    notes,
    references,
    narrative=None,
    writing=None,
    mode="automatic",
    assessments=None,
):
    included = [r for r in evidence if r.get("eligibility_status") == "include"]
    provisional = [
        r for r in evidence if r.get("eligibility_status") not in ("include", "exclude")
    ]
    if not included:
        writing = None
    scientific = {
        s: section_prose(writing, s)
        for s in ("introduction", "results", "discussion", "conclusion", "abstract")
    }
    sources = ", ".join(protocol.get("sources", [])) or "Sources not recorded"
    dates = f"{protocol.get('date_from') or 'no lower date limit'} to {protocol.get('date_to') or 'no upper date limit'}"
    tables = scientific_tables(papers, included, writing) if included else None
    conclusion = scientific["conclusion"] or (
        "No report currently has an include recommendation. No scientific conclusion can be drawn."
        if not included
        else "A verified scientific conclusion is not yet available."
    )
    limitations = [
        f"The synthesis is based on {len(included)} included reports. Its coverage is bounded by the searched sources and the retrieval limit of {protocol.get('max_records_per_query', 'an unrecorded number of')} records per query; it should not be interpreted as an exhaustive account of the literature.",
        "The interpretation is restricted to the populations, datasets, outcome definitions and evaluation settings reported in the included evidence. No pooled effect or general effectiveness ranking was established.",
    ]
    metadata = {p["id"].rsplit("/", 1)[-1]: p for p in papers}
    reported_limitations = []
    seen = set()
    for fact in cited_facts(writing).values():
        pid = fact["paper_id"]
        if (
            fact["kind"] == "limitations"
            and fact["scope"] == "primary"
            and pid not in seen
        ):
            reported_limitations.append(
                f"{study_label(metadata.get(pid, {}), pid)} reported the following study limitation: "
                f"“{fact['text']}” [{pid}; PDF p. {fact.get('page') or 'not available'}]"
            )
            seen.add(pid)
    if flow.get("reports_not_retrieved"):
        limitations.append(
            f"Full texts were unavailable for {count(flow['reports_not_retrieved'])} sought reports, which may affect the coverage of the synthesis."
        )
    if provisional:
        limitations.append(
            f"Eligibility remained unresolved for {len(provisional)} reports; these were not used to support the primary conclusions."
        )
    if mode == "automatic":
        limitations.append(
            "A formal risk-of-bias assessment and certainty-of-evidence grading were not completed; the strength of the conclusions must be interpreted accordingly."
        )
    parts = [
        f"# {topic.strip().rstrip('.')}: a systematic review draft",
        "*AI-assisted manuscript. Final scientific review by the authors is pending.*",
        "## Abstract",
        f"**Objective:** To address the research question: {protocol['research_question']}",
        f"**Methods:** Literature searches covered {sources} ({dates}). Records were deduplicated, screened against prespecified criteria and assessed in full text. Findings were synthesised narratively; no meta-analysis was performed.",
        f"**Results:** {count(flow.get('records_identified'))} records were identified, {count(flow.get('reports_retrieved'))} full texts were retrieved, and {len(included)} reports contributed to the primary synthesis."
        + (
            f" {len(provisional)} reports remained provisional and were not used for primary conclusions."
            if provisional
            else ""
        ),
        "**Scientific findings:** "
        + (
            scientific["abstract"]
            or "A verified abstract narrative is not yet available."
        ),
        "**Conclusions:** The findings are specific to the evaluation settings of the included reports. No pooled estimate or overall effectiveness ranking was established.",
        "## Introduction",
        scientific["introduction"]
        or "Scientific introduction awaiting a source-verified writing pass.",
        f"The objective of this review is to address: {protocol['research_question']}",
        "## Methods",
        "### Eligibility criteria",
        "Inclusion criteria:\n\n"
        + "\n".join("- " + c for c in protocol.get("inclusion_criteria", [])),
        "Exclusion criteria:\n\n"
        + "\n".join("- " + c for c in protocol.get("exclusion_criteria", [])),
        "### Information sources and search strategy",
        f"Searches covered {sources}. The publication date range was {dates}. Retrieval was capped at {protocol.get('max_records_per_query', 'an unrecorded number of')} records per query. Exact queries and execution dates are provided in the accompanying technical and reproducibility report.",
        "### Selection and data collection",
        (
            "Study selection, source evidence and appraisal were reviewed by human reviewers in the guided workflow. "
            if mode == "guided"
            else "Selection and extraction were AI-assisted. Title/abstract screening used two blinded prompt roles of the same model, followed by full-text assessment; these are not independent human reviews. "
        )
        + "Eligibility criteria were applied before primary synthesis. Reports with unresolved eligibility were kept separate. Unavailable full texts were recorded as access gaps rather than scientific exclusions. Source citations and PDF page references were retained.",
        "### Appraisal and synthesis",
        (
            f"Study appraisal used {protocol.get('appraisal_name', 'the protocol rubric')}; recorded domain judgments are provided in the accompanying report. "
            if mode == "guided"
            else "No formal risk-of-bias or certainty-of-evidence grading was completed. "
        )
        + protocol.get("synthesis_plan", "A narrative synthesis was planned.")
        + " Results were interpreted within each study's evaluation setting. No pooled effect was calculated.",
        "## Results",
        "### Study selection",
        f"The search identified {count(flow.get('records_identified'))} records. After deduplication, {count(flow.get('unique_records'))} unique records remained. Of {count(flow.get('reports_retrieved'))} retrieved full texts, {len(included)} reports entered the primary synthesis. Figure 1 summarises selection.",
        "![Study selection flow](prisma_flow.png)",
        "*Figure 1. Flow of record identification, screening and full-text selection.* Access failures, exclusions and unresolved eligibility are shown separately. Adapted from the PRISMA 2020 flow diagram.",
        "### Study characteristics",
        "The characteristics and evaluation methods of included reports are summarised in Table 1.",
        tables[0]
        if tables
        else "No eligible source evidence is available for a characteristics table.",
        "### Findings",
        scientific["results"]
        or "No verified scientific results narrative is available yet.",
        "Principal reported findings and their evaluation context are presented in Table 2."
        if tables
        else "",
        tables[1] if tables else "",
        *(tables[2:] if tables else []),
        "## Discussion",
        scientific["discussion"]
        or "No source-audited comparative narrative is available for the currently eligible evidence.",
        "### Interpretation across studies",
        "The findings are interpreted within the evaluation settings of the included reports. Numerical differences between studies do not, by themselves, establish comparative superiority. The evidence presented here does not provide a pooled estimate or an overall ranking of approaches.",
        "## Limitations",
        "### Limitations reported in the included studies"
        if reported_limitations
        else "",
        "\n\n".join(reported_limitations),
        "### Limitations of this review",
        "\n\n".join(limitations),
        "## Conclusion",
        conclusion,
        "Taken together, these reports support conclusions confined to their respective study settings. Broader applicability and comparative effectiveness require evidence beyond the estimates summarised here."
        if included
        else "",
        "## Declarations",
        "### AI assistance",
        "AI assistance was used for review preparation. The accompanying technical and reproducibility report documents the tools, generation settings, validation procedure and audit trail. This manuscript remains subject to final author verification.",
        f"Registration: {protocol.get('registration', 'Not reported')}. Funding: {protocol.get('funding', 'Not reported')}. Conflicts of interest: {protocol.get('conflicts', 'Not reported')}.",
        "## References",
        references or "No source references are available.",
    ]
    return "\n\n".join(part for part in parts if part) + "\n"
