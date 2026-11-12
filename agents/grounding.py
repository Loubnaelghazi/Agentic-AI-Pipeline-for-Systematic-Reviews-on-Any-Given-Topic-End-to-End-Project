"""Deterministic quotation checks shared by extraction, reporting and QA."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rag.provenance import normalize

EVIDENCE_VERSION = "selected-quotes-v2"


class EvidenceQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["research_objective", "methodology", "main_findings", "limitations"]
    passage_id: str
    quote: str = Field(min_length=15, max_length=700)


class SentenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["research_objective", "methodology", "main_findings", "limitations"]
    statement_id: str
    field: str | None = None


class SelectedEvidence(BaseModel):
    selections: list[SentenceSelection] = Field(default_factory=list, max_length=16)


def validate_claims(claims, passages):
    lookup = {item["passage_id"]: item for item in passages}
    accepted, rejected = [], []
    seen = set()
    for value in claims:
        try:
            claim = EvidenceQuote.model_validate(value).model_dump()
        except ValueError as error:
            rejected.append({"claim": value, "reason": str(error)})
            continue
        passage = lookup.get(claim["passage_id"])
        if not passage or normalize(claim["quote"]) not in normalize(passage["text"]):
            rejected.append(
                {"claim": claim, "reason": "Quote is absent from the cited passage"}
            )
            continue
        claim["quote"] = normalize(claim["quote"])
        key = (claim["kind"], claim["quote"])
        if key not in seen:
            accepted.append(claim)
            seen.add(key)
    return accepted, rejected


def validate_record(record, review_id=None):
    if record.get("evidence_version") != EVIDENCE_VERSION:
        raise ValueError("Evidence requires quote-grounded re-extraction")
    if review_id is not None and record.get("review_id") != review_id:
        raise ValueError("Evidence belongs to a different review")
    passages = record.get("supporting_passages", [])
    expected_source = record["paper_id"] + ".txt"
    if any(p.get("source") != expected_source for p in passages):
        raise ValueError("Evidence contains passages from a different paper")
    if len({p["passage_id"] for p in passages}) != len(passages):
        raise ValueError("Duplicate passage IDs")
    claims, rejected = validate_claims(record.get("claims", []), passages)
    if rejected:
        raise ValueError("Evidence has unverified quotations")
    return claims
