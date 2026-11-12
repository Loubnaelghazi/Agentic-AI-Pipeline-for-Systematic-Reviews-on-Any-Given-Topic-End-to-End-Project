"""Per-review model controls, verified against the running local Ollama server."""

import json
import time
from datetime import date

import requests

from config import EMBEDDING_MODEL, OLLAMA_BASE_URL, OLLAMA_MODEL
from storage.human_review import read_json
from storage.review_manager import get_review_path, write_json

_cache = {}


def model_controls(model=None):
    model = model or OLLAMA_MODEL
    key = (OLLAMA_BASE_URL, model)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < 60:
        return cached[1]
    result = {
        "model": model,
        "options": [{"value": "default", "label": "Model default"}],
        "available": False,
        "error": None,
    }
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/show", json={"model": model}, timeout=5
        )
        response.raise_for_status()
        data = response.json()
        values = (data.get("thinking") or {}).get("values")
        if values is None and "thinking" in data.get("capabilities", []):
            family = data.get("details", {}).get("family", "")
            values = (
                ["low", "medium", "high"]
                if "gpt-oss" in model or "gptoss" in family
                else [False, True]
            )
        for value in values or []:
            if value is True:
                result["options"].append(
                    {"value": "on", "label": "On · may take longer"}
                )
            elif value is False:
                result["options"].append(
                    {"value": "off", "label": "Off · faster responses"}
                )
            elif isinstance(value, str) and value and len(value) <= 40:
                result["options"].append({"value": value, "label": value.capitalize()})
        result["available"] = any(
            o["value"] not in ("default", "off") for o in result["options"]
        )
        _cache[key] = (time.monotonic(), result)
    except (requests.RequestException, ValueError, AttributeError):
        result["error"] = (
            "Cannot inspect this model. Check that Ollama is running and the model is installed, then retry."
        )
    return result


def installed_models():
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        response.raise_for_status()
        models = [
            m
            for m in response.json().get("models", [])
            if m.get("name")
            and m["name"] != EMBEDDING_MODEL
            and not m.get("remote_model")
            and not m.get("remote_host")
            and "embed" not in m["name"].lower()
            and not m["name"].endswith((":cloud", "-cloud"))
        ]
        return {
            "models": [{"name": m["name"], "size": m.get("size")} for m in models],
            "default_model": OLLAMA_MODEL,
            "error": None,
        }
    except (requests.RequestException, ValueError):
        return {
            "models": [],
            "default_model": OLLAMA_MODEL,
            "error": "Cannot list installed models. Check Ollama and retry.",
        }


def settings(review_id):
    value = {
        "thinking": "off",
        "model": OLLAMA_MODEL,
        "mode": "guided",
        "temperature": 0.0,
        "max_records": 10,
        "sources": ["openalex", "pubmed", "arxiv"],
        "year_from": None,
        "year_to": None,
        **read_json(get_review_path(review_id) / "outputs/runtime_settings.json", {}),
    }
    value["model"] = value.get("model") or OLLAMA_MODEL
    if value["thinking"] == "default":
        value["thinking"] = "off"
    return value


def validate_year_range(year_from, year_to):
    for value in (year_from, year_to):
        if value is not None and (type(value) is not int or not 1 <= value <= 9999):
            raise ValueError("Years must be whole numbers between 1 and 9999")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValueError("The start year must not be after the end year")


def year_bounds(configuration):
    start, end = configuration.get("year_from"), configuration.get("year_to")
    validate_year_range(start, end)
    return (
        date(start, 1, 1) if start is not None else None,
        date(end, 12, 31) if end is not None else None,
    )


def validate_configuration_choices(changes, current_model=OLLAMA_MODEL):
    validate_year_range(changes.get("year_from"), changes.get("year_to"))
    model = changes.get("model") or current_model
    if changes.get("model"):
        result = installed_models()
        if model not in [m["name"] for m in result["models"]]:
            raise ValueError(result["error"] or "Choose an installed local chat model.")
    thinking = changes.get("thinking", "off")
    if thinking not in ("off", "default"):
        controls = model_controls(model)
        if thinking not in [o["value"] for o in controls["options"]]:
            raise ValueError("The selected model does not support this thinking mode.")


def save_configuration(review_id, patch, *, validated=False):
    value = settings(review_id)
    state = read_json(get_review_path(review_id) / "workflow_state.json", {})
    changes = {
        k: v for k, v in patch.items() if v is not None or k in ("year_from", "year_to")
    }
    validate_year_range(
        changes.get("year_from", value["year_from"]),
        changes.get("year_to", value["year_to"]),
    )
    if state.get("completed") and any(
        k != "thinking" and value.get(k) != v for k, v in changes.items()
    ):
        raise ValueError(
            "Create a new conversation to change model, run mode or search parameters after processing has started."
        )
    model = changes.get("model", value["model"])
    if not validated:
        validate_configuration_choices(changes, value["model"])
    if model != value["model"]:
        value["thinking"] = "off"
    value.update(changes)
    write_json(get_review_path(review_id) / "outputs/runtime_settings.json", value)
    return value


def save_thinking(review_id, mode):
    controls = model_controls(settings(review_id)["model"])
    if mode not in [option["value"] for option in controls["options"]]:
        raise ValueError(
            "This thinking mode is not supported by the current model. Refresh model controls."
        )
    value = {**settings(review_id), "thinking": mode}
    write_json(get_review_path(review_id) / "outputs/runtime_settings.json", value)
    return value


def reasoning_value(review_id):
    value = settings(review_id)
    mode = value["thinking"]
    if mode == "default":
        return None
    controls = model_controls(value["model"])
    options = [o["value"] for o in controls["options"]]
    if mode == "off":
        if "off" in options:
            return False
        if controls.get("error"):
            raise ValueError(
                "Cannot verify Thinking Off. Check Ollama and refresh model controls."
            )
        if not controls["available"]:
            return None  # Non-thinking models need no unsupported think parameter.
        raise ValueError(
            "This model cannot disable thinking. Choose a supported thinking level explicitly, or use a model with an Off option."
        )
    if mode not in options:
        raise ValueError(
            "Saved thinking mode is unavailable. Check Ollama and refresh model controls."
        )
    return {"on": True}.get(mode, mode)


def worker_environment(review_id):
    value = settings(review_id)
    return {
        "OLLAMA_REASONING": json.dumps(reasoning_value(review_id)),
        "OLLAMA_MODEL": value["model"],
        "OLLAMA_TEMPERATURE": str(value["temperature"]),
    }


def upgrade_generation_model(review_id, model, *, revalidate=False):
    """Explicit model migration; preserve sources and human decisions, archive drafts.

    The caller must hold the review mutation lock. Existing source-checked
    extraction is retained, and the new writer re-audits its scientific use.
    """
    from datetime import UTC, datetime

    from storage.review_manager import archive_outputs

    previous = settings(review_id)
    if previous["model"] == model and not revalidate:
        return {"changed": False, "model": model}
    validate_configuration_choices(
        {"model": model, "thinking": "off"}, previous["model"]
    )
    root = get_review_path(review_id)
    state = read_json(root / "workflow_state.json", {})
    archive_outputs(review_id)
    updated = {**previous, "model": model, "thinking": "off"}
    write_json(root / "outputs/runtime_settings.json", updated)
    affected = {"full_text_screening", "appraisal", "synthesis", "quality"}
    state["completed"] = [
        name for name in state.get("completed", []) if name not in affected
    ]
    state.update(status="ready_to_continue", awaiting_confirmation=None)
    if previous["mode"] == "automatic":
        state["automatic_generation_settings"] = updated
        write_json(root / "outputs/automatic_appraisal.json", {})
        write_json(root / "outputs/automatic_eligibility.json", {})
    write_json(root / "outputs/appraisal_proposals.json", {})
    for key in ("report", "quality_review", "scientific_writer_version"):
        state.pop(key, None)
    write_json(root / "workflow_state.json", state)
    write_json(
        root / "outputs/review_status.json",
        {
            "status": "ready_to_continue",
            "report_current": False,
            "mode": previous["mode"],
        },
    )
    event = {
        "from_model": previous["model"],
        "to_model": model,
        "timestamp": datetime.now(UTC).isoformat(),
        "action": "generation_profile_revalidation"
        if previous["model"] == model
        else "generation_model_upgrade",
        "scope": "Recompute eligibility proposals, automated appraisal and writing. Source-checked extraction and actual human decisions are preserved.",
    }
    history = read_json(root / "outputs/model_migrations.json", [])
    write_json(root / "outputs/model_migrations.json", [*history, event])
    return {"changed": True, **event}
