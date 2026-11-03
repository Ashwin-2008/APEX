"""Engineering Risk Prioritization Engine for APEX 2.0.

Computes transparent, multi-dimensional remediation priorities based on technical
severity, evidence quality, external exposure, and systemic architectural impact.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from app.services.intelligence.confidence_engine import ConfidenceLevel


class RemediationPriority(str, Enum):
    P0_IMMEDIATE = "P0_IMMEDIATE"  # Blocker / Critical exploitability
    P1_HIGH = "P1_HIGH"            # Serious defect / high confidence
    P2_MEDIUM = "P2_MEDIUM"        # Normal priority / moderate impact
    P3_LOW = "P3_LOW"              # Minor quality / low confidence


@dataclass
class PrioritizedRisk:
    finding_id: str
    rule_id: str
    category: str
    file: str | None
    line: int | None
    technical_severity: str
    evidence_confidence: str
    exposure: str  # public_api, internal_service, configuration, testing
    engineering_impact: str  # security_compromise, event_loop_stall, runtime_crash, maintainability
    priority: RemediationPriority
    rank_score: float  # 0.0 to 100.0
    justification: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["priority"] = self.priority.value
        return data


class RiskPrioritizer:
    """Prioritizes findings into actionable engineering remediation tiers."""

    @staticmethod
    def prioritize(
        finding: dict[str, Any],
        confidence_level: ConfidenceLevel | str = ConfidenceLevel.MEDIUM,
    ) -> PrioritizedRisk:
        fid = finding.get("fingerprint") or finding.get("rule_id", "unknown")
        rule_id = finding.get("rule_id", "")
        cat = (finding.get("category") or "general").lower()
        sev = (finding.get("severity") or "medium").lower()
        c_str = confidence_level.value if isinstance(confidence_level, ConfidenceLevel) else str(confidence_level).upper()
        file_path = (finding.get("file") or "").lower()

        # 1. Determine Exposure
        is_route = any(kw in file_path for kw in ["route", "controller", "api", "endpoint", "views"]) or any(
            "route" in str(s).lower() for s in finding.get("data_flow", [])
        )
        if is_route:
            exposure = "public_api"
            exposure_weight = 30.0
        elif any(kw in file_path for kw in ["service", "core", "auth", "db", "models"]):
            exposure = "internal_service"
            exposure_weight = 20.0
        elif any(kw in file_path for kw in ["test", "fixture", "mock"]):
            exposure = "testing"
            exposure_weight = 5.0
        else:
            exposure = "utility_or_config"
            exposure_weight = 10.0

        # 2. Determine Technical Severity Weight
        sev_weights = {"critical": 40.0, "high": 30.0, "medium": 15.0, "low": 5.0, "info": 1.0}
        sev_weight = sev_weights.get(sev, 15.0)

        # 3. Confidence Weight
        conf_weights = {"HIGH": 20.0, "MEDIUM": 12.0, "LOW": 5.0, "INSUFFICIENT": 0.0}
        conf_weight = conf_weights.get(c_str, 12.0)

        # 4. Engineering Impact Classification
        if cat == "security":
            impact = "security_compromise"
            impact_bonus = 10.0
        elif "ASYNC" in rule_id:
            impact = "event_loop_stall"
            impact_bonus = 8.0
        elif "RESOURCE" in rule_id:
            impact = "descriptor_leak"
            impact_bonus = 6.0
        elif "TYPE" in rule_id:
            impact = "runtime_crash"
            impact_bonus = 5.0
        elif cat == "architecture":
            impact = "architectural_degradation"
            impact_bonus = 4.0
        else:
            impact = "code_maintainability"
            impact_bonus = 0.0

        total_score = min(100.0, sev_weight + exposure_weight + conf_weight + impact_bonus)

        # Tier assignment
        if total_score >= 80.0 and c_str in {"HIGH", "MEDIUM"}:
            priority = RemediationPriority.P0_IMMEDIATE
        elif total_score >= 60.0:
            priority = RemediationPriority.P1_HIGH
        elif total_score >= 35.0:
            priority = RemediationPriority.P2_MEDIUM
        else:
            priority = RemediationPriority.P3_LOW

        justification = (
            f"Severity={sev.upper()} ({sev_weight:.0f}pts) + "
            f"Exposure={exposure} ({exposure_weight:.0f}pts) + "
            f"Confidence={c_str} ({conf_weight:.0f}pts) + "
            f"Impact={impact} ({impact_bonus:.0f}pts) = "
            f"{total_score:.0f}/100 => Tier {priority.value}"
        )

        return PrioritizedRisk(
            finding_id=fid,
            rule_id=rule_id,
            category=cat,
            file=finding.get("file"),
            line=finding.get("line"),
            technical_severity=sev,
            evidence_confidence=c_str,
            exposure=exposure,
            engineering_impact=impact,
            priority=priority,
            rank_score=round(total_score, 1),
            justification=justification,
        )

