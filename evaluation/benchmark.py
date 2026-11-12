"""Evaluate human-labelled samples: python -m evaluation.benchmark labels.json predictions.json output.json."""

import argparse
import json
import math
from pathlib import Path


def evaluate(labels, predictions):
    truth = {item["paper_id"]: item for item in labels}
    predicted = {item["paper_id"]: item for item in predictions}
    if len(truth) != len(labels) or len(predicted) != len(predictions):
        raise ValueError("Duplicate paper IDs")
    if not truth:
        raise ValueError("Human-labelled reference records are required")
    if set(predicted) != set(truth):
        raise ValueError("Predictions must cover exactly the labelled sample")
    if any(
        p.get("decision") not in ("include", "exclude", "uncertain")
        for p in predictions
    ):
        raise ValueError("Prediction labels must be include, exclude or uncertain")
    for item in labels:
        if (
            item.get("decision") not in ("include", "exclude")
            or not isinstance(item.get("reviewer"), str)
            or not item["reviewer"].strip()
        ):
            raise ValueError(
                "Each reference needs a human reviewer and include/exclude label"
            )
    tp = sum(
        t["decision"] == "include" and predicted[pid].get("decision") == "include"
        for pid, t in truth.items()
    )
    fp = sum(
        t["decision"] == "exclude" and predicted[pid].get("decision") == "include"
        for pid, t in truth.items()
    )
    fn = sum(
        t["decision"] == "include" and predicted[pid].get("decision") != "include"
        for pid, t in truth.items()
    )
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    results = {
        "sample_size": len(truth),
        "precision": precision,
        "recall": recall,
        "accuracy": sum(
            predicted[p].get("decision") == t["decision"] for p, t in truth.items()
        )
        / len(truth),
        "uncertain_predictions": sum(
            p.get("decision") == "uncertain" for p in predictions
        ),
        "f1": 2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None,
    }
    agreements = [p for p in predictions if len(p.get("reviewer_decisions", [])) == 2]
    results["simulated_reviewer_agreement"] = (
        sum(
            p["reviewer_decisions"][0] == p["reviewer_decisions"][1] for p in agreements
        )
        / len(agreements)
        if agreements
        else None
    )
    manual = [t.get("manual_seconds") for t in labels]
    automated = [p.get("automated_seconds") for p in predictions]
    valid_times = all(
        isinstance(v, (int, float)) and math.isfinite(v) and v >= 0
        for v in manual + automated
    )
    results["time_savings_fraction"] = (
        1 - sum(automated) / sum(manual) if valid_times and sum(manual) > 0 else None
    )
    for field in ("citation_correct", "extraction_correct", "required_fields_complete"):
        ratings = [t[field] for t in labels if isinstance(t.get(field), bool)]
        results[field + "_rate"] = sum(ratings) / len(ratings) if ratings else None
        results[field + "_rated_samples"] = len(ratings)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", type=Path)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = evaluate(
        json.loads(args.labels.read_text()), json.loads(args.predictions.read_text())
    )
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
