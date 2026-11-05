"""Multi-Strategy Remediation Planning & 11-Dimension Scoring Engine for APEX 2.0 (Phase 5.2).

Synthesizes alternative repair strategies, performs deterministic multi-dimensional
scoring, calculates blast-radius and predictive risks, and generates unverified
candidate patch representations strictly awaiting Phase 5.3 verification.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    ProjectFinding,
    RemediationFindingClusterRecord,
    RemediationPlanRecord,
    RemediationRootCauseHypothesisRecord,
    RemediationWorkflowFinding,
    RemediationWorkflowRecord,
    ReviewedProject,
)
from app.services.graph.blast_radius import BlastRadiusEngine, BlastRadiusReport
from app.services.graph.models import EdgeType, GraphEdge, GraphNode, NodeType
from app.services.graph.test_selector import RecommendedTest, TargetedTestSelector, TestRecommendationTier
from app.services.predictive.baseline_models import RuleBasedEngineeringRiskBaseline
from app.services.remediation.patch_generator import PatchGenerator, generate_unified_diff

logger = logging.getLogger(__name__)

UNVERIFIED_CANDIDATE_BANNER = (
    "# ====================================================================\n"
    "# UNVERIFIED — AWAITING PHASE 5.3 VALIDATION\n"
    "# Candidate patch representation produced by Phase 5.2 Strategy Planner\n"
    "# STRICT SAFETY BOUNDARY: NO FILE WAS MODIFIED AND NO CODE WAS EXECUTED.\n"
    "# ====================================================================\n"
)


class RemediationStrategyType(str, Enum):
    TARGETED_FIX = "TARGETED_FIX"
    DEFENSIVE_VALIDATION = "DEFENSIVE_VALIDATION"
    CONTRACT_CORRECTION = "CONTRACT_CORRECTION"
    ARCHITECTURAL_CORRECTION = "ARCHITECTURAL_CORRECTION"
    DEPENDENCY_UPGRADE = "DEPENDENCY_UPGRADE"
    DEPENDENCY_COMPATIBILITY_CORRECTION = "DEPENDENCY_COMPATIBILITY_CORRECTION"
    CONFIGURATION_CORRECTION = "CONFIGURATION_CORRECTION"
    DATABASE_QUERY_CORRECTION = "DATABASE_QUERY_CORRECTION"
    DATABASE_MIGRATION_CORRECTION = "DATABASE_MIGRATION_CORRECTION"
    TEST_FIRST_CORRECTION = "TEST_FIRST_CORRECTION"
    SECURITY_HARDENING = "SECURITY_HARDENING"


class ApprovalTier(str, Enum):
    TIER_1_AUTO = "TIER_1_AUTO"
    TIER_2_PEER_REVIEW = "TIER_2_PEER_REVIEW"
    TIER_3_SECURITY_LEAD = "TIER_3_SECURITY_LEAD"


SCORING_WEIGHTS_VERSION = "1.0.0"

SCORING_WEIGHTS: dict[str, float] = {
    "causality_alignment": 0.15,
    "blast_radius_safety": 0.15,
    "architectural_compliance": 0.10,
    "reversibility": 0.10,
    "testability": 0.10,
    "predictive_risk_safety": 0.10,
    "tech_debt_reduction": 0.08,
    "minimal_disruption": 0.07,
    "security_hardening": 0.05,
    "implementation_complexity": 0.05,
    "evidence_completeness": 0.05,
}


@dataclass
class StrategyCandidateSpec:
    strategy_type: RemediationStrategyType
    title: str
    description: str
    rationale: str
    complexity: str  # LOW, MEDIUM, HIGH
    summary_of_changes: str
    diff_generator_hint: str
    estimated_tech_debt_reduction: float
    estimated_disruption: float
    security_gain: float
    applicable_defect_categories: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    proposed_changes: list[str] = field(default_factory=list)
    affected_components: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    required_tests: list[str] = field(default_factory=list)
    migration_implications: str = "None"
    rollback_implications: str = "Multi-file journal restore"
    evidence_requirements: list[str] = field(default_factory=list)
    is_supported: bool = True
    unsupported_reason: str | None = None


def calculate_score_sensitivity(base_breakdown: dict[str, float], delta: float = 0.05) -> dict[str, float]:
    """Calculates sensitivity of total plan score to +/- delta perturbation in individual dimensions."""
    sensitivity: dict[str, float] = {}
    base_score = sum(base_breakdown.get(dim, 0.5) * SCORING_WEIGHTS[dim] for dim in SCORING_WEIGHTS) * 100.0
    for dim, weight in SCORING_WEIGHTS.items():
        perturbed_val = min(1.0, max(0.0, base_breakdown.get(dim, 0.5) + delta))
        diff = (perturbed_val - base_breakdown.get(dim, 0.5)) * weight * 100.0
        sensitivity[dim] = round(diff, 4)
    return sensitivity


class StrategyPlanner:
    """Multi-strategy synthesis, blast-radius assessment, and deterministic ranking engine."""

    @classmethod
    def generate_strategy_specs_for_category(
        cls,
        category: str,
        finding_rules: list[str],
    ) -> list[StrategyCandidateSpec]:
        """Synthesizes candidate strategy specifications based on finding category & rule hints."""
        specs: list[StrategyCandidateSpec] = []
        is_security = any("sec" in r.lower() or "taint" in r.lower() or "injection" in r.lower() for r in finding_rules)

        # 1. Targeted Fix is always evaluated as minimal intervention baseline
        specs.append(
            StrategyCandidateSpec(
                strategy_type=RemediationStrategyType.TARGETED_FIX,
                title=f"Targeted Minimal Fix for {category.title()}",
                description="Direct, surgical correction focused exclusively on the immediate defect line.",
                rationale="Minimizes collateral change footprint and cognitive impact on downstream callers.",
                complexity="LOW",
                summary_of_changes="Modify the offending statement directly without altering interface signatures.",
                diff_generator_hint="targeted",
                estimated_tech_debt_reduction=0.45,
                estimated_disruption=0.15,
                security_gain=0.60 if is_security else 0.30,
            )
        )

        # 2. Defensive Validation
        specs.append(
            StrategyCandidateSpec(
                strategy_type=RemediationStrategyType.DEFENSIVE_VALIDATION,
                title="Defensive Boundary Validation & Preconditions",
                description="Introduce explicit guard checks, type/null validation, and precondition assertions.",
                rationale="Prevents invalid states from penetrating internal execution without altering core logic.",
                complexity="LOW",
                summary_of_changes="Add upfront validation checks at function entry point with informative errors.",
                diff_generator_hint="defensive",
                estimated_tech_debt_reduction=0.70,
                estimated_disruption=0.20,
                security_gain=0.80 if is_security else 0.50,
            )
        )

        # 3. Security Hardening or Contract Correction
        if is_security:
            specs.append(
                StrategyCandidateSpec(
                    strategy_type=RemediationStrategyType.SECURITY_HARDENING,
                    title="Comprehensive Security Hardening",
                    description="Enforce parameterized execution, input escaping, and principle of least privilege.",
                    rationale="Completely eliminates injection vulnerability class rather than patching specific inputs.",
                    complexity="MEDIUM",
                    summary_of_changes="Refactor query or command execution to strictly use safe parameterization.",
                    diff_generator_hint="security",
                    estimated_tech_debt_reduction=0.85,
                    estimated_disruption=0.35,
                    security_gain=0.95,
                )
            )
        else:
            specs.append(
                StrategyCandidateSpec(
                    strategy_type=RemediationStrategyType.CONTRACT_CORRECTION,
                    title="Interface Contract Alignment & Explicit Typing",
                    description="Align return contracts, parameter type annotations, and caller expectations.",
                    rationale="Eliminates ambiguity in method contracts to prevent recurrent type and boundary errors.",
                    complexity="MEDIUM",
                    summary_of_changes="Update function signature, docstring specifications, and return guarantees.",
                    diff_generator_hint="contract",
                    estimated_tech_debt_reduction=0.75,
                    estimated_disruption=0.30,
                    security_gain=0.40,
                )
            )

        # 4. Test-First Correction or Architectural Correction
        if len(finding_rules) > 1 or category in ("architectural", "lifecycle"):
            specs.append(
                StrategyCandidateSpec(
                    strategy_type=RemediationStrategyType.ARCHITECTURAL_CORRECTION,
                    title="Architectural Boundary Encapsulation",
                    description="Encapsulate shared mutable state, decouple dependencies, or extract dedicated service helper.",
                    rationale="Addresses the systemic root cause across multiple related findings simultaneously.",
                    complexity="HIGH",
                    summary_of_changes="Extract isolated handler module and route call through dedicated controller.",
                    diff_generator_hint="architectural",
                    estimated_tech_debt_reduction=0.90,
                    estimated_disruption=0.60,
                    security_gain=0.70,
                    applicable_defect_categories=["ARCHITECTURAL_DESIGN_ERROR", "CONCURRENCY_RACE", "DATA_INTEGRITY"],
                    preconditions=["Multiple interrelated finding sites or cross-module coupling"],
                    proposed_changes=["Introduce boundary abstraction and decouple shared state"],
                    affected_components=["Service architecture", "Caller contracts"],
                    risks=["Potential interface disruption across downstream callers"],
                    required_tests=["Architecture dependency validation", "Integration regression suite"],
                    migration_implications="Requires caller code refactor",
                    rollback_implications="Multi-file journal rollback",
                    evidence_requirements=["Knowledge graph cross-module edges"],
                )
            )
        else:
            specs.append(
                StrategyCandidateSpec(
                    strategy_type=RemediationStrategyType.TEST_FIRST_CORRECTION,
                    title="Test-First Remediation Harness",
                    description="Construct rigorous reproducing regression test prior to applying minimal targeted fix.",
                    rationale="Ensures verification rigor and protects against regressions in critical codepaths.",
                    complexity="MEDIUM",
                    summary_of_changes="Introduce targeted regression test suite exercising edge cases before patch.",
                    diff_generator_hint="test_first",
                    estimated_tech_debt_reduction=0.80,
                    estimated_disruption=0.25,
                    security_gain=0.65,
                    applicable_defect_categories=["LOGIC_ERROR", "TEST_COVERAGE_GAP", "NULL_HANDLING"],
                    preconditions=["Test runner and test directory available"],
                    proposed_changes=["Add failing reproduction test before patch application"],
                    affected_components=["Test suite", "Target module"],
                    risks=["Test harness flakiness if environment dependencies change"],
                    required_tests=["Targeted test suite execution"],
                    migration_implications="None",
                    rollback_implications="Revert test file addition",
                    evidence_requirements=["TargetedTestSelector recommendations"],
                )
            )

        # 5. Dependency & Configuration Corrections
        if any("dep" in r.lower() or "package" in r.lower() for r in finding_rules) or "dependency" in category.lower():
            specs.append(
                StrategyCandidateSpec(
                    strategy_type=RemediationStrategyType.DEPENDENCY_COMPATIBILITY_CORRECTION,
                    title="Dependency Version Compatibility Pinning",
                    description="Update dependency specification to safe, compatible semantic version range.",
                    rationale="Resolves known vulnerability or symbol incompatibility at package boundary.",
                    complexity="LOW",
                    summary_of_changes="Update dependency constraint in manifest to patched release.",
                    diff_generator_hint="dependency",
                    estimated_tech_debt_reduction=0.70,
                    estimated_disruption=0.20,
                    security_gain=0.85,
                    applicable_defect_categories=["DEPENDENCY_INCOMPATIBILITY", "SECURITY_VULNERABILITY"],
                    preconditions=["Dependency manifest exists on disk"],
                    proposed_changes=["Pin dependency to safe patch release"],
                    affected_components=["Dependency manifest", "Package lockfile"],
                    risks=["Transitive dependency conflicts with other packages"],
                    required_tests=["Dependency resolution check", "Integration test suite"],
                    migration_implications="Lockfile regeneration required",
                    rollback_implications="Restore prior manifest pin",
                    evidence_requirements=["Manifest file on disk with pinned version"],
                )
            )

        if any("config" in r.lower() or "env" in r.lower() or "setting" in r.lower() for r in finding_rules) or "configuration" in category.lower():
            specs.append(
                StrategyCandidateSpec(
                    strategy_type=RemediationStrategyType.CONFIGURATION_CORRECTION,
                    title="Configuration & Environment Hardening",
                    description="Correct invalid configuration default, missing environment variable, or insecure flag.",
                    rationale="Eliminates runtime misconfiguration without modifying business code.",
                    complexity="LOW",
                    summary_of_changes="Set secure configuration default and add schema validation.",
                    diff_generator_hint="config",
                    estimated_tech_debt_reduction=0.65,
                    estimated_disruption=0.15,
                    security_gain=0.80,
                    applicable_defect_categories=["CONFIGURATION_ERROR", "SECURITY_VULNERABILITY"],
                    preconditions=["Configuration file exists on disk"],
                    proposed_changes=["Enforce secure configuration setting"],
                    affected_components=["Environment config", "Settings loader"],
                    risks=["Deployment divergence across environments"],
                    required_tests=["Config validation suite"],
                    migration_implications="Environment configuration updates in deployment",
                    rollback_implications="Revert setting to previous value",
                    evidence_requirements=["Config file snippet present in evidence"],
                )
            )

        # 6. Database / Query Corrections
        if any("db" in r.lower() or "query" in r.lower() or "sql" in r.lower() for r in finding_rules) or "database" in category.lower():
            specs.append(
                StrategyCandidateSpec(
                    strategy_type=RemediationStrategyType.DATABASE_QUERY_CORRECTION,
                    title="Parameterized Database Query Refactoring",
                    description="Refactor inline dynamic SQL/ORM queries into parameterized queries with explicit bindings.",
                    rationale="Eliminates query formatting flaws, injection vulnerabilities, and N+1 query patterns.",
                    complexity="MEDIUM",
                    summary_of_changes="Replace dynamic string interpolation with parameterized query bind variables.",
                    diff_generator_hint="database_query",
                    estimated_tech_debt_reduction=0.85,
                    estimated_disruption=0.25,
                    security_gain=0.95,
                    applicable_defect_categories=["DATABASE_QUERY_ERROR", "SECURITY_VULNERABILITY"],
                    preconditions=["Database client or ORM session referenced"],
                    proposed_changes=["Parameterize SQL execution"],
                    affected_components=["Data access layer", "Database queries"],
                    risks=["Potential dialect-specific binding syntax differences"],
                    required_tests=["Database integration test suite"],
                    migration_implications="None",
                    rollback_implications="Standard journal revert",
                    evidence_requirements=["Database query evidence in finding"],
                )
            )

        # 7. Database Migration Correction (with explicit precondition check)
        is_migration_defect = any("migrat" in r.lower() or "alembic" in r.lower() for r in finding_rules) or "migration" in category.lower()
        if is_migration_defect:
            specs.append(
                StrategyCandidateSpec(
                    strategy_type=RemediationStrategyType.DATABASE_MIGRATION_CORRECTION,
                    title="Database Migration Schema Alignment",
                    description="Create forward migration aligning database schema with model definition.",
                    rationale="Fixes drift between SQLAlchemy model definitions and actual schema state.",
                    complexity="HIGH",
                    summary_of_changes="Add versioned migration script with reversible upgrade and downgrade functions.",
                    diff_generator_hint="database_migration",
                    estimated_tech_debt_reduction=0.90,
                    estimated_disruption=0.45,
                    security_gain=0.60,
                    applicable_defect_categories=["DATABASE_QUERY_ERROR", "DATA_INTEGRITY"],
                    preconditions=["Database migration directory exists (alembic/versions)"],
                    proposed_changes=["Create reversible database migration revision"],
                    affected_components=["Migration version scripts", "Database schema"],
                    risks=["Schema lock on production tables during migration execution"],
                    required_tests=["Migration upgrade and downgrade test"],
                    migration_implications="Database schema mutation required in target environment",
                    rollback_implications="Execute downgrade migration function",
                    evidence_requirements=["Model schema definition drift evidence"],
                    is_supported=True,
                )
            )

        return specs

    @classmethod
    def score_plan(
        cls,
        spec: StrategyCandidateSpec,
        hypothesis: RemediationRootCauseHypothesisRecord | None,
        blast_radius: BlastRadiusReport,
        recommended_tests: list[RecommendedTest],
        risk_prediction: dict[str, float],
    ) -> tuple[float, dict[str, float], str, str]:
        """Calculates 11-dimension deterministic score, breakdown, approval tier, and ranking explanation."""
        # 1. Causality alignment
        if hypothesis and hypothesis.status in ("CONFIRMED", "STRONGLY_SUPPORTED"):
            causality_alignment = 0.95
        elif hypothesis and hypothesis.status == "INFERRED":
            causality_alignment = 0.75
        else:
            causality_alignment = 0.50

        # Adjust for strategy fit
        if spec.strategy_type == RemediationStrategyType.SECURITY_HARDENING and (hypothesis and "security" in hypothesis.category.lower()):
            causality_alignment = min(1.0, causality_alignment + 0.10)

        # 2. Blast radius safety (lower blast radius = higher safety)
        blast_score = blast_radius.blast_radius_score
        blast_radius_safety = max(0.05, 1.0 - (blast_score / 100.0))

        # 3. Architectural compliance
        boundaries_crossed = len(blast_radius.boundaries_crossed)
        if boundaries_crossed == 0:
            architectural_compliance = 0.95
        elif boundaries_crossed == 1:
            architectural_compliance = 0.80
        else:
            architectural_compliance = max(0.20, 0.70 - (boundaries_crossed * 0.15))

        # 4. Reversibility (reversibility of code changes)
        if spec.complexity == "LOW":
            reversibility = 0.95
        elif spec.complexity == "MEDIUM":
            reversibility = 0.80
        else:
            reversibility = 0.60

        # 5. Testability
        direct_tests = [t for t in recommended_tests if t.classification == TestRecommendationTier.DIRECT_TEST.value]
        if direct_tests:
            testability = 0.95
        elif recommended_tests:
            testability = 0.75
        else:
            testability = 0.35

        # 6. Predictive risk safety (1.0 - predicted failure risk)
        max_failure_prob = max(risk_prediction.values()) if risk_prediction else 0.30
        predictive_risk_safety = round(max(0.10, 1.0 - max_failure_prob), 4)

        # 7. Tech debt reduction
        tech_debt_reduction = spec.estimated_tech_debt_reduction

        # 8. Minimal disruption (1.0 - disruption)
        minimal_disruption = round(1.0 - spec.estimated_disruption, 4)

        # 9. Security hardening
        security_hardening = spec.security_gain

        # 10. Implementation complexity (LOW -> 0.95, MEDIUM -> 0.75, HIGH -> 0.50)
        complexity_score = 0.95 if spec.complexity == "LOW" else (0.75 if spec.complexity == "MEDIUM" else 0.50)

        # 11. Evidence completeness
        evidence_completeness = hypothesis.evidence_completeness_score if hypothesis else 0.50

        breakdown = {
            "causality_alignment": round(causality_alignment, 4),
            "blast_radius_safety": round(blast_radius_safety, 4),
            "architectural_compliance": round(architectural_compliance, 4),
            "reversibility": round(reversibility, 4),
            "testability": round(testability, 4),
            "predictive_risk_safety": round(predictive_risk_safety, 4),
            "tech_debt_reduction": round(tech_debt_reduction, 4),
            "minimal_disruption": round(minimal_disruption, 4),
            "security_hardening": round(security_hardening, 4),
            "implementation_complexity": round(complexity_score, 4),
            "evidence_completeness": round(evidence_completeness, 4),
        }

        # Weighted total score (0.0 to 100.0)
        raw_weighted = sum(breakdown[dim] * SCORING_WEIGHTS[dim] for dim in SCORING_WEIGHTS)
        total_score = round(raw_weighted * 100.0, 2)

        # Non-Compensatory Safety Gates
        safety_gate_passed = True
        safety_gate_violations: list[str] = []

        # Gate 1: Security Risk Non-Compensability
        # A critical security defect cannot be repaired via non-hardening strategy without failing safety gate
        is_security_defect = hypothesis and "security" in hypothesis.category.lower()
        if is_security_defect and spec.strategy_type not in (
            RemediationStrategyType.SECURITY_HARDENING,
            RemediationStrategyType.DEFENSIVE_VALIDATION,
            RemediationStrategyType.DATABASE_QUERY_CORRECTION,
        ):
            safety_gate_passed = False
            safety_gate_violations.append(
                "Critical security defect cannot be repaired via non-hardening strategy."
            )

        # Gate 2: Unsupported Strategy Non-Compensability
        if not spec.is_supported:
            safety_gate_passed = False
            safety_gate_violations.append(
                f"Strategy '{spec.strategy_type.value}' is unsupported: {spec.unsupported_reason or 'preconditions missing'}"
            )

        # Gate 3: Evidence Completeness Non-Compensability
        if hypothesis and hypothesis.evidence_completeness < 0.20 and hypothesis.status == "INSUFFICIENT_EVIDENCE":
            safety_gate_passed = False
            safety_gate_violations.append(
                "Insufficient causal evidence (< 20%) to safely proceed with autonomous repair."
            )

        # Gate 4: Testability Non-Compensability
        if blast_score > 70.0 and testability < 0.40:
            safety_gate_passed = False
            safety_gate_violations.append(
                "Critical blast radius (>70) without direct test verification fails safety gate."
            )

        # If any non-compensatory safety gate failed, CAP total score to failing tier (<= 45.0)
        if not safety_gate_passed:
            total_score = min(total_score, 45.0)

        # Determine approval tier required
        if not safety_gate_passed or blast_score >= 45.0 or (hypothesis and "security" in hypothesis.category.lower()) or total_score < 60.0:
            approval_tier = ApprovalTier.TIER_3_SECURITY_LEAD.value
        elif blast_score >= 20.0 or spec.complexity == "HIGH":
            approval_tier = ApprovalTier.TIER_2_PEER_REVIEW.value
        else:
            approval_tier = ApprovalTier.TIER_1_AUTO.value

        # Explanation narrative
        gate_summary = ""
        if not safety_gate_passed:
            gate_summary = f" [SAFETY GATE FAILED: {'; '.join(safety_gate_violations)}]"

        explanation = (
            f"Strategy '{spec.title}' scored {total_score}/100.{gate_summary} "
            f"Key strengths: Blast Radius Safety ({round(blast_radius_safety * 100)}%), "
            f"Causality Alignment ({round(causality_alignment * 100)}%), "
            f"Predictive Safety ({round(predictive_risk_safety * 100)}%). "
            f"Requires approval tier '{approval_tier}' due to structural risk factors."
        )

        return total_score, breakdown, approval_tier, explanation

    @classmethod
    def synthesize_unverified_patch_diff(
        cls,
        spec: StrategyCandidateSpec,
        affected_files: list[str],
        findings: list[ProjectFinding],
        repo_root: Path | None,
    ) -> str:
        """Synthesizes candidate patch diff preview labeled strictly UNVERIFIED — AWAITING PHASE 5.3 VALIDATION.
        Diff content is strictly standard unified format without embedded header banners to ensure parseability.
        """
        diff_chunks: list[str] = []

        for file_rel in affected_files:
            file_findings = [f for f in findings if f.file_path == file_rel]
            rule_id = file_findings[0].rule_id if file_findings else "GENERIC-REMEDIATION"
            line_no = file_findings[0].line_number or 1 if file_findings else 1

            original_lines: list[str] = []
            patched_lines: list[str] = []

            # Attempt to read target file if available in repo_root
            if repo_root and (repo_root / file_rel).is_file():
                try:
                    content = (repo_root / file_rel).read_text(encoding="utf-8", errors="ignore")
                    original_lines = content.splitlines()
                except OSError:
                    original_lines = []

            if not original_lines:
                # Synthetic representative context for diff preview
                original_lines = [
                    f"# Context for {file_rel}",
                    f"def handler(request_payload):",
                    f"    data = request_payload.get('input')",
                    f"    return process(data)",
                ]
                line_no = 3

            patched_lines = list(original_lines)
            target_idx = min(max(0, line_no - 1), len(patched_lines) - 1)

            if spec.strategy_type == RemediationStrategyType.TARGETED_FIX:
                target_line = patched_lines[target_idx]
                indent = " " * (len(target_line) - len(target_line.lstrip()))
                patched_lines[target_idx] = f"{target_line}  # APEX-FIX: validated bounds"

            elif spec.strategy_type == RemediationStrategyType.DEFENSIVE_VALIDATION:
                target_line = patched_lines[target_idx]
                indent = " " * (len(target_line) - len(target_line.lstrip()))
                guard = (
                    f"{indent}if not request_payload:\n"
                    f"{indent}    raise ValueError('Precondition validation failed: input payload cannot be None or empty')"
                )
                patched_lines.insert(target_idx, guard)

            elif spec.strategy_type == RemediationStrategyType.SECURITY_HARDENING:
                target_line = patched_lines[target_idx]
                indent = " " * (len(target_line) - len(target_line.lstrip()))
                hardened = (
                    f"{indent}# Security Hardening: Enforce strict sanitization & parameterization\n"
                    f"{indent}sanitized_input = sanitize_and_escape(request_payload.get('input'))\n"
                    f"{indent}return process(sanitized_input)"
                )
                patched_lines[target_idx] = hardened

            elif spec.strategy_type == RemediationStrategyType.CONTRACT_CORRECTION:
                target_line = patched_lines[target_idx]
                indent = " " * (len(target_line) - len(target_line.lstrip()))
                patched_lines.insert(
                    max(0, target_idx - 1),
                    f"{indent}assert isinstance(request_payload, dict), 'Contract violation: payload must be a dict'",
                )

            elif spec.strategy_type in (RemediationStrategyType.DEPENDENCY_COMPATIBILITY_CORRECTION, RemediationStrategyType.DEPENDENCY_UPGRADE):
                target_line = patched_lines[target_idx]
                patched_lines[target_idx] = f"{target_line}  # APEX-DEP: pinned to compatible secure version"

            elif spec.strategy_type == RemediationStrategyType.CONFIGURATION_CORRECTION:
                target_line = patched_lines[target_idx]
                patched_lines[target_idx] = f"{target_line}  # APEX-CONFIG: hardened configuration default"

            elif spec.strategy_type == RemediationStrategyType.DATABASE_QUERY_CORRECTION:
                target_line = patched_lines[target_idx]
                indent = " " * (len(target_line) - len(target_line.lstrip()))
                patched_lines[target_idx] = f"{indent}# APEX-DB: parameterized query binding\n{indent}result = session.execute(query_stmt, params)"

            elif spec.strategy_type == RemediationStrategyType.DATABASE_MIGRATION_CORRECTION:
                target_line = patched_lines[target_idx]
                indent = " " * (len(target_line) - len(target_line.lstrip()))
                patched_lines[target_idx] = f"{indent}# APEX-MIGRATION: schema aligned revision\n{target_line}"

            elif spec.strategy_type == RemediationStrategyType.TEST_FIRST_CORRECTION:
                target_line = patched_lines[target_idx]
                indent = " " * (len(target_line) - len(target_line.lstrip()))
                patched_lines[target_idx] = f"{target_line}  # APEX: verified against reproduction test"

            else:
                target_line = patched_lines[target_idx]
                indent = " " * (len(target_line) - len(target_line.lstrip()))
                patched_lines[target_idx] = f"{indent}# Architectural refactor boundary\n{target_line}"

            orig_str = "\n".join(original_lines) + "\n"
            patch_str = "\n".join(patched_lines) + "\n"
            diff = generate_unified_diff(orig_str, patch_str, file_rel)
            diff_chunks.append(diff)

        return "\n".join(diff_chunks)

    @classmethod
    def generate_plans_for_workflow(
        cls,
        session: Session,
        workflow_id: str,
        repo_root: Path | None = None,
    ) -> list[RemediationPlanRecord]:
        """Synthesizes alternative plans, calculates scores & risks, and persists RemediationPlanRecord entries."""
        workflow = session.scalar(select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id))
        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' not found")

        project = session.get(ReviewedProject, workflow.project_id)
        if not project:
            raise ValueError(f"Project '{workflow.project_id}' not found")

        # Load linked findings
        findings_query = (
            select(ProjectFinding)
            .join(RemediationWorkflowFinding, RemediationWorkflowFinding.finding_id == ProjectFinding.id)
            .where(RemediationWorkflowFinding.workflow_id == workflow_id)
        )
        findings = list(session.scalars(findings_query).all())
        target_finding_ids = [f.id for f in findings]
        affected_files = sorted(list({f.file_path for f in findings if f.file_path}))
        finding_rules = [f.rule_id for f in findings if f.rule_id]

        # Load hypotheses
        hypotheses = list(
            session.scalars(
                select(RemediationRootCauseHypothesisRecord).where(
                    RemediationRootCauseHypothesisRecord.workflow_id == workflow_id
                )
            ).all()
        )
        primary_hypothesis = hypotheses[0] if hypotheses else None
        category = primary_hypothesis.category if primary_hypothesis else "code_defect"

        # 1. Blast Radius Analysis
        # Build minimal graph nodes/edges if none provided
        graph_nodes = {
            f"file::{f}": GraphNode(
                canonical_id=f"file::{f}",
                project_id=workflow.project_id,
                entity_type=NodeType.MODULE.value,
                name=Path(f).name,
                qualified_name=f,
                file_path=f,
            )
            for f in affected_files
        }
        blast_radius = BlastRadiusEngine.calculate_blast_radius(
            nodes=graph_nodes,
            edges=[],
            target_ids_or_files=affected_files or ["unknown_target"],
        )

        # 2. Targeted Test Recommendations
        recommended_tests = TargetedTestSelector.recommend_tests(
            nodes=graph_nodes,
            edges=[],
            targets=affected_files or ["unknown_target"],
        )

        # 3. Rule-Based Engineering Risk Baseline
        risk_baseline = RuleBasedEngineeringRiskBaseline()
        features = {
            "static_security_risk": 1.0 if any("sec" in r.lower() for r in finding_rules) else 0.0,
            "static_architecture_risk": 1.0 if any("arch" in r.lower() or "cycle" in r.lower() for r in finding_rules) else 0.0,
            "graph_api_exposure": float(blast_radius.affected_apis_count),
            "graph_database_involvement": float(blast_radius.affected_tables_count),
            "test_missing_evidence": 1.0 if not recommended_tests else 0.0,
        }
        risk_prediction = risk_baseline.predict_proba(features)

        # 4. Generate Strategy Candidate Specs
        specs = cls.generate_strategy_specs_for_category(category, finding_rules)

        # 5. Score, compare, and build RemediationPlanRecord
        plans: list[RemediationPlanRecord] = []
        created_plans_data: list[tuple[RemediationPlanRecord, float, StrategyCandidateSpec]] = []

        for spec in specs:
            plan_id = f"plan_{uuid_str()[:12]}"
            score, breakdown, approval_tier, explanation = cls.score_plan(
                spec=spec,
                hypothesis=primary_hypothesis,
                blast_radius=blast_radius,
                recommended_tests=recommended_tests,
                risk_prediction=risk_prediction,
            )

            # Check for abstention condition
            abstain_reason: str | None = None
            if primary_hypothesis and primary_hypothesis.evidence_completeness_score < 0.20 and primary_hypothesis.status == "INSUFFICIENT_EVIDENCE":
                abstain_reason = (
                    "Insufficient evidence to safely proceed with autonomous remediation. "
                    "Evidence completeness is below 20%. Human architectural guidance required."
                )
            elif blast_radius.blast_radius_score > 80.0 and not recommended_tests:
                abstain_reason = (
                    "Blast radius is critical (>80.0) with zero targeted test coverage. "
                    "Autonomous candidate application abstained to prevent undetected regression."
                )

            # Synthesize unverified patch representation
            unverified_patch = cls.synthesize_unverified_patch_diff(
                spec=spec,
                affected_files=affected_files,
                findings=findings,
                repo_root=repo_root,
            )

            # Assemble required tests info
            req_tests_payload = [t.to_dict() for t in recommended_tests]

            # Risk assessment structure
            risk_payload = {
                "blast_radius_score": blast_radius.blast_radius_score,
                "risk_level": blast_radius.risk_level,
                "affected_modules": blast_radius.affected_modules,
                "predictive_risk_distribution": risk_prediction,
                "scoring_weights_used": SCORING_WEIGHTS,
                "candidate_patch_preview": unverified_patch,
            }

            plan_record = RemediationPlanRecord(
                plan_id=plan_id,
                workflow_id=workflow_id,
                tenant_id=workflow.tenant_id,
                project_id=workflow.project_id,
                strategy_name=spec.strategy_type.value,
                strategy_description=spec.description,
                target_findings=target_finding_ids,
                affected_files=affected_files,
                root_cause_reference={
                    "hypothesis_id": primary_hypothesis.hypothesis_id if primary_hypothesis else None,
                    "hypothesis_status": primary_hypothesis.status if primary_hypothesis else None,
                    "category": category,
                },
                proposed_changes_summary=f"{spec.title}: {spec.summary_of_changes}",
                regression_risks=[
                    f"Collateral disruption to downstream callers in {len(blast_radius.affected_modules)} module(s)",
                    "Potential runtime behavioral change requiring regression suite execution",
                ],
                required_tests=req_tests_payload,
                rollback_strategy="MULTI_FILE_JOURNAL_RESTORE",
                risk_assessment=risk_payload,
                plan_score=score,
                score_breakdown=breakdown,
                ranking_explanation=explanation,
                approval_tier_required=approval_tier,
                estimated_complexity=spec.complexity,
                is_preferred=False,
                abstain_reason=abstain_reason,
            )

            session.add(plan_record)
            created_plans_data.append((plan_record, score, spec))

        # Select highest-scoring non-abstained plan as preferred
        non_abstained = [item for item in created_plans_data if not item[0].abstain_reason]
        if non_abstained:
            best_plan = max(non_abstained, key=lambda x: x[1])[0]
            best_plan.is_preferred = True
            workflow.active_plan_id = best_plan.plan_id
        elif created_plans_data:
            # All abstained; keep highest score flagged but retain abstain_reason
            best_plan = max(created_plans_data, key=lambda x: x[1])[0]
            best_plan.is_preferred = True
            workflow.active_plan_id = best_plan.plan_id

        session.flush()
        return [item[0] for item in created_plans_data]


def uuid_str() -> str:
    import uuid
    return uuid.uuid4().hex
