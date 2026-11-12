import re
import uuid
from pathlib import Path

from config import DATA_DIR


def create_review(topic: str) -> tuple[str, Path]:
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    slug = slug[:40] or "review"

    review_id = f"{slug}_{uuid.uuid4().hex[:8]}"

    review_path = REVIEW_ROOT / review_id

    (review_path / "papers").mkdir(parents=True, exist_ok=True)
    (review_path / "outputs").mkdir(parents=True, exist_ok=True)

    (review_path / "topic.txt").write_text(
        topic,
        encoding="utf-8",
    )

    return review_id, review_path


REVIEW_ROOT = DATA_DIR / "reviews"


def get_review_path(review_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", review_id):
        raise ValueError("Invalid review ID")
    path = REVIEW_ROOT / review_id
    if not path.is_dir() or path.resolve().parent != REVIEW_ROOT.resolve():
        raise ValueError("Review not found or outside review root")
    return path


def write_json(path: Path, value):
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    temporary.replace(path)


def archive_outputs(review_id: str):
    """Copy prior scientific outputs before invalidating dependent workflow stages."""
    import shutil
    from datetime import UTC, datetime

    review = get_review_path(review_id)
    outputs = review / "outputs"
    sources = [
        outputs / name
        for name in (
            "automatic_review.md",
            "automatic_review.docx",
            "automatic_result.json",
            "automatic_quality.json",
            "automatic_eligibility.json",
            "automatic_appraisal.json",
            "final_decisions.json",
            "full_text_decisions.csv",
            "search_strategy.json",
            "search_log.json",
            "retrieved_records.json",
            "duplicates.json",
            "appraisals.json",
            "appraisal_proposals.json",
            "eligibility_proposals.json",
            "screening_progress.json",
            "prisma_flow.json",
            "prisma_flow.svg",
            "prisma_flow.png",
            "prisma_checklist.json",
            "evidence_table.csv",
            "numerical_results.csv",
            "narrative_proposals.json",
            "scientific_manuscript.json",
            "full_text_progress.json",
            "evidence_map.csv",
            "references.bib",
            "literature_review.docx",
            "meta_analysis_template.csv",
            "full_text.json",
            "human_decisions.json",
            "human_review_queue.json",
            "review_status.json",
            "evidence.json",
            "approved_evidence.json",
            "literature_review.md",
            "quality_review.json",
            "review_statistics.json",
        )
    ]
    sources.append(review / "workflow_state.json")
    sources = [source for source in sources if source.exists()]
    if not sources:
        return
    archive = outputs / "history" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    archive.mkdir(parents=True)
    for source in sources:
        shutil.copy2(source, archive / source.name)
    print(f"Previous outputs archived: {archive}", flush=True)
