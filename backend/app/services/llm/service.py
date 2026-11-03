from __future__ import annotations
from functools import lru_cache
import hashlib
import json
from app.core.config import settings
from .huggingface import HuggingFaceQwenProvider
from .groq import GroqProvider
from .remediation import generate_remediation_suggestion


def _provider():
    provider = settings.llm_provider.lower()
    if provider == "groq":
        return GroqProvider(settings.groq_api_key, settings.groq_model)
    return HuggingFaceQwenProvider(settings.hf_token, settings.hf_model, settings.hf_provider)


@lru_cache(maxsize=512)
def _cached(fingerprint: str, payload: str) -> dict:
    provider = _provider()
    return provider.explain_finding(json.loads(payload))


def explain_finding(evidence: dict) -> dict:
    if not settings.llm_enabled:
        return {"available": False, "message": "LLM explanation unavailable: LLM_ENABLED=false."}
    payload = json.dumps(evidence, sort_keys=True, default=str)
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()
    return _cached(fingerprint, payload)
