import argparse
import os

from storage.review_manager import create_review


def main():
    parser = argparse.ArgumentParser(
        description="Run or resume a preliminary scientific review"
    )
    parser.add_argument("--topic")
    parser.add_argument(
        "--thinking",
        help="Model thinking mode: default, on, off, or a supported named level",
    )
    parser.add_argument("--review-id", help="Resume an existing review")
    args = parser.parse_args()
    if args.review_id and args.topic:
        parser.error("Use either --topic or --review-id")
    review_id = args.review_id
    if not review_id:
        topic = (args.topic or input("Enter your research topic: ")).strip()
        if not topic:
            parser.error("Research topic cannot be empty")
        review_id, _ = create_review(topic)
    import config
    from methodology.runtime import reasoning_value, save_thinking, settings

    if args.thinking is not None:
        save_thinking(review_id, args.thinking)
    if args.thinking is not None or "OLLAMA_REASONING" not in os.environ:
        config.OLLAMA_REASONING = reasoning_value(review_id)
    runtime = settings(review_id)
    config.OLLAMA_MODEL = runtime["model"]
    config.OLLAMA_TEMPERATURE = runtime["temperature"]
    if runtime["mode"] == "automatic":
        from workflow.automatic import run_review
    else:
        from workflow.graph import run_review

    print(f"Review ID: {review_id}", flush=True)
    result = run_review(review_id)
    print(f"Status: {result['status']}\nWorkspace: {result['review_path']}")
    if result["status"].startswith("awaiting_"):
        if result["status"] == "awaiting_protocol_review":
            print(
                f"Inspect protocol: uv run python -m methodology.protocol show {review_id}"
            )
        elif result["status"] == "awaiting_step_confirmation":
            print("Confirm this phase in Review assistant: http://localhost:3000")
        else:
            print(
                f"Inspect review tasks in the dashboard or: uv run python human_review.py {review_id}"
            )
        print(
            "Report currency and pending tasks are recorded in outputs/review_status.json."
        )


if __name__ == "__main__":
    main()
