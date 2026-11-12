from typing import TypedDict


class ReviewState(TypedDict, total=False):
    scientific_writer_version: str
    awaiting_confirmation: dict | None
    pending_review_items: list[str]
    eligible_paper_ids: list[str]
    approved_evidence: list[dict]
    human_review_signatures: dict[str, str]
    reporting_signature: str
    protocol_fingerprint: str
    appraisal_signature: str
    search_strategies: dict
    search_log: list[dict]
    protocol: dict
    model_config: dict
    topic: str
    review_id: str
    review_path: str
    search_query: str
    papers: list[dict]
    full_text: list[dict]
    evidence: list[dict]
    report: str
    quality_review: dict
    errors: list[dict]
    status: str
    completed: list[str]
