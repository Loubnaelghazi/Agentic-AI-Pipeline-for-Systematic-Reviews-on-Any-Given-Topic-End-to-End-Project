"""Optional fixed-effect inverse-variance pooling of explicitly human-verified, comparable estimates."""

import argparse
import csv
import json
import math
from pathlib import Path


def pool(rows, reviewer, comparability_reason):
    if len(rows) < 2 or not reviewer.strip() or not comparability_reason.strip():
        raise ValueError(
            "Two comparable estimates and a human comparability assessment are required"
        )
    if any(not str(r.get("study_id", "")).strip() for r in rows):
        raise ValueError("Confirm an independent study identifier for every estimate")
    if len({r["study_id"] for r in rows}) != len(rows):
        raise ValueError(
            "Use one independent estimate per study; duplicated report IDs are not allowed"
        )
    for key in ("outcome", "effect_measure", "comparison_group"):
        if (
            any(not r.get(key, "").strip() for r in rows)
            or len({r[key] for r in rows}) != 1
        ):
            raise ValueError(f"Estimates must share a confirmed {key}")
    if any(str(r.get("human_verified", "")).lower() != "true" for r in rows):
        raise ValueError("All estimates must be explicitly human verified")
    effects = [float(r["effect"]) for r in rows]
    errors = [float(r["standard_error"]) for r in rows]
    if any(not math.isfinite(e) for e in effects + errors) or any(
        e <= 0 for e in errors
    ):
        raise ValueError("Finite effects and positive standard errors required")
    weights = [1 / e**2 for e in errors]
    mean = sum(w * e for w, e in zip(weights, effects, strict=True)) / sum(weights)
    se = math.sqrt(1 / sum(weights))
    q = sum(w * (e - mean) ** 2 for w, e in zip(weights, effects, strict=True))
    return {
        "method": "fixed-effect inverse variance; input scale retained",
        "effect": mean,
        "standard_error": se,
        "ci95": [mean - 1.96 * se, mean + 1.96 * se],
        "Q": q,
        "I2_percent": max(0, (q - len(rows) + 1) / q) * 100 if q else 0,
        "reviewer": reviewer,
        "comparability_reason": comparability_reason,
        "k": len(rows),
        "note": "Human attestation does not itself establish clinical or methodological homogeneity. Ratio measures must already be on an appropriate analysis scale.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--comparability-reason", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.input.open() as stream:
        result = pool(
            list(csv.DictReader(stream)), args.reviewer, args.comparability_reason
        )
    args.output.write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
