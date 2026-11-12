"""Explicit human confirmation between user-visible review phases."""

import json
import uuid
from datetime import UTC, datetime

from agents.writing_agent import writing_status
from methodology.appraisal import appraisal_queue
from methodology.protocol import load_protocol
from storage.human_review import (
    digest,
    pending,
    read_json,
    review_queue,
    signatures,
    write_status,
)
from storage.review_manager import get_review_path, write_json
from workflow.progress import WorkflowPaused

PHASES = {
    "retrieval": "Search results",
    "save": "Screening",
    "full_text_screening": "Full-text eligibility",
    "extraction": "Evidence review",
    "appraisal": "Study appraisal",
    "quality": "Report",
}
GATES = {
    "save": "screening",
    "full_text_screening": "eligibility",
    "extraction": "evidence",
}


class ConfirmationRequired(WorkflowPaused):
    pass


def await_confirmation(state, stage):
    if stage not in PHASES:
        return
    review_id = state["review_id"]
    queue = review_queue(review_id)
    state["human_review_signatures"] = signatures(review_id, queue)
    state["appraisal_signature"] = json.dumps(
        appraisal_queue(review_id, queue["included_papers"]), sort_keys=True
    )
    state["reporting_signature"] = digest(
        read_json(get_review_path(review_id) / "outputs/prisma_checklist.json", {})
    )
    state.update(
        status="awaiting_step_confirmation",
        awaiting_confirmation={
            "stage": stage,
            "title": PHASES[stage],
            "token": uuid.uuid4().hex,
            "protocol_fingerprint": state.get("protocol_fingerprint"),
        },
    )
    write_json(get_review_path(state["review_id"]) / "workflow_state.json", state)
    raise ConfirmationRequired()


def confirm_step(review_id, token, reviewer):
    root = get_review_path(review_id)
    state = read_json(root / "workflow_state.json", {})
    current = state.get("awaiting_confirmation") or {}
    if (
        state.get("status") != "awaiting_step_confirmation"
        or not token
        or current.get("token") != token
    ):
        raise ValueError(
            "This step changed or was already confirmed. Refresh the review."
        )
    protocol = load_protocol(review_id)
    if (
        not protocol
        or not protocol.get("approval")
        or protocol["fingerprint"] != state.get("protocol_fingerprint")
    ):
        raise ValueError(
            "The protocol changed. Approve it and resume the workflow before confirming results."
        )
    if not reviewer.strip():
        raise ValueError("Enter your reviewer name before confirming.")
    if current["stage"] == "quality" and not writing_status(review_id)["ready"]:
        raise ValueError(
            "Scientific writing is incomplete. Resume writing before confirming the report."
        )
    queue = review_queue(review_id)
    gate = GATES.get(current["stage"])
    if gate and pending(queue, gate):
        raise ValueError("Finish the pending decisions before confirming this step.")
    if current["stage"] == "appraisal" and any(
        not a["assessment"]
        for a in appraisal_queue(review_id, queue["included_papers"])
    ):
        raise ValueError("Finish the pending study assessments before confirming.")
    event = {
        **current,
        "reviewer": reviewer.strip(),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    history = read_json(root / "outputs/step_confirmations.json", [])
    # Persist the event first; a failed state write is recoverable without duplicate events.
    if not any(e["token"] == token for e in history):
        write_json(root / "outputs/step_confirmations.json", [*history, event])
    state.update(status="ready_to_continue", awaiting_confirmation=None)
    write_json(root / "workflow_state.json", state)
    write_status(review_id, state["status"], False)
    return event
