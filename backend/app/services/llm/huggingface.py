from __future__ import annotations
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

class HuggingFaceQwenProvider:
    def __init__(self, token: str, model: str, provider: str = ""):
        self.token, self.model, self.provider = token, model, provider

    def explain_finding(self, evidence: dict) -> dict:
        if not self.token or not self.model:
            return {"available": False, "message": "LLM explanation unavailable: HF token or model is not configured."}
        prompt = "Return JSON only with summary, why_it_matters, recommended_action, tests_to_add, affected_components, confidence. Use only supplied evidence. If unsupported, say Insufficient evidence.\n" + json.dumps(evidence, ensure_ascii=False)
        body = json.dumps({"inputs": prompt, "parameters": {"return_full_text": False, "max_new_tokens": 500}}).encode()
        request = Request(f"https://api-inference.huggingface.co/models/{self.model}", data=body, headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=30) as response:
                raw = json.loads(response.read().decode())
            text = raw[0].get("generated_text", "") if isinstance(raw, list) and raw else ""
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start: return {"available": False, "message": "LLM explanation unavailable: invalid structured response."}
            result = json.loads(text[start:end + 1]); result["available"] = True; return result
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as error:
            return {"available": False, "message": f"LLM explanation unavailable: {type(error).__name__}."}
