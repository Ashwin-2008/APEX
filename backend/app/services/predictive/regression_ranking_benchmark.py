"""Graph-Grounded Regression Ranking and Test Recommendation Benchmark (Phase 4.2 / 4.2.1 - Task C).

Evaluates test selection as a ranking problem rather than an arbitrary binary label:
- Precision@1 through Precision@10
- Recall@1 through Recall@10
- Mean Reciprocal Rank (MRR)
- Normalized Discounted Cumulative Gain (NDCG@K)
- Unnecessary Recommendation Rate (% recommended but irrelevant/passing)
- Relevant-Test Coverage (% failing/impacted tests captured in top-K)
- Negative Fixture Intrusion (penalizing selection of unrelated tests)
- Baseline Comparisons: Graph Reachability vs File Proximity vs Package Relevance vs Uniform
- Distinct status boundaries:
  - Recommendation status: RECOMMENDED vs NOT_RECOMMENDED
  - Execution status: NOT_EXECUTED, EXECUTED_PASS, EXECUTED_FAIL, SKIPPED
  - Scientific Rule: A recommended test is NOT a predicted failing test; execution is never claimed without evidence.
- Per-repository breakdown reporting
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import os
from typing import Any

import numpy as np


@dataclass
class TestCaseEvaluationRecord:
    """Ground truth and ranking record for a single test case relative to a change."""

    __test__ = False

    test_id: str
    test_path: str
    target_symbol_or_file: str
    is_directly_connected: bool = False  # Direct call or direct import
    is_transitively_connected: bool = False  # Multi-hop graph reach
    is_negative_fixture: bool = False  # Unrelated test that should NOT be selected
    ci_status: str = "NOT_EXECUTED"  # "NOT_EXECUTED", "EXECUTED_PASS", "EXECUTED_FAIL", "SKIPPED", "PASSED", "FAILED"
    failed_in_outcome: bool = False  # Ground-truth failure in subsequent build/CI
    relevance_score: float = 0.0  # 0.0 to 1.0 ground truth relevance grade
    recommendation_status: str = "NOT_RECOMMENDED"
    repository_id: str = "repo_main"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RankingMetrics:
    """Standard information retrieval ranking metrics across cutoffs."""

    precision_at_1: float
    precision_at_3: float
    precision_at_5: float
    precision_at_10: float
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_3: float
    ndcg_at_5: float
    ndcg_at_10: float
    unnecessary_recommendation_rate_at_5: float
    relevant_test_coverage_at_5: float
    negative_fixture_intrusion_rate: float
    unexecuted_test_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RegressionRankingEvaluator:
    """Benchmark engine evaluating ranked test recommendations against IR baselines."""

    @classmethod
    def score_and_rank_tests(
        cls,
        test_records: list[TestCaseEvaluationRecord],
        ranking_strategy: str = "graph_reachability",
    ) -> list[tuple[TestCaseEvaluationRecord, float]]:
        """Ranks test records according to a given strategy.

        Strategies:
        - "graph_reachability": direct connections ranked first, followed by transitive reach, then negative.
        - "file_proximity": matches file basename tokens between target and test path.
        - "package_relevance": matches directory/package path prefixes.
        - "all_tests": natural file order (no prioritization).
        - "random": deterministic pseudo-random baseline based on test_id hash.
        """
        scored: list[tuple[TestCaseEvaluationRecord, float]] = []

        for rec in test_records:
            score = 0.0
            if ranking_strategy == "graph_reachability":
                if rec.is_negative_fixture:
                    score = 0.01
                elif rec.is_directly_connected:
                    score = 0.95
                elif rec.is_transitively_connected:
                    score = 0.60
                else:
                    score = 0.10

            elif ranking_strategy == "file_proximity":
                target_base = os.path.splitext(os.path.basename(rec.target_symbol_or_file))[0].lower().replace("test_", "")
                test_base = os.path.splitext(os.path.basename(rec.test_path))[0].lower().replace("test_", "")
                if rec.is_negative_fixture:
                    score = 0.02
                elif target_base and (target_base in test_base or test_base in target_base):
                    score = 0.85
                else:
                    score = 0.15

            elif ranking_strategy == "package_relevance":
                target_dir = os.path.dirname(rec.target_symbol_or_file).replace("\\", "/").lower()
                test_dir = os.path.dirname(rec.test_path).replace("\\", "/").lower()
                if rec.is_negative_fixture:
                    score = 0.02
                elif target_dir and (target_dir in test_dir or test_dir in target_dir):
                    score = 0.70
                else:
                    score = 0.15

            elif ranking_strategy == "all_tests":
                score = 0.50

            elif ranking_strategy == "random":
                score = float((hash(rec.test_id) % 1000) / 1000.0)

            else:
                score = 0.50

            scored.append((rec, score))

        # Sort descending by score; break ties deterministically
        scored.sort(
            key=lambda item: (item[1], 1 if item[0].is_directly_connected else 0, item[0].test_id),
            reverse=True,
        )

        # Annotate top 5 as RECOMMENDED
        for idx, (rec, _) in enumerate(scored):
            rec.recommendation_status = "RECOMMENDED" if idx < 5 else "NOT_RECOMMENDED"

        return scored

    @classmethod
    def evaluate_ranking(
        cls,
        ranked_items: list[tuple[TestCaseEvaluationRecord, float]],
    ) -> RankingMetrics:
        """Computes Precision@K, Recall@K, MRR, NDCG@K, unnecessary rate, and negative intrusion."""
        if not ranked_items:
            return RankingMetrics(
                precision_at_1=0.0,
                precision_at_3=0.0,
                precision_at_5=0.0,
                precision_at_10=0.0,
                recall_at_1=0.0,
                recall_at_3=0.0,
                recall_at_5=0.0,
                recall_at_10=0.0,
                mrr=0.0,
                ndcg_at_3=0.0,
                ndcg_at_5=0.0,
                ndcg_at_10=0.0,
                unnecessary_recommendation_rate_at_5=0.0,
                relevant_test_coverage_at_5=0.0,
                negative_fixture_intrusion_rate=0.0,
                unexecuted_test_count=0,
            )

        # Ground truth relevance: failed_in_outcome OR relevance_score >= 0.5
        total_relevant = sum(
            1 for rec, _ in ranked_items if (rec.failed_in_outcome or rec.relevance_score >= 0.5)
        )
        unexecuted_count = sum(
            1 for rec, _ in ranked_items if str(rec.ci_status).upper() in {"NOT_EXECUTED", "UNEXECUTED"}
        )

        # MRR calculation
        first_rel_rank = 0
        for idx, (rec, _) in enumerate(ranked_items, start=1):
            if rec.failed_in_outcome or rec.relevance_score >= 0.5:
                first_rel_rank = idx
                break
        mrr = (1.0 / first_rel_rank) if first_rel_rank > 0 else 0.0

        def precision_at_k(k: int) -> float:
            top_k = ranked_items[:k]
            if not top_k:
                return 0.0
            rel_k = sum(1 for r, _ in top_k if (r.failed_in_outcome or r.relevance_score >= 0.5))
            return rel_k / len(top_k)

        def recall_at_k(k: int) -> float:
            if total_relevant == 0:
                return 1.0
            top_k = ranked_items[:k]
            rel_k = sum(1 for r, _ in top_k if (r.failed_in_outcome or r.relevance_score >= 0.5))
            return rel_k / total_relevant

        def dcg_at_k(k: int) -> float:
            top_k = ranked_items[:k]
            dcg = 0.0
            for idx, (r, _) in enumerate(top_k, start=1):
                gain = 1.0 if (r.failed_in_outcome or r.relevance_score >= 0.5) else 0.0
                dcg += gain / math.log2(idx + 1)
            return dcg

        def idcg_at_k(k: int) -> float:
            idcg = 0.0
            for idx in range(1, min(k, total_relevant) + 1):
                idcg += 1.0 / math.log2(idx + 1)
            return idcg

        def ndcg_at_k(k: int) -> float:
            idcg = idcg_at_k(k)
            if idcg == 0.0:
                return 1.0 if total_relevant == 0 else 0.0
            return dcg_at_k(k) / idcg

        # Unnecessary Recommendation Rate at 5
        top_5 = ranked_items[:5]
        if top_5:
            unnecessary_5 = sum(
                1 for r, _ in top_5 if not (r.failed_in_outcome or r.relevance_score >= 0.5)
            )
            unnecessary_rate_5 = unnecessary_5 / len(top_5)
        else:
            unnecessary_rate_5 = 0.0

        # Relevant-test coverage at 5
        relevant_coverage_5 = recall_at_k(5)

        # Negative fixture intrusion: fraction of negative fixtures in top 5
        if top_5:
            negative_intrusion = sum(1 for r, _ in top_5 if r.is_negative_fixture) / len(top_5)
        else:
            negative_intrusion = 0.0

        return RankingMetrics(
            precision_at_1=float(precision_at_k(1)),
            precision_at_3=float(precision_at_k(3)),
            precision_at_5=float(precision_at_k(5)),
            precision_at_10=float(precision_at_k(10)),
            recall_at_1=float(recall_at_k(1)),
            recall_at_3=float(recall_at_k(3)),
            recall_at_5=float(recall_at_k(5)),
            recall_at_10=float(recall_at_k(10)),
            mrr=float(mrr),
            ndcg_at_3=float(ndcg_at_k(3)),
            ndcg_at_5=float(ndcg_at_k(5)),
            ndcg_at_10=float(ndcg_at_k(10)),
            unnecessary_recommendation_rate_at_5=float(unnecessary_rate_5),
            relevant_test_coverage_at_5=float(relevant_coverage_5),
            negative_fixture_intrusion_rate=float(negative_intrusion),
            unexecuted_test_count=unexecuted_count,
        )

    @classmethod
    def evaluate_multi_repository_benchmark(
        cls,
        fixtures_by_repo: dict[str, list[TestCaseEvaluationRecord]],
        ranking_strategy: str = "graph_reachability",
    ) -> dict[str, Any]:
        """Evaluates ranking benchmark across multiple repositories with per-repository metrics."""
        per_repo_metrics = {}
        all_ranked: list[tuple[TestCaseEvaluationRecord, float]] = []

        for repo_id, records in fixtures_by_repo.items():
            ranked = cls.score_and_rank_tests(records, ranking_strategy=ranking_strategy)
            all_ranked.extend(ranked)
            per_repo_metrics[repo_id] = cls.evaluate_ranking(ranked).to_dict()

        aggregate_metrics = cls.evaluate_ranking(all_ranked).to_dict()

        return {
            "strategy": ranking_strategy,
            "aggregate_metrics": aggregate_metrics,
            "per_repository_metrics": per_repo_metrics,
            "total_test_cases_evaluated": len(all_ranked),
            "repository_count": len(fixtures_by_repo),
        }
