"""Export unlabelled review samples and predictions for a genuine human-reference benchmark."""

import argparse
from pathlib import Path

from storage.human_review import read_json
from storage.review_manager import get_review_path, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_id")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = get_review_path(args.review_id)
    papers = read_json(root / "papers.json", [])
    args.directory.mkdir(parents=True, exist_ok=True)
    labels = [
        {
            "paper_id": p["id"].split("/")[-1],
            "title": p.get("title"),
            "decision": None,
            "reviewer": None,
            "manual_seconds": None,
            "citation_correct": None,
            "extraction_correct": None,
            "required_fields_complete": None,
        }
        for p in papers
    ]
    predictions = [
        {
            "paper_id": p["id"].split("/")[-1],
            "decision": p.get("screening", {}).get("decision", "uncertain"),
            "reviewer_decisions": [
                r["decision"] for r in p.get("screening", {}).get("reviews", [])
            ],
            "automated_seconds": p.get("screening", {}).get("elapsed_seconds"),
        }
        for p in papers
    ]
    for name, values in (("labels.json", labels), ("predictions.json", predictions)):
        if (args.directory / name).exists():
            raise ValueError("Use a new directory to avoid overwriting human labels")
        write_json(args.directory / name, values)
    write_json(
        args.directory / "reference_material.json",
        {
            "review_id": args.review_id,
            "protocol": read_json(root / "protocol.json", {}).get("protocol"),
            "papers": [
                {
                    "paper_id": p["id"].split("/")[-1],
                    "title": p.get("title"),
                    "abstract": p.get("abstract"),
                    "doi": p.get("doi"),
                }
                for p in papers
            ],
            "evidence": read_json(root / "outputs/evidence.json", []),
            "instructions": "Read the protocol and original sources before reviewing machine predictions. Label title/abstract screening for all sampled records. For each available full text verify citation, extraction and required fields separately. Record actual manual screening seconds; do not include full-text audit time in a screening-only comparison. Leave unavailable assessments null.",
        },
    )


if __name__ == "__main__":
    main()
