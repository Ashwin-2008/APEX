"""Groq-Powered Evidence-Grounded Explanation, Remediation, Hallucination Guard, and Patch Validator.

Implements Phase 10 of the APEX architecture:
- Redacts secrets, credentials, and tokens before constructing any LLM prompt.
- Validates Groq responses against the strict Pydantic ``RemediationSuggestion``
  schema (`summary`, `why_it_matters`, `evidence_references`, `suggested_fix`,
  `patch`, `tests_to_add`, `validation_steps`, `potential_side_effects`,
  `confidence`, `limitations`).
- Runs deterministic grounding checks verifying that every referenced file and
  line range exists in the supplied context and that predicted categories are
  never mischaracterized as verified defects.
- Validates suggested patches against the target file on disk (checking file
  existence, staleness, and Python AST syntax when applicable) while keeping
  every patch strictly as a user-reviewed suggestion (`auto_applied=False`).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from backend.ml.mistiq_apr.constants import FAILURE_LABELS
from backend.ml.mistiq_apr.ingestion import redact_secrets


class RemediationSuggestion(BaseModel):
    """Validated structured output schema for AI-assisted remediation (Phase 10.3)."""

    summary: str = Field(..., min_length=1)
    why_it_matters: str = Field(..., min_length=1)
    evidence_references: list[str] = Field(default_factory=list)
    suggested_fix: str = Field(..., min_length=1)
    patch: str = Field(default="")
    tests_to_add: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    potential_side_effects: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    limitations: list[str] = Field(default_factory=list)

    @field_validator(
        "evidence_references",
        "tests_to_add",
        "validation_steps",
        "potential_side_effects",
        "limitations",
        mode="before",
    )
    @classmethod
    def _coerce_str_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [str(value)]

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: Any) -> float:
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        if isinstance(value, str):
            mapping = {"high": 0.88, "medium": 0.65, "low": 0.35}
            low = value.strip().lower()
            if low in mapping:
                return mapping[low]
            try:
                return max(0.0, min(1.0, float(low)))
            except ValueError:
                return 0.6
        return 0.6


def prepare_redacted_evidence_bundle(
    repository_path: str | Path | None,
    file_path: str | None,
    start_line: int | None,
    end_line: int | None,
    category: str,
    title: str,
    explanation: str,
    evidence_state: str = "verified_finding",
    predicted_category: str | None = None,
    supporting_features: list[dict[str, Any]] | None = None,
    historical_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble and redact code context + deterministic evidence before prompting Groq."""
    code_snippet = ""
    surrounding_context = ""
    file_line_count = 0
    file_exists = False

    if repository_path and file_path:
        target = Path(repository_path) / file_path
        if target.is_file():
            file_exists = True
            try:
                raw_text = target.read_text(encoding="utf-8", errors="replace")
                lines = raw_text.splitlines()
                file_line_count = len(lines)
                s_ln = max(1, int(start_line or 1))
                e_ln = min(file_line_count, max(s_ln, int(end_line or s_ln)))
                snippet_lines = [f"{ln}: {lines[ln - 1]}" for ln in range(s_ln, e_ln + 1)]
                ctx_lo = max(1, s_ln - 5)
                ctx_hi = min(file_line_count, e_ln + 5)
                ctx_lines = [f"{ln}: {lines[ln - 1]}" for ln in range(ctx_lo, ctx_hi + 1)]
                code_snippet = "\n".join(snippet_lines)
                surrounding_context = "\n".join(ctx_lines)
            except OSError:
                pass

    redacted_snippet, red_1 = redact_secrets(code_snippet)
    redacted_context, red_2 = redact_secrets(surrounding_context)
    redacted_title, red_3 = redact_secrets(title)
    redacted_explanation, red_4 = redact_secrets(explanation)

    ref_tag = (
        f"{file_path}:{start_line}-{end_line or start_line}"
        if file_path and start_line
        else (file_path or "project-scope")
    )

    return {
        "evidence_state": evidence_state,
        "category": category,
        "category_label": FAILURE_LABELS.get(category, category),
        "title": redacted_title,
        "explanation": redacted_explanation,
        "file_path": file_path,
        "file_exists": file_exists,
        "file_line_count": file_line_count,
        "start_line": start_line,
        "end_line": end_line or start_line,
        "canonical_reference": ref_tag,
        "code_snippet": redacted_snippet,
        "surrounding_context": redacted_context,
        "predicted_category": predicted_category,
        "supporting_features": (supporting_features or [])[:5],
        "historical_findings": (historical_findings or [])[:5],
        "secret_redactions_applied": red_1 + red_2 + red_3 + red_4,
    }


def validate_grounding(
    suggestion: RemediationSuggestion,
    evidence_bundle: dict[str, Any],
) -> dict[str, Any]:
    """Verify that the remediation response only references real files/lines and respects state."""
    allowed_file = str(evidence_bundle.get("file_path") or "").replace("\\", "/")
    max_line = int(evidence_bundle.get("file_line_count") or 0)
    state = str(evidence_bundle.get("evidence_state") or "verified_finding")

    referenced_files_exist = True
    referenced_lines_valid = True
    invalid_references: list[str] = []

    for ref in suggestion.evidence_references:
        ref_clean = ref.strip().replace("\\", "/")
        if not ref_clean or ref_clean == "project-scope":
            continue
        if ":" in ref_clean:
            f_part, ln_part = ref_clean.split(":", 1)
            if allowed_file and f_part != allowed_file and not allowed_file.endswith(f_part):
                referenced_files_exist = False
                invalid_references.append(ref)
                continue
            nums = [int(n) for n in re.findall(r"\d+", ln_part)]
            if nums and max_line > 0 and any(n < 1 or n > max_line for n in nums):
                referenced_lines_valid = False
                invalid_references.append(ref)
        else:
            if allowed_file and ref_clean != allowed_file and not allowed_file.endswith(ref_clean):
                referenced_files_exist = False
                invalid_references.append(ref)

    # Ensure predicted risk candidates are not claimed as guaranteed defects
    respects_state = True
    if state in ("model_ranked_candidate", "potential_risk"):
        lower_sum = suggestion.summary.lower()
        if "confirmed vulnerability" in lower_sum or "guaranteed defect" in lower_sum:
            respects_state = False

    passed = referenced_files_exist and referenced_lines_valid and respects_state
    return {
        "passed": passed,
        "referenced_files_exist": referenced_files_exist,
        "referenced_lines_valid": referenced_lines_valid,
        "respects_prediction_vs_verified_distinction": respects_state,
        "invalid_references": invalid_references,
    }


def validate_patch_safety(
    patch_text: str,
    repository_path: str | Path | None,
    file_path: str | None,
    evidence_bundle: dict[str, Any],
) -> dict[str, Any]:
    """Validate a proposed code patch without ever auto-applying it to disk (Phase 10.5)."""
    if not patch_text or not patch_text.strip():
        return {
            "has_patch": False,
            "target_file_exists": bool(evidence_bundle.get("file_exists")),
            "original_lines_fresh": True,
            "syntax_valid": True,
            "auto_applied": False,
            "review_only": True,
            "status": "no_patch_supplied",
        }

    target_exists = False
    lines_fresh = False
    syntax_valid = True

    if repository_path and file_path:
        target = Path(repository_path) / file_path
        if target.is_file():
            target_exists = True
            try:
                disk_text = target.read_text(encoding="utf-8", errors="replace")
                snippet = str(evidence_bundle.get("code_snippet") or "")
                # Strip line-number prefixes ("12: code") to verify staleness
                raw_snippet_lines = [
                    re.sub(r"^\d+:\s?", "", ln).strip()
                    for ln in snippet.splitlines()
                    if re.sub(r"^\d+:\s?", "", ln).strip()
                ]
                lines_fresh = all(sl in disk_text for sl in raw_snippet_lines) if raw_snippet_lines else True
            except OSError:
                lines_fresh = False

    # If the patch contains Python replacement code and target is a .py file, check syntax of added lines if standalone
    if file_path and str(file_path).endswith(".py"):
        code_lines = []
        for ln in patch_text.splitlines():
            if ln.startswith(("+++", "---", "@@")):
                continue
            if ln.startswith("+"):
                code_lines.append(ln[1:])
            elif not ln.startswith("-"):
                code_lines.append(ln)
        candidate_block = "\n".join(code_lines).strip()
        if candidate_block and not candidate_block.startswith("#"):
            try:
                ast.parse(candidate_block)
                syntax_valid = True
            except SyntaxError:
                # Unified diffs often contain partial indentation blocks; check balanced parens/quotes
                syntax_valid = (
                    candidate_block.count("(") == candidate_block.count(")")
                    and candidate_block.count("[") == candidate_block.count("]")
                )

    return {
        "has_patch": True,
        "target_file_exists": target_exists,
        "original_lines_fresh": lines_fresh,
        "syntax_valid": syntax_valid,
        "auto_applied": False,
        "review_only": True,
        "status": "validated_for_human_review" if (target_exists and lines_fresh and syntax_valid) else "review_with_caution",
    }


def _build_deterministic_remediation_fallback(evidence_bundle: dict[str, Any]) -> RemediationSuggestion:
    """Build an evidence-grounded deterministic remediation guide when Groq is disabled or unreachable."""
    cat = str(evidence_bundle.get("category") or "error_handling")
    cat_label = FAILURE_LABELS.get(cat, cat)
    title = str(evidence_bundle.get("title") or f"{cat_label} finding")
    explanation = str(evidence_bundle.get("explanation") or "")
    ref = str(evidence_bundle.get("canonical_reference") or "project-scope")
    state = str(evidence_bundle.get("evidence_state") or "verified_finding")
    f_path = str(evidence_bundle.get("file_path") or "")
    s_ln = evidence_bundle.get("start_line")

    state_prefix = (
        f"[Verified deterministic finding at `{ref}`]"
        if state == "verified_finding"
        else f"[{state.replace('_', ' ').title()} at `{ref}` — not a confirmed defect]"
    )

    playbook: dict[str, dict[str, Any]] = {
        "security": {
            "why": "Hardcoded credentials, unsafe command execution, or unescaped DOM sinks expose the application to credential leakage or remote code injection.",
            "fix": "Move secrets to environment variables (`os.getenv`), replace `shell=True` / `eval()` with parameterized argument lists, and sanitize untrusted HTML.",
            "patch": (
                f"--- a/{f_path or 'config.py'}\n+++ b/{f_path or 'config.py'}\n"
                f"@@ -{s_ln or 1},1 +{s_ln or 1},2 @@\n"
                "-# Replace hardcoded credential or unsafe call\n"
                "+import os\n+API_CREDENTIAL = os.environ.get('APP_SECRET_TOKEN', '')"
            ),
            "tests": [
                f"Add a regression test verifying `{f_path or 'module'}` loads credentials from environment variables and fails closed when missing.",
                "Add a static security test asserting no literal tokens or `shell=True` calls exist in the module.",
            ],
        },
        "error_handling": {
            "why": "Silent exception swallowing (`except: pass`) masks runtime failures, prevents root-cause diagnosis, and can leave transactions in an inconsistent state.",
            "fix": "Catch specific exception types, log structured context with traceback/error details, and either raise a domain exception or return an explicit error response.",
            "patch": (
                f"--- a/{f_path or 'service.py'}\n+++ b/{f_path or 'service.py'}\n"
                f"@@ -{s_ln or 1},2 +{s_ln or 1},3 @@\n"
                "-except Exception:\n-    pass\n"
                "+except Exception as exc:\n+    logger.warning('Operation failed in %s: %s', __name__, exc)\n+    raise"
            ),
            "tests": [
                f"Add a unit test simulating an exception at `{ref}` and asserting that it is logged or surfaced rather than silently swallowed."
            ],
        },
        "integration": {
            "why": "External network or HTTP calls without an explicit timeout or retry guard can block worker threads indefinitely during upstream outages.",
            "fix": "Pass an explicit `timeout=(connect_timeout, read_timeout)` parameter to every `requests` or `httpx` call and handle `TimeoutError` / `RequestException`.",
            "patch": (
                f"--- a/{f_path or 'client.py'}\n+++ b/{f_path or 'client.py'}\n"
                f"@@ -{s_ln or 1},1 +{s_ln or 1},1 @@\n"
                "-response = requests.get(url)\n"
                "+response = requests.get(url, timeout=10)"
            ),
            "tests": [
                f"Add a unit test mocking the HTTP client in `{f_path or 'client.py'}` to verify `timeout` is passed and timeout exceptions are handled cleanly."
            ],
        },
        "testing": {
            "why": "Untested modules and low test-to-code coverage allow regressions in business logic and API contracts to ship undetected.",
            "fix": "Create a dedicated unit test module covering the happy path, boundary inputs, and error branches of the target function.",
            "patch": "",
            "tests": [
                f"Create unit tests for `{ref}` covering normal execution, invalid input handling, and edge conditions."
            ],
        },
        "authentication": {
            "why": "State-mutating routes without explicit authentication dependencies allow unauthenticated callers to modify application state.",
            "fix": "Attach an authentication dependency (e.g., `Depends(get_current_user)`) to the route signature and reject unauthenticated requests with HTTP 401.",
            "patch": "",
            "tests": [
                f"Add an API test verifying `{ref}` returns HTTP 401/403 when called without valid authentication credentials."
            ],
        },
    }

    selected = playbook.get(
        cat,
        {
            "why": f"Issues in `{cat_label}` increase operational risk and maintenance overhead if left unaddressed.",
            "fix": f"Inspect `{ref}`, address the `{cat_label}` finding ({title}), and add automated regression verification.",
            "patch": "",
            "tests": [f"Add a targeted regression test covering `{ref}` ({cat_label})."],
        },
    )

    return RemediationSuggestion(
        summary=f"{state_prefix} {title}. {explanation}".strip(),
        why_it_matters=selected["why"],
        evidence_references=[ref] if ref else [],
        suggested_fix=selected["fix"],
        patch=selected["patch"],
        tests_to_add=selected["tests"],
        validation_steps=[
            f"Inspect `{ref}` and review the proposed change in context.",
            "Run the backend and frontend test suites (`pytest` and `npm test`) to confirm no regressions.",
            "Re-run the APEX project review to verify the finding transitions to FIXED.",
        ],
        potential_side_effects=[
            "Raising or logging previously swallowed errors may surface latent upstream failures during testing.",
            "Requiring environment variables or auth guards requires updating test fixtures and deployment configs.",
        ],
        confidence=0.82 if state == "verified_finding" else 0.65,
        limitations=[
            "Generated using deterministic engineering remediation rules grounded in local source evidence.",
            "Patches are human-reviewed suggestions only and are never auto-applied to the repository.",
        ],
    )


def generate_remediation_suggestion(
    repository_path: str | Path | None,
    file_path: str | None,
    start_line: int | None,
    end_line: int | None,
    category: str,
    title: str,
    explanation: str,
    evidence_state: str = "verified_finding",
    predicted_category: str | None = None,
    supporting_features: list[dict[str, Any]] | None = None,
    historical_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate an evidence-grounded remediation suggestion via Groq (with deterministic fallback)."""
    evidence_bundle = prepare_redacted_evidence_bundle(
        repository_path=repository_path,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        category=category,
        title=title,
        explanation=explanation,
        evidence_state=evidence_state,
        predicted_category=predicted_category,
        supporting_features=supporting_features,
        historical_findings=historical_findings,
    )

    groq_used = False
    provider_message = "Deterministic evidence-grounded remediation (Groq not invoked)."
    suggestion: RemediationSuggestion | None = None

    if (
        settings.llm_enabled
        and settings.llm_provider.lower() == "groq"
        and settings.groq_api_key
        and settings.groq_model
    ):
        prompt = (
            "You are a senior software reliability engineer assisting with evidence-grounded code remediation.\n"
            "Return ONLY a valid JSON object matching this exact schema:\n"
            "{\n"
            '  "summary": "string",\n'
            '  "why_it_matters": "string",\n'
            '  "evidence_references": ["file:start-end"],\n'
            '  "suggested_fix": "string",\n'
            '  "patch": "unified diff string or empty string",\n'
            '  "tests_to_add": ["string"],\n'
            '  "validation_steps": ["string"],\n'
            '  "potential_side_effects": ["string"],\n'
            '  "confidence": 0.85,\n'
            '  "limitations": ["string"]\n'
            "}\n"
            "STRICT GROUNDING RULES:\n"
            "1. Only reference the file path and line numbers present in the supplied evidence (`canonical_reference`). Never invent files or line numbers.\n"
            "2. If `evidence_state` is `model_ranked_candidate` or `potential_risk`, explicitly state that it is a review candidate rather than a confirmed defect.\n"
            "3. Never include real secrets or credentials in the response.\n\n"
            f"EVIDENCE:\n{json.dumps(evidence_bundle, ensure_ascii=False)}"
        )
        body = json.dumps(
            {
                "model": settings.groq_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 900,
                "temperature": 0.0,
                "stream": False,
            }
        ).encode("utf-8")
        req = Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "APEX-Remediation/2.0",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=25) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            choices = raw.get("choices") or []
            text = (choices[0].get("message") or {}).get("content", "") if choices else ""
            start_idx, end_idx = text.find("{"), text.rfind("}")
            if start_idx >= 0 and end_idx > start_idx:
                parsed_json = json.loads(text[start_idx : end_idx + 1])
                cand_suggestion = RemediationSuggestion.model_validate(parsed_json)
                g_check = validate_grounding(cand_suggestion, evidence_bundle)
                if not g_check["passed"]:
                    # Enforce canonical reference if LLM hallucinated a file/line reference
                    cand_suggestion.evidence_references = [evidence_bundle["canonical_reference"]]
                suggestion = cand_suggestion
                groq_used = True
                provider_message = f"Generated by Groq ({settings.groq_model}) and verified against local code evidence."
            else:
                provider_message = "Groq returned an unparseable response; fell back to deterministic remediation."
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
            provider_message = f"Groq API unavailable ({type(exc).__name__}); using deterministic evidence-grounded remediation."
    else:
        if not settings.llm_enabled:
            provider_message = "LLM_ENABLED is false; using deterministic evidence-grounded remediation."
        elif not settings.groq_api_key:
            provider_message = "GROQ_API_KEY is not configured; using deterministic evidence-grounded remediation."

    if suggestion is None:
        suggestion = _build_deterministic_remediation_fallback(evidence_bundle)

    grounding = validate_grounding(suggestion, evidence_bundle)
    patch_validation = validate_patch_safety(
        suggestion.patch, repository_path, file_path, evidence_bundle
    )

    return {
        "available": True,
        "llm_used": groq_used,
        "provider": "groq" if groq_used else "deterministic_fallback",
        "model": settings.groq_model if groq_used else "APEX-Deterministic-Remediation-v1",
        "message": provider_message,
        "evidence_state": evidence_state,
        "secret_redactions_applied": evidence_bundle["secret_redactions_applied"],
        "remediation": suggestion.model_dump(),
        "grounding_validation": grounding,
        "patch_validation": patch_validation,
    }

