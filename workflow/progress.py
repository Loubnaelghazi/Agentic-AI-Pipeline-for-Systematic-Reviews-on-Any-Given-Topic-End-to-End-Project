"""Durable live progress and cooperative pauses at saved-work boundaries."""

from datetime import UTC, datetime

from storage.review_manager import get_review_path, write_json


class WorkflowPaused(Exception):
    pass


def check_pause(review_id):
    if (get_review_path(review_id) / "outputs/pause_requested").exists():
        raise WorkflowPaused("Paused at a safe checkpoint. Saved work will be reused.")


def progress(review_id, stage, completed=0, total=None, message=""):
    check_pause(review_id)
    write_json(
        get_review_path(review_id) / "outputs/progress.json",
        {
            "stage": stage,
            "completed": completed,
            "total": total,
            "message": message,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
