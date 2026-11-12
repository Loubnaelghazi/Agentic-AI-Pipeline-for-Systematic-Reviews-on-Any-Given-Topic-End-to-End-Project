import hashlib

import httpx
import requests
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

from agents.transport import retry_ollama, retry_ollama_async
from config import (
    EMBEDDING_MODEL,
    EMBEDDING_NUM_GPU,
    OLLAMA_BASE_URL,
    OLLAMA_NUM_CTX,
    OLLAMA_REQUEST_TIMEOUT,
)
from storage.review_manager import get_review_path, write_json


class RetrievalEmbeddings(OllamaEmbeddings):
    def query_text(self, text):
        if self.model.startswith("qwen3-embedding"):
            text = (
                "Instruct: Retrieve scientific passages relevant to the research question."
                "\nQuery: " + text
            )
        elif self.model.startswith("nomic-embed-text"):
            text = "search_query: " + text
        return text

    def document_texts(self, texts):
        if self.model.startswith("nomic-embed-text"):
            texts = ["search_document: " + text for text in texts]
        return texts

    def embed_query(self, text):
        # Ollama's base embed_query delegates to self.embed_documents; calling it
        # here would add a document prefix to an already-prefixed query.
        parent = super().embed_documents
        return retry_ollama(lambda: parent([self.query_text(text)]))[0]

    def embed_documents(self, texts):
        parent = super().embed_documents
        return retry_ollama(lambda: parent(self.document_texts(texts)))

    async def aembed_query(self, text):
        parent = super().aembed_documents
        return (await retry_ollama_async(lambda: parent([self.query_text(text)])))[0]

    async def aembed_documents(self, texts):
        parent = super().aembed_documents
        return await retry_ollama_async(lambda: parent(self.document_texts(texts)))


def index_identity(embedding_model=None, revision="unresolved"):
    embedding_model = embedding_model or EMBEDDING_MODEL
    # Never mix embedding spaces, including models with equal dimensions.
    return hashlib.sha256(
        (
            OLLAMA_BASE_URL
            + "|"
            + embedding_model
            + "|"
            + revision
            + "|instructions-v1"
        ).encode()
    ).hexdigest()[:16]


def get_vector_store(review_id: str, embedding_model=None):
    embedding_model = embedding_model or EMBEDDING_MODEL

    def read_tags():
        response = requests.get(OLLAMA_BASE_URL + "/api/tags", timeout=(5, 15))
        response.raise_for_status()
        return response

    response = retry_ollama(read_tags)
    installed = {item["name"]: item for item in response.json()["models"]}
    model = installed.get(embedding_model) or installed.get(embedding_model + ":latest")
    if not model or not model.get("digest"):
        raise ValueError(
            f"Embedding model {embedding_model} is unavailable; pull it in Ollama first"
        )
    revision = model["digest"]
    embeddings = RetrievalEmbeddings(
        model=embedding_model,
        num_gpu=EMBEDDING_NUM_GPU,
        base_url=OLLAMA_BASE_URL,
        num_ctx=OLLAMA_NUM_CTX,
        client_kwargs={"timeout": httpx.Timeout(OLLAMA_REQUEST_TIMEOUT, connect=10)},
    )

    db_path = (
        get_review_path(review_id)
        / "indexes"
        / index_identity(embedding_model, revision)
    )
    db_path.mkdir(parents=True, exist_ok=True)
    write_json(
        db_path / "model.json",
        {
            "model": embedding_model,
            "base_url": OLLAMA_BASE_URL,
            "instruction_version": "instructions-v1",
            "digest": revision,
        },
    )

    return Chroma(
        collection_name="scientific_papers",
        embedding_function=embeddings,
        persist_directory=str(db_path),
    )
