"""Download, test and adopt a model only if local diagnostic and GPU checks pass.

The original model stays active while downloading. Every phase is recorded.
Source documents and actual human decisions are never rewritten.
"""

import argparse
import json
import math
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.audit_models import api, run  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]
AUDIT = PROJECT / "data/model_audits"
STATUS = AUDIT / "upgrade_status.json"


def status(phase, **values):
    previous = json.loads(STATUS.read_text()) if STATUS.exists() else {}
    previous.update(status=phase, updated_at=datetime.now(UTC).isoformat(), **values)
    temp = STATUS.with_suffix(".tmp")
    temp.write_text(json.dumps(previous, indent=2))
    temp.replace(STATUS)
    print(phase, flush=True)


def wait_idle(app, review_id):
    for _ in range(360):
        reviews = api(app, "/api/reviews")
        ids = {item["id"] for item in reviews} | {review_id}
        jobs = [api(app, f"/api/reviews/{rid}/run") for rid in ids]
        if all(job.get("status") not in ("queued", "running") for job in jobs):
            return
        time.sleep(10)
    raise RuntimeError("The review is still running; migration was not forced")


def download(base, model):
    request = Request(
        base + "/api/pull",
        data=json.dumps({"model": model, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    last = 0
    with urlopen(request, timeout=120) as response:
        for raw in response:
            item = json.loads(raw)
            if item.get("error"):
                raise RuntimeError(item["error"])
            if time.monotonic() - last >= 10 or item.get("status") == "success":
                status("downloading", download=item)
                last = time.monotonic()


def update_default(model):
    path = PROJECT / ".env"
    lines = path.read_text().splitlines()
    old = next(
        (line.split("=", 1)[1] for line in lines if line.startswith("OLLAMA_MODEL=")),
        None,
    )
    lines = [line for line in lines if not line.startswith("OLLAMA_MODEL=")]
    lines.append("OLLAMA_MODEL=" + model)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=".env.", delete=False
    ) as handle:
        handle.write("\n".join(lines) + "\n")
        tmp = handle.name
    os.replace(tmp, path)
    return old


def referenced(model):
    env_path = PROJECT / ".env"
    if env_path.exists() and any(
        line == "OLLAMA_MODEL=" + model for line in env_path.read_text().splitlines()
    ):
        return True
    return any(
        json.loads(p.read_text()).get("model") == model
        for p in (PROJECT / "data/reviews").glob("*/outputs/runtime_settings.json")
    )


def adoption_check(candidate, baseline):
    loaded = candidate.get("loaded_model") or {}
    gpu_fraction = (
        loaded.get("size_vram", 0) / loaded["size"] if loaded.get("size") else 0
    )
    critical = {
        "missing_split",
        "cited_work_not_this_study",
        "missing_detail_not_absence",
        "table_wrong_dataset",
        "crossvalidation_not_annotation",
    }
    rows = {row["id"]: row for row in candidate["cases"]}
    safe = all(rows.get(key, {}).get("correct") is True for key in critical)
    accepted = (
        candidate["passed"] > baseline["passed"]
        and safe
        and candidate.get("embedding_coexistence_ok") is True
        and gpu_fraction >= 0.95
        and (candidate.get("median_tokens_per_second") or 0) >= 15
    )
    return accepted, gpu_fraction


def main(args):
    AUDIT.mkdir(parents=True, exist_ok=True)
    status(
        "starting",
        candidate=args.model,
        review_id=args.review_id,
        adoption_rule="Strict diagnostic score must improve over baseline, all critical negation/attribution cases must pass, full GPU residency >=95%, median generation >=15 tokens/s. No human review accuracy is inferred.",
    )
    for attempt in range(3):
        try:
            download(args.base_url, args.model)
            break
        except Exception as error:
            status("download_retry", error=str(error), attempt=attempt + 1)
            if attempt == 2:
                raise
            time.sleep(10)
    status("waiting_for_idle_application")
    wait_idle(args.app_url, args.review_id)
    status("benchmarking")
    report = run(
        args.base_url,
        [args.model],
        AUDIT / "candidate_diagnostic.json",
        keep_loaded=True,
    )
    candidate = report["models"][0]
    status("checking_embedding_memory")
    try:
        embedding = next(
            (
                line.split("=", 1)[1]
                for line in (PROJECT / ".env").read_text().splitlines()
                if line.startswith("EMBEDDING_MODEL=")
            ),
            "qwen3-embedding:0.6b",
        )
        vectors = api(
            args.base_url,
            "/api/embed",
            {
                "model": embedding,
                "input": "Instruct: Retrieve relevant scientific evidence.\nQuery: model evaluation",
                "options": {"num_gpu": 0, "num_ctx": 8192},
            },
        )["embeddings"]
        loaded = api(args.base_url, "/api/ps")["models"]
        candidate["loaded_model"] = next(
            (m for m in loaded if m["name"] == args.model), None
        )
        embedder = next((m for m in loaded if m["name"] == embedding), None)
        candidate["embedding_coexistence_ok"] = bool(
            vectors
            and vectors[0]
            and all(map(math.isfinite, vectors[0]))
            and embedder
            and embedder.get("size_vram") == 0
            and candidate["loaded_model"]
        )
        candidate["embedding_execution"] = {
            "model": embedding,
            "dimensions": len(vectors[0]),
            "num_gpu": 0,
        }
    except Exception as error:
        candidate["embedding_coexistence_ok"] = False
        candidate["embedding_execution_error"] = str(error)
    (AUDIT / "candidate_diagnostic.json").write_text(json.dumps(report, indent=2))
    baseline = json.loads((AUDIT / "local_diagnostic.json").read_text())["models"][0]
    accepted, gpu_fraction = adoption_check(candidate, baseline)
    status(
        "candidate_verified" if accepted else "not_adopted",
        passed=candidate["passed"],
        total=candidate["total"],
        baseline_passed=baseline["passed"],
        gpu_fraction=gpu_fraction,
        median_tokens_per_second=candidate.get("median_tokens_per_second"),
    )
    if not accepted:
        if not referenced(args.model):
            request = Request(
                args.base_url + "/api/delete",
                data=json.dumps({"model": args.model}).encode(),
                headers={"Content-Type": "application/json"},
                method="DELETE",
            )
            with urlopen(request, timeout=60):
                pass
            status("not_adopted", candidate_removed=True)
        return
    wait_idle(args.app_url, args.review_id)
    if (PROJECT / "data/reviews" / args.review_id / "outputs/pause_requested").exists():
        status("candidate_verified_review_paused", review_ready=False)
        return
    previous = update_default(args.model)
    status("adopting", previous_default=previous)
    # Per-review workers receive the model explicitly. Do not restart a live
    # backend unattended: the .env default takes effect on its next restart.
    status("adopting", previous_default=previous, default_restart_pending=True)
    wait_idle(args.app_url, args.review_id)
    migration = api(
        args.app_url,
        f"/api/reviews/{args.review_id}/generation-model",
        {"model": args.model},
    )
    job = api(args.app_url, f"/api/reviews/{args.review_id}/run", {})
    status("adopted_review_running", migration=migration, job_id=job.get("id"))
    wait_idle(args.app_url, args.review_id)
    detail = api(args.app_url, f"/api/reviews/{args.review_id}")
    result = detail.get("automatic_result") or {}
    status(
        "complete" if result.get("ready") else "adopted_needs_scientific_review",
        review_ready=result.get("ready"),
        writing=result.get("writing"),
    )
    # Remove the previous model only after a real, current manuscript completes
    # and no review configuration still depends on it.
    server_default = api(args.app_url, "/api/runtime")["configuration"]["llm"]
    status(
        "complete" if result.get("ready") else "adopted_needs_scientific_review",
        default_restart_pending=server_default != args.model,
    )
    if (
        server_default == args.model
        and result.get("ready")
        and previous
        and previous != args.model
        and not referenced(previous)
    ):
        request = Request(
            args.base_url + "/api/delete",
            data=json.dumps({"model": previous}).encode(),
            headers={"Content-Type": "application/json"},
            method="DELETE",
        )
        with urlopen(request, timeout=60):
            pass
        status("complete", previous_model_removed=previous)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--app-url", default="http://localhost:8000")
    parser.add_argument("--model", default="qwen3.5:9b-q4_K_M")
    parser.add_argument("--review-id", required=True)
    args = parser.parse_args()
    try:
        main(args)
    except Exception as error:
        status("failed", error=str(error))
        raise
