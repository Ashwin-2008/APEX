"""Prediction Explainability and Evidence Attribution Engine (Phase 4.2).

Explains predictions by strictly separating into a 5-Tier Evidence Classification:
Tier 1: Direct Historical Evidence (observed findings, commit transitions, verified test outcomes)
Tier 2: Structural Graph Evidence (dependencies, reachability, API/DB exposure, fan-in/fan-out)
Tier 3: Rule-Based Deterministic Evidence (churn heuristics, historical failure density, threshold triggers)
Tier 4: Statistical Model Evidence (calibrated feature importances, probability attributions)
Tier 5: Missing Evidence and Limitations (unexecuted tests, lack of runtime trace, low sample counts)
"""
from __future__ import annotations

from typing import Any
from .constants import FAILURE_CATEGORIES


class PredictionExplanationEngine:
    """Builds truthful, transparent 5-tier explanations without fabricating causal claims."""

    @classmethod
    def build_explanation(
        cls,
        *,
        predicted_outcome: str,
        confidence: float,
        features: dict[str, float],
        feature_importances: dict[str, float] | None = None,
        historical_findings: list[dict[str, Any]] | None = None,
        graph_paths: list[dict[str, Any]] | None = None,
        missing_evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generates evidence-backed structured explanation with 5-tier attribution."""

        # Tier 1: Direct Observed / Historical Evidence
        direct_historical_evidence: list[dict[str, Any]] = []
        if historical_findings:
            matching = [f for f in historical_findings if f.get("category") == predicted_outcome]
            for f in matching[:4]:
                direct_historical_evidence.append({
                    "evidence_type": "HISTORICAL_FINDING",
                    "title": f.get("title") or f.get("category"),
                    "severity": f.get("severity", "medium"),
                    "file": f.get("file"),
                    "line": f.get("line"),
                    "detected_at": str(f.get("detected_at") or ""),
                })

        # Tier 2: Structural Graph Evidence
        structural_graph_evidence: list[dict[str, Any]] = []
        if features.get("graph_api_exposure", 0.0) > 0:
            structural_graph_evidence.append({
                "type": "API_EXPOSURE",
                "detail": "Target entity is directly reachable from public REST API route handlers.",
            })
        if features.get("graph_database_involvement", 0.0) > 0:
            structural_graph_evidence.append({
                "type": "DATABASE_INVOLVEMENT",
                "detail": "Target component participates in persistent ORM model data manipulation.",
            })
        if features.get("graph_fan_in", 0.0) > 3:
            structural_graph_evidence.append({
                "type": "HIGH_FAN_IN",
                "detail": f"Target has elevated fan-in ({int(features['graph_fan_in'])} callers).",
            })
        if graph_paths:
            structural_graph_evidence.extend(graph_paths[:3])

        # Tier 3: Rule-Based Deterministic Evidence
        rule_based_evidence: list[dict[str, Any]] = []
        churn = features.get("churn_line_modifications", 0.0)
        if churn > 50:
            rule_based_evidence.append({
                "rule": "HIGH_CODE_CHURN",
                "detail": f"Elevated modification churn ({int(churn)} lines modified) triggers change risk threshold.",
            })
        total_findings = sum(
            features.get(k, 0.0)
            for k in ("static_high_findings", "static_critical_findings", "static_medium_findings")
        )
        if total_findings >= 3:
            rule_based_evidence.append({
                "rule": "ACTIVE_DEFECT_ACCUMULATION",
                "detail": f"Component has {int(total_findings)} active static findings awaiting remediation.",
            })

        # Tier 4: Statistical Model Evidence (Attributions)
        statistical_model_evidence: list[dict[str, Any]] = []
        if feature_importances:
            for feat_name, imp in list(feature_importances.items())[:5]:
                val = features.get(feat_name, 0.0)
                if val != 0.0 or imp > 0.05:
                    statistical_model_evidence.append({
                        "feature": feat_name,
                        "value": val,
                        "model_importance": round(imp, 4),
                        "description": cls._describe_feature(feat_name, val),
                    })

        # Tier 5: Missing Evidence and Limitations
        missing_evidence_list: list[str] = list(missing_evidence or [])
        if features.get("test_missing_evidence", 0.0) > 0:
            missing_evidence_list.append("Missing dynamic runtime test coverage evidence for target component.")
        if confidence < 0.60:
            missing_evidence_list.append("Prediction confidence is moderate; statistical variation remains possible.")

        # Summary text
        summary = (
            f"Component displays elevated likelihood of {predicted_outcome.replace('_', ' ').upper()} "
            f"(confidence {confidence:.1%}), derived from historical defect frequency and graph dependency topology."
        )

        return {
            "summary": summary,
            "predicted_outcome": predicted_outcome,
            "confidence": round(confidence, 4),
            # 5-Tier explicit structure
            "direct_historical_evidence": direct_historical_evidence,
            "structural_graph_evidence": structural_graph_evidence,
            "rule_based_evidence": rule_based_evidence,
            "statistical_model_evidence": statistical_model_evidence,
            "missing_evidence_and_limitations": missing_evidence_list,
            # Backward-compatible keys
            "feature_attributions": statistical_model_evidence,
            "direct_observed_evidence": direct_historical_evidence,
            "graph_structural_evidence": structural_graph_evidence,
            "limitations_and_missing_evidence": missing_evidence_list,
        }

    @staticmethod
    def _describe_feature(feat_name: str, val: float) -> str:
        if feat_name.startswith("seq_freq_"):
            cat = feat_name.replace("seq_freq_", "")
            return f"Historical occurrences of {cat}: {int(val)}"
        if feat_name.startswith("static_") and feat_name.endswith("_findings"):
            sev = feat_name.replace("static_", "").replace("_findings", "")
            return f"Active {sev} severity findings in component: {int(val)}"
        if feat_name.startswith("graph_"):
            metric = feat_name.replace("graph_", "").replace("_", " ")
            return f"Structural graph {metric}: {val}"
        return f"{feat_name}: {val}"
