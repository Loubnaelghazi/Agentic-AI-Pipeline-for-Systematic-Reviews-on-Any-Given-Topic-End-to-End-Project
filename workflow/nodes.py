"""Review stages. Imports of model clients are deferred until needed."""

import json
import logging
import re

from agents.grounding import EVIDENCE_VERSION, validate_record
from methodology.appraisal import appraisal_queue
from methodology.protocol import load_protocol, require_protocol, strategies
from methodology.reporting import checklist, export_review
from storage.human_review import (
    approved_evidence,
    digest,
    pending,
    read_json,
    review_queue,
    validate_record_source,
)
from storage.review_manager import archive_outputs, get_review_path, write_json
from workflow.progress import WorkflowPaused
from workflow.progress import progress as report_progress

logger = logging.getLogger(__name__)


def output(state, name):
    path = get_review_path(state["review_id"]) / "outputs" / name
    path.parent.mkdir(exist_ok=True)
    return path


def search_strategy(state):
    protocol = require_protocol(state["review_id"])
    queries = strategies(protocol)
    write_json(output(state, "search_strategy.json"), queries)
    return {"search_query": protocol.research_question, "search_strategies": queries}


def retrieval(state):
    from tools.search import retrieve

    result = retrieve(require_protocol(state["review_id"]), state["search_strategies"])
    for key, filename in (
        ("raw_records", "retrieved_records.json"),
        ("duplicates", "duplicates.json"),
        ("search_log", "search_log.json"),
    ):
        write_json(output(state, filename), result[key])
    if not result["papers"] and any(event["error"] for event in result["search_log"]):
        raise RuntimeError(
            "All configured searches failed or produced no retrievable records; inspect search_log.json"
        )
    return {"papers": result["papers"], "search_log": result["search_log"]}


def screening(state):
    from agents.screening_agent import dual_screen

    protocol = require_protocol(state["review_id"])
    fingerprint = load_protocol(state["review_id"])["fingerprint"]
    papers = state["papers"]
    path = get_review_path(state["review_id"]) / "papers.json"
    cached = {item["id"]: item for item in read_json(path, [])}
    progress_path = output(state, "screening_progress.json")
    progress = read_json(progress_path, {})
    for index, paper in enumerate(papers):
        report_progress(
            state["review_id"],
            "screening",
            index,
            len(papers),
            f"Screening paper {index + 1} of {len(papers)}: {paper.get('title', paper['id'])}",
        )
        item = cached.get(paper["id"], paper)
        if (
            item.get("screening", {}).get("protocol_fingerprint") == fingerprint
            and len(item["screening"].get("reviews", [])) == 2
        ):
            papers[index] = item
            continue
        identity = digest(
            {
                "protocol": fingerprint,
                "id": paper["id"],
                "title": paper.get("title"),
                "abstract": paper.get("abstract"),
            }
        )
        previous = progress.get(paper["id"], {})
        partial = (
            previous.get("reviews", [])
            if previous.get("fingerprint") == identity
            else []
        )

        def persist(reviews, paper_id=paper["id"], identity=identity):
            progress[paper_id] = {"fingerprint": identity, "reviews": reviews}
            write_json(progress_path, progress)

        papers[index] = dual_screen(
            protocol, paper, fingerprint, previous=partial, on_review=persist
        )
        write_json(path, papers)
    return {"papers": papers}


def save(state):
    write_json(get_review_path(state["review_id"]) / "papers.json", state["papers"])
    return {}


def review_gate(state, stage):
    queue = review_queue(state["review_id"])
    write_json(output(state, "human_review_queue.json"), queue)
    waiting = pending(queue, stage)
    update = {
        "status": f"awaiting_{stage}_review" if waiting else "running",
        "pending_review_items": [item["item_id"] for item in waiting],
    }
    if waiting:
        print(
            f"Human {stage} review required: {len(waiting)} item(s). "
            f"Run: uv run python human_review.py {state['review_id']}",
            flush=True,
        )
    return queue, update


def screening_review(state):
    queue, update = review_gate(state, "screening")
    decisions = {
        item["paper_id"]: item["decision"]
        for item in queue["items"]
        if item["stage"] == "screening" and item["decision"]
    }
    papers = read_json(
        get_review_path(state["review_id"]) / "papers.json", state["papers"]
    )
    effective = []
    for paper in papers:
        decision = decisions.get(paper["id"].split("/")[-1])
        effective.append(
            {
                **paper,
                "automated_screening": paper.get("screening"),
                "screening": {
                    "decision": decision["decision"],
                    "reason": decision["reason"],
                    "reviewer": decision["reviewer"],
                },
            }
            if decision
            else paper
        )
    return {**update, "papers": effective}


def eligibility_review(state):
    queue, update = review_gate(state, "eligibility")
    return {**update, "eligible_paper_ids": queue["included_papers"]}


def evidence_review(state):
    queue, update = review_gate(state, "evidence")
    available = {
        item["paper_id"] for item in state.get("evidence", []) if "error" not in item
    }
    if set(queue["included_papers"]) - available or queue["invalid_evidence"]:
        raise ValueError(
            "Included studies require valid evidence extraction before evidence review"
        )
    reviewed = approved_evidence(queue, state.get("evidence", []))
    if not update["pending_review_items"]:
        write_json(output(state, "approved_evidence.json"), reviewed)
    return {**update, "approved_evidence": reviewed}


def download(state):
    from tools.pdf_downloader import download_paper

    folder = get_review_path(state["review_id"]) / "papers"
    previous = read_json(output(state, "full_text.json"), [])
    existing = {item["paper_id"]: item for item in previous}
    outcomes = list(previous)
    selected = [
        p
        for p in state["papers"]
        if p.get("screening", {}).get("decision") == "include"
    ]
    for index, paper in enumerate(selected):
        report_progress(
            state["review_id"],
            "download",
            index,
            len(selected),
            f"Retrieving full text {index + 1} of {len(selected)}",
        )
        if paper.get("screening", {}).get("decision") != "include":
            continue
        paper_id = paper["id"].split("/")[-1]
        if paper_id in existing:
            cached = existing[paper_id]
            if (
                cached["status"] == "unavailable"
                or (folder / f"{paper_id}.txt").exists()
            ):
                continue
        try:
            result = download_paper(paper, output_dir=folder)
            existing[paper_id] = {
                "paper_id": paper_id,
                "status": "retrieved" if result else "unavailable",
            }
        except Exception as error:
            logger.exception("Full-text retrieval failed for %s", paper_id)
            existing[paper_id] = {
                "paper_id": paper_id,
                "status": "unavailable",
                "error": str(error),
            }
        outcomes = list(existing.values())
        write_json(output(state, "full_text.json"), outcomes)
    write_json(output(state, "full_text.json"), outcomes)
    return {"full_text": outcomes}


def ingestion(state):
    from rag.ingest import ingest_papers

    if state.get("eligible_paper_ids"):
        ingest_papers(state["review_id"])
    return {}


def extraction(state):
    from agents.extraction_agent import extract_evidence

    require_protocol(state["review_id"])
    queue = review_queue(state["review_id"])
    if queue["full_text_not_sought"]:
        raise ValueError("Full-text acquisition must be attempted before extraction")
    if pending(queue, "screening") or pending(queue, "eligibility"):
        raise ValueError(
            "Human screening and full-text eligibility review are required before extraction"
        )
    eligible = queue["included_papers"]
    path = output(state, "evidence.json")
    previous = json.loads(path.read_text()) if path.exists() else []
    if state.get("model_config", {}).get(
        "extraction_version"
    ) != EVIDENCE_VERSION and any(
        item.get("evidence_version") != EVIDENCE_VERSION and "error" not in item
        for item in previous
    ):
        archive_outputs(state["review_id"])
    cached = {}
    for item in previous:
        try:
            validate_record_source(state["review_id"], item)
        except (KeyError, ValueError, OSError, RuntimeError):
            continue
        cached[item["paper_id"]] = item
    records = []
    all_records = {item["paper_id"]: item for item in previous}
    for item in state.get("full_text", []):
        if item["status"] != "retrieved" or item["paper_id"] not in eligible:
            continue
        paper_id = item["paper_id"]
        report_progress(
            state["review_id"],
            "extraction",
            len(records),
            len(eligible),
            f"Extracting evidence from {paper_id}",
        )
        print(f"Extracting {paper_id}", flush=True)
        try:
            record = cached.get(paper_id) or extract_evidence(
                state["review_id"], paper_id
            )
        except WorkflowPaused:
            raise
        except Exception as error:
            logger.exception("Evidence extraction failed for %s", paper_id)
            record = {"paper_id": paper_id, "error": str(error)}
        records.append(record)
        all_records[paper_id] = record
        write_json(path, list(all_records.values()))
    write_json(path, list(all_records.values()))
    return {"evidence": records}


def synthesis(state):
    from agents.synthesis_agent import synthesize_evidence

    require_protocol(state["review_id"])
    queue = review_queue(state["review_id"])
    if queue["full_text_not_sought"]:
        raise ValueError(
            "Full-text acquisition must be attempted before report generation or QA"
        )
    if any(pending(queue, stage) for stage in ("screening", "eligibility", "evidence")):
        raise ValueError(
            "Human screening, eligibility and evidence decisions are required before synthesis"
        )
    raw = read_json(output(state, "evidence.json"), [])
    if set(queue["included_papers"]) - {
        item["paper_id"] for item in raw if "error" not in item
    }:
        raise ValueError("Included studies require completed evidence extraction")
    evidence = approved_evidence(queue, raw)
    write_json(output(state, "approved_evidence.json"), evidence)
    body = (
        synthesize_evidence(state["topic"], evidence)
        if evidence
        else "No full-text studies were approved for inclusion. No scientific conclusions are generated."
    )
    assessments = appraisal_queue(state["review_id"], queue["included_papers"])
    if any(not item["assessment"] for item in assessments):
        raise ValueError("Complete study appraisal before synthesis")
    from agents.writing_agent import WRITER_VERSION, write_manuscript

    primary = [{**r, "eligibility_status": "include"} for r in evidence]
    writing = write_manuscript(
        state["review_id"],
        require_protocol(state["review_id"]).model_dump(mode="json"),
        primary,
        {i["paper_id"]: i["assessment"] for i in assessments},
        mode="guided",
    )
    write_json(output(state, "scientific_manuscript.json"), writing)
    state["scientific_writer_version"] = WRITER_VERSION
    report = export_review(state["review_id"], queue, evidence, assessments, body)
    output(state, "literature_review.md").write_text(report, encoding="utf-8")
    return {"report": report, "scientific_writer_version": WRITER_VERSION}


def quality(state):
    from agents.critic_agent import review_report

    require_protocol(state["review_id"])
    queue = review_queue(state["review_id"])
    if queue["full_text_not_sought"]:
        raise ValueError(
            "Full-text acquisition must be attempted before report generation or QA"
        )
    if any(pending(queue, stage) for stage in ("screening", "eligibility", "evidence")):
        raise ValueError("Human review is incomplete; resume the workflow before QA")
    valid = approved_evidence(queue, read_json(output(state, "evidence.json"), []))
    result = (
        review_report(state["topic"], valid, state["report"])
        if valid
        else {"passed": False, "issues": ["No usable evidence"], "recommendations": []}
    )
    ids = {item["paper_id"] for item in valid}
    referenced = set(
        re.findall(
            r"\[((?:W\d+|P\d+|A[a-f0-9]+))(?::[^\]]*|;[^\]]*)?\]", state["report"]
        )
    )
    # The exported manuscript uses numbered reader citations; provenance IDs
    # remain in the evidence artifact rather than the displayed prose.
    numbered = [
        p["id"].rsplit("/", 1)[-1]
        for p in state["papers"]
        if p["id"].rsplit("/", 1)[-1] in queue["included_papers"]
    ]
    for match in re.finditer(r"\[(\d+)(?:;\s*PDF p\. [\d, ]+)?\]", state["report"]):
        number = int(match[1])
        if 1 <= number <= len(numbered):
            referenced.add(numbered[number - 1])
    unknown = referenced - ids
    from agents.writing_agent import writing_status

    writing = writing_status(state["review_id"])
    issues = list(result["issues"]) + writing["issues"]
    if not writing["ready"]:
        issues.append(
            "Scientific manuscript writing is incomplete; regenerate the unverified sections."
        )
        result["passed"] = False
    for record in valid:
        try:
            claims = validate_record(record, state["review_id"])
            if not claims:
                issues.append(f"{record['paper_id']}: no verified evidence quotations")
            if record.get("rejected_claims"):
                issues.append(
                    f"{record['paper_id']}: proposed quotations failed source matching"
                )
            if record.get("missing_fields"):
                issues.append(
                    f"{record['paper_id']}: incomplete evidence fields: {record['missing_fields']}"
                )
        except (KeyError, ValueError) as error:
            issues.append(f"{record.get('paper_id')}: {error}")
    paper_ids = [paper.get("id") for paper in state["papers"]]
    if any(not paper_id for paper_id in paper_ids):
        issues.append("Retrieved records have missing paper IDs")
    if len(set(paper_ids)) != len(paper_ids):
        issues.append("Retrieved records contain duplicate paper IDs")
    if unknown:
        issues.append(f"Unknown paper IDs: {sorted(unknown)}")
    missing = ids - referenced
    if missing:
        issues.append(f"Evidence papers not referenced in report: {sorted(missing)}")
    if len(ids) != len(valid):
        issues.append("Duplicate evidence paper IDs")
    if any("error" in item for item in state["evidence"]):
        issues.append("Evidence extraction failures remain")
    uncertain = len(pending(queue, "screening"))
    if uncertain:
        issues.append(f"{uncertain} uncertain screening decisions require human review")
    require_protocol(state["review_id"])
    appraisals = appraisal_queue(state["review_id"], queue["included_papers"])
    if any(not item["assessment"] for item in appraisals):
        issues.append("Incomplete study appraisal")
    log = read_json(output(state, "search_log.json"), [])
    if not log or any(item.get("error") or item.get("truncated") for item in log):
        issues.append("Search coverage is incomplete or legacy provenance is missing")
    if any(
        len(p.get("screening", {}).get("reviews", [])) != 2 for p in state["papers"]
    ):
        issues.append("Dual screening is incomplete")
    reporting = checklist(state["review_id"])
    if any(
        item["status"] in ("missing", "requires_human_review")
        for item in reporting["items"]
    ):
        issues.append("PRISMA reporting checklist needs human review")
    result.update(passed=bool(result["passed"] and not issues), issues=issues)
    write_json(output(state, "quality_review.json"), result)
    stats = {
        "retrieved_records": len(state["papers"]),
        "screened_records": sum("screening" in p for p in state["papers"]),
        "uncertain_records": uncertain,
        "automated_uncertain_records": sum(
            item.get("automated_decision") == "uncertain"
            for item in queue["items"]
            if item["stage"] == "screening"
        ),
        "full_text_reports_sought": len(state.get("full_text", [])),
        "full_text_reports_retrieved": sum(
            i["status"] == "retrieved" for i in state.get("full_text", [])
        ),
        "evidence_records": len(valid),
        "full_text_eligible_studies": len(queue["included_papers"]),
        "final_included_studies": None,
        "human_approved_quotes": sum(len(item["claims"]) for item in valid),
        "source_matched_quotes": sum(
            len(item.get("claims", []))
            for item in state["evidence"]
            if item["paper_id"] in queue["included_papers"] and "error" not in item
        ),
        "human_rejected_quotes": sum(
            item["decision"]["decision"] == "reject"
            for item in queue["items"]
            if item["stage"] == "evidence" and item.get("decision")
        ),
        "full_text_excluded_reports": sum(
            item["decision"]["decision"] == "exclude"
            for item in queue["items"]
            if item["stage"] == "eligibility" and item.get("decision")
        ),
        "rejected_quotes": sum(len(item.get("rejected_claims", [])) for item in valid),
    }
    write_json(output(state, "review_statistics.json"), stats)
    return {"quality_review": result}


def appraisal(state):
    from agents.appraisal_agent import propose_appraisal

    queue = review_queue(state["review_id"])
    require_protocol(state["review_id"])
    raw = read_json(output(state, "evidence.json"), [])
    approved = approved_evidence(queue, raw)
    existing = read_json(output(state, "appraisal_proposals.json"), {})
    items = appraisal_queue(state["review_id"], queue["included_papers"])
    for index, item in enumerate(items):
        report_progress(
            state["review_id"],
            "appraisal",
            index,
            len(items),
            f"Preparing appraisal for {item['paper_id']}",
        )
        if (
            item["assessment"]
            or existing.get(item["paper_id"], {}).get("fingerprint")
            == item["fingerprint"]
        ):
            continue
        record = next(
            record for record in approved if record["paper_id"] == item["paper_id"]
        )
        existing[item["paper_id"]] = {
            "fingerprint": item["fingerprint"],
            "proposal": propose_appraisal(require_protocol(state["review_id"]), record),
        }
        write_json(output(state, "appraisal_proposals.json"), existing)
    return {}


def appraisal_review(state):
    queue = review_queue(state["review_id"])
    items = appraisal_queue(state["review_id"], queue["included_papers"])
    waiting = [i["paper_id"] for i in items if not i["assessment"]]
    if waiting:
        print(f"Study appraisal required: {waiting}", flush=True)
    return {
        "status": "awaiting_appraisal_review" if waiting else "running",
        "pending_review_items": waiting,
    }


def full_text_screening(state):
    from agents.full_text_agent import DECISION_VERSION
    from agents.screening_agent import full_text_proposal
    from config import model_config

    protocol = require_protocol(state["review_id"])
    queue = review_queue(state["review_id"])
    path = output(state, "eligibility_proposals.json")
    proposals = read_json(path, {})
    items = [
        i
        for i in queue["items"]
        if i["stage"] == "eligibility" and not i.get("decision")
    ]
    for index, item in enumerate(items):
        report_progress(
            state["review_id"],
            "full_text_screening",
            index,
            len(items),
            f"Assessing full text {index + 1} of {len(items)}",
        )
        if item["stage"] != "eligibility" or item.get("decision"):
            continue
        if (
            proposals.get(item["paper_id"], {}).get("fingerprint")
            == item["fingerprint"]
            and proposals[item["paper_id"]].get("proposal", {}).get("decision_version")
            == DECISION_VERSION
            and proposals[item["paper_id"]].get("proposal", {}).get("model_config")
            == model_config()
        ):
            continue
        proposal = full_text_proposal(
            protocol, item["paper_id"], get_review_path(state["review_id"]) / "papers"
        )
        proposals[item["paper_id"]] = {
            "fingerprint": item["fingerprint"],
            "proposal": proposal,
        }
        write_json(path, proposals)
    return {}
