"""Run one review-scoped stage without duplicating the full workflow CLI."""

import argparse

from storage.human_review import read_json
from storage.review_manager import get_review_path
from workflow import nodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=("download", "extraction", "synthesis", "quality")
    )
    parser.add_argument("review_id")
    args = parser.parse_args()
    try:
        path = get_review_path(args.review_id)
        state = {
            "review_id": args.review_id,
            "topic": (path / "topic.txt").read_text(encoding="utf-8").strip(),
            "papers": read_json(path / "papers.json", []),
            "full_text": read_json(path / "outputs/full_text.json", []),
            "evidence": read_json(path / "outputs/evidence.json", []),
        }
        report = path / "outputs/literature_review.md"
        if report.exists():
            state["report"] = report.read_text(encoding="utf-8")
        if args.stage == "download":
            state.update(nodes.screening_review(state))
            if state["pending_review_items"]:
                parser.error(
                    "Resolve uncertain screening decisions before downloading full texts"
                )
        getattr(nodes, args.stage)(state)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
