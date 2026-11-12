import json
from datetime import UTC, datetime
from itertools import pairwise
from time import perf_counter

from langgraph.graph import END, START, StateGraph

from agents.grounding import EVIDENCE_VERSION
from agents.writing_agent import WRITER_VERSION, writing_status
from config import EMBEDDING_MODEL, OLLAMA_MODEL, OLLAMA_REASONING, OLLAMA_TEMPERATURE
from methodology.appraisal import appraisal_queue
from methodology.protocol import (
    draft_protocol,
    load_protocol,
    require_protocol,
    save_protocol,
)
from storage.human_review import (
    digest,
    read_json,
    review_queue,
    signatures,
    write_status,
)
from storage.review_manager import archive_outputs, get_review_path, write_json
from workflow import nodes
from workflow.confirmations import ConfirmationRequired, await_confirmation
from workflow.progress import WorkflowPaused, progress
from workflow.state import ReviewState

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


def checkpoint(state):
    write_json(get_review_path(state["review_id"]) / "workflow_state.json", state)


def stage(name):
    def execute(state):
        if name in state.get("completed", []):
            print(f"Using completed stage: {name}", flush=True)
            return {}
        print(f"Running: {name}", flush=True)
        progress(
            state["review_id"],
            name,
            message=f"Working on {name.replace(chr(95), chr(32))}",
        )
        started = perf_counter()
        timestamp = datetime.now(UTC).isoformat()
        outcome = "failed"
        try:
            update = getattr(nodes, name)(state)
            complete = list(state.get("completed", [])) + [name]
            # Partial extraction is persisted but must be retried on resume.
            if name == "extraction" and any(
                "error" in item for item in update["evidence"]
            ):
                raise RuntimeError(
                    "Extraction incomplete; see outputs/evidence.json and resume to retry"
                )
            merged = {**state, **update, "completed": complete, "status": "running"}
            checkpoint(merged)
            outcome = "completed"
            await_confirmation(merged, name)
            return {**update, "completed": complete, "status": "running"}
        except ConfirmationRequired:
            outcome = "completed_awaiting_confirmation"
            raise
        except WorkflowPaused:
            outcome = "paused"
            raise
        except Exception as error:
            failed = {
                **state,
                "status": "failed",
                "errors": state.get("errors", [])
                + [
                    {
                        "stage": name,
                        "error": str(error),
                        "time": datetime.now(UTC).isoformat(),
                    }
                ],
            }
            checkpoint(failed)
            raise
        finally:
            path = get_review_path(state["review_id"]) / "outputs/execution_trace.json"
            trace = read_json(path, [])
            trace.append(
                {
                    "stage": name,
                    "started_at": timestamp,
                    "elapsed_seconds": perf_counter() - started,
                    "outcome": outcome,
                    "protocol_fingerprint": state.get("protocol_fingerprint"),
                    "model_config": state.get("model_config", {}),
                }
            )
            write_json(path, trace)

    return execute


def build_graph():
    builder = StateGraph(ReviewState)
    for name in STAGES:
        builder.add_node(name, stage(name))
    for name in (
        "screening_review",
        "eligibility_review",
        "evidence_review",
        "appraisal_review",
    ):
        builder.add_node(name, getattr(nodes, name))
    route = [
        "search_strategy",
        "retrieval",
        "screening",
        "save",
        "screening_review",
        "download",
        "full_text_screening",
        "eligibility_review",
        "ingestion",
        "extraction",
        "evidence_review",
        "appraisal",
        "appraisal_review",
        "synthesis",
        "quality",
    ]
    builder.add_edge(START, route[0])
    for current, following in pairwise(route):
        if current.endswith("_review"):
            builder.add_conditional_edges(
                current,
                lambda state: (
                    "pause"
                    if state.get("status", "").startswith("awaiting_")
                    else "continue"
                ),
                {"pause": END, "continue": following},
            )
        else:
            builder.add_edge(current, following)
    builder.add_edge("quality", END)
    return builder.compile()


graph = build_graph()


def run_review(review_id):
    path = get_review_path(review_id)
    saved = path / "workflow_state.json"
    state = (
        json.loads(saved.read_text())
        if saved.exists()
        else {"completed": [], "errors": []}
    )
    state.update(
        review_id=review_id,
        review_path=str(path),
        topic=(path / "topic.txt").read_text().strip(),
    )
    document = load_protocol(review_id)
    if document is None:
        document = save_protocol(
            review_id,
            draft_protocol(review_id).model_dump(mode="json"),
            "System draft template",
            adopt_existing=(path / "papers.json").exists(),
        )
    if not document.get("approval"):
        state.update(
            status="awaiting_protocol_review",
            pending_review_items=["protocol"],
            protocol=document["protocol"],
        )
        checkpoint(state)
        write_status(review_id, state["status"], False)
        return state
    require_protocol(review_id)
    if (
        state.get("protocol_fingerprint") == document["fingerprint"]
        and state.get("status") == "awaiting_step_confirmation"
        and state.get("awaiting_confirmation")
    ):
        retry_writing = state["awaiting_confirmation"]["stage"] == "quality" and (
            state.get("scientific_writer_version") != WRITER_VERSION
            or not writing_status(review_id)["ready"]
        )
        if not retry_writing:
            return state
        state.update(awaiting_confirmation=None, status="running")
    if state.get("protocol_fingerprint") != document["fingerprint"]:
        archive_outputs(review_id)
        state["awaiting_confirmation"] = None
        state["completed"] = (
            ["search_strategy", "retrieval"]
            if document.get("adopt_existing") and (path / "papers.json").exists()
            else []
        )
        if document.get("adopt_existing"):
            state["papers"] = read_json(path / "papers.json", [])
        state["protocol_fingerprint"] = document["fingerprint"]
    state["protocol"] = document["protocol"]
    state.setdefault(
        "model_config",
        {
            "llm": OLLAMA_MODEL,
            "embedding": EMBEDDING_MODEL,
            "extraction_version": "bounded-passages-v1",
        },
    )
    state["model_config"].update(
        llm=OLLAMA_MODEL, thinking=OLLAMA_REASONING, temperature=OLLAMA_TEMPERATURE
    )
    # Import acquisition outcomes without pretending legacy search/screening met a new protocol.
    if (
        (path / "papers.json").exists()
        and not (path / "outputs/full_text.json").exists()
        and any((path / "papers").glob("*.txt"))
    ):
        imported = [
            {
                "paper_id": paper["id"].split("/")[-1],
                "status": "retrieved"
                if (path / "papers" / (paper["id"].split("/")[-1] + ".txt")).exists()
                else "unavailable",
                "origin": "legacy workspace",
            }
            for paper in read_json(path / "papers.json", [])
            if paper.get("screening", {}).get("decision") == "include"
        ]
        write_json(path / "outputs/full_text.json", imported)
        state["full_text"] = imported
    if state["model_config"].get("extraction_version") != EVIDENCE_VERSION:
        if (
            "extraction" in state.get("completed", [])
            or (path / "outputs" / "evidence.json").exists()
        ):
            archive_outputs(review_id)
            state["completed"] = [
                name
                for name in state["completed"]
                if name not in ("extraction", "synthesis", "quality")
            ]
            for key in ("evidence", "report", "quality_review"):
                state.pop(key, None)
        state["model_config"]["extraction_version"] = EVIDENCE_VERSION
    # Gates run on every invocation, even for legacy completed workflows.
    current_queue = review_queue(review_id)
    current_signatures = signatures(review_id, current_queue)
    prior = state.get("human_review_signatures")
    invalidated = set()
    if state.get("scientific_writer_version") != WRITER_VERSION or (
        "synthesis" in state.get("completed", [])
        and not writing_status(review_id)["ready"]
    ):
        invalidated.update(("synthesis", "quality"))
    if prior is None:
        invalidated.update(("synthesis", "quality"))
    else:
        for gate, first in (
            ("screening", "download"),
            ("eligibility", "extraction"),
            ("evidence", "synthesis"),
        ):
            if prior.get(gate) != current_signatures[gate]:
                invalidated.update(STAGES[STAGES.index(first) :])
    if current_queue["invalid_evidence"]:
        invalidated.update(STAGES[STAGES.index("extraction") :])
    appraisal_signature = json.dumps(
        appraisal_queue(review_id, current_queue["included_papers"]), sort_keys=True
    )
    if state.get("appraisal_signature") != appraisal_signature:
        invalidated.update(("synthesis", "quality"))
    state["appraisal_signature"] = appraisal_signature
    reporting_signature = digest(read_json(path / "outputs/prisma_checklist.json", {}))
    if state.get("reporting_signature") not in (None, reporting_signature):
        invalidated.add("quality")
    if invalidated.intersection(state.get("completed", [])):
        archive_outputs(review_id)
    state["completed"] = [
        name for name in state["completed"] if name not in invalidated
    ]
    if "synthesis" in invalidated:
        state.pop("approved_evidence", None)
        state.pop("report", None)
    if "quality" in invalidated:
        state.pop("quality_review", None)
    if (path / "papers.json").exists():
        state["papers"] = read_json(path / "papers.json", [])
    checkpoint(state)
    write_status(review_id, "running", False)
    try:
        result = graph.invoke(state)
    except ConfirmationRequired:
        result = read_json(path / "workflow_state.json", state)
        write_status(
            review_id,
            "awaiting_step_confirmation",
            "quality" in result.get("completed", []),
        )
        return result
    except WorkflowPaused:
        result = read_json(path / "workflow_state.json", state)
        result["status"] = "paused"
        checkpoint(result)
        write_status(review_id, "paused", False)
        return result
    except Exception:
        write_json(
            path / "outputs" / "review_status.json",
            {"review_id": review_id, "status": "failed", "report_current": False},
        )
        raise
    if not result.get("status", "").startswith("awaiting_"):
        result["status"] = (
            "completed_preliminary"
            if result.get("quality_review", {}).get("passed")
            else "completed_with_issues"
        )
    result["reporting_signature"] = digest(
        read_json(path / "outputs/prisma_checklist.json", {})
    )
    result["human_review_signatures"] = signatures(review_id)
    checkpoint(result)
    write_status(
        review_id,
        result["status"],
        not result["status"].startswith("awaiting_")
        and "synthesis" in result.get("completed", []),
    )
    return result
