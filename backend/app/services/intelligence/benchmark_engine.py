"""Detection Benchmark & Scientific Evaluation Engine for APEX 2.0.

Provides rigorous, reproducible precision, recall, and F1 evaluation across
security, architecture, type-safety, concurrency, and runtime domains using labeled fixtures.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.services.analyzers.base import AnalyzerOutput, FindingItem


@dataclass
class BenchmarkMetricResult:
    category: str
    sample_count: int
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float
    recall: float
    f1_score: float
    duration_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkFixture:
    fixture_id: str
    category: str
    expected_rule: str
    is_vulnerability: bool  # True for TP test cases, False for clean code / true negative tests
    source_files: dict[str, str]  # rel_path -> file content


class BenchmarkEvaluationEngine:
    """Executes benchmark suites against labeled fixtures and compiles scientific accuracy reports."""

    def __init__(self) -> None:
        self.fixtures: list[BenchmarkFixture] = []

    def register_fixture(self, fixture: BenchmarkFixture) -> None:
        self.fixtures.append(fixture)

    def run_evaluation(
        self,
        analysis_fn: Callable[[Path], list[FindingItem | dict[str, Any]]],
        temp_work_dir: Path,
    ) -> dict[str, BenchmarkMetricResult]:
        """Execute all registered fixtures and compute category-level and overall metrics."""
        results_by_cat: dict[str, list[dict[str, Any]]] = {}

        for fix in self.fixtures:
            fix_dir = temp_work_dir / fix.fixture_id
            fix_dir.mkdir(parents=True, exist_ok=True)
            for rel_file, content in fix.source_files.items():
                p = fix_dir / rel_file
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")

            t0 = time.perf_counter()
            findings = analysis_fn(fix_dir)
            duration_ms = (time.perf_counter() - t0) * 1000

            # Evaluate finding presence
            matched = any(
                (f.get("rule_id") if isinstance(f, dict) else f.rule_id) == fix.expected_rule
                for f in findings
            )

            # Score outcome
            tp = 1 if fix.is_vulnerability and matched else 0
            fp = 1 if not fix.is_vulnerability and matched else 0
            fn = 1 if fix.is_vulnerability and not matched else 0
            tn = 1 if not fix.is_vulnerability and not matched else 0

            if fix.category not in results_by_cat:
                results_by_cat[fix.category] = []

            results_by_cat[fix.category].append({
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
                "duration_ms": duration_ms,
            })

        metrics: dict[str, BenchmarkMetricResult] = {}

        for cat, runs in results_by_cat.items():
            tot_tp = sum(r["tp"] for r in runs)
            tot_fp = sum(r["fp"] for r in runs)
            tot_fn = sum(r["fn"] for r in runs)
            tot_tn = sum(r["tn"] for r in runs)
            total_samples = len(runs)
            tot_duration = sum(r["duration_ms"] for r in runs)

            precision = round(tot_tp / max(1, tot_tp + tot_fp), 3) if (tot_tp + tot_fp) > 0 else 1.0
            recall = round(tot_tp / max(1, tot_tp + tot_fn), 3) if (tot_tp + tot_fn) > 0 else 1.0
            f1 = (
                round(2 * precision * recall / (precision + recall), 3)
                if (precision + recall) > 0
                else 0.0
            )

            metrics[cat] = BenchmarkMetricResult(
                category=cat,
                sample_count=total_samples,
                true_positives=tot_tp,
                false_positives=tot_fp,
                false_negatives=tot_fn,
                true_negatives=tot_tn,
                precision=precision,
                recall=recall,
                f1_score=f1,
                duration_ms=round(tot_duration, 2),
            )

        return metrics

