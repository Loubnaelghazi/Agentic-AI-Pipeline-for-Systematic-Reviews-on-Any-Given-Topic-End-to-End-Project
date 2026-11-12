import sys
from collections import defaultdict

from agents.client import chat_model
from methodology.runtime import reasoning_value, settings
from rag.retrieval import hybrid_search
from rag.vector_store import get_vector_store
from storage.review_manager import get_review_path


def ask_question(review_id: str, question: str):
    store = get_vector_store(review_id)

    indexed = store.get(include=["metadatas"])
    sources = sorted(
        {m["source"] for m in indexed.get("metadatas", []) if m and m.get("source")}
    )
    documents = [
        document
        for source in sources
        for document in hybrid_search(store, question, source, k=2)
    ]

    if not documents:
        print("No indexed documents found.")
        return

    grouped = defaultdict(list)

    for doc in documents:
        source = doc.metadata["source"]

        if len(grouped[source]) < 2:
            grouped[source].append(doc)

    context_parts = []

    for source, chunks in grouped.items():
        for chunk in chunks:
            context_parts.append(f"Source: {source}\n{chunk.page_content}")

    context = "\n\n---\n\n".join(context_parts)

    llm = chat_model(
        1500,
        timeout=180,
        model=settings(review_id)["model"],
        reasoning=reasoning_value(review_id),
        temperature=settings(review_id)["temperature"],
    )

    prompt = f"""
You are a scientific research assistant.

Answer using ONLY the retrieved scientific evidence.

Rules:
- Do not invent information.
- Cite paper filenames when making claims.
- Clearly distinguish findings from different papers.
- If evidence is insufficient, explain what is missing.
- Do not claim to have read papers beyond the excerpts.

Evidence:
{context}

Question:
{question}
"""

    response = llm.invoke(prompt)

    print("\nAI Answer:")
    print(response.content)

    print("\nSources used:")
    for source in grouped:
        print(f"- {source}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python -m rag.ask <review_id>")
        sys.exit(1)

    review_id = sys.argv[1]

    get_review_path(review_id)

    question = input("Ask a question about your papers: ")
    ask_question(review_id, question)
