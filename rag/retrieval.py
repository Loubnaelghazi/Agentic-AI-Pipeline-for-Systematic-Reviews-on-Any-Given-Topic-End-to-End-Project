"""Dense + BM25-like sparse retrieval, reciprocal-rank fusion and extractive compression."""

import logging
import math
import re
from collections import Counter

from langchain_core.documents import Document
from langchain_core.exceptions import OutputParserException

from agents.transport import transient_error
from config import RERANK_ENABLED


def tokens(text):
    return re.findall(r"\w+", text.casefold())


def hybrid_search(store, query, source, k=5, trace=None, use_reranker=None):
    use_reranker = RERANK_ENABLED if use_reranker is None else use_reranker
    dense = store.similarity_search(query, k=max(k * 2, 10), filter={"source": source})
    raw = store.get(where={"source": source}, include=["documents", "metadatas"])
    corpus = [tokens(t) for t in raw.get("documents", [])]
    terms = set(tokens(query))
    average = sum(map(len, corpus)) / len(corpus) if corpus else 1
    counts = [Counter(words) for words in corpus]
    frequency = {term: sum(term in c for c in counts) for term in terms}
    sparse = []
    for index, count in enumerate(counts):
        score = sum(
            math.log(1 + (len(corpus) - frequency[t] + 0.5) / (frequency[t] + 0.5))
            * (count[t] * 2.2)
            / (count[t] + 1.2 * (0.25 + 0.75 * len(corpus[index]) / average))
            for t in terms
            if count[t]
        )
        if score:
            sparse.append(
                (
                    score,
                    Document(
                        page_content=raw["documents"][index],
                        metadata=raw["metadatas"][index] or {},
                    ),
                )
            )
    rankings = [
        dense,
        [doc for _, doc in sorted(sparse, key=lambda row: row[0], reverse=True)],
    ]
    scores, documents = {}, {}
    for ranking in rankings:
        for rank, document in enumerate(ranking, 1):
            key = document.page_content
            documents[key] = document
            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
    candidates = [
        documents[key] for key in sorted(scores, key=scores.get, reverse=True)[:10]
    ]
    rerank_error = None
    reranked = False
    if use_reranker:
        from rag.rerank import rerank

        try:
            candidates = rerank(query, candidates)
            reranked = True
        except Exception as error:
            if not transient_error(error) and not isinstance(
                error, (ValueError, OutputParserException)
            ):
                raise
            rerank_error = f"{type(error).__name__}: {error}"
            logging.getLogger(__name__).warning(
                "Optional reranking failed; using saved dense/sparse fusion: %s",
                rerank_error,
            )
    if trace is not None:
        trace.append(
            {
                "query": query,
                "source": source,
                "reranked": reranked,
                "rerank_requested": use_reranker,
                "rerank_error": rerank_error,
                "results": [
                    {
                        "text": d.page_content,
                        "metadata": d.metadata,
                        "rrf_score": scores[d.page_content],
                    }
                    for d in candidates[:k]
                ],
            }
        )
    return candidates[:k]


def compress(text, query, max_chars=1800):
    """Keep a contiguous, source-exact window around the most overlapping sentence."""
    if len(text) <= max_chars:
        return text
    terms = set(tokens(query))
    matches = list(re.finditer(r"[^.!?]+[.!?]", text))
    best = max(matches, key=lambda m: len(terms & set(tokens(m.group()))), default=None)
    start = max(0, (best.start() if best else 0) - 200)
    return text[start : start + max_chars]
