"""Source-supported human study appraisal; preserves per-domain judgements and revisions."""

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from methodology.protocol import load_protocol, require_protocol
from rag.provenance import PaperSource, normalize
from storage.human_review import digest, read_json, source_fingerprint
from storage.review_manager import get_review_path, write_json

Judgement = Literal["low", "some_concerns", "high", "unclear", "not_applicable"]


class DomainJudgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain_id: str
    judgement: Judgement
    rationale: str = ""
    quote: str = ""

    @model_validator(mode="after")
    def meaningful(self):
        if self.judgement != "unclear" and len(self.rationale.strip()) < 5:
            raise ValueError(
                "Explain substantive or not-applicable appraisal judgements"
            )
        return self


class Characteristic(BaseModel):
    value: str = ""
    quote: str = ""


class AppraisalSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str
    reviewer: str = Field(min_length=1)
    overall: Judgement
    rationale: str = ""
    domains: list[DomainJudgement]
    characteristics: dict[str, Characteristic] = Field(default_factory=dict)
    study_id: str = ""

    @model_validator(mode="after")
    def nonblank(self):
        if not self.reviewer.strip():
            raise ValueError("Reviewer is required")
        if self.overall != "unclear" and len(self.rationale.strip()) < 5:
            raise ValueError("Explain the overall appraisal judgement")
        return self


def appraisal_queue(review_id, included):
    document = load_protocol(review_id)
    if not document or not document.get("approval"):
        return []
    root = get_review_path(review_id)
    events = read_json(root / "outputs/appraisals.json", [])
    latest = {e["paper_id"]: e for e in events}
    result = []
    for paper_id in included:
        fingerprint = digest(
            {
                "protocol": document["fingerprint"],
                "paper_id": paper_id,
                "source": source_fingerprint(root / "papers", paper_id),
            }
        )
        event = latest.get(paper_id)
        current = event if event and event["fingerprint"] == fingerprint else None
        result.append(
            {
                "paper_id": paper_id,
                "fingerprint": fingerprint,
                "assessment": current,
                "domains": document["protocol"]["appraisal_domains"],
                "tool": document["protocol"]["appraisal_name"],
            }
        )
    return result


def appraisal_source(review_id, paper_id):
    """Read the same body text used by appraisal verification (never PDF references)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", paper_id):
        raise ValueError("Invalid paper identifier")
    root = get_review_path(review_id).resolve()
    folder = root / "papers"
    if folder.resolve().parent != root:
        raise ValueError("Invalid source directory")
    pdf = folder / f"{paper_id}.pdf"
    txt = folder / f"{paper_id}.txt"
    for path in (pdf, txt):
        if path.resolve().parent != folder.resolve():
            raise ValueError("Invalid source path")
    if pdf.exists():
        source = PaperSource(pdf)
        return source, source.text[: source.body_end].strip()
    return None, normalize(txt.read_text()) if txt.exists() else ""


def quote_support(source, plain, quote):
    quote = normalize(quote)
    if not quote:
        return None
    if source:
        passage = source.passage(quote, limit=len(quote))
        # passage() can truncate at the reference boundary; an entire quote must match.
        return passage if passage and passage["text"] == quote else None
    return (
        {"text": quote, "page_start": None, "page_end": None}
        if quote in plain
        else None
    )


def check_appraisal_quote(review_id, paper_id, quote):
    source, plain = appraisal_source(review_id, paper_id)
    support = quote_support(source, plain, quote)
    if not support:
        raise ValueError(
            "Quote not found in this paper's body text. Copy a continuous passage from the source text below; put your interpretation in Reason, not in the quotation. References are not accepted."
        )
    return support


def save_appraisal(review_id, paper_id, value, included):
    protocol = require_protocol(review_id)
    if paper_id not in included:
        raise ValueError("Only eligible included studies may be appraised")
    value = AppraisalSubmission.model_validate(value)
    item = next(
        i for i in appraisal_queue(review_id, included) if i["paper_id"] == paper_id
    )
    if value.fingerprint != item["fingerprint"]:
        raise ValueError("Study or protocol changed; refresh the appraisal")
    if sorted(d.domain_id for d in value.domains) != sorted(
        d.id for d in protocol.appraisal_domains
    ):
        raise ValueError("Assess each protocol domain exactly once")
    root = get_review_path(review_id)
    source, plain = appraisal_source(review_id, paper_id)
    domains = []
    for domain in value.domains:
        if (
            domain.judgement not in ("unclear", "not_applicable")
            and not domain.quote.strip()
        ):
            raise ValueError(
                "Substantive judgements require an exact supporting quotation"
            )
        support = None
        if domain.quote:
            support = quote_support(source, plain, domain.quote)
            if not support:
                raise ValueError(
                    f"[domain:{domain.domain_id}] Quote not found in this paper's body text. Copy an exact continuous passage from Source text; keep your interpretation in Reason."
                )
        domains.append({**domain.model_dump(), "support": support})
    if set(value.characteristics) != set(protocol.extraction_fields):
        raise ValueError(
            "Review each extraction field; leave value empty when not reported"
        )
    characteristics = {}
    for field, entry in value.characteristics.items():
        support = None
        if entry.value.strip():
            if not entry.quote.strip():
                raise ValueError(f"{field} needs a supporting source quote")
            support = quote_support(source, plain, entry.quote)
            if not support:
                raise ValueError(
                    f"[field:{field}] Quote not found in this paper's body text. Copy an exact continuous passage from Source text."
                )
        characteristics[field] = {**entry.model_dump(), "support": support}
    event = {
        **value.model_dump(),
        "domains": domains,
        "characteristics": characteristics,
        "paper_id": paper_id,
        "tool": protocol.appraisal_name,
        "timestamp": datetime.now(UTC).isoformat(),
        "method": "Human domain-level appraisal; no validated-tool scoring algorithm is claimed",
    }
    path = root / "outputs/appraisals.json"
    events = read_json(path, [])
    events.append(event)
    write_json(path, events)
    write_json(
        root / "outputs/review_status.json",
        {"status": "appraisal_changed_resume_required", "report_current": False},
    )
    return event
