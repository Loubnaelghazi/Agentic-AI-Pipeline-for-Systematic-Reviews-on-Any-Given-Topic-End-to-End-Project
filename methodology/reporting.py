"""Auditable manuscript artifacts; unknown counts and unassessed checklist items stay explicit."""

import csv
import io
import re
from collections import Counter
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from methodology.citations import readable_citations
from methodology.docx import write_document
from methodology.presentation import render_selection_flow
from methodology.protocol import load_protocol
from storage.human_review import read_json
from storage.review_manager import get_review_path, write_json

PRISMA_SOURCE = "https://www.prisma-statement.org/prisma-2020-checklist"
ITEMS = [
    ("1", "Title"),
    ("2", "Abstract"),
    ("3", "Rationale"),
    ("4", "Objectives"),
    ("5", "Eligibility"),
    ("6", "Sources"),
    ("7", "Search strategies"),
    ("8", "Selection process"),
    ("9", "Collection process"),
    ("10a", "Outcomes"),
    ("10b", "Other data"),
    ("11", "Study appraisal"),
    ("12", "Effect measures"),
    *[
        (f"13{c}", title)
        for c, title in zip(
            "abcdef",
            [
                "Synthesis eligibility",
                "Data preparation",
                "Displays",
                "Synthesis methods",
                "Heterogeneity",
                "Sensitivity",
            ],
            strict=True,
        )
    ],
    ("14", "Reporting bias methods"),
    ("15", "Certainty methods"),
    ("16a", "Selection counts"),
    ("16b", "Excluded reports"),
    ("17", "Study characteristics"),
    ("18", "Study bias results"),
    ("19", "Individual results"),
    *[
        (f"20{c}", title)
        for c, title in zip(
            "abcd",
            [
                "Synthesis groups",
                "Statistical synthesis",
                "Heterogeneity results",
                "Sensitivity results",
            ],
            strict=True,
        )
    ],
    ("21", "Reporting bias results"),
    ("22", "Certainty results"),
    *[
        (f"23{c}", title)
        for c, title in zip(
            "abcd",
            [
                "Interpretation",
                "Evidence limitations",
                "Process limitations",
                "Implications",
            ],
            strict=True,
        )
    ],
    ("24a", "Registration"),
    ("24b", "Protocol access"),
    ("24c", "Amendments"),
    ("25", "Support"),
    ("26", "Conflicts"),
    ("27", "Materials access"),
]


def csv_file(path, rows, fields):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(output.getvalue(), encoding="utf-8")


def flow_data(review_id, queue, appraisals=None):
    root = get_review_path(review_id)
    out = root / "outputs"
    papers = read_json(root / "papers.json", [])
    raw = read_json(out / "retrieved_records.json", None)
    duplicates = read_json(out / "duplicates.json", None)
    all_outcomes = read_json(out / "full_text.json", [])
    selected = {
        item["paper_id"]
        for item in queue["items"]
        if item["stage"] == "screening"
        and (
            item["decision"]["decision"]
            if item["decision"]
            else item["automated_decision"]
        )
        == "include"
    }
    outcomes = [item for item in all_outcomes if item["paper_id"] in selected]
    screens = [i for i in queue["items"] if i["stage"] == "screening"]
    excluded = sum(
        (i["decision"]["decision"] if i["decision"] else i["automated_decision"])
        == "exclude"
        for i in screens
    )
    full = [i for i in queue["items"] if i["stage"] == "eligibility" and i["decision"]]
    reasons = Counter(
        i["decision"]["reason"] for i in full if i["decision"]["decision"] == "exclude"
    )
    values = {
        "records_identified": len(raw) if raw is not None else None,
        "duplicates_removed": len(duplicates) if duplicates is not None else None,
        "unique_records": len(papers),
        "records_screened": sum("screening" in p for p in papers),
        "records_excluded": excluded,
        "screening_unresolved": sum(
            i["required"] and not i["decision"] for i in screens
        ),
        "reports_sought": len(outcomes),
        "historical_acquisitions_outside_current_selection": len(all_outcomes)
        - len(outcomes),
        "reports_not_retrieved": sum(o["status"] != "retrieved" for o in outcomes),
        "reports_retrieved": sum(o["status"] == "retrieved" for o in outcomes),
        "reports_assessed": len(full),
        "eligibility_uncertain": sum(
            i["stage"] == "eligibility" and not i["decision"] for i in queue["items"]
        ),
        "reports_excluded": sum(reasons.values()),
        "exclusion_reasons": dict(reasons),
        "reports_included": len(queue["included_papers"]),
        "studies_included": None,
        "note": "Report counts are not automatically unique-study counts. Legacy identification counts remain unknown.",
    }
    study_ids = [
        (item.get("assessment") or {}).get("study_id") for item in (appraisals or [])
    ]
    if len(study_ids) == len(queue["included_papers"]) and all(study_ids):
        values["studies_included"] = len(set(study_ids))
    values["count_checks"] = {
        "deduplication_balances": values["records_identified"]
        == values["unique_records"] + values["duplicates_removed"]
        if values["records_identified"] is not None
        and values["duplicates_removed"] is not None
        else None,
        "acquisition_balances": values["reports_sought"]
        == values["reports_retrieved"] + values["reports_not_retrieved"],
    }
    write_json(out / "prisma_flow.json", values)
    render_selection_flow(out / "prisma_flow.svg", values)
    return values


def bibliography(papers):
    references, bib = [], []
    for paper in papers:
        pid = paper["id"].split("/")[-1]
        title = paper.get("title") or "Title unavailable"
        authors = paper.get("authors") or []
        year = paper.get("year") or "Year unavailable"
        doi = paper.get("doi") or ""
        link = (
            doi
            if doi.startswith("http")
            else (
                "https://doi.org/" + doi
                if doi
                else paper.get("landing_url") or paper["id"]
            )
        )
        references.append(
            f"- [{pid}] {', '.join(authors) or 'Authors unavailable'}. {title}. {year}. {link}"
        )

        def clean(value):
            return str(value).replace("{", "").replace("}", "").replace("\\", " ")

        bib.append(
            f"@misc{{{pid},\n  title = {{{clean(title)}}},\n  author = {{{clean(' and '.join(authors))}}},\n  year = {{{clean(paper.get('year') or '')}}},\n  doi = {{{clean(doi.removeprefix('https://doi.org/'))}}},\n  url = {{{clean(link)}}}\n}}"
        )
    return "\n".join(references), "\n\n".join(bib)


def manuscript_path(review_id):
    from methodology.runtime import settings

    name = (
        "automatic_review.md"
        if settings(review_id)["mode"] == "automatic"
        else "literature_review.md"
    )
    return get_review_path(review_id) / "outputs" / name


def checklist(review_id):
    root = get_review_path(review_id)
    out = root / "outputs"
    old = read_json(out / "prisma_checklist.json", {})
    path = manuscript_path(review_id)
    report = path.read_text() if path.exists() else ""
    from storage.human_review import digest

    fingerprint = digest(report)
    previous = (
        {i["id"]: i for i in old.get("items", [])}
        if old.get("report_fingerprint") == fingerprint
        else {}
    )
    items = [
        previous.get(
            code,
            {
                "id": code,
                "topic": title,
                "status": "requires_human_review",
                "location": "",
                "reason": "",
                "reviewer": "",
            },
        )
        for code, title in ITEMS
    ]
    document = {
        "source": PRISMA_SOURCE,
        "report_fingerprint": fingerprint,
        "compliance_claimed": False,
        "items": items,
    }
    write_json(out / "prisma_checklist.json", document)
    return document


def review_checklist_item(
    review_id, item_id, status, location, reason, reviewer, fingerprint
):
    if (
        status not in ("reported", "not_applicable", "missing")
        or not reviewer.strip()
        or (status != "reported" and not reason.strip())
    ):
        raise ValueError(
            "A valid status and reviewer are required; explain missing or not-applicable items"
        )
    if status == "reported" and not location.strip():
        raise ValueError("Reported items require a manuscript location")
    if not manuscript_path(review_id).exists():
        raise ValueError("Generate a manuscript before assessing its reporting")
    document = checklist(review_id)
    if document["report_fingerprint"] != fingerprint:
        raise ValueError("Manuscript changed; refresh the checklist")
    item = next((i for i in document["items"] if i["id"] == item_id), None)
    if not item:
        raise ValueError("Unknown checklist item")
    item.update(status=status, location=location, reason=reason, reviewer=reviewer)
    root = get_review_path(review_id)
    history = read_json(root / "outputs/prisma_checklist_history.json", [])
    history.append(
        {
            **item,
            "report_fingerprint": fingerprint,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
    write_json(root / "outputs/prisma_checklist_history.json", history)
    write_json(root / "outputs/prisma_checklist.json", document)
    from methodology.runtime import settings

    if settings(review_id)["mode"] == "automatic":
        # Checklist ratings do not rewrite the manuscript or claim compliance.
        quality_path = root / "outputs/automatic_quality.json"
        quality = read_json(
            quality_path, {"passed": False, "issues": [], "recommendations": []}
        )
        pending_items = sum(
            i["status"] in ("missing", "requires_human_review")
            for i in document["items"]
        )
        quality["prisma_checklist_pending"] = pending_items
        issue = "PRISMA reporting checklist needs human review."
        quality["issues"] = [i for i in quality["issues"] if i != issue]
        if pending_items:
            quality["issues"].append(issue)
        write_json(quality_path, quality)
    else:
        write_json(
            root / "outputs/review_status.json",
            {
                "status": "reporting_review_changed_resume_required",
                "report_current": False,
            },
        )
    return document


def write_docx(path, text, figure_path=None, *, scientific=False):
    write_document(path, text, figure_path, scientific=scientific)


def export_technical_report(review_id, appendix, papers, mode):
    """Operational limitations and source audits never replace scientific limitations."""
    from agents.writing_agent import writing_status
    from config import model_config
    from methodology.presentation import markdown_table

    out = get_review_path(review_id) / "outputs"
    from methodology.runtime import settings

    config = model_config()
    runtime = settings(review_id)
    config.update(
        llm=runtime.get("model") or config.get("llm"),
        thinking=runtime.get("thinking", config.get("thinking")),
        temperature=runtime.get("temperature", config.get("temperature")),
    )
    writing = writing_status(review_id)
    trace = read_json(out / "execution_trace.json", [])
    text = (
        "\n\n".join(
            [
                "# Technical and reproducibility report",
                "This document describes the AI-assisted review process. The scientific manuscript is provided separately.",
                "## Generation environment",
                markdown_table(
                    ["Setting", "Recorded value"],
                    [
                        ["Review mode", mode],
                        *[
                            [key, config.get(key, "Not recorded")]
                            for key in (
                                "llm",
                                "embedding",
                                "num_ctx",
                                "thinking",
                                "temperature",
                                "pipeline_version",
                            )
                        ],
                    ],
                ),
                "## Technical limitations",
                "Model outputs can misattribute cited work, omit findings or introduce unsupported claims. Source matching verifies presence, not scientific validity. Writer and auditor can share the same underlying model, so their errors may be correlated. Automated appraisal suggestions are not validated risk-of-bias ratings. Human scientific evaluation remains necessary.",
                "## Writing and validation",
                f"Scientific sections passing automated checks: {writing['completed_sections']} of {writing['total_sections']}. Status: {writing['status']}.",
                "\n".join("- " + issue for issue in writing.get("issues", []))
                or "No unresolved writing issues were recorded at export.",
                "## Execution trace",
                markdown_table(
                    ["Stage", "Outcome", "Duration (s)"],
                    [
                        [
                            row.get("stage", ""),
                            row.get("outcome", ""),
                            round(row["elapsed_seconds"], 2)
                            if isinstance(row.get("elapsed_seconds"), (int, float))
                            else "Not recorded",
                        ]
                        for row in trace
                    ],
                ),
                "## Audit files",
                "Detailed decisions, retrieval passages, extraction checkpoints, model changes and source fingerprints are available in the accompanying JSON/CSV artifacts. Genuine human approvals remain separate from machine proposals.",
                appendix,
            ]
        )
        + "\n"
    )
    text = readable_citations(text, papers)
    (out / "technical_report.md").write_text(text, encoding="utf-8")
    write_docx(out / "technical_report.docx", text)
    return text


def export_review(review_id, queue, evidence, appraisals, digest_text):
    root = get_review_path(review_id)
    out = root / "outputs"
    document = load_protocol(review_id)
    protocol = document["protocol"]
    papers = [
        p
        for p in read_json(root / "papers.json", [])
        if p["id"].split("/")[-1] in queue["included_papers"]
    ]
    flow = flow_data(review_id, queue, appraisals)
    references, bib = bibliography(papers)
    (out / "references.bib").write_text(bib)
    assessments = {a["paper_id"]: a["assessment"] for a in appraisals}
    rows = []
    for record in evidence:
        pid = record["paper_id"]
        assessment = assessments.get(pid) or {}
        fields = assessment.get("characteristics", {})
        row = {"paper_id": pid, "appraisal": assessment.get("overall", "Not assessed")}
        row.update(
            {
                field: (fields.get(field, {}).get("value") or "Not reported/confirmed")
                for field in protocol["extraction_fields"]
            }
        )
        for field in protocol["extraction_fields"]:
            entry = fields.get(field, {})
            row[field + "_quote"] = entry.get("quote", "")
            support = entry.get("support") or {}
            row[field + "_page"] = support.get("page_start") or "Unavailable"
        rows.append(row)
    csv_file(
        out / "evidence_table.csv",
        rows,
        [
            "paper_id",
            "appraisal",
            *[
                column
                for field in protocol["extraction_fields"]
                for column in (field, field + "_quote", field + "_page")
            ],
        ],
    )
    csv_file(
        out / "evidence_map.csv",
        [
            {
                "paper_id": e["paper_id"],
                **{
                    kind: sum(c["kind"] == kind for c in e["claims"])
                    for kind in (
                        "research_objective",
                        "methodology",
                        "main_findings",
                        "limitations",
                    )
                },
            }
            for e in evidence
        ],
        [
            "paper_id",
            "research_objective",
            "methodology",
            "main_findings",
            "limitations",
        ],
    )
    csv_file(
        out / "meta_analysis_template.csv",
        [
            {
                "paper_id": p["id"].split("/")[-1],
                "study_id": (assessments.get(p["id"].split("/")[-1]) or {}).get(
                    "study_id", ""
                ),
            }
            for p in papers
        ],
        [
            "paper_id",
            "study_id",
            "outcome",
            "effect_measure",
            "effect",
            "standard_error",
            "comparison_group",
            "human_verified",
        ],
    )
    width = max(700, 180 + len(protocol["extraction_fields"]) * 105)
    height = 100 + len(rows) * 42
    matrix = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><rect width="100%" height="100%" fill="white"/><text x="20" y="25" font-family="sans-serif">Human-confirmed evidence coverage</text>'
    ]
    for column, field in enumerate(protocol["extraction_fields"]):
        matrix.append(
            f'<text x="{160 + column * 105}" y="55" font-family="sans-serif" font-size="9">{escape(field)}</text>'
        )
    for index, row in enumerate(rows):
        y = 70 + index * 42
        matrix.append(
            f'<text x="20" y="{y + 19}" font-family="sans-serif" font-size="12">{escape(row["paper_id"])}</text>'
        )
        for column, field in enumerate(protocol["extraction_fields"]):
            fill = "#35634c" if row[field] != "Not reported/confirmed" else "#e7eae3"
            matrix.append(
                f'<rect x="{160 + column * 105}" y="{y}" width="90" height="27" fill="{fill}"/>'
            )
    matrix.append("</svg>")
    (out / "evidence_map.svg").write_text("".join(matrix))
    from agents.writing_agent import writing_packet
    from methodology.manuscript import build_manuscript

    primary = [{**record, "eligibility_status": "include"} for record in evidence]
    writing = read_json(out / "scientific_manuscript.json", {})
    packet = writing_packet(review_id, protocol, primary, assessments, mode="guided")
    if writing.get("input_fingerprint") != packet["input_fingerprint"]:
        writing = None
    report = build_manuscript(
        (root / "topic.txt").read_text(),
        protocol,
        papers,
        primary,
        {**flow, "mode": "guided", "reports_in_synthesis": len(primary)},
        {},
        references,
        writing=writing,
        mode="guided",
        assessments=assessments,
    )
    appendix = "\n\n## Appendix A — Human-approved source evidence\n\n" + re.sub(
        r"(?m)^(#{1,5}) ", r"#\1 ", digest_text
    )
    appendix += "\n\n## Appendix B — Human study appraisal\n\n" + "\n\n".join(
        "### "
        + next(
            (
                p.get("title", "Article")
                for p in papers
                if p["id"].rsplit("/", 1)[-1] == pid
            ),
            "Article",
        )
        + "\n\nOverall judgement: "
        + str(value.get("overall", "Not assessed"))
        + ". "
        + value.get("rationale", "")
        + "\n\n"
        + "\n".join(
            "- "
            + domain["domain_id"]
            + ": "
            + domain["judgement"]
            + ". "
            + domain.get("rationale", "")
            for domain in value.get("domains", [])
        )
        for pid, value in assessments.items()
    )
    export_technical_report(review_id, appendix, papers, "guided")
    report = readable_citations(report, read_json(root / "papers.json", []))
    (out / "literature_review.md").write_text(report, encoding="utf-8")
    write_docx(
        out / "literature_review.docx", report, out / "prisma_flow.png", scientific=True
    )
    checklist(review_id)
    return report
