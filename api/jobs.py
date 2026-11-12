"""One local workflow worker, with per-review mutation locks and durable run logs."""

import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from methodology.runtime import worker_environment
from storage.human_review import read_json
from storage.review_manager import get_review_path, write_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(UTC).isoformat()


class BusyReview(ValueError):
    pass


class JobManager:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="review")
        self.guard = threading.RLock()
        self.locks = {}
        self.active = {}
        self.processes = {}
        self.stopping = False

    def lock(self, review_id):
        with self.guard:
            return self.locks.setdefault(review_id, threading.Lock())

    @contextmanager
    def mutation(self, review_id):
        lock = self.lock(review_id)
        if not lock.acquire(blocking=False):
            raise BusyReview(
                "This review is running. Wait for it to finish before making changes."
            )
        try:
            with self.guard:
                if self.active.get(review_id, {}).get("status") in (
                    "queued",
                    "running",
                ):
                    raise BusyReview(
                        "This review already has a queued or running workflow."
                    )
            yield
        finally:
            lock.release()

    def status(self, review_id):
        root = get_review_path(review_id)
        with self.guard:
            active = self.active.get(review_id)
            result = (
                dict(active) if active else read_json(root / "outputs/api_run.json", {})
            )
        if not active and result.get("status") in ("queued", "running"):
            result.update(
                status="interrupted",
                error="The API restarted. Resume this review to continue from its checkpoint.",
            )
        if result.get("id"):
            log = root / "outputs" / "runs" / f"{result['id']}.log"
            if (
                log.is_file()
                and log.resolve().parent == (root / "outputs/runs").resolve()
            ):
                with log.open("rb") as file:
                    file.seek(max(0, log.stat().st_size - 24000))
                    result["log"] = file.read().decode("utf-8", errors="replace")
        return result

    def pause(self, review_id):
        root = get_review_path(review_id)
        with self.guard:
            job = self.active.get(review_id)
            if not job or job.get("status") not in ("queued", "running"):
                raise BusyReview("No active workflow to pause.")
            (root / "outputs/pause_requested").touch()
            job["pause_requested"] = True
            return dict(job)

    def start(self, review_id):
        root = get_review_path(review_id)
        with self.mutation(review_id), self.guard:
            if self.stopping:
                raise BusyReview("The API is shutting down.")
            (root / "outputs/pause_requested").unlink(missing_ok=True)
            (root / "outputs/progress.json").unlink(missing_ok=True)
            state = read_json(root / "workflow_state.json", {})
            if state.get("status") == "awaiting_step_confirmation":
                from methodology.protocol import load_protocol

                document = load_protocol(review_id)
                if (
                    document
                    and document.get("approval")
                    and document["fingerprint"] == state.get("protocol_fingerprint")
                ):
                    raise BusyReview(
                        "Confirm the current step in Review assistant before continuing."
                    )
            environment = worker_environment(review_id)
            job = {
                "id": uuid.uuid4().hex,
                "review_id": review_id,
                "model_environment": environment,
                "status": "queued",
                "started_at": now(),
                "finished_at": None,
            }
            self.active[review_id] = job
            write_json(root / "outputs/api_run.json", job)
            self.executor.submit(self._run, review_id)
            return dict(job)

    def _run(self, review_id):
        root = get_review_path(review_id)
        with self.lock(review_id):
            with self.guard:
                job = self.active[review_id]
                job["status"] = "running"
                write_json(root / "outputs/api_run.json", job)
            folder = root / "outputs/runs"
            folder.mkdir(parents=True, exist_ok=True)
            try:
                with (folder / f"{job['id']}.log").open("w", encoding="utf-8") as log:
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-u",
                            str(PROJECT_ROOT / "main.py"),
                            "--review-id",
                            review_id,
                        ],
                        cwd=PROJECT_ROOT,
                        env={**os.environ, **job["model_environment"]},
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                    with self.guard:
                        self.processes[review_id] = process
                        if self.stopping:
                            process.terminate()
                    code = process.wait()
                state = read_json(root / "workflow_state.json", {})
                with self.guard:
                    job.update(
                        status="interrupted"
                        if self.stopping
                        else ("completed" if code == 0 else "failed"),
                        workflow_status=state.get("status", "unknown"),
                        exit_code=code,
                    )
                    if code and not self.stopping:
                        job["error"] = (
                            "The workflow stopped with an error. Inspect the run log and resume after resolving it."
                        )
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                with self.guard:
                    job.update(status="failed", error=str(error))
            finally:
                with self.guard:
                    self.processes.pop(review_id, None)
                    job["finished_at"] = now()
                    write_json(root / "outputs/api_run.json", job)

    def close(self):
        with self.guard:
            self.stopping = True
            for process in self.processes.values():
                if process.poll() is None:
                    process.terminate()
        self.executor.shutdown(wait=True, cancel_futures=True)
