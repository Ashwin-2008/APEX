"""Multi-Protocol Comparative Evaluation Engine (Phase 4.2).

Executes rigorous benchmarks across three evaluation protocols:
1. Chronological Walk-Forward Validation
2. Repository-Grouped Validation
3. Leave-One-Repository-Out (LORO) Validation

Compares:
- Majority Baseline
- Historical Frequency Baseline
- Latest Failure Baseline
- Rule-Based Engineering Risk
- Logistic Regression
- Random Forest

Measures and documents:
- Number of folds
- Training observations per fold
- Test observations per fold
- Training repository count
- Test repository count
- Per-class distribution
- Macro-F1, Balanced Accuracy, Brier Score, PR-AUC, ECE
- Generalization Gap between chronological and unseen-repository evaluation
"""
from __future__ import annotations

from typing import Any
import numpy as np

from .baseline_models import (
    HistoricalFrequencyBaseline,
    LatestFailureBaseline,
    LogisticRegressionBaseline,
    MajorityClassBaseline,
    RandomForestBaseline,
    RuleBasedEngineeringRiskBaseline,
)
from .constants import MIN_REPO_OBSERVATIONS_FOR_LORO
from .model_evaluation import PredictiveModelEvaluator
from .temporal_dataset import TemporalDatasetEngine, TemporalObservation


class ComparativeEvaluationEngine:
    """Executes multi-protocol benchmarking and computes generalization gaps."""

    MODEL_FACTORIES = {
        "Majority Class Baseline": MajorityClassBaseline,
        "Historical Frequency Baseline": HistoricalFrequencyBaseline,
        "Latest Failure Baseline": LatestFailureBaseline,
        "Rule-Based Engineering Risk": RuleBasedEngineeringRiskBaseline,
        "Logistic Regression": LogisticRegressionBaseline,
        "Random Forest": RandomForestBaseline,
    }

    @classmethod
    def run_walk_forward_evaluation(
        cls,
        observations: list[TemporalObservation],
        min_train_size: int = 50,
        test_size: int = 25,
    ) -> dict[str, Any]:
        """Protocol 1: Chronological Walk-Forward Validation."""
        splits = TemporalDatasetEngine.generate_walk_forward_splits(
            observations, min_train_size=min_train_size, test_size=test_size
        )
        results: dict[str, Any] = {
            "protocol": "CHRONOLOGICAL_WALK_FORWARD",
            "folds_count": len(splits),
            "fold_metadata": [],
            "models": {},
        }

        # Record fold structural metadata
        for idx, (train_part, test_part) in enumerate(splits):
            results["fold_metadata"].append({
                "fold_index": idx + 1,
                "train_sample_size": len(train_part),
                "test_sample_size": len(test_part),
                "train_repo_count": len(set(o.repository_group for o in train_part)),
                "test_repo_count": len(set(o.repository_group for o in test_part)),
                "test_class_distribution": dict(PredictiveModelEvaluator.compute_calibration_details(
                    [o.target for o in test_part], []
                ).get("bins", [])),
            })

        for model_name, factory in cls.MODEL_FACTORIES.items():
            split_metrics = []
            for train_obs, test_obs in splits:
                model = factory().fit(train_obs)
                eval_res = PredictiveModelEvaluator.evaluate(model, test_obs, model_name=model_name)
                split_metrics.append(eval_res)

            mean_acc = round(float(np.mean([m["accuracy"] for m in split_metrics])), 4)
            mean_f1 = round(float(np.mean([m["macro_f1"] for m in split_metrics])), 4)
            mean_balanced_acc = round(float(np.mean([m.get("balanced_accuracy", m["accuracy"]) for m in split_metrics])), 4)
            mean_brier = round(float(np.mean([m["brier_score"] for m in split_metrics])), 4)
            mean_pr_auc = round(float(np.mean([m.get("pr_auc_dominant", 0.0) for m in split_metrics])), 4)
            mean_ece = round(float(np.mean([m["expected_calibration_error"] for m in split_metrics])), 4)

            results["models"][model_name] = {
                "mean_accuracy": mean_acc,
                "mean_macro_f1": mean_f1,
                "mean_balanced_accuracy": mean_balanced_acc,
                "mean_brier_score": mean_brier,
                "mean_pr_auc": mean_pr_auc,
                "mean_ece": mean_ece,
                "split_results": split_metrics,
            }

        return results

    @classmethod
    def run_repository_grouped_evaluation(
        cls,
        observations: list[TemporalObservation],
        n_groups_test: int = 2,
    ) -> dict[str, Any]:
        """Protocol 2: Repository-Grouped Validation."""
        splits = TemporalDatasetEngine.generate_repository_grouped_splits(
            observations, n_groups_test=n_groups_test
        )
        results: dict[str, Any] = {
            "protocol": "REPOSITORY_GROUPED",
            "folds_count": len(splits),
            "fold_metadata": [],
            "models": {},
        }

        for idx, (train_part, test_part) in enumerate(splits):
            results["fold_metadata"].append({
                "fold_index": idx + 1,
                "train_sample_size": len(train_part),
                "test_sample_size": len(test_part),
                "train_repo_count": len(set(o.repository_group for o in train_part)),
                "test_repo_count": len(set(o.repository_group for o in test_part)),
                "test_repositories": sorted(list(set(o.repository_group for o in test_part))),
            })

        for model_name, factory in cls.MODEL_FACTORIES.items():
            fold_metrics = []
            for train_obs, test_obs in splits:
                model = factory().fit(train_obs)
                eval_res = PredictiveModelEvaluator.evaluate(model, test_obs, model_name=model_name)
                fold_metrics.append(eval_res)

            mean_acc = round(float(np.mean([m["accuracy"] for m in fold_metrics])), 4) if fold_metrics else 0.0
            mean_f1 = round(float(np.mean([m["macro_f1"] for m in fold_metrics])), 4) if fold_metrics else 0.0
            mean_balanced_acc = round(float(np.mean([m.get("balanced_accuracy", m["accuracy"]) for m in fold_metrics])), 4) if fold_metrics else 0.0
            mean_brier = round(float(np.mean([m["brier_score"] for m in fold_metrics])), 4) if fold_metrics else 0.0
            mean_pr_auc = round(float(np.mean([m.get("pr_auc_dominant", 0.0) for m in fold_metrics])), 4) if fold_metrics else 0.0
            mean_ece = round(float(np.mean([m["expected_calibration_error"] for m in fold_metrics])), 4) if fold_metrics else 0.0

            results["models"][model_name] = {
                "mean_accuracy": mean_acc,
                "mean_macro_f1": mean_f1,
                "mean_balanced_accuracy": mean_balanced_acc,
                "mean_brier_score": mean_brier,
                "mean_pr_auc": mean_pr_auc,
                "mean_ece": mean_ece,
                "fold_results": fold_metrics,
            }

        return results

    @classmethod
    def run_leave_one_repo_out_evaluation(
        cls,
        observations: list[TemporalObservation],
        min_repo_observations: int = MIN_REPO_OBSERVATIONS_FOR_LORO,
    ) -> dict[str, Any]:
        """Protocol 3: Leave-One-Repository-Out (LORO) Validation."""
        loro_data = TemporalDatasetEngine.generate_leave_one_repo_out_splits(
            observations, min_repo_observations=min_repo_observations
        )
        folds = loro_data["folds"]
        results: dict[str, Any] = {
            "protocol": "LEAVE_ONE_REPOSITORY_OUT",
            "folds_count": len(folds),
            "eligible_repositories_count": loro_data["eligible_count"],
            "eligible_repositories": loro_data["eligible_repositories"],
            "excluded_repositories_count": loro_data["excluded_count"],
            "excluded_repositories": loro_data["excluded_repositories"],
            "fold_metadata": [
                {
                    "fold_index": idx + 1,
                    "held_out_repository": fold["held_out_repository"],
                    "train_sample_size": fold["train_sample_size"],
                    "test_sample_size": fold["test_sample_size"],
                }
                for idx, fold in enumerate(folds)
            ],
            "models": {},
        }

        for model_name, factory in cls.MODEL_FACTORIES.items():
            fold_metrics = []
            for fold in folds:
                held_out_repo = fold["held_out_repository"]
                train_obs = fold["train_observations"]
                test_obs = fold["test_observations"]

                model = factory().fit(train_obs)
                eval_res = PredictiveModelEvaluator.evaluate(model, test_obs, model_name=model_name)
                eval_res["held_out_repository"] = held_out_repo
                fold_metrics.append(eval_res)

            mean_acc = round(float(np.mean([m["accuracy"] for m in fold_metrics])), 4) if fold_metrics else 0.0
            mean_f1 = round(float(np.mean([m["macro_f1"] for m in fold_metrics])), 4) if fold_metrics else 0.0
            mean_balanced_acc = round(float(np.mean([m.get("balanced_accuracy", m["accuracy"]) for m in fold_metrics])), 4) if fold_metrics else 0.0
            mean_brier = round(float(np.mean([m["brier_score"] for m in fold_metrics])), 4) if fold_metrics else 0.0
            mean_pr_auc = round(float(np.mean([m.get("pr_auc_dominant", 0.0) for m in fold_metrics])), 4) if fold_metrics else 0.0
            mean_ece = round(float(np.mean([m["expected_calibration_error"] for m in fold_metrics])), 4) if fold_metrics else 0.0

            results["models"][model_name] = {
                "mean_accuracy": mean_acc,
                "mean_macro_f1": mean_f1,
                "mean_balanced_accuracy": mean_balanced_acc,
                "mean_brier_score": mean_brier,
                "mean_pr_auc": mean_pr_auc,
                "mean_ece": mean_ece,
                "per_repository_results": [
                    {
                        "held_out_repository": m["held_out_repository"],
                        "sample_size": m["sample_size"],
                        "accuracy": m["accuracy"],
                        "macro_f1": m["macro_f1"],
                        "balanced_accuracy": m.get("balanced_accuracy", m["accuracy"]),
                        "brier_score": m["brier_score"],
                        "expected_calibration_error": m["expected_calibration_error"],
                    }
                    for m in fold_metrics
                ],
            }

        return results

    @classmethod
    def execute_full_benchmark_suite(
        cls,
        observations: list[TemporalObservation],
    ) -> dict[str, Any]:
        """Runs all three protocols and calculates generalization gap."""
        wf_res = cls.run_walk_forward_evaluation(observations)
        grouped_res = cls.run_repository_grouped_evaluation(observations)
        loro_res = cls.run_leave_one_repo_out_evaluation(observations)

        generalization_gap = {}
        for m_name in cls.MODEL_FACTORIES.keys():
            wf_f1 = wf_res["models"].get(m_name, {}).get("mean_macro_f1", 0.0)
            grouped_f1 = grouped_res["models"].get(m_name, {}).get("mean_macro_f1", 0.0)
            loro_f1 = loro_res["models"].get(m_name, {}).get("mean_macro_f1", 0.0)

            gap_loro = round(wf_f1 - loro_f1, 4)
            gap_grouped = round(wf_f1 - grouped_f1, 4)

            generalization_gap[m_name] = {
                "walk_forward_f1": wf_f1,
                "repository_grouped_f1": grouped_f1,
                "loro_f1": loro_f1,
                "generalization_gap_loro": gap_loro,
                "generalization_gap_grouped": gap_grouped,
                "interpretation": (
                    f"Performance drops by {gap_loro:.1%} on unseen repositories"
                    if gap_loro > 0
                    else "Generalizes stably to unseen repositories"
                ),
            }

        return {
            "walk_forward": wf_res,
            "repository_grouped": grouped_res,
            "leave_one_repository_out": loro_res,
            "generalization_gap": generalization_gap,
            "scientific_note": (
                "Chronological Walk-Forward measures temporal progression within seen projects. "
                "Repository-Grouped and LORO measure cross-project transfer to completely unseen repositories. "
                "Protocols are kept strictly separate and not averaged into an opaque headline metric."
            ),
        }
