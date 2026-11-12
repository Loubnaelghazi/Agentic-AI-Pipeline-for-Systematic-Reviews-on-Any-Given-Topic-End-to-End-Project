"""PRISMA-oriented reporting for machine drafts, without inventing human approvals."""

import json
import re
from collections import Counter

from methodology.citations import readable_citations
from methodology.manuscript import build_manuscript
from methodology.presentation import (
    appraisal_summary,
    render_selection_flow,
)
from methodology.protocol import load_protocol
from methodology.reporting import (
    bibliography,
    checklist,
    csv_file,
    export_technical_report,
    write_docx,
)
from storage.human_review import read_json, validate_record_source
from storage.review_manager import get_review_path, write_json

REPORTING_VERSION = "scientific-and-technical-v2.2"
MARKER = "<!-- AUTOMATIC PRISMA REPORTING -->"


def automatic_flow(review_id):
    root = get_review_path(review_id)
    out = root / "outputs"
    papers = read_json(root / "papers.json", [])
    raw = read_json(out / "retrieved_records.json", None)
    duplicates = read_json(out / "duplicates.json", None)
    decisions = {
        p["id"].split("/")[-1]: p.get("screening", {}).get("decision") for p in papers
    }
    selected = {
        pid
        for pid, decision in decisions.items()
        if decision in ("include", "uncertain")
    }
    outcomes = {
        p["paper_id"]: p
        for p in read_json(out / "full_text.json", [])
        if p["paper_id"] in selected
    }
    retrieved = {
        pid for pid, outcome in outcomes.items() if outcome["status"] == "retrieved"
    }
    proposals = read_json(out / "automatic_eligibility.json", {})
    assessed = {
        pid
        for pid in retrieved
        if proposals.get(pid, {}).get("recommendation")
        in ("include", "exclude", "uncertain")
    }
    excluded = {
        pid for pid in assessed if proposals[pid]["recommendation"] == "exclude"
    }
    retained = {
        pid for pid in assessed if proposals[pid]["recommendation"] == "include"
    }
    uncertain = assessed - excluded - retained
    reasons = Counter(
        proposals[pid].get("reason") or "No exclusion rationale recorded"
        for pid in excluded
    )
    valid, failures = [], []
    for record in read_json(out / "evidence.json", []):
        if record["paper_id"] not in retained | uncertain:
            continue
        if "error" in record:
            failures.append(record["paper_id"])
            continue
        validate_record_source(review_id, record)
        valid.append(record)
    values = {
        "mode": "automatic",
        "reporting_version": REPORTING_VERSION,
        "records_identified": len(raw) if raw is not None else None,
        "records_by_source": dict(Counter(p.get("source", "unrecorded") for p in raw))
        if raw is not None
        else None,
        "duplicates_removed": len(duplicates) if duplicates is not None else None,
        "unique_records": len(papers),
        "records_screened": sum(
            d in ("include", "exclude", "uncertain") for d in decisions.values()
        ),
        "records_not_screened": sum(
            d not in ("include", "exclude", "uncertain") for d in decisions.values()
        ),
        "records_excluded": sum(d == "exclude" for d in decisions.values()),
        "screening_uncertain_forwarded": sum(
            d == "uncertain" for d in decisions.values()
        ),
        "reports_sought": len(outcomes),
        "reports_not_sought": len(selected - outcomes.keys()),
        "reports_retrieved": len(retrieved),
        "reports_not_retrieved": len(outcomes) - len(retrieved),
        "reports_assessed": len(assessed),
        "reports_not_assessed": len(retrieved - assessed),
        "reports_excluded": len(excluded),
        "exclusion_reasons": dict(reasons),
        "reports_included": len(retained),
        "eligibility_uncertain": len(uncertain),
        "reports_in_synthesis": len({r["paper_id"] for r in valid}),
        "reports_retained_without_usable_extraction": len(
            (retained | uncertain) - {r["paper_id"] for r in valid}
        ),
        "studies_included": None,
        "selection_method": "Machine proposals; uncertain full texts retained provisionally and counted separately.",
        "note": "Reports are not confirmed independent studies. Acquisition and extraction failures are not scientific exclusions. No PRISMA compliance is certified.",
    }
    values["count_checks"] = {
        "deduplication_balances": len(raw) == len(papers) + len(duplicates)
        if raw is not None and duplicates is not None
        else None,
        "screening_balances": values["records_screened"]
        == values["records_excluded"] + len(selected),
        "acquisition_balances": values["reports_sought"]
        == values["reports_retrieved"] + values["reports_not_retrieved"],
        "eligibility_balances": values["reports_assessed"]
        == values["reports_excluded"]
        + values["reports_included"]
        + values["eligibility_uncertain"],
    }
    write_json(out / "prisma_flow.json", values)
    render_flow(out / "prisma_flow.svg", values)
    rows = []
    for pid in sorted(assessed):
        rows.append(
            {
                "paper_id": pid,
                "recommendation": proposals[pid]["recommendation"],
                "reason": proposals[pid].get("reason", ""),
                "origin": "AI proposal; not human adjudication",
            }
        )
    csv_file(
        out / "full_text_decisions.csv",
        rows,
        ["paper_id", "recommendation", "reason", "origin"],
    )
    evidence_rows = []
    for record in valid:
        for claim in record.get("claims", []):
            passage = next(
                p
                for p in record["supporting_passages"]
                if p["passage_id"] == claim["passage_id"]
            )
            evidence_rows.append(
                {
                    "paper_id": record["paper_id"],
                    "kind": claim["kind"],
                    "quote": claim["quote"],
                    "page_start": passage.get("page_start"),
                    "page_end": passage.get("page_end"),
                    "origin": "Source-checked AI selection; not human approved",
                }
            )
    csv_file(
        out / "evidence_table.csv",
        evidence_rows,
        ["paper_id", "kind", "quote", "page_start", "page_end", "origin"],
    )
    numerical_rows = []
    for record in valid:
        tables = {t["table_id"]: t for t in record.get("source_tables", [])}
        for result in record.get("numerical_results", []):
            table = tables[result["table_id"]]
            numerical_rows.append(
                {
                    "paper_id": record["paper_id"],
                    "eligibility": proposals[record["paper_id"]]["recommendation"],
                    "page": table["page"],
                    "table_id": table["table_id"],
                    "row_index": result["row_index"],
                    "headers": json.dumps(table["cells"][0], ensure_ascii=False),
                    "cells": json.dumps(
                        table["cells"][result["row_index"]], ensure_ascii=False
                    ),
                    "preceding_groups": json.dumps(
                        [r[:2] for r in table["cells"][1 : result["row_index"]]],
                        ensure_ascii=False,
                    ),
                    "origin": "Source cells; AI attribution audit; not human approved",
                }
            )
    csv_file(
        out / "numerical_results.csv",
        numerical_rows,
        [
            "paper_id",
            "eligibility",
            "page",
            "table_id",
            "row_index",
            "headers",
            "cells",
            "preceding_groups",
            "origin",
        ],
    )
    return values, valid


def render_flow(path, values):
    render_selection_flow(path, values)


def export_automatic_reporting(review_id, manuscript=None):
    root = get_review_path(review_id)
    out = root / "outputs"
    flow, evidence = automatic_flow(review_id)
    protocol = load_protocol(review_id)["protocol"]
    from agents.synthesis_agent import synthesize_evidence

    proposals = read_json(out / "automatic_eligibility.json", {})
    records = [
        {
            **record,
            "eligibility_status": proposals.get(record["paper_id"], {}).get(
                "recommendation", "uncertain"
            ),
        }
        for record in evidence
    ]
    source_ids = {r["paper_id"] for r in evidence}
    papers = [
        p
        for p in read_json(root / "papers.json", [])
        if p["id"].split("/")[-1] in source_ids
    ]
    refs, bib = bibliography(papers)
    (out / "references.bib").write_text(bib, encoding="utf-8")
    notes = read_json(out / "automatic_appraisal.json", {})
    from agents.writing_agent import writing_packet

    writing = read_json(out / "scientific_manuscript.json", {})
    packet = writing_packet(review_id, protocol, records, mode="automatic")
    if writing.get("input_fingerprint") != packet["input_fingerprint"]:
        writing = None
    manuscript = build_manuscript(
        (root / "topic.txt").read_text(),
        protocol,
        papers,
        records,
        flow,
        notes,
        refs,
        read_json(out / "narrative_proposals.json", {}),
        writing=writing,
        mode="automatic",
    )
    digest = (
        synthesize_evidence((root / "topic.txt").read_text(), records)
        if records
        else "No usable source evidence was obtained."
    )
    digest = re.sub(
        r"(?s)^## Research question.*?(?=## Evidence scope)", "", digest, count=1
    )
    digest = re.sub(r"(?m)^(#{1,5}) ", r"#\1 ", digest)
    appraisal = appraisal_summary(notes, papers).split("\n\n", 1)[1]
    logs = read_json(out / "search_log.json", [])
    from methodology.presentation import count, markdown_table

    search_table = (
        markdown_table(
            ["Source", "Query", "Search date", "Records", "Coverage note"],
            [
                [
                    entry.get("source", "Not recorded"),
                    entry.get("query", "Not recorded"),
                    entry.get("timestamp", "Not recorded"),
                    count(entry.get("records")),
                    "Search error; inspect audit record"
                    if entry.get("error")
                    else (
                        "Result limit reached"
                        if entry.get("truncated")
                        else "No error reported"
                    ),
                ]
                for entry in logs
            ],
        )
        if logs
        else "No executed-search records are available."
    )
    lines = [
        MARKER,
        "## Appendix A — Source-linked evidence and numerical results",
        "Detailed source excerpts and table rows are retained below for verification. They are not a substitute for the manuscript's scientific interpretation.",
        digest,
        "## Appendix B — Appraisal questions for scientific review",
        appraisal,
        "## Appendix C — Search strategy and reporting details",
        "### Executed searches",
        search_table,
        "### Reporting assessment",
        "The reporting checklist requires scientific review. Suggested locations are navigation aids, not verified judgements of PRISMA compliance.",
    ]
    export_technical_report(review_id, "\n\n".join(lines), papers, "automatic")
    report = readable_citations(manuscript, papers)
    (out / "automatic_review.md").write_text(report, encoding="utf-8")
    write_docx(
        out / "automatic_review.docx", report, out / "prisma_flow.png", scientific=True
    )
    document = checklist(review_id)
    locations = {
        "4": "Introduction",
        "5": "Protocol and eligibility criteria",
        "6": "Information sources and search strategy",
        "7": "Executed searches; search_strategy.json",
        "8": "Study selection",
        "16a": "Search and selection; PRISMA selection diagram",
        "16b": "full_text_decisions.csv",
        "17": "Characteristics of the available reports",
        "19": "Findings; Table 2",
        "24a": "Registration, funding and conflicts of interest",
        "25": "Registration, funding and conflicts of interest",
        "26": "Registration, funding and conflicts of interest",
    }
    for item in document["items"]:
        item["suggested_location"] = locations.get(item["id"], "")
    document.update(
        report_kind="automatic_review.md", reporting_version=REPORTING_VERSION
    )
    write_json(out / "prisma_checklist.json", document)
    return flow
