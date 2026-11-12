#Inspect human-review tasks and record one explicit decision at a time.

import argparse
import json

from storage.human_review import KINDS, record_decision, review_queue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_id")
    parser.add_argument("--item", help="Item ID shown in the review queue")
    parser.add_argument(
        "--decision", choices=("include", "exclude", "approve", "reject")
    )
    parser.add_argument("--reviewer")
    parser.add_argument("--reason")
    parser.add_argument(
        "--kind", choices=KINDS, help="Correct an approved quotation's category"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Show full queue, including abstracts and passages",
    )
    args = parser.parse_args()
    try:
        if args.decision:
            if not all((args.item, args.reviewer, args.reason)):
                parser.error("A decision requires --item, --reviewer and --reason")
            print(
                json.dumps(
                    record_decision(
                        args.review_id,
                        args.item,
                        args.decision,
                        args.reviewer,
                        args.reason,
                        args.kind,
                    ),
                    indent=2,
                )
            )
            print(f"Resume with: uv run python main.py --review-id {args.review_id}")
            return
        if args.kind or args.reviewer or args.reason:
            parser.error("Decision options require --decision")
        queue = review_queue(args.review_id)
        if args.item:
            items = [item for item in queue["items"] if item["item_id"] == args.item]
            if not items:
                parser.error("Review item not found")
            print(json.dumps(items[0], indent=2, ensure_ascii=False))
        elif args.json:
            print(json.dumps(queue, indent=2, ensure_ascii=False))
        else:
            for item in queue["items"]:
                if item["required"] or item["decision"]:
                    choice = (
                        item["decision"]["decision"]
                        if item["decision"]
                        else item["status"]
                    )
                    print(
                        f"{item['item_id']} | {choice} | {item['paper_id']} | {item.get('title') or item.get('quote', '')}"
                    )
            print(
                f"Unavailable full texts (not exclusions): {len(queue['unavailable_full_texts'])}"
            )
            print(f"Full texts not yet sought: {len(queue['full_text_not_sought'])}")
            if queue["invalid_evidence"]:
                print(
                    f"Evidence requires re-extraction: {queue['invalid_evidence']}; resume the workflow."
                )
            print("Inspect an item with --item ITEM_ID; use --json for full context.")
    except (ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
