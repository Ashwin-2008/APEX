from __future__ import annotations
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from backend.ml.mistiq_apr.ingestion import redact_secrets

class GroqProvider:
    endpoint = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, token: str, model: str, provider: str = ""):
        self.token, self.model, self.provider = token, model, provider

    @staticmethod
    def _generated_text(raw) -> str:
        if isinstance(raw, dict):
            choices = raw.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict):
                    return message.get("content", "") or ""
                return choices[0].get("text", "") or ""
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            return raw[0].get("generated_text", "") or ""
        return ""

    @staticmethod
    def _normalise(result: dict) -> dict:
        """Coerce optional LLM quirks into the structured schema."""
        for key in ("tests_to_add", "affected_components"):
            value = result.get(key)
            if isinstance(value, str):
                result[key] = [value] if value else []
            elif value is None:
                result[key] = []
            elif not isinstance(value, list):
                result[key] = [str(value)]
        confidence = result.get("confidence")
        if isinstance(confidence, str):
            level = confidence.strip().lower()
            levels = {"high": 0.9, "medium": 0.6, "low": 0.3}
            if level in levels:
                result["confidence"] = levels[level]
            else:
                try:
                    result["confidence"] = float(confidence)
                except ValueError:
                    result["confidence"] = None
        return result

    def explain_finding(self, evidence: dict) -> dict:
        if not self.token or not self.model:
            return {"available": False, "message": "LLM explanation unavailable: Groq token or model is not configured."}
        redacted_evidence_json, redactions = redact_secrets(json.dumps(evidence, ensure_ascii=False))
        prompt = (
            "Return ONLY a JSON object with these exact keys and types: "
            'summary (string), why_it_matters (string), recommended_action (string), '
            'tests_to_add (array of strings; use an empty array if none can be justified), '
            'affected_components (array of strings), confidence (number between 0 and 1). '
            "Use only the supplied evidence; never invent files, vulnerabilities, requirements, tests or evidence. "
            "If the evidence does not support an explanation, put \"Insufficient evidence\" in summary and use an empty array for tests_to_add.\n"
            + redacted_evidence_json
        )
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "temperature": 0.0,
            "stream": False,
        }).encode()
        request = Request(self.endpoint, data=body, headers={
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "MISTIQ-APR/1.0",
        }, method="POST")
        try:
            with urlopen(request, timeout=30) as response:
                raw = json.loads(response.read().decode())
            text = self._generated_text(raw)
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                return {"available": False, "message": "LLM explanation unavailable: invalid structured response."}
            result = json.loads(text[start:end + 1])
            result = self._normalise(result)
            result["available"] = True
            return result
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as error:
            return {"available": False, "message": f"LLM explanation unavailable: {type(error).__name__}."}
