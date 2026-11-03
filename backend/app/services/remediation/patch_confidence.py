"""Evidence-Based Multi-Dimensional Patch Confidence & Explanation for APEX 2.0.

Evaluates patches across six distinct dimensions:
1. Detection Confidence (original evidence grounding & validation state).
2. Transformation Confidence (deterministic AST rewrite vs heuristic/AI).
3. Semantic Confidence (function contract preservation & scope integrity).
4. Behavioral Verification (test execution, baseline comparison & regression absence).
5. Application Integrity (cryptographic hash provenance & stale check).
6. Remediation Confirmation (post-apply flaw elimination & zero new findings).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.remediation.patch_lifecycle import PatchRecord, PatchLifecycleState
from app.services.remediation.semantic_verifier import SemanticRisk


@dataclass
class ConfidenceDimension:
    name: str
    status: str
    score: float
    verified: bool
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PatchConfidenceReport:
    patch_id: str
    overall_status: str
    dimensions: list[ConfidenceDimension] = field(default_factory=list)
    human_explanation: str = ""
    can_apply: bool = False
    requires_human_approval: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "overall_status": self.overall_status,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "human_explanation": self.human_explanation,
            "can_apply": self.can_apply,
            "requires_human_approval": self.requires_human_approval,
        }


class PatchConfidenceEngine:
    """Computes transparent, multi-dimensional confidence assessment for candidate patches."""

    @classmethod
    def evaluate_patch(
        cls,
        record: PatchRecord,
        finding_confidence: float = 0.95,
        validation_state: str = "CONFIRMED",
    ) -> PatchConfidenceReport:
        patch = record.patch
        dims: list[ConfidenceDimension] = []

        # 1. Detection Confidence
        det_score = finding_confidence
        det_verified = validation_state in {"CONFIRMED", "VERIFIED"}
        dims.append(
            ConfidenceDimension(
                name="Detection Confidence",
                status=validation_state,
                score=det_score,
                verified=det_verified,
                explanation=f"Finding validated with {int(det_score * 100)}% confidence ({validation_state}).",
            )
        )

        # 2. Transformation Confidence
        is_det = patch.strategy.value == "DETERMINISTIC_AST"
        trans_score = 1.0 if is_det else 0.8
        trans_status = "DETERMINISTIC_AST" if is_det else "AI_GROUNDED"
        dims.append(
            ConfidenceDimension(
                name="Transformation Confidence",
                status=trans_status,
                score=trans_score,
                verified=True,
                explanation="Synthesized using deterministic AST rewrite rules with guaranteed syntax." if is_det else "AI-grounded contextual synthesis.",
            )
        )

        # 3. Semantic Confidence
        sem_res = record.semantic_verification
        if sem_res:
            sem_verified = sem_res.valid
            sem_score = 1.0 if sem_res.risk_level == SemanticRisk.SAFE_TRANSFORMATION else (0.85 if sem_res.risk_level == SemanticRisk.LOW_RISK_TRANSFORMATION else 0.5)
            sem_status = sem_res.risk_level.value
            sem_expl = sem_res.summary
        else:
            sem_verified = False
            sem_score = 0.5
            sem_status = "PENDING"
            sem_expl = "Semantic verification has not been executed yet."
        dims.append(
            ConfidenceDimension(
                name="Semantic Confidence",
                status=sem_status,
                score=sem_score,
                verified=sem_verified,
                explanation=sem_expl,
            )
        )

        # 4. Behavioral Verification
        beh_res = record.behavioral_verification
        if beh_res:
            beh_status = beh_res.get("status", "NOT_RUN")
            beh_verified = beh_res.get("valid", False)
            beh_score = 1.0 if beh_status == "PASSED" else (0.75 if beh_status == "PARTIALLY_PASSED" else (0.5 if beh_status == "UNVERIFIABLE" else 0.0))
            beh_expl = beh_res.get("summary", "")
        else:
            beh_status = "NOT_RUN"
            beh_verified = False
            beh_score = 0.5
            beh_expl = "Behavioral test execution has not been evaluated."
        dims.append(
            ConfidenceDimension(
                name="Behavioral Verification",
                status=beh_status,
                score=beh_score,
                verified=beh_verified,
                explanation=beh_expl,
            )
        )

        # 5. Application Integrity
        prov = record.provenance
        if prov and record.state not in {PatchLifecycleState.STALE_PATCH, PatchLifecycleState.FAILED}:
            integ_verified = True
            integ_score = 1.0
            integ_status = "VERIFIED"
            integ_expl = f"SHA-256 provenance bound to source {prov.original_source_sha256[:8]}."
        elif record.state == PatchLifecycleState.STALE_PATCH:
            integ_verified = False
            integ_score = 0.0
            integ_status = "STALE"
            integ_expl = "Target file changed on disk after patch generation."
        else:
            integ_verified = False
            integ_score = 0.5
            integ_status = "UNBOUND"
            integ_expl = "Cryptographic provenance pending registration."
        dims.append(
            ConfidenceDimension(
                name="Application Integrity",
                status=integ_status,
                score=integ_score,
                verified=integ_verified,
                explanation=integ_expl,
            )
        )

        # 6. Remediation Confirmation
        post_res = record.post_apply_verification
        if post_res:
            post_outcome = post_res.get("outcome", "POST_APPLY_UNVERIFIABLE")
            post_verified = post_res.get("flaw_eliminated", False)
            post_score = 1.0 if post_outcome == "REMEDIATION_CONFIRMED" else (0.7 if post_outcome == "REMEDIATION_PARTIAL" else 0.0)
            post_expl = post_res.get("summary", "")
        else:
            post_outcome = "PENDING_APPLICATION"
            post_verified = False
            post_score = 0.5
            post_expl = "Awaiting post-apply reanalysis."
        dims.append(
            ConfidenceDimension(
                name="Remediation Confirmation",
                status=post_outcome,
                score=post_score,
                verified=post_verified,
                explanation=post_expl,
            )
        )

        # Compute overall status & approval
        can_apply = (
            record.verification is not None and record.verification.valid and
            (sem_res is None or sem_res.valid) and
            record.state not in {PatchLifecycleState.STALE_PATCH, PatchLifecycleState.FAILED, PatchLifecycleState.APPLIED}
        )

        overall_status = "VERIFIED" if can_apply else record.state.value

        human_explanation = (
            f"Patch {patch.patch_id} targeting rule {patch.rule_id} in {patch.file}. "
            f"Strategy: {trans_status}. "
            f"Semantic: {sem_status}. "
            f"Integrity: {integ_status}."
        )

        return PatchConfidenceReport(
            patch_id=patch.patch_id,
            overall_status=overall_status,
            dimensions=dims,
            human_explanation=human_explanation,
            can_apply=can_apply,
            requires_human_approval=True,
        )

