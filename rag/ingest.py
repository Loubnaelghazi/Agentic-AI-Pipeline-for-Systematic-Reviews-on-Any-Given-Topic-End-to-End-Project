import hashlib
import sys
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag.vector_store import get_vector_store
from storage.review_manager import get_review_path


def ingest_papers(review_id: str, embedding_model=None):
    if Path(review_id).name != review_id or not review_id:
        raise ValueError("Invalid review ID")

    folder = get_review_path(review_id) / "papers"

    if not folder.is_dir():
        print("Review papers directory not found.")
        return

    files = sorted(folder.glob("*.txt"))

    if not files:
        store = get_vector_store(review_id, embedding_model)
        old_ids = store.get(include=[])["ids"]
        for start in range(0, len(old_ids), 500):
            store.delete(ids=old_ids[start : start + 500])
        print("No extracted text files found; current index cleared.")
        return {"chunks": 0, "added": 0}

    documents = []

    for file in files:
        text = file.read_text(encoding="utf-8")

        if text.strip():
            documents.append(
                Document(
                    page_content=text,
                    metadata={
                        "source": file.name,
                        "paper_id": file.stem,
                    },
                )
            )

    if not documents:
        store = get_vector_store(review_id, embedding_model)
        old_ids = store.get(include=[])["ids"]
        for start in range(0, len(old_ids), 500):
            store.delete(ids=old_ids[start : start + 500])
        return {"chunks": 0, "added": 0}

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=2000,
        chunk_overlap=200,
    )

    chunks = splitter.split_documents(documents)

    print(f"Generated {len(chunks)} chunks.", flush=True)

    ids = [
        hashlib.sha256(
            (
                review_id + chunk.metadata["source"] + str(index) + chunk.page_content
            ).encode("utf-8")
        ).hexdigest()
        for index, chunk in enumerate(chunks)
    ]

    store = get_vector_store(review_id, embedding_model)

    # Remove stale chunks when a PDF/text is replaced or removed. Old model
    # indexes live in distinct directories and are retained for reproducibility.
    prior = store.get(include=[])["ids"]
    stale = sorted(set(prior) - set(ids))
    for start in range(0, len(stale), 500):
        store.delete(ids=stale[start : start + 500])

    existing = set()
    for start in range(0, len(ids), 500):
        existing.update(store.get(ids=ids[start : start + 500], include=[])["ids"])
    pending = [
        (chunk, chunk_id)
        for chunk, chunk_id in zip(chunks, ids, strict=True)
        if chunk_id not in existing
    ]
    if not pending:
        return {"chunks": len(chunks), "added": 0}
    chunks, ids = map(list, zip(*pending, strict=True))
    batch_size = 10

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        batch_ids = ids[start : start + batch_size]

        store.add_documents(batch, ids=batch_ids)

        print(
            f"Indexed {min(start + batch_size, len(chunks))}/{len(chunks)} chunks",
            flush=True,
        )

    print("\nRAG ingestion completed!")
    return {"added": len(chunks)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python -m rag.ingest <review_id>")
        sys.exit(1)

    ingest_papers(sys.argv[1])
