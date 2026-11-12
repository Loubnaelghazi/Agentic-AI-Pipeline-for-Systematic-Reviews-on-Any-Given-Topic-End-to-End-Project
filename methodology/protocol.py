"""Versioned protocols and explicit human approval, including legacy adoption."""

import re
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from storage.human_review import digest, read_json
from storage.review_manager import archive_outputs, get_review_path, write_json


class Domain(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    question: str = Field(min_length=5, max_length=1000)


class Protocol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    research_question: str = Field(min_length=5, max_length=2000)
    rationale: str = Field(min_length=10, max_length=5000)
    inclusion_criteria: list[str] = Field(min_length=1, max_length=30)
    exclusion_criteria: list[str] = Field(min_length=1, max_length=30)
    concepts: list[list[str]] = Field(min_length=1, max_length=6)
    mesh_terms: list[str] = Field(default_factory=list, max_length=20)
    sources: list[Literal["openalex", "pubmed", "arxiv"]] = Field(
        default_factory=lambda: ["openalex", "pubmed", "arxiv"], min_length=1
    )
    max_records_per_query: int = Field(default=25, ge=1, le=500)
    date_from: date | None = None
    date_to: date | None = None
    extraction_fields: list[str] = Field(
        default_factory=lambda: [
            "study_design",
            "population",
            "intervention_or_exposure",
            "comparator",
            "outcomes",
            "sample_size",
            "results",
            "limitations",
            "funding",
        ],
        min_length=1,
        max_length=30,
    )
    appraisal_name: str = Field(
        default="Project-defined domain appraisal (not a validated instrument)",
        min_length=5,
    )
    appraisal_domains: list[Domain] = Field(
        default_factory=lambda: [
            Domain(id=k, question=q)
            for k, q in [
                ("design_fit", "Is the design appropriate for the research question?"),
                ("selection", "Could sample or study selection introduce bias?"),
                (
                    "measurement",
                    "Are measurements and outcomes described and credible?",
                ),
                (
                    "confounding",
                    "Are important confounders or alternative explanations addressed?",
                ),
                (
                    "missing_data",
                    "Could missing data or incomplete results bias findings?",
                ),
                (
                    "selective_reporting",
                    "Is there evidence of selective outcome or result reporting?",
                ),
            ]
        ],
        min_length=1,
        max_length=20,
    )
    synthesis_plan: str = Field(
        default="Group approved evidence by outcome and compare study designs, contexts, findings and appraisal limitations. Do not pool incompatible outcomes.",
        min_length=10,
    )
    meta_analysis: bool = False
    registration: str = "Not registered"
    funding: str = "Not reported"
    conflicts: str = "Not reported"

    @field_validator("inclusion_criteria", "exclusion_criteria", "extraction_fields")
    @classmethod
    def nonblank_items(cls, values):
        if any(not v.strip() for v in values):
            raise ValueError("List entries must not be blank")
        return list(dict.fromkeys(v.strip() for v in values))

    @field_validator("concepts")
    @classmethod
    def concept_groups(cls, values):
        if any(
            not group or any(not term.strip() for term in group) for group in values
        ):
            raise ValueError("Each concept needs at least one nonblank term")
        return [[term.strip() for term in dict.fromkeys(group)] for group in values]

    @model_validator(mode="after")
    def valid_dates_domains(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Publication start date must precede end date")
        if len({d.id for d in self.appraisal_domains}) != len(self.appraisal_domains):
            raise ValueError("Appraisal domain identifiers must be unique")
        return self


def protocol_path(review_id):
    return get_review_path(review_id) / "protocol.json"


def load_protocol(review_id):
    return read_json(protocol_path(review_id), None)


def draft_protocol(review_id):
    from methodology.runtime import settings, year_bounds

    runtime = settings(review_id)
    date_from, date_to = year_bounds(runtime)
    topic = (get_review_path(review_id) / "topic.txt").read_text().strip()
    return Protocol(
        research_question=topic if len(topic) >= 5 else f"Review of {topic}",
        rationale=f"Investigate the available scientific evidence concerning {topic}. Refine this rationale before approval.",
        inclusion_criteria=[
            f"Directly addresses: {topic}",
            "Reports an identifiable study design and relevant findings",
        ],
        exclusion_criteria=[
            "Does not address the approved research question",
            "No relevant study findings or review findings are reported",
        ],
        concepts=[[topic]],
        sources=runtime["sources"],
        max_records_per_query=runtime["max_records"],
        date_from=date_from,
        date_to=date_to,
    )


def protocol_digest(value, adopt_existing=False):
    return digest({"protocol": value, "adopt_existing": bool(adopt_existing)})


def save_protocol(review_id, value, author, adopt_existing=False):
    if not author.strip():
        raise ValueError("Protocol author is required")
    protocol = Protocol.model_validate(value).model_dump(mode="json")
    old = load_protocol(review_id)
    versions = read_json(
        get_review_path(review_id) / "outputs/protocol_history.json", []
    )
    if old:
        versions.append(old)
    document = {
        "revision": (old or {}).get("revision", 0) + 1,
        "protocol": protocol,
        "fingerprint": protocol_digest(protocol, adopt_existing),
        "author": author.strip(),
        "created_at": datetime.now(UTC).isoformat(),
        "approval": None,
        "adopt_existing": bool(adopt_existing),
    }
    archive_outputs(review_id)
    write_json(get_review_path(review_id) / "outputs/protocol_history.json", versions)
    write_json(protocol_path(review_id), document)
    write_json(
        get_review_path(review_id) / "outputs/review_status.json",
        {"status": "awaiting_protocol_review", "report_current": False},
    )
    return document


def approve_protocol(review_id, fingerprint, reviewer, reason):
    document = load_protocol(review_id)
    if (
        not document
        or document["fingerprint"] != fingerprint
        or document["fingerprint"]
        != protocol_digest(document["protocol"], document.get("adopt_existing", False))
    ):
        raise ValueError("Protocol changed; inspect the current revision")
    if not reviewer.strip():
        raise ValueError("Reviewer is required")
    document["approval"] = {
        "fingerprint": fingerprint,
        "reviewer": reviewer.strip(),
        "reason": reason.strip(),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    events = read_json(
        get_review_path(review_id) / "outputs/protocol_approvals.json", []
    )
    events.append({"revision": document["revision"], **document["approval"]})
    write_json(get_review_path(review_id) / "outputs/protocol_approvals.json", events)
    write_json(protocol_path(review_id), document)
    return document


def require_protocol(review_id):
    document = load_protocol(review_id)
    if (
        not document
        or not document.get("approval")
        or document["fingerprint"]
        != protocol_digest(document["protocol"], document.get("adopt_existing", False))
        or document["approval"]["fingerprint"] != document["fingerprint"]
    ):
        raise ValueError("Approve the current review protocol before continuing")
    return Protocol.model_validate(document["protocol"])


def strategies(protocol):
    def quoted(term):
        return '"' + re.sub(r'["\n\r]', " ", term).strip() + '"'

    groups = [
        "(" + " OR ".join(quoted(t) for t in terms) + ")" for terms in protocol.concepts
    ]
    boolean = " AND ".join(groups)
    return {
        "openalex": [
            " ".join(group[0] for group in protocol.concepts),
            " ".join(t for group in protocol.concepts for t in group),
        ],
        "pubmed": [
            boolean
            + (
                " AND ("
                + " OR ".join(quoted(t) + "[MeSH Terms]" for t in protocol.mesh_terms)
                + ")"
                if protocol.mesh_terms
                else ""
            )
        ],
        "arxiv": [
            " AND ".join(
                "(" + " OR ".join("all:" + quoted(t) for t in group) + ")"
                for group in protocol.concepts
            )
        ],
    }


def main():
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Create, edit, inspect and explicitly approve review protocols"
    )
    parser.add_argument("action", choices=("show", "draft", "save", "approve"))
    parser.add_argument("review_id")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--reviewer")
    parser.add_argument("--reason")
    parser.add_argument("--fingerprint")
    parser.add_argument("--adopt-existing", action="store_true")
    args = parser.parse_args()
    if args.action == "show":
        result = load_protocol(args.review_id)
    elif args.action == "draft":
        result = load_protocol(args.review_id) or save_protocol(
            args.review_id,
            draft_protocol(args.review_id).model_dump(mode="json"),
            "System draft template",
            args.adopt_existing,
        )
    elif args.action == "save":
        if not args.file or not args.reviewer:
            parser.error("save requires --file and --reviewer")
        result = save_protocol(
            args.review_id,
            json.loads(args.file.read_text()),
            args.reviewer,
            args.adopt_existing,
        )
    else:
        if not all((args.fingerprint, args.reviewer)):
            parser.error("approve requires --fingerprint and --reviewer")
        result = approve_protocol(
            args.review_id, args.fingerprint, args.reviewer, args.reason or ""
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
