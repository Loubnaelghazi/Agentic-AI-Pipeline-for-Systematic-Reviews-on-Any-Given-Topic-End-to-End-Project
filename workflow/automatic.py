"""Unattended preliminary drafts with a single, explicit final-result decision.

Machine proposals never create human protocol, evidence or appraisal approvals.
"""

import hashlib
import json
from datetime import UTC, datetime
from time import perf_counter

from agents.full_text_agent import DECISION_VERSION
from agents.grounding import validate_record
from agents.semantic_validation import SCIENTIFIC_VERSION
from agents.writing_agent import (
    WRITER_VERSION,
    write_manuscript,
    writing_packet,
    writing_status,
)
from config import (
    OLLAMA_AUDIT_REASONING,
    OLLAMA_MODEL,
    OLLAMA_REASONING,
    OLLAMA_TEMPERATURE,
    model_config,
)
from methodology.automatic_reporting import (
    REPORTING_VERSION,
    export_automatic_reporting,
)
from methodology.protocol import Protocol, load_protocol, save_protocol, strategies
from methodology.runtime import settings, year_bounds
from storage.human_review import (
    digest,
    read_json,
    source_fingerprint,
    validate_record_source,
)
from storage.review_manager import get_review_path, write_json
from workflow.progress import WorkflowPaused, progress

STAGES = [
    "search_strategy",
    "retrieval",
    "screening",
    "save",
    "download",
    "full_text_screening",
    "ingestion",
    "extraction",
    "appraisal",
    "synthesis",
    "quality",
]


def result_fingerprint(review_id):
    root = get_review_path(review_id)
    report = root / "outputs/automatic_review.md"
    if not report.exists():
        return None
    records = read_json(root / "outputs/evidence.json", [])
    protocol = load_protocol(review_id)
    reporting = read_json(root / "outputs/prisma_flow.json", {})
    reporting_artifacts = (
        {
            name: read_json(root / "outputs" / name, None)
            for name in (
                "prisma_flow.json",
                "search_strategy.json",
                "retrieved_records.json",
                "duplicates.json",
            )
        }
        if reporting.get("mode") == "automatic" and reporting.get("reporting_version")
        else {}
    )
    return digest(
        {
            "scientific_version": SCIENTIFIC_VERSION,
            "eligibility_decision_version": DECISION_VERSION,
            "scientific_writer_version": WRITER_VERSION,
            **(
                {"reporting_artifacts": reporting_artifacts}
                if reporting_artifacts
                else {}
            ),
            "report": hashlib.sha256(report.read_bytes()).hexdigest(),
            "sources": {
                r["paper_id"]: source_fingerprint(root / "papers", r["paper_id"])
                for r in records
            },
            "protocol": protocol.get("fingerprint") if protocol else None,
            "generation_settings": read_json(root / "workflow_state.json", {}).get(
                "automatic_generation_settings"
            ),
            "evidence": records,
            "machine_artifacts": {
                name: read_json(root / "outputs" / name, None)
                for name in (
                    "automatic_eligibility.json",
                    "automatic_appraisal.json",
                    "scientific_manuscript.json",
                    "search_log.json",
                )
            },
            "papers": read_json(root / "papers.json", []),
        }
    )


def extraction_failures(review_id):
    root = get_review_path(review_id)
    state = read_json(root / "workflow_state.json", {})
    eligible = state.get("eligible_paper_ids", [])
    records = {r["paper_id"]: r for r in read_json(root / "outputs/evidence.json", [])}
    failures = []
    for pid in eligible:
        record = records.get(pid)
        if not record or "error" in record or not record.get("claims"):
            failures.append(pid)
    return failures


def result(review_id):
    root = get_review_path(review_id)
    value = read_json(root / "outputs/automatic_result.json", None)
    if value is None:
        return None
    fingerprint = result_fingerprint(review_id)
    current = value["fingerprint"] == fingerprint
    events = read_json(root / "outputs/final_decisions.json", [])
    decision = (
        next((e for e in reversed(events) if e["fingerprint"] == fingerprint), None)
        if current
        else None
    )
    failures = extraction_failures(review_id)
    eligibility = read_json(root / "outputs/automatic_eligibility.json", {})
    records = [
        {
            **r,
            "eligibility_status": eligibility.get(r["paper_id"], {}).get(
                "recommendation", "uncertain"
            ),
        }
        for r in read_json(root / "outputs/evidence.json", [])
        if "error" not in r
    ]
    protocol = load_protocol(review_id)
    try:
        packet = (
            writing_packet(review_id, protocol["protocol"], records)
            if protocol
            else None
        )
        writing = writing_status(review_id, packet)
    except (ValueError, KeyError, OSError):
        writing = {
            "ready": False,
            "status": "stale",
            "completed_sections": 0,
            "total_sections": 5,
            "issues": ["Source evidence must be repaired before scientific writing."],
        }
    return {
        **value,
        "current": current,
        "decision": decision,
        "ready": current and not failures and writing["ready"],
        "writing": writing,
        "failed_paper_ids": failures,
    }


def decide_final(review_id, fingerprint, decision, reviewer, note=""):
    if settings(review_id)["mode"] != "automatic":
        raise ValueError("Final-only decisions belong to automated drafts.")
    state = read_json(get_review_path(review_id) / "workflow_state.json", {})
    if state.get("status") not in (
        "awaiting_final_review",
        "accepted_automatic_draft",
        "rejected_automatic_draft",
    ):
        raise ValueError("Wait for the automated draft to finish.")
    value = result(review_id)
    if not value or not value["current"] or value["fingerprint"] != fingerprint:
        raise ValueError(
            "The result or its sources changed. Regenerate before deciding."
        )
    if decision == "accept" and not value["ready"]:
        raise ValueError(
            "Extraction or scientific writing is incomplete. Resolve the reported issues before accepting the draft."
        )
    if decision not in ("accept", "reject") or not reviewer.strip():
        raise ValueError("Choose Accept or Reject and enter your reviewer name.")
    if value["decision"]:
        raise ValueError(
            "This result already has a final decision. Start a new conversation for another run."
        )
    root = get_review_path(review_id)
    event = {
        "fingerprint": fingerprint,
        "decision": decision,
        "reviewer": reviewer.strip(),
        "note": note.strip(),
        "timestamp": datetime.now(UTC).isoformat(),
        "scope": "Acceptance/rejection of the overall automated draft; does not certify individual studies, claims, bias assessments or PRISMA compliance.",
    }
    events = read_json(root / "outputs/final_decisions.json", [])
    write_json(root / "outputs/final_decisions.json", [*events, event])
    state["status"] = (
        "accepted_automatic_draft"
        if decision == "accept"
        else "rejected_automatic_draft"
    )
    write_json(root / "workflow_state.json", state)
    write_json(
        root / "outputs/review_status.json",
        {"status": state["status"], "report_current": True, "mode": "automatic"},
    )
    return event


def run_review(review_id):
    from agents.appraisal_agent import propose_appraisal
    from agents.extraction_agent import extract_evidence
    from agents.planner_agent import propose_protocol
    from agents.screening_agent import dual_screen, full_text_proposal
    from agents.synthesis_agent import synthesize_evidence
    from rag.ingest import ingest_papers
    from tools.pdf_downloader import download_paper
    from tools.search import retrieve

    root = get_review_path(review_id)
    runtime = settings(review_id)
    if runtime["mode"] != "automatic":
        raise ValueError("Automated runner requires Automated draft mode.")
    state = read_json(root / "workflow_state.json", {"completed": [], "errors": []})
    state.setdefault("completed", [])
    state.setdefault("errors", [])
    state.update(
        review_id=review_id,
        review_path=str(root),
        topic=(root / "topic.txt").read_text(),
        mode="automatic",
    )
    existing = result(review_id)
    needs_scientific_upgrade = (
        state.get("scientific_version") != SCIENTIFIC_VERSION
        or state.get("eligibility_decision_version") != DECISION_VERSION
        or state.get("eligibility_audit_reasoning") != OLLAMA_AUDIT_REASONING
    )
    failed_ids = extraction_failures(review_id)
    retry_failed = bool(failed_ids) and "full_text_screening" in state["completed"]
    retry_writing = bool(existing and not existing.get("writing", {}).get("ready"))
    if (
        existing
        and existing["current"]
        and not retry_failed
        and not needs_scientific_upgrade
        and not retry_writing
    ):
        if existing.get("reporting_version") != REPORTING_VERSION:
            upgrade_reporting(review_id)
            return read_json(root / "workflow_state.json", state)
        return state
    state["automatic_generation_settings"] = runtime
    if needs_scientific_upgrade and "full_text_screening" in state["completed"]:
        from storage.review_manager import archive_outputs

        archive_outputs(review_id)
        state["completed"] = [
            s
            for s in state["completed"]
            if STAGES.index(s) < STAGES.index("full_text_screening")
        ]
        write_json(root / "outputs/automatic_appraisal.json", {})
    elif retry_failed:
        from storage.review_manager import archive_outputs

        archive_outputs(review_id)
        state["completed"] = [
            s
            for s in state["completed"]
            if s not in ("extraction", "appraisal", "synthesis", "quality")
        ]
        state["status"] = "running"
        write_json(root / "workflow_state.json", state)
        write_json(
            root / "outputs/review_status.json",
            {"status": "running", "report_current": False, "mode": "automatic"},
        )
        print(
            "Retrying incomplete extraction for: " + ", ".join(failed_ids), flush=True
        )
    elif retry_writing and not retry_failed:
        from storage.review_manager import archive_outputs

        archive_outputs(review_id)
        state["completed"] = [
            s for s in state["completed"] if s not in ("synthesis", "quality")
        ]
    elif existing:
        write_json(root / "outputs/automatic_appraisal.json", {})
        state["completed"] = [
            s for s in state["completed"] if STAGES.index(s) < STAGES.index("ingestion")
        ]
    state["scientific_version"] = SCIENTIFIC_VERSION
    state["eligibility_decision_version"] = DECISION_VERSION
    state["eligibility_audit_reasoning"] = OLLAMA_AUDIT_REASONING
    state["status"] = "running"
    write_json(root / "workflow_state.json", state)

    def out(name):
        return root / "outputs" / name

    def stage(name, callback):
        if name in state["completed"]:
            return
        progress(review_id, name, message=f"Automated draft: {name.replace('_', ' ')}")
        started = perf_counter()
        timestamp = datetime.now(UTC).isoformat()
        outcome = "failed"
        try:
            callback()
            state["completed"].append(name)
            state["status"] = "running"
            write_json(root / "workflow_state.json", state)
            outcome = "completed"
        except WorkflowPaused:
            outcome = "paused"
            raise
        finally:
            trace = read_json(out("execution_trace.json"), [])
            write_json(
                out("execution_trace.json"),
                [
                    *trace,
                    {
                        "stage": name,
                        "started_at": timestamp,
                        "elapsed_seconds": perf_counter() - started,
                        "outcome": outcome,
                        "mode": "automatic",
                        "model_config": runtime,
                    },
                ],
            )

    def plan():
        document = load_protocol(review_id)
        if document and document.get("approval"):
            proposal = Protocol.model_validate(document["protocol"])
        else:
            proposal = propose_protocol(state["topic"])
            proposal.sources = runtime["sources"]
            proposal.max_records_per_query = runtime["max_records"]
            proposal.date_from, proposal.date_to = year_bounds(runtime)
            document = save_protocol(
                review_id,
                proposal.model_dump(mode="json"),
                "Automated planner proposal; not human approved",
            )
        state["protocol_fingerprint"] = document["fingerprint"]
        write_json(out("search_strategy.json"), strategies(proposal))

    def search():
        proposal = Protocol.model_validate(load_protocol(review_id)["protocol"])
        found = retrieve(proposal, read_json(out("search_strategy.json"), {}))
        if not found["papers"] and any(e.get("error") for e in found["search_log"]):
            raise RuntimeError(
                "All searches failed. Check the source errors and retry."
            )
        write_json(root / "papers.json", found["papers"])
        for key, filename in [
            ("raw_records", "retrieved_records.json"),
            ("duplicates", "duplicates.json"),
            ("search_log", "search_log.json"),
        ]:
            write_json(out(filename), found[key])

    def screen():
        papers = read_json(root / "papers.json", [])
        protocol = Protocol.model_validate(load_protocol(review_id)["protocol"])
        for index, paper in enumerate(papers):
            progress(
                review_id,
                "screening",
                index,
                len(papers),
                f"Assessing paper {index + 1} of {len(papers)}",
            )
            if (
                paper.get("screening", {}).get("protocol_fingerprint")
                != state["protocol_fingerprint"]
            ):
                papers[index] = dual_screen(
                    protocol, paper, state["protocol_fingerprint"]
                )
                write_json(root / "papers.json", papers)

    def download():
        papers = [
            p
            for p in read_json(root / "papers.json", [])
            if p.get("screening", {}).get("decision") != "exclude"
        ]
        outcomes = {p["paper_id"]: p for p in read_json(out("full_text.json"), [])}
        for index, paper in enumerate(papers):
            progress(
                review_id,
                "download",
                index,
                len(papers),
                f"Downloading original PDF {index + 1} of {len(papers)}",
            )
            pid = paper["id"].split("/")[-1]
            if pid in outcomes:
                continue
            download_error = None
            try:
                text = download_paper(paper, root / "papers")
            except Exception as error:
                text = None
                download_error = str(error)
            outcomes[pid] = {
                "paper_id": pid,
                "status": "retrieved" if text else "unavailable",
                "method": "automated acquisition",
                "error": download_error,
            }
            write_json(out("full_text.json"), list(outcomes.values()))
        write_json(out("full_text.json"), list(outcomes.values()))

    def eligibility():
        available = [
            p
            for p in read_json(out("full_text.json"), [])
            if p["status"] == "retrieved"
        ]
        proposals = read_json(out("automatic_eligibility.json"), {})
        protocol = Protocol.model_validate(load_protocol(review_id)["protocol"])
        for index, paper in enumerate(available):
            progress(
                review_id,
                "full_text_screening",
                index,
                len(available),
                f"Assessing full text {index + 1} of {len(available)}",
            )
            pid = paper["paper_id"]
            if (
                pid not in proposals
                or proposals[pid].get("scientific_version") != SCIENTIFIC_VERSION
                or proposals[pid].get("decision_version") != DECISION_VERSION
                or proposals[pid].get("model_config") != model_config()
                or proposals[pid].get("audit_reasoning_requested")
                != OLLAMA_AUDIT_REASONING
            ):
                proposals[pid] = full_text_proposal(protocol, pid, root / "papers")
                write_json(out("automatic_eligibility.json"), proposals)
        state["eligible_paper_ids"] = [
            p["paper_id"]
            for p in available
            if proposals[p["paper_id"]].get("recommendation") != "exclude"
        ]

    def extraction():
        records = {r["paper_id"]: r for r in read_json(out("evidence.json"), [])}
        for index, pid in enumerate(state.get("eligible_paper_ids", [])):
            progress(
                review_id,
                "extraction",
                index,
                len(state["eligible_paper_ids"]),
                f"Extracting source quotations {index + 1} of {len(state['eligible_paper_ids'])}",
            )
            record = records.get(pid)
            try:
                if record and "error" not in record:
                    try:
                        validate_record_source(review_id, record)
                    except (ValueError, KeyError, OSError, RuntimeError):
                        record = None
                if (
                    not record
                    or "error" in record
                    or not record.get("claims")
                    or record.get("scientific_version") != SCIENTIFIC_VERSION
                ):
                    record = extract_evidence(review_id, pid)
                if "error" not in record:
                    validate_record_source(review_id, record)
            except WorkflowPaused:
                raise
            except Exception as error:
                record = {"paper_id": pid, "error": str(error)}
            records[pid] = record
            write_json(out("evidence.json"), list(records.values()))
        write_json(out("evidence.json"), list(records.values()))

        failures = extraction_failures(review_id)
        if failures:
            raise RuntimeError(
                "Extraction incomplete for "
                + ", ".join(failures)
                + ". Results were saved. Check Ollama, then Resume to retry only failed papers."
            )

    def appraisal():
        notes = read_json(out("automatic_appraisal.json"), {})
        protocol = Protocol.model_validate(load_protocol(review_id)["protocol"])
        records = read_json(out("evidence.json"), [])
        for index, record in enumerate(records):
            progress(
                review_id,
                "appraisal",
                index,
                len(records),
                f"Preparing appraisal notes {index + 1} of {len(records)}",
            )
            if "error" not in record and record["paper_id"] not in notes:
                try:
                    notes[record["paper_id"]] = propose_appraisal(protocol, record)
                except Exception as error:
                    notes[record["paper_id"]] = {"notes": [], "error": str(error)}
                write_json(out("automatic_appraisal.json"), notes)

    def synthesis():
        eligibility = read_json(out("automatic_eligibility.json"), {})
        evidence = [
            {
                **r,
                "eligibility_status": eligibility.get(r["paper_id"], {}).get(
                    "recommendation", "uncertain"
                ),
            }
            for r in read_json(out("evidence.json"), [])
            if "error" not in r
            and eligibility.get(r["paper_id"], {}).get("recommendation") != "exclude"
        ]
        for record in evidence:
            validate_record_source(review_id, record)
            validate_record(record)
        body = (
            synthesize_evidence(state["topic"], evidence)
            if evidence
            else "No usable full-text evidence was obtained. No scientific conclusions are generated."
        )
        protocol = Protocol.model_validate(load_protocol(review_id)["protocol"])
        writing = write_manuscript(
            review_id, protocol.model_dump(mode="json"), evidence, mode="automatic"
        )
        write_json(out("scientific_manuscript.json"), writing)
        state["scientific_writer_version"] = WRITER_VERSION
        notes = read_json(out("automatic_appraisal.json"), {})
        papers = read_json(root / "papers.json", [])
        refs = "\n".join(
            f"- [{p['id'].split('/')[-1]}] {p.get('title', 'Untitled')} ({p.get('year') or 'year unavailable'}). {p.get('doi') or p.get('landing_url') or p['id']}"
            for p in papers
        )
        report = f"# Automated preliminary literature review\n\n> MACHINE-GENERATED DRAFT. Intermediate protocol, screening, eligibility, evidence categorization and appraisal have not been individually human-validated. Final acceptance concerns the overall draft only. No validated risk-of-bias or PRISMA compliance claim is made.\n\n{body}\n\n## Automated appraisal questions and gaps\n\n{json.dumps(notes, ensure_ascii=False, indent=2)}\n\n## Search and selection limitations\n\nUncertain screening and eligibility proposals were retained provisionally. Source access, search caps and model errors can affect completeness. No pooled effect or validated certainty-of-evidence assessment is generated.\n\n## Retrieved references\n\n{refs}\n"
        export_automatic_reporting(review_id, report)

    def quality():
        log = read_json(out("search_log.json"), [])
        records = read_json(out("evidence.json"), [])
        issues = [
            "Intermediate decisions and appraisal were automated, not human-validated.",
            "Final acceptance does not certify scientific accuracy or PRISMA compliance.",
        ]
        if read_json(out("narrative_proposals.json"), {}).get("rejected_themes"):
            issues.append(
                "Some narrative themes failed evidence validation; inspect narrative_proposals.json."
            )
        if any(e.get("error") or e.get("truncated") for e in log):
            issues.append("Search errors or record limits may affect completeness.")
        if not records or any("error" in r for r in records):
            issues.append("Evidence is missing or some extractions failed.")
        flow = read_json(out("prisma_flow.json"), {})
        if any(check is not True for check in flow.get("count_checks", {}).values()):
            issues.append(
                "PRISMA selection counts need reconciliation; missing provenance is not a zero."
            )
        writing = writing_status(review_id)
        issues.extend(writing["issues"])
        if not writing["ready"]:
            issues.append(
                "Scientific manuscript writing is incomplete; this draft cannot be accepted yet."
            )
        issues.append("PRISMA reporting checklist needs human review.")
        write_json(
            out("automatic_quality.json"),
            {
                "passed": False,
                "issues": issues,
                "recommendations": [
                    "Inspect quoted passages, original PDFs and machine proposals before accepting."
                ],
            },
        )

    stages = [
        ("search_strategy", plan),
        ("retrieval", search),
        ("screening", screen),
        ("save", lambda: None),
        ("download", download),
        ("full_text_screening", eligibility),
        ("ingestion", lambda: ingest_papers(review_id)),
        ("extraction", extraction),
        ("appraisal", appraisal),
        ("synthesis", synthesis),
        ("quality", quality),
    ]
    try:
        for name, callback in stages:
            stage(name, callback)
        fingerprint = result_fingerprint(review_id)
        write_json(
            out("automatic_result.json"),
            {
                "fingerprint": fingerprint,
                "generated_at": datetime.now(UTC).isoformat(),
                "model": OLLAMA_MODEL,
                "thinking": OLLAMA_REASONING,
                "temperature": OLLAMA_TEMPERATURE,
                "scope": "Unvalidated automated draft; final acceptance is not individual evidence approval.",
                "reporting_version": REPORTING_VERSION,
            },
        )
        state["status"] = "awaiting_final_review"
    except WorkflowPaused:
        state["status"] = "paused"
    except Exception as error:
        state["status"] = "failed"
        state["errors"].append(
            {"stage": name, "error": str(error), "time": datetime.now(UTC).isoformat()}
        )
        write_json(root / "workflow_state.json", state)
        write_json(
            out("review_status.json"),
            {"status": "failed", "report_current": False, "mode": "automatic"},
        )
        raise
    write_json(root / "workflow_state.json", state)
    write_json(
        out("review_status.json"),
        {
            "status": state["status"],
            "report_current": state["status"] == "awaiting_final_review",
            "mode": "automatic",
        },
    )
    return state


def upgrade_reporting(review_id):
    """Add reporting to a current completed draft without rerunning search or models."""
    root = get_review_path(review_id)
    existing = result(review_id)
    if not existing or not existing["current"]:
        raise ValueError("Only an unchanged completed automatic draft can be upgraded")
    if existing.get("reporting_version") == REPORTING_VERSION:
        return existing
    from storage.review_manager import archive_outputs

    archive_outputs(review_id)
    export_automatic_reporting(review_id)
    metadata = read_json(root / "outputs/automatic_result.json", {})
    metadata.update(
        fingerprint=result_fingerprint(review_id),
        reporting_version=REPORTING_VERSION,
        reporting_updated_at=datetime.now(UTC).isoformat(),
    )
    write_json(root / "outputs/automatic_result.json", metadata)
    state = read_json(root / "workflow_state.json", {})
    state["status"] = "awaiting_final_review"
    write_json(root / "workflow_state.json", state)
    write_json(
        root / "outputs/review_status.json",
        {
            "status": "awaiting_final_review",
            "report_current": True,
            "mode": "automatic",
        },
    )
    quality_path = root / "outputs/automatic_quality.json"
    quality = read_json(
        quality_path, {"passed": False, "issues": [], "recommendations": []}
    )
    quality["issues"] = list(
        dict.fromkeys(
            [*quality["issues"], "PRISMA reporting checklist needs human review."]
        )
    )
    write_json(quality_path, quality)
    return result(review_id)
