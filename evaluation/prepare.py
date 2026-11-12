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


if __name__ == "__main__":
    main()
