from __future__ import annotations
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

class HuggingFaceQwenProvider:
    endpoint = "https://router.huggingface.co/v1/chat/completions"

    def __init__(self, token: str, model: str, provider: str = ""):
        self.token, self.model, self.provider = token, model, provider

    @staticmethod
    def _generated_text(raw) -> str:
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            return raw[0].get("generated_text", "") or ""
        if isinstance(raw, dict):
            choices = raw.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict):
                    return message.get("content", "") or ""
                return choices[0].get("text", "") or ""
        return ""

    def explain_finding(self, evidence: dict) -> dict:
        if not self.token or not self.model:
            return {"available": False, "message": "LLM explanation unavailable: HF token or model is not configured."}
        prompt = "Return JSON only with summary, why_it_matters, recommended_action, tests_to_add, affected_components, confidence. Use only supplied evidence. If unsupported, say Insufficient evidence.\n" + json.dumps(evidence, ensure_ascii=False)
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "temperature": 0.0,
            "stream": False,
        }).encode()
        request = Request(self.endpoint, data=body, headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=30) as response:
                raw = json.loads(response.read().decode())
            text = self._generated_text(raw)
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start: return {"available": False, "message": "LLM explanation unavailable: invalid structured response."}
            result = json.loads(text[start:end + 1]); result["available"] = True; return result
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as error:
            return {"available": False, "message": f"LLM explanation unavailable: {type(error).__name__}."}
