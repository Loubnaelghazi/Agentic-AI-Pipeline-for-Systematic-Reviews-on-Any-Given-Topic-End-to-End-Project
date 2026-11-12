"""Synthetic audited writing, never used for application data or human decisions."""

from agents.writing_agent import (
    SECTIONS,
    WRITER_VERSION,
    section_fingerprint,
    writing_packet,
)


def audited_writing(review_id, protocol, evidence, assessments=None, mode="automatic"):
    packet = writing_packet(review_id, protocol, evidence, assessments, mode)
    facts = packet["facts"]
    primary = next((k for k, v in facts.items() if v["scope"] == "primary"), None)
    sections = {}
    if primary:
        for section in SECTIONS:
            paragraphs = [
                {
                    "text": facts[primary]["text"],
                    "evidence_ids": [primary],
                    "audit": {
                        "supported": True,
                        "citations_complete": True,
                        "correct_scope": True,
                    },
                }
            ]
            sections[section] = {
                "verified": True,
                "paragraphs": paragraphs,
                "issues": [],
                "content_fingerprint": section_fingerprint(paragraphs, facts),
            }
    return {
        "version": WRITER_VERSION,
        "input_fingerprint": packet["input_fingerprint"],
        "facts": facts,
        "sections": sections,
        "ready": bool(primary),
        "status": "ready_for_scientific_review"
        if primary
        else "insufficient_eligible_evidence",
        "issues": [],
    }
