"""Read-only readiness diagnostics for the configured local model provider."""

import requests

from config import OLLAMA_BASE_URL, model_config


def inspect_runtime():
    settings = model_config()
    try:
        response = requests.get(OLLAMA_BASE_URL + "/api/tags", timeout=5)
        response.raise_for_status()
        models = response.json()["models"]
        installed = {item["name"]: item for item in models}
        resolved = {}
        for kind in ("llm", "embedding"):
            name = settings[kind]
            model = installed.get(name) or installed.get(name + ":latest")
            resolved[kind] = {
                "configured_name": name,
                "available": model is not None,
                "digest": model.get("digest") if model else None,
                "size_bytes": model.get("size") if model else None,
            }
        return {
            "ready": all(m["available"] for m in resolved.values()),
            "configuration": settings,
            "models": resolved,
            "error": None,
        }
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        return {
            "ready": False,
            "configuration": settings,
            "models": {},
            "error": str(error),
        }
