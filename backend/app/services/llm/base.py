from __future__ import annotations
from typing import Protocol

class LLMProvider(Protocol):
    def explain_finding(self, evidence: dict) -> dict: ...
