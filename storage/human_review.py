"""Human decisions bound to review content; no scientific decisions are inferred."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

import pymupdf
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agents.grounding import validate_record
from rag.provenance import PaperSource, normalize
from storage.review_manager import get_review_path, write_json

KINDS = ("research_objective", "methodology", "main_findings", "limitations")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def source_fingerprint(folder, paper_id):
    return digest(
        {
            suffix: hashlib.sha256(
                (folder / f"{paper_id}.{suffix}").read_bytes()
            ).hexdigest()
            for suffix in ("pdf", "txt")
            if (folder / f"{paper_id}.{suffix}").is_file()
        }
    )


def validate_record_source(review_id, record):
    claims = validate_record(record, review_id)
    folder = get_review_path(review_id) / "papers"
    pdf = folder / f"{record['paper_id']}.pdf"
    if pdf.is_file():
        original = PaperSource(pdf)
        for passage in record["supporting_passages"]:
            current = original.passage(
                passage["text"], limit=len(normalize(passage["text"]))
            )
            if not current or any(
                current[key] != passage.get(key) for key in ("page_start", "page_end")
            ):
                raise ValueError(
                    "Passage or page citation no longer matches the source PDF"
                )
        # Validate structured cells against their original geometry as well as
        # ordinary quotations. A page number alone cannot authorize a metric.
        with pymupdf.open(pdf) as document:
            tables = {}
            pages = {}
            for table in record.get("source_tables", []):
                if table["table_id"] in tables:
                    raise ValueError("Duplicate source table identifier")
                tables[table["table_id"]] = table
                number = table["page"]
                if not 1 <= number <= len(document):
                    raise ValueError("Table page is outside the source PDF")
                if number not in pages:
                    page = document[number - 1]
                    pages[number] = (
                        page,
                        page.get_textpage(),
                        normalize(page.get_text()),
                    )
                page, textpage, page_text = pages[number]
                if page_text != table["page_context"]:
                    raise ValueError("Table page context no longer matches PDF")
                if len(table["cells"]) != len(table["cell_bboxes"]):
                    raise ValueError("Table geometry does not match cells")
                for cells, boxes in zip(
                    table["cells"], table["cell_bboxes"], strict=True
                ):
                    expected = [
                        normalize(page.get_textbox(box, textpage=textpage))
                        if box
                        else None
                        for box in boxes
                    ]
                    if expected != cells:
                        raise ValueError("Table cells no longer match the source PDF")
            for value in record.get("numerical_results", []):
                table = tables.get(value["table_id"])
                if not table or not 0 < value["row_index"] < len(table["cells"]):
                    raise ValueError("Unknown numerical result row")
    else:
        if record.get("source_tables") or record.get("numerical_results"):
            raise ValueError("Structured tables require an original PDF")
        text = folder / f"{record['paper_id']}.txt"
        if not text.is_file():
            raise ValueError("Original full text is missing")
        current = normalize(text.read_text(encoding="utf-8"))
        if any(
            normalize(passage["text"]) not in current
            for passage in record["supporting_passages"]
        ):
            raise ValueError("Passage no longer matches the original full text")
    return claims


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str
    stage: Literal["screening", "eligibility", "evidence"]
    fingerprint: str
    decision: Literal["include", "exclude", "approve", "reject"]
    reviewer: str = Field(min_length=1)
    reason: str = ""
    timestamp: str
    reviewed_item: dict = Field(default_factory=dict)
    kind: (
        Literal["research_objective", "methodology", "main_findings", "limitations"]
        | None
    ) = None

    @field_validator("reviewer")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Reviewer must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def valid_action(self):
        choices = (
            ("approve", "reject")
            if self.stage == "evidence"
            else ("include", "exclude")
        )
        if self.decision not in choices:
            raise ValueError("Decision is invalid for this review stage")
        if (
            self.stage == "eligibility"
            and self.decision == "exclude"
            and not self.reason.strip()
        ):
            raise ValueError("Select or enter a reason for full-text exclusion")
        if self.kind is not None and (
            self.stage != "evidence" or self.decision != "approve"
        ):
            raise ValueError("Only approved evidence may have a category override")
        return self


class DecisionLog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    review_id: str
    events: list[Decision] = Field(default_factory=list)


def decision_log(review_id):
    path = get_review_path(review_id) / "outputs" / "human_decisions.json"
    log = DecisionLog.model_validate(read_json(path, {"review_id": review_id}))
    if log.review_id != review_id:
        raise ValueError("Decision log belongs to another review")
    return log


def review_queue(review_id, *, papers=None, full_text=None, evidence=None):
    root = get_review_path(review_id)
    outputs = root / "outputs"
    papers = papers if papers is not None else read_json(root / "papers.json", [])
    full_text = (
        full_text
        if full_text is not None
        else read_json(outputs / "full_text.json", [])
    )
    evidence = (
        evidence if evidence is not None else read_json(outputs / "evidence.json", [])
    )
    topic = (root / "topic.txt").read_text(encoding="utf-8")
    from methodology.protocol import load_protocol

    protocol_document = load_protocol(review_id)
    protocol_fingerprint = (
        protocol_document["fingerprint"] if protocol_document else None
    )
    latest = {
        event.item_id: event.model_dump() for event in decision_log(review_id).events
    }
    items, included, unavailable = [], set(), []
    not_sought = []
    invalid_evidence = []

    def add(item):
        event = latest.get(item["item_id"])
        item["decision"] = (
            event if event and event["fingerprint"] == item["fingerprint"] else None
        )
        item["status"] = (
            "decided" if item["decision"] else ("stale" if event else "pending")
        )
        items.append(item)
        return item["decision"]

    source_hashes = {}

    def get_source_fingerprint(paper_id):
        if paper_id not in source_hashes:
            source_hashes[paper_id] = source_fingerprint(root / "papers", paper_id)
        return source_hashes[paper_id]

    availability = {item["paper_id"]: item for item in full_text}
    for paper in papers:
        paper_id = paper["id"].split("/")[-1]
        identity = {
            "review_id": review_id,
            "topic": topic,
            "paper": paper,
            "protocol": protocol_fingerprint,
        }
        # Keep automated screening separate from human decisions in papers.json.
        automated = paper.get("screening", {}).get("decision")
        screen = add(
            {
                "item_id": f"screening:{paper_id}",
                "stage": "screening",
                "paper_id": paper_id,
                "title": paper.get("title"),
                "abstract": paper.get("abstract"),
                "automated_decision": automated,
                "required": automated == "uncertain",
                "fingerprint": digest(identity),
            }
        )
        effective = screen["decision"] if screen else automated
        if effective != "include":
            continue
        outcome = availability.get(paper_id)
        if outcome is None:
            not_sought.append(paper_id)
            continue
        text = root / "papers" / f"{paper_id}.txt"
        pdf = root / "papers" / f"{paper_id}.pdf"
        available = (text.is_file() and text.stat().st_size > 0) or (
            pdf.is_file() and pdf.stat().st_size > 0
        )
        if outcome.get("status") != "retrieved" or not available:
            unavailable.append(paper_id)
            continue
        source_hash = get_source_fingerprint(paper_id)
        eligibility = add(
            {
                "item_id": f"eligibility:{paper_id}",
                "stage": "eligibility",
                "paper_id": paper_id,
                "title": paper.get("title"),
                "required": True,
                "full_text": str(pdf if pdf.exists() else text),
                "fingerprint": digest({**identity, "source": source_hash}),
            }
        )
        proposals = read_json(outputs / "eligibility_proposals.json", {})
        candidate = proposals.get(paper_id, {})
        if candidate.get("fingerprint") == items[-1]["fingerprint"]:
            items[-1]["proposal"] = candidate.get("proposal")
        if eligibility and eligibility["decision"] == "include":
            included.add(paper_id)

    for record in evidence:
        if record.get("paper_id") not in included or "error" in record:
            continue
        try:
            claims = validate_record_source(review_id, record)
        except (KeyError, ValueError, OSError, RuntimeError):
            invalid_evidence.append(record["paper_id"])
            continue
        passages = {p["passage_id"]: p for p in record["supporting_passages"]}
        source_hash = get_source_fingerprint(record["paper_id"])
        if not claims:
            fingerprint = digest(
                {"review_id": review_id, "record": record, "source": source_hash}
            )
            add(
                {
                    "item_id": f"evidence-empty:{record['paper_id']}",
                    "stage": "evidence",
                    "paper_id": record["paper_id"],
                    "required": True,
                    "fingerprint": fingerprint,
                    "empty_evidence": True,
                    "quote": "No source-matched quotations; acknowledge the extraction gap.",
                }
            )
        for claim in claims:
            passage = passages[claim["passage_id"]]
            fingerprint = digest(
                {
                    "review_id": review_id,
                    "topic": topic,
                    "paper_id": record["paper_id"],
                    "version": record["evidence_version"],
                    "protocol": protocol_fingerprint,
                    "claim": claim,
                    "passage": passage,
                    "source": source_hash,
                }
            )
            add(
                {
                    "item_id": f"evidence:{fingerprint[:24]}",
                    "stage": "evidence",
                    "paper_id": record["paper_id"],
                    "required": True,
                    "fingerprint": fingerprint,
                    "proposed_kind": claim["kind"],
                    "quote": claim["quote"],
                    "passage": passage,
                }
            )
    return {
        "review_id": review_id,
        "items": items,
        "included_papers": sorted(included),
        "unavailable_full_texts": unavailable,
        "full_text_not_sought": not_sought,
        "invalid_evidence": invalid_evidence,
    }


def record_decision(review_id, item_id, decision, reviewer, reason, kind=None):
    from methodology.protocol import require_protocol

    require_protocol(review_id)
    if not reviewer.strip():
        raise ValueError("Reviewer is required")
    queue = review_queue(review_id)
    item = next((item for item in queue["items"] if item["item_id"] == item_id), None)
    if not item:
        raise ValueError(
            "Unknown review item; evidence decisions require an eligible included study"
        )
    allowed = (
        ("approve", "reject") if item["stage"] == "evidence" else ("include", "exclude")
    )
    if decision not in allowed:
        raise ValueError(f"Allowed decisions for {item['stage']}: {allowed}")
    if kind is not None and item.get("empty_evidence"):
        raise ValueError("An empty extraction cannot be assigned a category")
    if kind is not None and (
        kind not in KINDS or item["stage"] != "evidence" or decision != "approve"
    ):
        raise ValueError(
            "Category overrides require evidence approval and a valid kind"
        )
    event = Decision(
        item_id=item_id,
        stage=item["stage"],
        fingerprint=item["fingerprint"],
        decision=decision,
        reviewer=reviewer.strip(),
        reason=reason.strip(),
        timestamp=datetime.now(UTC).isoformat(),
        kind=kind,
        reviewed_item={
            key: value
            for key, value in item.items()
            if key not in ("decision", "status")
        },
    )
    log = decision_log(review_id)
    log.events.append(event)
    write_json(
        get_review_path(review_id) / "outputs" / "human_decisions.json",
        log.model_dump(),
    )
    write_status(review_id, "review_decisions_changed_resume_required", False)
    return event.model_dump()


def write_status(review_id, status, report_current):
    queue = review_queue(review_id)
    result = {
        "review_id": review_id,
        "status": status,
        "report_current": report_current,
        "pending": {
            stage: len(pending(queue, stage))
            for stage in ("screening", "eligibility", "evidence")
        },
        "full_text_eligible_studies": len(queue["included_papers"]),
        "unavailable_full_texts": queue["unavailable_full_texts"],
        "full_text_not_sought": queue["full_text_not_sought"],
    }
    write_json(get_review_path(review_id) / "outputs" / "review_status.json", result)


def pending(queue, stage):
    return [
        item
        for item in queue["items"]
        if item["stage"] == stage and item["required"] and not item["decision"]
    ]


def signatures(review_id, queue=None):
    queue = review_queue(review_id) if queue is None else queue
    return {
        stage: digest(
            [
                {key: item[key] for key in ("item_id", "fingerprint", "decision")}
                for item in queue["items"]
                if item["stage"] == stage
            ]
        )
        for stage in ("screening", "eligibility", "evidence")
    }


def approved_evidence(queue, evidence):
    """Build a separate export, leaving raw model extractions untouched."""
    result = []
    for record in evidence:
        if record.get("paper_id") not in queue["included_papers"]:
            continue
        validate_record(record, queue["review_id"])
        approved = []
        for item in queue["items"]:
            event = item.get("decision")
            if (
                not item.get("empty_evidence")
                and item["stage"] == "evidence"
                and item["paper_id"] == record["paper_id"]
                and event
                and event["decision"] == "approve"
            ):
                approved.append(
                    {
                        "kind": event["kind"] or item["proposed_kind"],
                        "passage_id": item["passage"]["passage_id"],
                        "quote": item["quote"],
                    }
                )
        grouped = {
            kind: [claim["quote"] for claim in approved if claim["kind"] == kind]
            for kind in KINDS
        }
        result.append(
            {
                **record,
                "claims": approved,
                "numerical_results": [
                    value
                    for value in record.get("numerical_results", [])
                    if any(
                        c["quote"] == value.get("quote")
                        and c["passage_id"] == value.get("passage_id")
                        and c["kind"] == "main_findings"
                        for c in approved
                    )
                ],
                "research_objective": " ".join(grouped["research_objective"]),
                "methodology": " ".join(grouped["methodology"]),
                "main_findings": grouped["main_findings"],
                "limitations": grouped["limitations"],
                "missing_fields": [kind for kind in KINDS if not grouped[kind]],
                "human_reviewed": all(
                    item["decision"] is not None
                    for item in queue["items"]
                    if item["stage"] == "evidence"
                    and item["paper_id"] == record["paper_id"]
                ),
                "human_review_decisions": [
                    item["decision"]
                    for item in queue["items"]
                    if item["paper_id"] == record["paper_id"]
                    and item["stage"] in ("eligibility", "evidence")
                    and item.get("decision")
                ],
            }
        )
    return result
