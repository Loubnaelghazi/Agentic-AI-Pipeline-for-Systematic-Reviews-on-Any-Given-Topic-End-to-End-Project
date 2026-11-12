"""Compare dense embeddings and optional reranking against human-labelled passages.

python -m evaluation.retrieval REVIEW_ID labels.json results.json --models nomic-embed-text qwen3-embedding:0.6b

Labels: [{"query": "...", "source": "W123.txt", "relevant_quotes": ["exact passage"],
          "reviewer": "human name"}]. Quotes must occur in the indexed source.
"""

import argparse
from pathlib import Path
from time import perf_counter

from rag.ingest import ingest_papers
from rag.retrieval import hybrid_search
from rag.vector_store import get_vector_store
from storage.human_review import read_json
from storage.review_manager import write_json


def score(ranked, relevant_quotes, k=5):
    hits = [any(quote in text for quote in relevant_quotes) for text in ranked[:k]]
    covered = sum(
        any(quote in text for text in ranked[:k]) for quote in relevant_quotes
    )
    return {
        "recall_at_k": covered / len(relevant_quotes),
        "reciprocal_rank": next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0),
    }


def compare(review_id, labels, models, k=5, modes=("dense", "hybrid", "reranked")):
    if not labels or not models or k < 1:
        raise ValueError("A nonempty labelled sample and positive k are required")
    for label in labels:
        if not label.get("reviewer", "").strip() or not label.get("query", "").strip():
            raise ValueError("Every query needs a named human reference reviewer")
        if not label.get("relevant_quotes") or any(
            not q.strip() for q in label["relevant_quotes"]
        ):
            raise ValueError("Reference passages must be nonempty exact quotations")
    results = []
    for model in models:
        started = perf_counter()
        ingest_papers(review_id, model)
        index_seconds = perf_counter() - started
        store = get_vector_store(review_id, model)
        for mode in modes:
            rows = []
            for label in labels:
                raw = store.get(
                    where={"source": label["source"]}, include=["documents"]
                )
                if any(
                    not any(q in text for text in raw["documents"])
                    for q in label["relevant_quotes"]
                ):
                    raise ValueError(
                        "Reference quote is missing from the indexed source; choose a quote inside a chunk"
                    )
                started = perf_counter()
                docs = (
                    store.similarity_search(
                        label["query"], k=k, filter={"source": label["source"]}
                    )
                    if mode == "dense"
                    else hybrid_search(
                        store,
                        label["query"],
                        label["source"],
                        k=k,
                        use_reranker=mode == "reranked",
                    )
                )
                rows.append(
                    {
                        "query": label["query"],
                        "source": label["source"],
                        "seconds": perf_counter() - started,
                        **score(
                            [d.page_content for d in docs], label["relevant_quotes"], k
                        ),
                    }
                )
            results.append(
                {
                    "model": model,
                    "mode": mode,
                    "k": k,
                    "index_seconds": index_seconds,
                    "sample_size": len(rows),
                    "queries": rows,
                    **{
                        key: sum(r[key] for r in rows) / len(rows)
                        for key in ("recall_at_k", "reciprocal_rank", "seconds")
                    },
                }
            )
    return {
        "scope": "within-paper passage retrieval; human reference quality determines validity",
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_id")
    parser.add_argument("labels", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new output path to retain prior evaluation results")
    write_json(
        args.output,
        compare(args.review_id, read_json(args.labels, []), args.models, args.k),
    )


if __name__ == "__main__":
    main()
