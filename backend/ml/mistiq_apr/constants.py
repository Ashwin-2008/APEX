"""Failure taxonomy, severity handling, and feature schema for MISTIQ-APR."""
from __future__ import annotations

# The engineering failure categories used by the MISTIQ project review engine.
# Must match FAILURE_CATEGORIES in backend/app/services/project_review_service.py
# and the category column of the ProjectFinding table.
FAILURE_CATEGORIES = (
    "requirements",
    "architecture",
    "authentication",
    "authorization",
    "input_validation",
    "data_integrity",
    "api_contract",
    "error_handling",
    "testing",
    "dependency",
    "performance",
    "security",
    "configuration",
    "deployment",
    "observability",
    "integration",
)

# Severity ordering used by the review engine and the metrics stored per review.
SEVERITY_LEVELS = ("critical", "high", "medium", "low")
SEVERITY_RANK = {sev: idx for idx, sev in enumerate(SEVERITY_LEVELS)}

# Dataset version: bump when the schema of a persisted observation changes.
PROJECT_REVIEW_DATASET_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Research evaluation thresholds.
# These gates decide when a rigorous evaluation is possible. They are only
# ever used to REFUSE evaluation on small data — never to fabricate results.
# ---------------------------------------------------------------------------

# Minimum chronological observations before any model evaluation is attempted.
MIN_OBSERVATIONS_FOR_EVALUATION = 10

# Minimum number of distinct chronological timepoints (source reviews) required.
MIN_DISTINCT_TIMEPOINTS_FOR_EVALUATION = 3

# Minimum distinct failure categories (targets) required for evaluation.
MIN_DISTINCT_CATEGORIES_FOR_EVALUATION = 2

# Minimum training observations at any walk-forward cutoff.
WALK_FORWARD_MIN_TRAIN_OBSERVATIONS = 6

# Minimum pooled walk-forward test predictions before calibration is reported.
MIN_CALIBRATION_SAMPLES = 20

# Persisted model metadata.
MODEL_NAME = "MISTIQ-APR"
MODEL_VERSION = "1.0"
EVALUATION_PROTOCOL = "walk_forward"

# Honest messaging shared by evaluation, report, and API layers.
STATUS_INSUFFICIENT_EVALUATION = "INSUFFICIENT DATA FOR VALID MODEL EVALUATION"
STATUS_INSUFFICIENT_WALK_FORWARD = "INSUFFICIENT DATA FOR WALK-FORWARD EVALUATION"
STATUS_VALID_EVALUATION = "VALID EVALUATION AVAILABLE"
ABLATION_UNAVAILABLE_MESSAGE = "Ablation evaluation unavailable: insufficient chronological observations."

# Human-readable labels for the 16 failure categories.
FAILURE_LABELS = {
    "requirements": "Requirements",
    "architecture": "Architecture",
    "authentication": "Authentication",
    "authorization": "Authorization",
    "input_validation": "Input Validation",
    "data_integrity": "Data Integrity",
    "api_contract": "API Contract",
    "error_handling": "Error Handling",
    "testing": "Testing",
    "dependency": "Dependency",
    "performance": "Performance",
    "security": "Security",
    "configuration": "Configuration",
    "deployment": "Deployment",
    "observability": "Observability",
    "integration": "Integration",
}

# ---------------------------------------------------------------------------
# Fixed feature schema (MISTIQ-APR feature vector).
#
# Each observation (project state at review N) is represented by a fixed-length
# float vector in this order. The ordering must remain stable so artifacts
# (weights, preprocessing, reports) stay compatible.
# ---------------------------------------------------------------------------

# Group A: static / project-quality features (extracted from review N metrics + snapshot).
STATIC_FEATURE_NAMES = (
    "static_total_findings",
    "static_critical_findings",
    "static_high_findings",
    "static_medium_findings",
    "static_low_findings",
    "static_security_risk",
    "static_testing_risk",
    "static_architecture_risk",
    "static_dependency_risk",
    "static_config_risk",
    "static_requirement_coverage",
    "static_complexity_index",
)

# Group B: latest-failure baseline (one-hot of the most recent failure category).
LATEST_FAILURE_FEATURE_NAMES = tuple(
    f"latest_failure_{cat}" for cat in FAILURE_CATEGORIES
)

# Group C: sequential failure-history features.
SEQ_FREQUENCY_FEATURE_NAMES = tuple(f"seq_freq_{cat}" for cat in FAILURE_CATEGORIES)
SEQ_RECENCY_FEATURE_NAMES = tuple(f"seq_recency_{cat}" for cat in FAILURE_CATEGORIES)
SEQ_REPETITION_FEATURE_NAMES = tuple(f"seq_repetition_{cat}" for cat in FAILURE_CATEGORIES)
SEQ_TRANSITION_FEATURE_NAMES = tuple(f"seq_transition_{cat}" for cat in FAILURE_CATEGORIES)
SEQ_COMPONENT_FEATURE_NAMES = tuple(f"seq_component_{cat}" for cat in FAILURE_CATEGORIES)

SEQ_SCALAR_FEATURE_NAMES = (
    "seq_failure_diversity_recent",
    "seq_change_intensity",
    "seq_testing_weakness",
    "seq_severity_trajectory",
)

ALL_FEATURE_NAMES = (
    STATIC_FEATURE_NAMES
    + LATEST_FAILURE_FEATURE_NAMES
    + SEQ_FREQUENCY_FEATURE_NAMES
    + SEQ_RECENCY_FEATURE_NAMES
    + SEQ_REPETITION_FEATURE_NAMES
    + SEQ_TRANSITION_FEATURE_NAMES
    + SEQ_COMPONENT_FEATURE_NAMES
    + SEQ_SCALAR_FEATURE_NAMES
)

FEATURE_BLOCKS = {
    "static": STATIC_FEATURE_NAMES,
    "latest_failure": LATEST_FAILURE_FEATURE_NAMES,
    "frequency": SEQ_FREQUENCY_FEATURE_NAMES,
    "recency": SEQ_RECENCY_FEATURE_NAMES,
    "repetition": SEQ_REPETITION_FEATURE_NAMES,
    "transition": SEQ_TRANSITION_FEATURE_NAMES,
    "component": SEQ_COMPONENT_FEATURE_NAMES,
    "scalar_summary": SEQ_SCALAR_FEATURE_NAMES,
}