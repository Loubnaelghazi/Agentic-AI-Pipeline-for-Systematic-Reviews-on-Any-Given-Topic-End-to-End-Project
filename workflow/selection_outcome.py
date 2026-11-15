"""Stop empty reviews with a selection record rather than a scientific manuscript."""

from storage.human_review import (
    approved_evidence,
    digest,
    pending,
    read_json,
    review_queue,
)
from storage.review_manager import archive_outputs, get_review_path, write_json
from workflow.progress import WorkflowPaused


class EmptySelection(WorkflowPaused):
    pass


MESSAGES = {
    "no_search_results": "The searches returned no records. Revise the search concepts, sources or date range.",
    "all_screened_out": "No records remain after title and abstract screening. Extraction and scientific writing were not started.",
    "full_texts_unavailable": "None of the retained records has an available full text. This is an access gap, not a scientific exclusion.",
    "no_eligible_reports": "No full-text reports remain eligible under the current decisions. There is no evidence for a scientific synthesis.",
    "eligibility_unresolved": "No full-text report has a supported include recommendation. Resolve uncertain eligibility before scientific writing.",
    "no_approved_evidence": "No source evidence was approved for synthesis. Review the evidence decisions before writing a manuscript.",
}


def selection_reason(state, mode="guided"):
    root = get_review_path(state["review_id"])
    done = set(state.get("completed", []))
    papers = read_json(root / "papers.json", state.get("papers", []))
    if "retrieval" not in done:
        return None
    if not papers:
        return "no_search_results"
    if "save" not in done:
        return None
    queue = review_queue(state["review_id"])
    if mode == "guided":
        if pending(queue, "screening"):
            return None
        selected = {
            i["paper_id"]
            for i in queue["items"]
            if i["stage"] == "screening"
            and (
                i["decision"]["decision"]
                if i.get("decision")
                else i.get("automated_decision")
            )
            == "include"
        }
    else:
        selected = {
            p["id"].rsplit("/", 1)[-1]
            for p in papers
            if p.get("screening", {}).get("decision") in ("include", "uncertain")
        }
    if not selected:
        return "all_screened_out"
    if "download" not in done:
        return None
    outcomes = {
        i["paper_id"]: i for i in read_json(root / "outputs/full_text.json", [])
    }
    # Missing acquisition outcomes are incomplete work, not evidence of unavailability.
    if not selected.issubset(outcomes):
        return None
    retrieved = {pid for pid in selected if outcomes[pid]["status"] == "retrieved"}
    if not retrieved:
        return "full_texts_unavailable"
    if "full_text_screening" not in done:
        return None
    if mode == "guided":
        if pending(queue, "eligibility"):
            return None
        if not queue["included_papers"]:
            return "no_eligible_reports"
        if "extraction" in done and not pending(queue, "evidence"):
            records = read_json(root / "outputs/evidence.json", [])
            if not any(r.get("claims") for r in approved_evidence(queue, records)):
                return "no_approved_evidence"
    else:
        decisions = read_json(root / "outputs/automatic_eligibility.json", {})
        if not retrieved.issubset(decisions):
            return None
        if not any(
            decisions[pid].get("recommendation") == "include" for pid in retrieved
        ):
            return (
                "eligibility_unresolved"
                if any(
                    decisions[pid].get("recommendation") == "uncertain"
                    for pid in retrieved
                )
                else "no_eligible_reports"
            )
    return None


def stop_if_empty(state, mode="guided"):
    reason = selection_reason(state, mode)
    if not reason:
        state["selection_outcome"] = None
        return
    root = get_review_path(state["review_id"])
    out = root / "outputs"
    queue = review_queue(state["review_id"])
    identity = digest(
        {
            "reason": reason,
            "papers": read_json(root / "papers.json", []),
            "decisions": read_json(out / "human_decisions.json", {}),
            "eligibility": read_json(out / "automatic_eligibility.json", {}),
        }
    )
    if read_json(out / "selection_outcome.json", {}).get("fingerprint") != identity:
        from methodology.presentation import markdown_table
        from methodology.reporting import flow_data, write_docx

        archive_outputs(state["review_id"])
        if mode == "automatic":
            from methodology.automatic_reporting import automatic_flow

            flow, _ = automatic_flow(state["review_id"])
        else:
            flow = flow_data(state["review_id"], queue)
        text = (
            "\n\n".join(
                [
                    "# Search and selection outcome",
                    "Research question: " + (root / "topic.txt").read_text().strip(),
                    "## Why the review stopped",
                    MESSAGES[reason],
                    "No scientific findings, appraisal or manuscript are generated from an empty selection.",
                    "## Recorded selection counts",
                    markdown_table(
                        ["Measure", "Count"],
                        [
                            [key.replace("_", " "), flow.get(key)]
                            for key in (
                                "records_identified",
                                "records_excluded",
                                "reports_retrieved",
                                "reports_not_retrieved",
                                "reports_excluded",
                                "reports_included",
                            )
                        ],
                    ),
                    "## Next steps",
                    "Inspect the recorded reasons and access gaps. You may revise the protocol or recorded decisions after reading the sources, obtain accessible full texts, or create a new review with appropriate search settings. No criteria or decisions are changed automatically.",
                ]
            )
            + "\n"
        )
        (out / "selection_report.md").write_text(text, encoding="utf-8")
        write_docx(out / "selection_report.docx", text)
    outcome = {
        "reason": reason,
        "message": MESSAGES[reason],
        "fingerprint": identity,
        "status": "no_evidence",
        "scientific_manuscript_available": False,
    }
    state.update(
        status="no_evidence",
        selection_outcome=outcome,
        awaiting_confirmation=None,
        report=None,
        quality_review=None,
    )
    write_json(out / "selection_outcome.json", outcome)
    write_json(root / "workflow_state.json", state)
    write_json(
        out / "review_status.json",
        {"status": "no_evidence", "report_current": False, "mode": mode},
    )
    raise EmptySelection(MESSAGES[reason])
