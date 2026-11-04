"""Targeted Test Selection Engine for APEX 2.0 (Phase 3.1).

Ranks and prioritizes evidence-backed test suites for modified files or functions:
- Classifies recommendations into:
  - DIRECT_TEST (direct AST invocation or assertion on the modified symbol).
  - RUNTIME_CONFIRMED_TEST (observed execution in dynamic runtime traces).
  - STATICALLY_INFERRED_TEST (downstream caller within 1-2 hops).
  - INTEGRATION_TEST (exercises affected API routes or database models).
  - END_TO_END_TEST (system-level integration tests).
  - POTENTIALLY_RELEVANT (downstream at depth >= 3).
- Strictly rejects false direct associations arising solely from shared module imports.
- Never falsely claims an unexecuted test passed (sets execution_status='NOT_EXECUTED').
- Provides Precision@K and Recall@K evaluation benchmarks.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from app.services.graph.impact_engine import ChangeImpactEngine
from app.services.graph.models import EdgeType, GraphEdge, GraphNode, NodeType


class TestRecommendationTier(str, Enum):
    __test__ = False
    DIRECT_TEST = "DIRECT_TEST"
    RUNTIME_CONFIRMED_TEST = "RUNTIME_CONFIRMED_TEST"
    STATICALLY_INFERRED_TEST = "STATICALLY_INFERRED_TEST"
    INTEGRATION_TEST = "INTEGRATION_TEST"
    END_TO_END_TEST = "END_TO_END_TEST"
    POTENTIALLY_RELEVANT = "POTENTIALLY_RELEVANT"


@dataclass
class RecommendedTest:
    test_id: str
    test_name: str
    file_path: str
    tier: str  # Kept for backward compatibility: DIRECT_TEST, TRANSITIVE_TEST, INTEGRATION_TEST
    confidence: float
    reason: str
    target_symbol: str
    # Phase 3.1 Extensions:
    classification: str = TestRecommendationTier.DIRECT_TEST.value
    evidence_path: list[str] = field(default_factory=list)
    execution_status: str = "NOT_EXECUTED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TestSelectionEngine:
    """Selects targeted tests to validate code changes with traceable evidence."""

    @classmethod
    def select_tests_for_changes(
        cls,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
        target_ids_or_files: list[str],
        max_depth: int = 4,
        runtime_traces: list[dict[str, Any]] | None = None,
    ) -> list[RecommendedTest]:
        impact_report = ChangeImpactEngine.analyze_impact(
            nodes=nodes,
            edges=edges,
            target_ids_or_files=target_ids_or_files,
            max_depth=max_depth,
        )

        test_map: dict[str, RecommendedTest] = {}
        runtime_covered_pairs: set[tuple[str, str]] = set()

        if runtime_traces:
            for t in runtime_traces:
                test_name = t.get("test_name") or t.get("test_symbol")
                target = t.get("target_symbol") or t.get("callee")
                if test_name and target:
                    runtime_covered_pairs.add((str(test_name), str(target)))

        # 1. Direct tests: Edges with rel_type == TESTED_BY
        for edge in edges:
            if edge.rel_type == EdgeType.TESTED_BY.value:
                for seed in impact_report.target_canonical_ids:
                    if edge.source_canonical_id == seed:
                        test_node = nodes.get(edge.target_canonical_id)
                        if test_node:
                            target_name = nodes[seed].name if seed in nodes else seed
                            is_runtime = bool(
                                (test_node.name, target_name) in runtime_covered_pairs
                                or (test_node.qualified_name, target_name) in runtime_covered_pairs
                            )
                            is_e2e = "e2e" in test_node.file_path.lower() or "system" in test_node.file_path.lower()
                            if is_e2e:
                                classification = TestRecommendationTier.END_TO_END_TEST.value
                            elif is_runtime:
                                classification = TestRecommendationTier.RUNTIME_CONFIRMED_TEST.value
                            else:
                                classification = TestRecommendationTier.DIRECT_TEST.value
                            conf = 1.0 if is_runtime else round(edge.confidence, 2)
                            reason = (
                                f"Directly tests modified symbol '{target_name}' (runtime confirmed)"
                                if is_runtime
                                else f"Directly tests modified symbol '{target_name}'"
                            )

                            test_map[test_node.canonical_id] = RecommendedTest(
                                test_id=test_node.canonical_id,
                                test_name=test_node.name,
                                file_path=test_node.file_path,
                                tier="DIRECT_TEST",
                                confidence=conf,
                                reason=reason,
                                target_symbol=target_name,
                                classification=classification,
                                evidence_path=[seed, test_node.canonical_id],
                                execution_status="NOT_EXECUTED",
                            )

        # 2. Transitive, API, and Database Integration Tests
        for comp in impact_report.impacted_components:
            if comp.entity_type in (NodeType.TEST_FUNCTION.value, NodeType.TEST_FILE.value):
                if comp.canonical_id not in test_map:
                    # Classify based on depth and evidence
                    fp_lower = comp.file_path.lower()
                    is_e2e = "e2e" in fp_lower or "system" in fp_lower
                    is_integration = "integration" in fp_lower or comp.depth == 2

                    if is_e2e:
                        tier = "INTEGRATION_TEST"
                        classification = TestRecommendationTier.END_TO_END_TEST.value
                    elif comp.depth == 1:
                        tier = "DIRECT_TEST"
                        classification = TestRecommendationTier.DIRECT_TEST.value
                    elif is_integration or len(impact_report.affected_apis) > 0:
                        tier = "INTEGRATION_TEST"
                        classification = TestRecommendationTier.INTEGRATION_TEST.value
                    elif comp.depth == 2:
                        tier = "TRANSITIVE_TEST"
                        classification = TestRecommendationTier.STATICALLY_INFERRED_TEST.value
                    else:
                        tier = "TRANSITIVE_TEST"
                        classification = TestRecommendationTier.POTENTIALLY_RELEVANT.value

                    test_map[comp.canonical_id] = RecommendedTest(
                        test_id=comp.canonical_id,
                        test_name=comp.name,
                        file_path=comp.file_path,
                        tier=tier,
                        confidence=round(comp.confidence, 2),
                        reason=f"Covers downstream dependency at depth {comp.depth} ({classification})",
                        target_symbol=comp.name,
                        classification=classification,
                        evidence_path=comp.evidence_path,
                        execution_status="NOT_EXECUTED",
                    )

        # Rank tests: DIRECT_TEST first, then INTEGRATION_TEST, then TRANSITIVE_TEST, by confidence descending
        tier_priority = {
            "DIRECT_TEST": 0,
            "INTEGRATION_TEST": 1,
            "TRANSITIVE_TEST": 2,
        }

        sorted_tests = sorted(
            test_map.values(),
            key=lambda t: (tier_priority.get(t.tier, 3), -t.confidence),
        )
        return sorted_tests


class TestSelectionBenchmark:
    """Evaluates test selection recommendation precision and recall against labeled pairs."""
    __test__ = False

    @classmethod
    def evaluate_precision_recall_at_k(
        cls,
        recommended: list[RecommendedTest],
        ground_truth_test_ids: set[str],
        k_values: list[int] | None = None,
    ) -> dict[str, float]:
        """Calculates Precision@K and Recall@K for the given recommendation list."""
        ks = k_values or [1, 3, 5]
        metrics: dict[str, float] = {}

        total_relevant = len(ground_truth_test_ids)

        for k in ks:
            top_k = recommended[:k]
            top_k_ids = {t.test_id for t in top_k}
            hits = len(top_k_ids & ground_truth_test_ids)

            precision_k = (hits / min(k, len(recommended))) if recommended else 0.0
            recall_k = (hits / total_relevant) if total_relevant > 0 else 0.0

            metrics[f"precision@{k}"] = round(precision_k, 4)
            metrics[f"recall@{k}"] = round(recall_k, 4)

        return metrics

    @classmethod
    def evaluate_benchmark(
        cls,
        recommended: list[RecommendedTest],
        ground_truth_test_ids: set[str],
        k_values: list[int] | None = None,
    ) -> dict[str, Any]:
        """Calculates full benchmark metrics including Precision@K, Recall@K,

        unnecessary recommendation rate, and relevant test coverage.
        """
        metrics = cls.evaluate_precision_recall_at_k(recommended, ground_truth_test_ids, k_values)

        total_rec = len(recommended)
        total_rel = len(ground_truth_test_ids)
        all_rec_ids = {t.test_id for t in recommended}
        unnecessary_hits = len([t for t in recommended if t.test_id not in ground_truth_test_ids])
        relevant_hits = len(all_rec_ids & ground_truth_test_ids)

        metrics["unnecessary_recommendation_rate"] = (
            round(unnecessary_hits / total_rec, 4) if total_rec > 0 else 0.0
        )
        metrics["relevant_test_coverage"] = (
            round(relevant_hits / total_rel, 4) if total_rel > 0 else 0.0
        )
        metrics["total_recommended"] = total_rec
        metrics["total_relevant"] = total_rel
        return metrics
