"""Small diagnostic for local models, not a human-labelled SR benchmark.

python scripts/audit_models.py --base-url URL --models MODEL MODEL --output data/model_audits/diagnostic.json
"""

import argparse
import json
import statistics
import time
from pathlib import Path
from urllib.request import Request, urlopen

CASES = [
    (
        "negated_modality",
        "Studies using non-CXR modalities such as CT or MRI.",
        "Our study used frontal chest X-ray images exclusively to detect pneumonia. We evaluated our network on a held-out test set.",
        "no",
    ),
    (
        "missing_split",
        "Studies lacking a training and testing split.",
        "We used five-fold cross-validation with disjoint training and test folds for our model.",
        "no",
    ),
    (
        "original_not_review",
        "Systematic reviews, meta-analyses or opinion pieces.",
        "In this original experimental study we propose an ensemble and evaluate it on two publicly available datasets. We report accuracy and F1 for our model and baselines.",
        "no",
    ),
    (
        "pneumonia_outcome",
        "Studies evaluating pneumonia detection as a primary outcome.",
        "Our aim is pneumonia detection from chest radiographs. We evaluate pneumonia classification using F1 and sensitivity on a held-out dataset.",
        "yes",
    ),
    (
        "crossvalidation_not_annotation",
        "Expert physicians independently annotated every image.",
        "We evaluated our neural network with five-fold cross-validation. Our F1 was 0.81. The report gives no annotation procedure.",
        "unknown",
    ),
    (
        "cited_work_not_this_study",
        "The evaluated study uses CT images.",
        "Smith et al. used CT images to detect pneumonia. Our study proposes a new classifier but the supplied excerpt does not describe our imaging modality.",
        "unknown",
    ),
    (
        "missing_detail_not_absence",
        "Studies without a test set.",
        "Our model uses a convolutional backbone with dropout. This supplied passage does not discuss the evaluation design.",
        "unknown",
    ),
    (
        "table_correct_metric",
        "The proposed model has F1 98.79 percent on Kermany.",
        "Own experiment, Table 9: Dataset Kermany; Model Proposed; Accuracy 98.81%; Precision 98.82%; Recall 98.80%; F1 98.79%; AUC 98.35%.",
        "yes",
    ),
    (
        "table_wrong_metric",
        "The proposed model has AUC 98.79 percent on Kermany.",
        "Own experiment, Table 9: Dataset Kermany; Model Proposed; Accuracy 98.81%; F1 98.79%; AUC 98.35%.",
        "no",
    ),
    (
        "table_wrong_dataset",
        "The proposed model has F1 98.79 percent on RSNA.",
        "Our experiments: Kermany proposed F1 98.79%; RSNA proposed F1 86.95%.",
        "no",
    ),
    (
        "nonmedical_original",
        "The publication is a narrative review rather than original research.",
        "We built a solar cell, measured its output in our laboratory and compared its efficiency with three baselines. This paper reports our new experimental measurements.",
        "no",
    ),
    (
        "nonmedical_missing_control",
        "Studies lacking a comparator.",
        "We tested our new battery against two commercial control batteries under the same load and temperature.",
        "no",
    ),
]
SCHEMA = {
    "type": "object",
    "properties": {
        "condition_met": {"type": "string", "enum": ["yes", "no", "unknown"]},
        "quote": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["condition_met", "quote", "reason"],
    "additionalProperties": False,
}


def api(base, path, data=None):
    request = Request(
        base.rstrip("/") + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=300) as response:
        return json.load(response)


def run(base, models, output, *, keep_loaded=False):
    tags = {m["name"]: m for m in api(base, "/api/tags")["models"]}
    report = {
        "purpose": "Diagnostic explicit-source cases; not human review accuracy or a publication benchmark",
        "context_tokens": 8192,
        "temperature": 0,
        "models": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    for model in models:
        if model not in tags:
            print(f"Unavailable: {model}", flush=True)
            continue
        details = api(base, "/api/show", {"model": model})
        result = {
            "name": model,
            "digest": tags[model]["digest"],
            "size_bytes": tags[model]["size"],
            "cases": [],
        }
        report["models"].append(result)
        for name, criterion, context, expected in CASES:
            payload = {
                "model": model,
                "stream": False,
                "format": SCHEMA,
                "keep_alive": "10m",
                "options": {"num_ctx": 8192, "num_predict": 450, "temperature": 0},
                "messages": [
                    {
                        "role": "user",
                        "content": "Evaluate ONE property of THIS STUDY, not a review's exclusion policy. yes if the literal property holds, no if its opposite is established, unknown if not established. Use only supplied text and distinguish cited work. Missing details do not prove absence. Return a short reason and exact source quote for yes/no.\nPROPERTY: "
                        + criterion
                        + "\nSOURCE: "
                        + context,
                    }
                ],
            }
            if "thinking" in details.get("capabilities", []):
                payload["think"] = False
            started = time.perf_counter()
            try:
                response = api(base, "/api/chat", payload)
                value = json.loads(response["message"]["content"])
                grounded = value.get("condition_met") == "unknown" or (
                    len(value.get("quote", "")) >= 15
                    and " ".join(value["quote"].split()) in " ".join(context.split())
                )
                tokens = response.get("eval_count", 0)
                seconds = response.get("eval_duration", 0) / 1e9
                row = {
                    "id": name,
                    "expected": expected,
                    "response": value,
                    "grounded": grounded,
                    "correct": grounded and value.get("condition_met") == expected,
                    "elapsed_seconds": time.perf_counter() - started,
                    "tokens_per_second": tokens / seconds if seconds else None,
                }
            except Exception as error:
                row = {
                    "id": name,
                    "expected": expected,
                    "correct": False,
                    "error": str(error),
                }
            result["cases"].append(row)
            result["passed"] = sum(r["correct"] for r in result["cases"])
            result["total"] = len(CASES)
            output.write_text(json.dumps(report, indent=2))
            print(model, name, "PASS" if row["correct"] else "FAIL", flush=True)
        result["loaded_model"] = next(
            (m for m in api(base, "/api/ps")["models"] if m["name"] == model), None
        )
        speeds = [
            r["tokens_per_second"]
            for r in result["cases"]
            if r.get("tokens_per_second")
        ]
        result["median_tokens_per_second"] = (
            statistics.median(speeds) if speeds else None
        )
        output.write_text(json.dumps(report, indent=2))
        # Release memory before comparing the next model on an 8 GB GPU.
        if not keep_loaded:
            api(base, "/api/generate", {"model": model, "keep_alive": 0})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.base_url, args.models, args.output)
