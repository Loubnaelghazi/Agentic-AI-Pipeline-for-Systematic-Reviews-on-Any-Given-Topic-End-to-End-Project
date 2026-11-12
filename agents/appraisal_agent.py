"""Conservative proposals only: humans must assess and confirm each study domain."""

from pydantic import BaseModel, Field

from agents.client import chat_model


class AppraisalProposal(BaseModel):
    notes: list[str] = Field(default_factory=list)


def propose_appraisal(protocol, evidence):
    client = chat_model(400, timeout=180)
    prompt = f"""Identify questions for an appraiser using ONLY the supplied source quotations.
Do not issue risk-of-bias scores. Missing details in excerpts do not prove poor study quality.
Question: {protocol.research_question}
Appraisal domains: {[d.model_dump() for d in protocol.appraisal_domains]}
Source quotations (human-reviewed: {evidence.get("human_reviewed", False)}): {evidence.get("claims", [])}
Return at most 4 short appraisal questions or evidence gaps. These are unverified suggestions.
"""
    return (
        client.with_structured_output(AppraisalProposal, method="json_schema")
        .invoke(prompt)
        .model_dump()
    )
