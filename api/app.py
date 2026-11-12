"""FastAPI backend for the local research workspace. Run with one Uvicorn worker."""

import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from httpx import HTTPError
from ollama import ResponseError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agents.writing_agent import writing_status
from api.jobs import BusyReview, JobManager
from config import cors_origins
from methodology.appraisal import (
    AppraisalSubmission,
    appraisal_queue,
    appraisal_source,
    check_appraisal_quote,
    save_appraisal,
)
from methodology.protocol import (
    Protocol,
    approve_protocol,
    draft_protocol,
    load_protocol,
    save_protocol,
)
from methodology.reporting import review_checklist_item
from methodology.runtime import (
    installed_models,
    model_controls,
    reasoning_value,
    save_configuration,
    save_thinking,
    settings,
    validate_configuration_choices,
)
from storage import review_manager
from storage.human_review import (
    decision_log,
    pending,
    read_json,
    record_decision,
    review_queue,
)
from storage.review_manager import create_review, get_review_path, write_json
from workflow.confirmations import confirm_step

ARTIFACTS = {
    "technical_report.md",
    "technical_report.docx",
    "step_confirmations.json",
    "chat_messages.json",
    "runtime_settings.json",
    "automatic_review.md",
    "automatic_review.docx",
    "full_text_decisions.csv",
    "narrative_proposals.json",
    "scientific_manuscript.json",
    "model_migrations.json",
    "full_text_progress.json",
    "automatic_result.json",
    "automatic_quality.json",
    "automatic_eligibility.json",
    "automatic_appraisal.json",
    "final_decisions.json",
    "literature_review.md",
    "evidence.json",
    "approved_evidence.json",
    "quality_review.json",
    "review_statistics.json",
    "human_decisions.json",
    "review_status.json",
    "search_strategy.json",
    "search_log.json",
    "retrieved_records.json",
    "duplicates.json",
    "protocol_history.json",
    "appraisals.json",
    "appraisal_proposals.json",
    "eligibility_proposals.json",
    "prisma_flow.json",
    "prisma_flow.svg",
    "prisma_flow.png",
    "prisma_checklist.json",
    "evidence_table.csv",
    "numerical_results.csv",
    "evidence_map.csv",
    "evidence_map.svg",
    "execution_trace.json",
    "protocol_approvals.json",
    "references.bib",
    "literature_review.docx",
    "meta_analysis_template.csv",
}


class GenerationModelChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=128)
    revalidate: bool = False


class RunConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = Field(default=None, min_length=1, max_length=200)
    thinking: str = Field(default="off", max_length=40)
    mode: Literal["guided", "automatic"] = "guided"
    temperature: float = Field(default=0, ge=0, le=1)
    max_records: int = Field(default=10, ge=1, le=100)
    sources: list[Literal["openalex", "pubmed", "arxiv"]] = Field(
        default_factory=lambda: ["openalex", "pubmed", "arxiv"],
        min_length=1,
        max_length=3,
    )

    year_from: int | None = Field(default=None, ge=1, le=9999, strict=True)
    year_to: int | None = Field(default=None, ge=1, le=9999, strict=True)

    @model_validator(mode="after")
    def valid_years(self):
        from methodology.runtime import validate_year_range

        validate_year_range(self.year_from, self.year_to)
        return self


class FinalDecision(BaseModel):
    fingerprint: str
    decision: Literal["accept", "reject"]
    reviewer: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=5000)


class NewReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1, max_length=2000)
    configuration: RunConfiguration = Field(default_factory=RunConfiguration)

    @field_validator("topic")
    @classmethod
    def valid_topic(cls, value):
        if not value.strip():
            raise ValueError("Enter a research question or topic")
        return value.strip()


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str
    fingerprint: str
    decision: Literal["include", "exclude", "approve", "reject"]
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=5000)
    kind: (
        Literal["research_objective", "methodology", "main_findings", "limitations"]
        | None
    ) = None


class QuoteCheck(BaseModel):
    quote: str = Field(min_length=1, max_length=50000)


class ThinkingSetting(BaseModel):
    thinking: str = Field(max_length=40)


class StepConfirmation(BaseModel):
    token: str
    reviewer: str


class ChatMessage(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter a message")
        return value.strip()


class ProtocolSave(BaseModel):
    protocol: Protocol
    author: str
    adopt_existing: bool = False


class ProtocolApproval(BaseModel):
    fingerprint: str
    reviewer: str
    reason: str = ""


class ChecklistReview(BaseModel):
    fingerprint: str
    status: Literal["reported", "not_applicable", "missing"]
    location: str = ""
    reason: str = ""
    reviewer: str


def checked_path(review_id):
    try:
        return get_review_path(review_id)
    except ValueError as error:
        raise HTTPException(404, "Review not found") from error


def summary(review_id, papers=None, state=None):
    root = checked_path(review_id)
    papers = read_json(root / "papers.json", []) if papers is None else papers
    status = read_json(root / "outputs/review_status.json", {})
    state = read_json(root / "workflow_state.json", {}) if state is None else state
    return {
        "id": review_id,
        "topic": (root / "topic.txt").read_text(encoding="utf-8").strip()
        if (root / "topic.txt").exists()
        else review_id,
        "status": status.get("status", state.get("status", "ready")),
        "paper_count": len(papers),
        "report_current": status.get("report_current", False),
    }


def create_app(manager=None):
    jobs = manager or JobManager()

    @asynccontextmanager
    async def lifespan(_app):
        yield
        jobs.close()

    application = FastAPI(
        title="Folio Research API", version="0.1.0", lifespan=lifespan
    )
    application.state.jobs = jobs
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )

    @application.get("/api/health")
    def health():
        return {"status": "ok"}

    @application.get("/api/runtime")
    def runtime_diagnostics():
        from agents.runtime import inspect_runtime

        return inspect_runtime()

    @application.get("/api/reviews")
    def reviews():
        root = review_manager.REVIEW_ROOT
        result = []
        if root.exists():
            for folder in sorted(root.iterdir()):
                if folder.is_dir() and (folder / "topic.txt").is_file():
                    try:
                        result.append(summary(folder.name))
                    except HTTPException:
                        continue

        def updated(entry):
            folder = root / entry["id"]
            checkpoint = folder / "workflow_state.json"
            return (
                (checkpoint if checkpoint.exists() else folder / "topic.txt")
                .stat()
                .st_mtime
            )

        return sorted(result, key=updated, reverse=True)

    @application.post("/api/reviews", status_code=201)
    def new_review(body: NewReview):
        choices = body.configuration.model_dump(exclude_none=True)
        try:
            validate_configuration_choices(choices)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        review_id, _ = create_review(body.topic)
        save_configuration(review_id, choices, validated=True)
        return summary(review_id)

    @application.get("/api/reviews/{review_id}")
    def details(review_id: str):
        root = checked_path(review_id)
        try:
            papers = read_json(root / "papers.json", [])
            outcomes = read_json(root / "outputs/full_text.json", [])
            evidence = read_json(root / "outputs/evidence.json", [])
            state = read_json(root / "workflow_state.json", {})
            queue = review_queue(
                review_id, papers=papers, full_text=outcomes, evidence=evidence
            )
            for item in queue["items"]:
                if "full_text" in item:
                    del item["full_text"]
        except (ValueError, KeyError, OSError) as error:
            raise HTTPException(409, f"Review data needs attention: {error}") from error
        lookup = {p["paper_id"]: p for p in outcomes}
        enriched = []
        for paper in papers:
            paper_id = paper["id"].split("/")[-1]
            files = {
                kind: f"/api/reviews/{review_id}/papers/{paper_id}/file?format={kind}"
                for kind in ("pdf", "txt")
                if (root / "papers" / f"{paper_id}.{kind}").is_file()
            }
            enriched.append(
                {
                    **paper,
                    "paper_id": paper_id,
                    "full_text_status": lookup.get(paper_id, {}).get(
                        "status", "not_sought"
                    ),
                    "files": files,
                }
            )
        automatic = settings(review_id)["mode"] == "automatic"
        from workflow.automatic import result as automatic_result

        final_result = automatic_result(review_id) if automatic else None
        report_path = (
            root
            / "outputs"
            / ("automatic_review.md" if automatic else "literature_review.md")
        )
        review_info = summary(review_id, papers=papers, state=state)
        if automatic:
            review_info["report_current"] = bool(
                final_result
                and final_result["current"]
                and final_result.get("ready", True)
            )
        return {
            **review_info,
            "queue": queue,
            "protocol": load_protocol(review_id),
            "appraisals": appraisal_queue(review_id, queue["included_papers"]),
            "appraisal_proposals": read_json(
                root / "outputs/appraisal_proposals.json", {}
            ),
            "prisma": read_json(root / "outputs/prisma_checklist.json", None),
            "prisma_flow": read_json(root / "outputs/prisma_flow.json", None),
            "search_log": read_json(root / "outputs/search_log.json", []),
            "papers": enriched,
            "pending": {
                stage: len(pending(queue, stage))
                for stage in ("screening", "eligibility", "evidence")
            },
            "evidence": evidence,
            "report": report_path.read_text(encoding="utf-8")
            if report_path.exists()
            else None,
            "writing": writing_status(review_id),
            "quality": read_json(
                root
                / "outputs"
                / ("automatic_quality.json" if automatic else "quality_review.json"),
                None,
            ),
            "statistics": read_json(root / "outputs/review_statistics.json", None),
            "completed": state.get("completed", []),
            "total_stages": 11,
            "errors": state.get("errors", []),
            "decisions": [
                event.model_dump() for event in decision_log(review_id).events
            ],
            "workflow_status": state.get("status", "new"),
            "automatic_result": final_result,
            "chat_messages": read_json(root / "outputs/chat_messages.json", []),
            "runtime_settings": settings(review_id),
            "workflow_protocol_fingerprint": state.get("protocol_fingerprint"),
            "awaiting_confirmation": state.get("awaiting_confirmation")
            if state.get("status") == "awaiting_step_confirmation"
            else None,
            "step_confirmations": read_json(
                root / "outputs/step_confirmations.json", []
            ),
            "progress": read_json(root / "outputs/progress.json", None),
            "job": jobs.status(review_id),
            "artifacts": [
                name
                for name in sorted(ARTIFACTS)
                if (root / "outputs" / name).is_file()
            ],
        }

    @application.post("/api/reviews/{review_id}/decisions", status_code=201)
    def decide(review_id: str, body: ReviewDecision):
        checked_path(review_id)
        try:
            with jobs.mutation(review_id):
                queue = review_queue(review_id)
                item = next(
                    (
                        item
                        for item in queue["items"]
                        if item["item_id"] == body.item_id
                    ),
                    None,
                )
                if not item or item["fingerprint"] != body.fingerprint:
                    raise HTTPException(
                        409,
                        "This review item changed. Refresh and inspect it before deciding.",
                    )
                return record_decision(
                    review_id,
                    body.item_id,
                    body.decision,
                    body.reviewer,
                    body.reason,
                    body.kind,
                )
        except BusyReview as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, KeyError) as error:
            raise HTTPException(422, str(error)) from error

    @application.post("/api/reviews/{review_id}/messages")
    def chat_message(review_id: str, body: ChatMessage):
        from agents.chat_agent import reply

        root = checked_path(review_id)
        try:
            with jobs.mutation(review_id):
                path = root / "outputs/chat_messages.json"
                history = read_json(path, [])
                existing = next(
                    (
                        m
                        for m in history
                        if m.get("request_id") == body.request_id
                        and m.get("role") == "assistant"
                    ),
                    None,
                )
                if existing:
                    previous_user = next(
                        (
                            m
                            for m in history
                            if m.get("request_id") == body.request_id
                            and m.get("role") == "user"
                        ),
                        {},
                    )
                    if previous_user.get("content") != body.text:
                        raise ValueError(
                            "This message ID was already used. Send a new message."
                        )
                    return existing
                answer = reply(review_id, body.text, history)
                timestamp = datetime.now(UTC).isoformat()
                user = {
                    "id": body.request_id + "-user",
                    "request_id": body.request_id,
                    "role": "user",
                    "content": body.text,
                    "timestamp": timestamp,
                }
                assistant = {
                    "id": body.request_id + "-assistant",
                    "request_id": body.request_id,
                    "role": "assistant",
                    "content": answer,
                    "timestamp": timestamp,
                }
                write_json(path, [*history, user, assistant])
                return assistant
        except (
            BusyReview,
            ValueError,
            RuntimeError,
            ConnectionError,
            TimeoutError,
            HTTPError,
            ResponseError,
        ) as error:
            raise HTTPException(409, str(error)) from error

    @application.get("/api/models")
    def local_models():
        return installed_models()

    @application.post("/api/reviews/{review_id}/final-decision")
    def final_decision(review_id: str, body: FinalDecision):
        from workflow.automatic import decide_final

        checked_path(review_id)
        try:
            with jobs.mutation(review_id):
                return decide_final(
                    review_id, body.fingerprint, body.decision, body.reviewer, body.note
                )
        except (BusyReview, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @application.post("/api/reviews/{review_id}/reporting")
    def upgrade_automatic_reporting(review_id: str):
        from workflow.automatic import upgrade_reporting

        checked_path(review_id)
        if settings(review_id)["mode"] != "automatic":
            raise HTTPException(
                409, "Use the guided reporting workflow for this review"
            )
        try:
            with jobs.mutation(review_id):
                return upgrade_reporting(review_id)
        except (BusyReview, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @application.get("/api/model-controls")
    def thinking_controls(model: str | None = Query(None, max_length=200)):
        return model_controls(model)

    @application.put("/api/reviews/{review_id}/settings")
    def review_settings(review_id: str, body: ThinkingSetting):
        checked_path(review_id)
        try:
            with jobs.mutation(review_id):
                return save_thinking(review_id, body.thinking)
        except (BusyReview, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @application.post("/api/reviews/{review_id}/confirm-step")
    def confirm_phase(review_id: str, body: StepConfirmation):
        checked_path(review_id)
        try:
            with jobs.mutation(review_id):
                return confirm_step(review_id, body.token, body.reviewer)
        except (BusyReview, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @application.post("/api/reviews/{review_id}/generation-model")
    def change_generation_model(review_id: str, body: GenerationModelChange):
        from methodology.runtime import upgrade_generation_model

        checked_path(review_id)
        try:
            with jobs.mutation(review_id):
                return upgrade_generation_model(
                    review_id, body.model, revalidate=body.revalidate
                )
        except (BusyReview, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @application.post("/api/reviews/{review_id}/run", status_code=202)
    def run(review_id: str):
        checked_path(review_id)
        try:
            return jobs.start(review_id)
        except (BusyReview, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @application.post("/api/reviews/{review_id}/pause", status_code=202)
    def pause(review_id: str):
        checked_path(review_id)
        try:
            return jobs.pause(review_id)
        except BusyReview as error:
            raise HTTPException(409, str(error)) from error

    @application.get("/api/reviews/{review_id}/run")
    def run_status(review_id: str):
        checked_path(review_id)
        return jobs.status(review_id)

    @application.post("/api/reviews/{review_id}/protocol/draft")
    def protocol_draft(review_id: str):
        checked_path(review_id)
        try:
            with jobs.mutation(review_id):
                existing = load_protocol(review_id)
                return existing or save_protocol(
                    review_id,
                    draft_protocol(review_id).model_dump(mode="json"),
                    "System draft template",
                    adopt_existing=False,
                )
        except BusyReview as error:
            raise HTTPException(409, str(error)) from error

    @application.post("/api/reviews/{review_id}/protocol/suggest")
    def protocol_suggest(review_id: str):
        from agents.planner_agent import propose_protocol

        root = checked_path(review_id)
        try:
            with jobs.mutation(review_id):
                draft = propose_protocol(
                    (root / "topic.txt").read_text(),
                    reasoning=reasoning_value(review_id),
                    model=settings(review_id)["model"],
                    temperature=settings(review_id)["temperature"],
                )
                from methodology.runtime import year_bounds

                draft.date_from, draft.date_to = year_bounds(settings(review_id))
                return save_protocol(
                    review_id,
                    draft.model_dump(mode="json"),
                    "Local planner proposal",
                    adopt_existing=False,
                )
        except (BusyReview, ValueError, RuntimeError, ConnectionError) as error:
            raise HTTPException(409, str(error)) from error

    @application.post("/api/reviews/{review_id}/protocol")
    def protocol_save(review_id: str, body: ProtocolSave):
        checked_path(review_id)
        try:
            with jobs.mutation(review_id):
                return save_protocol(
                    review_id,
                    body.protocol.model_dump(mode="json"),
                    body.author,
                    body.adopt_existing,
                )
        except (BusyReview, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @application.post("/api/reviews/{review_id}/protocol/approve")
    def protocol_approve(review_id: str, body: ProtocolApproval):
        checked_path(review_id)
        try:
            with jobs.mutation(review_id):
                return approve_protocol(
                    review_id, body.fingerprint, body.reviewer, body.reason
                )
        except (BusyReview, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @application.get("/api/reviews/{review_id}/appraisals/{paper_id}/source")
    def appraisal_body(review_id: str, paper_id: str):
        checked_path(review_id)
        try:
            _, text = appraisal_source(review_id, paper_id)
            return {"text": text}
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @application.post("/api/reviews/{review_id}/appraisals/{paper_id}/check-quote")
    def appraisal_quote_check(review_id: str, paper_id: str, body: QuoteCheck):
        checked_path(review_id)
        try:
            return check_appraisal_quote(review_id, paper_id, body.quote)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @application.post("/api/reviews/{review_id}/appraisals/{paper_id}")
    def appraisal_save(review_id: str, paper_id: str, body: AppraisalSubmission):
        checked_path(review_id)
        try:
            with jobs.mutation(review_id):
                queue = review_queue(review_id)
                return save_appraisal(
                    review_id, paper_id, body.model_dump(), queue["included_papers"]
                )
        except (BusyReview, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @application.post("/api/reviews/{review_id}/prisma/{item_id}")
    def prisma_save(review_id: str, item_id: str, body: ChecklistReview):
        checked_path(review_id)
        try:
            with jobs.mutation(review_id):
                return review_checklist_item(
                    review_id,
                    item_id,
                    body.status,
                    body.location,
                    body.reason,
                    body.reviewer,
                    body.fingerprint,
                )
        except (BusyReview, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    def paper_asset(review_id, paper_id, kind):
        root = checked_path(review_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", paper_id):
            raise HTTPException(404, "Paper not found")
        folder = root / "papers"
        path = folder / f"{paper_id}.{kind}"
        if (
            not path.is_file()
            or folder.resolve().parent != root.resolve()
            or path.resolve().parent != folder.resolve()
        ):
            raise HTTPException(404, "Full text is not available")
        return path

    @application.get("/api/reviews/{review_id}/papers/{paper_id}/pdf-info")
    def pdf_info(review_id: str, paper_id: str):
        import pymupdf

        path = paper_asset(review_id, paper_id, "pdf")
        try:
            with pymupdf.open(path) as document:
                return {
                    "pages": len(document),
                    "filename": path.name,
                    "bytes": path.stat().st_size,
                }
        except (RuntimeError, ValueError) as error:
            raise HTTPException(422, "This PDF could not be opened") from error

    @application.get("/api/reviews/{review_id}/papers/{paper_id}/page/{page_number}")
    def pdf_page(
        review_id: str,
        paper_id: str,
        page_number: int,
        scale: float = Query(1.5, ge=0.5, le=2),
    ):
        import math

        import pymupdf

        path = paper_asset(review_id, paper_id, "pdf")
        try:
            with pymupdf.open(path) as document:
                if page_number < 1 or page_number > len(document):
                    raise HTTPException(404, "PDF page not found")
                page = document[page_number - 1]
                # Bound raster memory even for unusually large PDF page dimensions.
                area = max(1, page.rect.width * page.rect.height)
                factor = min(scale, math.sqrt(8_000_000 / area))
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(factor, factor), alpha=False
                )
                return Response(
                    pixmap.tobytes("png"),
                    media_type="image/png",
                    headers={"Cache-Control": "no-store"},
                )
        except (RuntimeError, ValueError) as error:
            raise HTTPException(422, "This PDF page could not be rendered") from error

    @application.get("/api/reviews/{review_id}/papers/{paper_id}/file")
    def paper_file(
        review_id: str,
        paper_id: str,
        format: Literal["pdf", "txt"] = "pdf",
        download: bool = False,
    ):
        path = paper_asset(review_id, paper_id, format)
        return FileResponse(
            path,
            media_type="application/pdf" if format == "pdf" else "text/plain",
            filename=path.name,
            content_disposition_type="attachment" if download else "inline",
        )

    @application.get("/api/reviews/{review_id}/artifacts/{name}")
    def artifact(review_id: str, name: str, download: bool = Query(False)):
        root = checked_path(review_id)
        folder = root / "outputs"
        path = folder / name
        if (
            name not in ARTIFACTS
            or not path.is_file()
            or folder.resolve().parent != root.resolve()
            or path.resolve().parent != folder.resolve()
        ):
            raise HTTPException(404, "Artifact not found")
        return FileResponse(
            path,
            media_type={
                "md": "text/plain",
                "json": "application/json",
                "csv": "text/csv",
                "svg": "image/svg+xml",
                "png": "image/png",
                "bib": "application/x-bibtex",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }.get(name.rsplit(".", 1)[-1], "application/octet-stream"),
            filename=name,
            content_disposition_type="attachment" if download else "inline",
        )

    return application


app = create_app()
