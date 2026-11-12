"""Shared local/container configuration; environment variables override .env."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR = (
    Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser().resolve()
)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
# Keep the small embedder off limited VRAM so it cannot evict the larger LLM.
EMBEDDING_NUM_GPU = int(os.getenv("EMBEDDING_NUM_GPU", "0"))


def cors_origins():
    default = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
    return list(
        dict.fromkeys(
            origin.strip().rstrip("/")
            for origin in os.getenv("CORS_ORIGINS", default).split(",")
            if origin.strip()
        )
    )


# Worker-specific request value; None preserves the selected model default.
OLLAMA_REASONING = json.loads(os.getenv("OLLAMA_REASONING", "null"))
# Critical eligibility auditing can reason carefully while drafting stays fast.
OLLAMA_AUDIT_REASONING = json.loads(os.getenv("OLLAMA_AUDIT_REASONING", "true"))

OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0"))

OLLAMA_REQUEST_TIMEOUT = float(os.getenv("OLLAMA_REQUEST_TIMEOUT", "300"))
OLLAMA_RETRY_ATTEMPTS = max(1, int(os.getenv("OLLAMA_RETRY_ATTEMPTS", "2")))

OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() == "true"
AI_PLANNER_ENABLED = os.getenv("AI_PLANNER_ENABLED", "true").lower() == "true"
PIPELINE_VERSION = "teammate-integration-v1"


def model_config():
    return {
        "llm": OLLAMA_MODEL,
        "embedding": EMBEDDING_MODEL,
        "base_url": OLLAMA_BASE_URL,
        "num_ctx": OLLAMA_NUM_CTX,
        "rerank": RERANK_ENABLED,
        "pipeline_version": PIPELINE_VERSION,
        "thinking": OLLAMA_REASONING,
        "temperature": OLLAMA_TEMPERATURE,
    }
