import json

from pydantic import BaseModel, Field

from agents.client import chat_model


class QualityReview(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


llm = chat_model(600, timeout=180)

critic = llm.with_structured_output(
    QualityReview,
    method="json_schema",
)


def review_report(
    topic: str,
    evidence: list[dict],
    report: str,
) -> dict:

    evidence = [
        {
            key: value
            for key, value in item.items()
            if key
            in (
                "paper_id",
                "claims",
                "missing_fields",
                "grounding_status",
                "rejected_claims",
            )
        }
        for item in evidence
    ]

    prompt = f"""
You are a scientific quality assurance reviewer.

Research topic:
{topic}

Extracted evidence:
{json.dumps(evidence, ensure_ascii=False)}

Generated report:
{report}

Check:
1. Does the report address the research topic?
2. Are claims supported by the extracted evidence?
3. Are the paper IDs correctly referenced?
4. Are findings and limitations accurately represented?
5. Does the report acknowledge insufficient evidence?
6. Are quoted statements about this study rather than cited secondary studies?
7. Are missing extracted fields kept separate from author-reported limitations?
This report may be a conservative extractive digest. Do not require unsupported
comparisons or invent the missing information. Exact quote matching is not a
semantic correctness guarantee. Identify ambiguous attribution for human review.

Set passed=false if important problems exist.

Return a structured quality review.
"""

    result = critic.invoke(prompt)

    return result.model_dump()
