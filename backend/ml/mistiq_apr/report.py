"""Adaptive MISTIQ-APR research report generation.

The report automatically switches between an INSUFFICIENT DATA state and a
VALID EVALUATION AVAILABLE state (or a leakage-refusal state). Every number
shown is measured; unavailable sections render an explicit reason and an em
dash instead of placeholders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_FILENAME = "MISTIQ_APR_RESEARCH_REPORT.md"
_PROTECTED_REPORT_PATH = (
    Path(__file__).resolve().parents[1] / "artifacts" / "mistiq_apr" / REPORT_FILENAME
).resolve()


def _f(value: Any) -> str:
    """Format a metric; em dash when unavailable (never a fake number)."""
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _metrics_of(result: dict[str, Any]) -> dict[str, Any]:
    return result.get("metrics") or {}


def _format_range(date_range: dict[str, str] | None) -> str:
    if not date_range:
        return "—"
    return f"{date_range.get('first', '—')} → {date_range.get('last', '—')}"


def write_report(path: str | Path, dataset: dict[str, Any], evaluation: dict[str, Any]) -> Path:
    """Write the full research report; adapts honestly to the available data."""
    destination = Path(path)
    try:
        if destination.resolve() == _PROTECTED_REPORT_PATH and _PROTECTED_REPORT_PATH.exists():
            destination = _PROTECTED_REPORT_PATH.parent / "reports" / REPORT_FILENAME
    except OSError:
        pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    status = str(evaluation.get("status") or "UNKNOWN")
    refused = bool(evaluation.get("refused"))
    valid = status.startswith("VALID EVALUATION AVAILABLE")

    if refused:
        headline = "EVALUATION REFUSED: DATA LEAKAGE DETECTED"
        summary = (
            "Critical data leakage was detected by the automated validator, so no model "
            "evaluation was run. See the leakage checks below."
        )
    elif valid:
        headline = "VALID EVALUATION AVAILABLE"
        summary = (
            "The chronological dataset passed every leakage check and reached the "
            "walk-forward threshold; results below are measured, not projected."
        )
    else:
        headline = "INSUFFICIENT DATA"
        summary = (
            "There are not enough real chronological review transitions for a rigorous "
            "evaluation. No accuracy is reported because none has been measured."
        )

    lines = [
        "# MISTIQ-APR Research Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "## Research question",
        "Can the trajectory of software engineering failures predict the next project",
        "failure category better than static project-quality metrics?",
        "",
        f"## Status: {headline}",
        summary,
        "",
        "## Dataset status",
        f"- Projects: {dataset.get('projects', 0)}",
        f"- Reviews: {dataset.get('reviews', 0)}",
        f"- Transitions: {dataset.get('transitions', 0)}",
        f"- Training observations: {dataset.get('training_observations', 0)}",
        f"- Failure categories observed: {dataset.get('failure_categories', 0)}",
        f"- Date range: {_format_range(dataset.get('date_range'))}",
        f"- Sample size (observations available for modeling): {dataset.get('training_observations', 0)}",
        f"- Dataset status: {dataset.get('status', 'UNKNOWN')}",
        f"- Dataset version: {dataset.get('dataset_version', '—')}",
        "",
        "## Temporal evaluation methodology",
        evaluation.get(
            "methodology",
            "Walk-forward temporal evaluation with expanding training windows and no shuffling.",
        ),
        "",
    ]
    lines += _leakage_section(evaluation.get("leakage"))
    lines += _baseline_section(evaluation)
    lines += _mistiq_section(evaluation)
    lines += _walk_forward_section(evaluation.get("walk_forward") or {})
    lines += _ablation_section(evaluation.get("ablation"))
    lines += _calibration_section(evaluation.get("calibration"))
    lines += _artifact_section(evaluation.get("training"))
    lines += _limitations_section(dataset, evaluation)

    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


def _leakage_section(leakage: dict[str, Any] | None) -> list[str]:
    lines = ["## Leakage checks", ""]
    if not leakage:
        lines += ["Leakage validation has not been run for this report.", ""]
        return lines
    verdict = "PASSED" if leakage.get("passed") else "FAILED"
    lines += [f"Verdict: **{verdict}**", ""]
    lines += ["| Check | Status | Detail |", "|---|---|---|"]
    for check in leakage.get("checks", []):
        lines.append(f"| {check.get('name')} | {check.get('status')} | {check.get('detail')} |")
    for error in leakage.get("errors", []):
        lines.append(f"- ERROR: {error}")
    for warning in leakage.get("warnings", []):
        lines.append(f"- Warning: {warning}")
    lines.append("")
    return lines


def _baseline_section(evaluation: dict[str, Any]) -> list[str]:
    lines = [
        "## Baseline comparison",
        "",
        "Pooled across all valid walk-forward cutoffs (accuracy / macro F1 / top-3 accuracy).",
        "",
        "| Model | Accuracy | Macro F1 | Top-3 | Status |",
        "|---|---:|---:|---:|---|",
    ]
    results = evaluation.get("results") or []
    if not results:
        lines += [
            "| Majority | — | — | — | INSUFFICIENT DATA |",
            "| Latest Failure | — | — | — | INSUFFICIENT DATA |",
            "| Static Logistic | — | — | — | INSUFFICIENT DATA |",
            "| Random Forest | — | — | — | INSUFFICIENT DATA |",
            "| MISTIQ-APR | — | — | — | INSUFFICIENT DATA |",
            "",
        ]
        return lines
    for result in results:
        row_metrics = _metrics_of(result)
        lines.append(
            f"| {result.get('model')} | {_f(row_metrics.get('accuracy'))} "
            f"| {_f(row_metrics.get('macro_f1'))} | {_f(row_metrics.get('top_3_accuracy'))} "
            f"| {result.get('status', '—')} |"
        )
    lines.append("")
    return lines


def _mistiq_section(evaluation: dict[str, Any]) -> list[str]:
    lines = ["## MISTIQ-APR results", ""]
    results = evaluation.get("results") or []
    primary = next((row for row in results if row.get("model") == "MISTIQ-APR"), None)
    if not primary:
        lines += [
            evaluation.get("status", "INSUFFICIENT DATA"),
            "",
            "No MISTIQ-APR performance claim can be made from the current dataset.",
            "",
        ]
        return lines
    row_metrics = _metrics_of(primary)
    lines += [
        f"Walk-forward status: {evaluation.get('status')}",
        f"- Cutoffs: {(evaluation.get('walk_forward') or {}).get('n_cutoffs', 0)}",
        f"- Accuracy: {_f(row_metrics.get('accuracy'))}",
        f"- Macro F1: {_f(row_metrics.get('macro_f1'))}",
        f"- Macro precision: {_f(row_metrics.get('macro_precision'))}",
        f"- Macro recall: {_f(row_metrics.get('macro_recall'))}",
        f"- Top-3 accuracy: {_f(row_metrics.get('top_3_accuracy'))}",
        f"- Log loss: {_f(row_metrics.get('log_loss'))}",
        "",
    ]
    return lines


def _walk_forward_section(walk_forward: dict[str, Any]) -> list[str]:
    lines = ["## Walk-forward results", ""]
    if walk_forward.get("status") != "COMPLETED":
        lines += [
            walk_forward.get("status") or "INSUFFICIENT DATA FOR WALK-FORWARD EVALUATION",
            "",
            walk_forward.get("message") or "",
            "",
        ]
        return lines
    lines += [
        walk_forward.get("message", ""),
        "",
        "| Cutoff | Train size | Test size | Train time range | Test time range | MISTIQ-APR macro F1 |",
        "|---:|---:|---:|---|---|---:|",
    ]
    for cutoff in walk_forward.get("cutoffs", []):
        train_range = cutoff.get("train_time_range", {})
        test_range = cutoff.get("test_time_range", {})
        lines.append(
            f"| {cutoff.get('cutoff')} | {cutoff.get('train_size')} | {cutoff.get('test_size')} "
            f"| {train_range.get('start', '—')} → {train_range.get('end', '—')} "
            f"| {test_range.get('start', '—')} → {test_range.get('end', '—')} "
            f"| {_f((cutoff.get('metrics') or {}).get('macro_f1'))} |"
        )
    lines += [
        "",
        f"Total pooled test predictions: {walk_forward.get('total_test_predictions', 0)}",
        "",
    ]
    return lines


def _ablation_section(ablation: dict[str, Any] | None) -> list[str]:
    lines = ["## Ablation results", ""]
    if not ablation:
        lines += ["Ablation study has not been run for this report.", ""]
        return lines
    rows = ablation.get("results") or []
    if not rows:
        message = ablation.get("status") or "Ablation evaluation unavailable: insufficient chronological observations."
        lines += [message, ""]
        return lines
    lines += [
        ablation.get("message", ""),
        "",
        "| Variant | Removed feature group | Accuracy | Macro F1 | Top-3 | Δ Macro F1 vs full |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        row_metrics = row.get("metrics") or {}
        delta = row.get("delta_macro_f1")
        lines.append(
            f"| {row.get('variant')} | {row.get('removed') or '—'} "
            f"| {_f(row_metrics.get('accuracy'))} | {_f(row_metrics.get('macro_f1'))} "
            f"| {_f(row_metrics.get('top_3_accuracy'))} "
            f"| {'—' if delta is None else f'{delta:+.4f}'} |"
        )
    lines.append("")
    return lines


def _calibration_section(calibration: dict[str, Any] | None) -> list[str]:
    lines = ["## Calibration", ""]
    if not calibration:
        lines += ["Calibration analysis has not been run for this report.", ""]
        return lines
    if not calibration.get("available"):
        reason = calibration.get("reason") or "Calibration withheld for insufficient sample size."
        lines += ["Calibration metrics are not reported.", f"Reason: {reason}", ""]
        return lines
    lines += [
        calibration.get("methodology", ""),
        "",
        f"- Sample count: {calibration.get('sample_count', 0)}",
        f"- Brier score (multiclass, lower is better): {_f(calibration.get('brier_score'))}",
        f"- Expected Calibration Error (lower is better): {_f(calibration.get('expected_calibration_error'))}",
        "",
        "| Confidence bin | Count | Mean predicted | Empirical accuracy |",
        "|---|---:|---:|---:|",
    ]
    for bin_row in calibration.get("reliability_bins", []):
        lines.append(
            f"| {bin_row.get('lower')}–{bin_row.get('upper')} | {bin_row.get('count')} "
            f"| {_f(bin_row.get('mean_predicted_confidence'))} "
            f"| {_f(bin_row.get('empirical_accuracy'))} |"
        )
    lines.append("")
    return lines


def _artifact_section(training: dict[str, Any] | None) -> list[str]:
    lines = ["## Model artifact", ""]
    if not training:
        lines += ["No training stage has been run for this report.", ""]
        return lines
    if not training.get("trained"):
        lines += [
            "No model artifact was written.",
            f"Reason: {training.get('reason') or 'training gates not satisfied'}.",
            "",
        ]
        return lines
    metadata = training.get("metadata") or {}
    lines += [
        f"Trained artifact: {training.get('path')}",
        f"- Model: {metadata.get('model')} v{metadata.get('version')}",
        f"- Feature count: {metadata.get('feature_count')}",
        f"- Categories: {len(metadata.get('categories') or [])}",
        f"- Training observations: {metadata.get('training_observations')}",
        f"- Dataset hash: {metadata.get('dataset_hash')}",
        f"- Trained at: {metadata.get('trained_at')}",
        f"- Evaluation protocol: {metadata.get('evaluation_protocol')}",
        "",
    ]
    return lines


def _limitations_section(dataset: dict[str, Any], evaluation: dict[str, Any]) -> list[str]:
    sample_size = dataset.get("training_observations", 0)
    valid = str(evaluation.get("status", "")).startswith("VALID EVALUATION AVAILABLE")
    if valid:
        confidence = (
            "Confidence: metrics are pooled over walk-forward cutoffs on this dataset only. "
            "Small-sample metrics (few cutoffs, few categories) carry high variance; "
            "confidence intervals cannot be established until more projects accumulate."
        )
    else:
        confidence = (
            "Confidence: none - no evaluation has been performed, so no performance "
            "confidence can be stated."
        )
    return [
        "## Limitations, sample size, and confidence",
        f"- Sample size: {sample_size} chronological observations across "
        f"{dataset.get('projects', 0)} project(s) and {dataset.get('reviews', 0)} review(s).",
        confidence,
        "MISTIQ-APR is a project-specific sequential failure-prediction framework adapted",
        "from the MISTIQ mistake-intelligence architecture. It is not claimed as a newly",
        "invented universal machine-learning paradigm. Results are associations, not causal",
        "claims, and cannot establish general software-engineering efficacy without more",
        "real repositories with long chronological review histories.",
        "Predictions describe historical association and are never certainties.",
        "",
    ]


write_mistiq_apr_report = write_report
