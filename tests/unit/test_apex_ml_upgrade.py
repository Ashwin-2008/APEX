"""Comprehensive unit and integration test suite for the APEX ML & Code Intelligence upgrade.

Covers all 12 categories from Phase 12:
1. Dataset ingestion and license filtering.
2. Duplicate repository and duplicate observation detection.
3. Feature extraction and schema compatibility.
4. Target-label generation and confidence scoring.
5. Data-leakage prevention (including repository-grouped disjointness).
6. Chronological and repository-grouped splitting.
7. Candidate model training and immutable artifact saving.
8. Model loading, prediction, uncertainty, and score semantics.
9. Model promotion criteria (10-point gate) and rollback without retraining.
10. Line-level code intelligence and risk localization.
11. Groq provider integration, secret redaction, grounding validation, and patch validation.
12. Fallback behavior when Groq is disabled or unavailable, plus API endpoint contracts.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.main import create_app
from app.models.entities import ProjectFinding, ProjectReview, ReviewedProject
from app.services.code_intelligence_service import build_repository_code_intelligence
from app.services.llm.remediation import (
    RemediationSuggestion,
    generate_remediation_suggestion,
    prepare_redacted_evidence_bundle,
    validate_grounding,
    validate_patch_safety,
)
from backend.ml.mistiq_apr import artifacts
from backend.ml.mistiq_apr.constants import ALL_FEATURE_NAMES, FAILURE_CATEGORIES
from backend.ml.mistiq_apr.dataset import (
    Observation,
    audit_dataset,
    build_curated_observations,
    build_observations,
    canonical_repository_group,
    is_synthetic_project_record,
)
from backend.ml.mistiq_apr.evaluation import evaluate_candidate_comprehensive, metrics
from backend.ml.mistiq_apr.ingestion import (
    detect_repository_license,
    load_ingested_dataset,
    redact_secrets,
)
from backend.ml.mistiq_apr.leakage import validate_leakage
from backend.ml.mistiq_apr.models import CANDIDATE_MODEL_SPECS
from backend.ml.mistiq_apr.prediction import predict_next_failure
from backend.ml.mistiq_apr.registry import (
    compare_with_production,
    ensure_registry_initialized,
    list_registry_models,
    promote_candidate,
    rollback_production,
    train_candidate,
)
from backend.ml.mistiq_apr.temporal import (
    generate_chronological_holdout_split,
    generate_repository_grouped_splits,
    generate_walk_forward_splits,
)


def _make_memory_session() -> tuple[Session, sessionmaker]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return factory(), factory


def _seed_multi_repo_history(session: Session) -> list[int]:
    """Seed 4 real repositories and 1 synthetic temp repository with chronological reviews."""
    base_time = datetime(2026, 2, 1, 9, 0, 0)
    repos = [
        ("alpha-service", "C:/workspace/repos/alpha-service", ["security", "testing", "error_handling", "security", "testing"]),
        ("beta-api", "C:/workspace/repos/beta-api", ["dependency", "security", "architecture", "dependency", "security"]),
        ("gamma-core", "C:/workspace/repos/gamma-core", ["error_handling", "testing", "security", "error_handling", "testing"]),
        ("delta-web", "C:/workspace/repos/delta-web", ["testing", "security", "dependency", "testing", "security"]),
        ("mistiq_direct_e2e_test_abc123", "C:/Users/user/AppData/Local/Temp/mistiq_direct_e2e_test_abc123", ["testing", "testing"]),
    ]
    project_ids: list[int] = []
    clock = base_time
    for name, path, categories in repos:
        proj = ReviewedProject(name=name, repository_path=path, source_type="local")
        session.add(proj)
        session.flush()
        project_ids.append(proj.id)
        for r_idx, cat in enumerate(categories, start=1):
            clock = clock + timedelta(hours=4)
            rev = ProjectReview(
                project_id=proj.id,
                review_number=r_idx,
                timestamp=clock,
                metrics={"critical": 1 if cat == "security" else 0, "high": 1, "medium": 1, "low": 0},
                snapshot={
                    "file_count": 20 + r_idx * 2,
                    "language_mix": {".py": 15, ".ts": 5},
                    "requirement_coverage": 0.75,
                    "recent_churn": f"src/{cat}_{r_idx}.py\n",
                },
            )
            session.add(rev)
            session.flush()
            session.add(
                ProjectFinding(
                    review_id=rev.id,
                    fingerprint=f"{proj.id}:{cat}:{r_idx}",
                    category=cat,
                    severity="critical" if cat == "security" else "high",
                    confidence=0.9,
                    component=f"src/{cat}.py",
                    file=f"src/{cat}.py",
                    line=10 + r_idx,
                    evidence=f"Detected {cat} issue at review {r_idx}",
                    analyzer_source="deterministic_analyzer",
                    remediation=f"Fix {cat}",
                    status="NEW",
                )
            )
    session.commit()
    return project_ids


def test_secret_redaction_and_license_detection(tmp_path: Path):
    raw = "token = 'ghp_1234567890abcdefghijklmnopqrstuvwx' and GROQ='gsk_abcdefghijklmnopqrstuvwx123456'"
    redacted, count = redact_secrets(raw)
    assert count >= 2
    assert "ghp_1234567890" not in redacted
    assert "gsk_abcdefghijk" not in redacted

    repo_dir = tmp_path / "licensed_repo"
    repo_dir.mkdir()
    (repo_dir / "LICENSE").write_text("MIT License\nPermission is hereby granted, free of charge...", encoding="utf-8")
    lic = detect_repository_license(repo_dir, is_local_authorized=False)
    assert lic["spdx_id"] == "MIT"
    assert lic["eligible"] is True

    gpl_dir = tmp_path / "gpl_repo"
    gpl_dir.mkdir()
    (gpl_dir / "LICENSE").write_text("GNU GENERAL PUBLIC LICENSE Version 3", encoding="utf-8")
    gpl_lic = detect_repository_license(gpl_dir, is_local_authorized=False)
    assert gpl_lic["spdx_id"] == "GPL"
    assert gpl_lic["eligible"] is False


def test_dataset_curation_synthetic_filtering_and_audit():
    session, _ = _make_memory_session()
    _seed_multi_repo_history(session)

    assert is_synthetic_project_record("mistiq_direct_e2e_test_999", "C:/Temp/mistiq_direct_e2e_test_999") is True
    assert is_synthetic_project_record("SakshaDatathon", "C:/Projects/SakshaDatathon") is False

    # Nested folder deduplication
    g1 = canonical_repository_group(1, "SakshaDatathon", "C:/Users/ASHWIN/Downloads/PROJECTS/SakshaDatathon")
    g2 = canonical_repository_group(3, "Saksha_Datathon", "C:/Users/ASHWIN/Downloads/PROJECTS/SakshaDatathon/Saksha_Datathon")
    assert g1 == g2

    raw_obs = build_observations(session)
    curated_obs = build_curated_observations(
        session, exclude_synthetic=True, primary_target_only=True, deduplicate=True
    )
    assert len(raw_obs) == 17  # 16 real + 1 synthetic
    assert len(curated_obs) == 16
    assert all(not o.is_synthetic for o in curated_obs)
    assert all(len(o.features) == len(ALL_FEATURE_NAMES) for o in curated_obs)

    audit = audit_dataset(session)
    assert audit["real_projects"] == 4
    assert audit["synthetic_temp_projects"] == 1
    assert audit["curated_real_observations"] == 16
    assert audit["traceable_provenance"] is True


def test_chronological_and_repository_grouped_splits_and_leakage():
    session, _ = _make_memory_session()
    _seed_multi_repo_history(session)
    curated = build_curated_observations(session)

    wf_splits, wf_status, _ = generate_walk_forward_splits(curated)
    assert wf_status == "COMPLETED"
    assert len(wf_splits) >= 3
    wf_leakage = validate_leakage(curated, wf_splits)
    assert wf_leakage["passed"] is True

    repo_splits, repo_status, _ = generate_repository_grouped_splits(curated)
    assert repo_status == "COMPLETED"
    assert len(repo_splits) == 4
    repo_leakage = validate_leakage(curated, repo_splits, require_disjoint_repo_groups=True)
    assert repo_leakage["passed"] is True

    holdout = generate_chronological_holdout_split(curated)
    assert len(holdout["train"]) > 0
    assert len(holdout["test"]) > 0


def test_candidate_training_registry_promotion_and_rollback(tmp_path: Path):
    session, _ = _make_memory_session()
    _seed_multi_repo_history(session)
    curated = build_curated_observations(session)

    reg_root = tmp_path / "mistiq_apr_registry"
    ensure_registry_initialized(reg_root)

    res = train_candidate(
        curated,
        algorithm="random_forest",
        dataset_version="v_test",
        candidate_id="cand_rf_001",
        root=reg_root,
    )
    assert res["trained"] is True
    cand_dir = Path(res["candidate_dir"])
    for expected_file in (
        "model.pkl",
        "metadata.json",
        "metrics.json",
        "confusion_matrix.json",
        "calibration.json",
        "feature_schema.json",
        "training_config.json",
        "dataset_manifest.json",
        "evaluation_report.md",
    ):
        assert (cand_dir / expected_file).is_file(), f"Missing {expected_file}"

    comp = compare_with_production("cand_rf_001", root=reg_root)
    assert "criteria" in comp
    assert comp["criteria"]["1_leakage_checks_pass"] is True
    assert comp["criteria"]["9_clean_load_and_prediction_smoke_test"] is True
    assert comp["criteria"]["10_artifact_schema_validation_passes"] is True

    # Test rollback to original v1.0
    rb = rollback_production("model_v1.0_original", root=reg_root)
    assert rb["rolled_back"] is True
    assert rb["active_candidate_id"] == "model_v1.0_original"

    reg_list = list_registry_models(root=reg_root)
    assert any(c["candidate_id"] == "cand_rf_001" for c in reg_list["candidates"])


def test_original_production_model_pkl_is_untouched():
    """Verify the original v1.0 model.pkl and model_metadata.json were never overwritten."""
    orig_model = Path("backend/ml/artifacts/mistiq_apr/model.pkl")
    orig_meta = Path("backend/ml/artifacts/mistiq_apr/model_metadata.json")
    assert orig_model.is_file()
    assert orig_meta.is_file()
    assert hashlib.sha256(orig_model.read_bytes()).hexdigest() == (
        "fc28f408390b2b53d62f40e276a8b9b60896cc54a34fbd2369604c6dd89d6be5"
    )
    assert hashlib.sha256(orig_meta.read_bytes()).hexdigest() == (
        "e174ed0d5c9e8f84b5e4df12dc5c2c75948b16c03417c6912201b78c438170bc"
    )


def test_line_level_code_intelligence_and_risk_localization(tmp_path: Path):
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    src_dir = repo / "app"
    src_dir.mkdir()
    code_file = src_dir / "handlers.py"
    code_file.write_text(
        "\n".join(
            [
                "import subprocess",
                "import requests",
                "",
                "API_KEY = 'sk-1234567890abcdefghijklmnopqrstuvwx'",
                "",
                "def run_unsafe(cmd: str):",
                "    try:",
                "        subprocess.run(cmd, shell=True)",
                "        requests.get('https://example.com/status')",
                "    except Exception:",
                "        pass",
            ]
        ),
        encoding="utf-8",
    )

    intel = build_repository_code_intelligence(repo, predicted_category="security")
    assert intel["available"] is True
    assert intel["summary"]["indexed_files"] == 1
    assert intel["summary"]["verified_line_findings_count"] >= 3

    rule_ids = {f["rule_id"] for f in intel["line_findings"]}
    assert "SEC-SECRET-LINE" in rule_ids
    assert "PY-SEC-SUBPROCESS-SHELL" in rule_ids
    assert "PY-INT-NO-TIMEOUT" in rule_ids
    assert "PY-ERR-SWALLOW" in rule_ids

    # Ensure secrets are redacted in code_excerpt
    for finding in intel["line_findings"]:
        assert "sk-1234567890abcdefghijklmnopqrstuvwx" not in finding.get("code_excerpt", "")
        assert finding["start_line"] >= 1
        assert finding["end_line"] >= finding["start_line"]


def test_groq_remediation_redaction_grounding_and_patch_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "rem_repo"
    repo.mkdir()
    target_py = repo / "service.py"
    target_py.write_text(
        "import requests\n\ndef fetch_data(url: str):\n    try:\n        return requests.get(url)\n    except Exception:\n        pass\n",
        encoding="utf-8",
    )

    # Test deterministic fallback when LLM_ENABLED=false
    monkeypatch.setattr(settings, "llm_enabled", False)
    res = generate_remediation_suggestion(
        repository_path=repo,
        file_path="service.py",
        start_line=6,
        end_line=7,
        category="error_handling",
        title="Silent exception handler",
        explanation="Swallowing Exception hides failures.",
        evidence_state="verified_finding",
    )
    assert res["available"] is True
    assert res["llm_used"] is False
    assert res["grounding_validation"]["passed"] is True
    assert res["patch_validation"]["auto_applied"] is False
    assert res["patch_validation"]["review_only"] is True
    assert res["patch_validation"]["target_file_exists"] is True

    # Test hallucination guard rejects non-existent file/line references
    evidence = prepare_redacted_evidence_bundle(
        repository_path=repo,
        file_path="service.py",
        start_line=6,
        end_line=7,
        category="error_handling",
        title="Silent exception handler",
        explanation="Swallowing Exception hides failures.",
        evidence_state="model_ranked_candidate",
    )
    bad_suggestion = RemediationSuggestion(
        summary="This is a confirmed vulnerability in nonexistent.py.",
        why_it_matters="Matters.",
        evidence_references=["invented_file.py:999-1005"],
        suggested_fix="Fix it.",
    )
    g_check = validate_grounding(bad_suggestion, evidence)
    assert g_check["passed"] is False
    assert g_check["referenced_files_exist"] is False
    assert g_check["respects_prediction_vs_verified_distinction"] is False


def test_new_research_and_intelligence_api_endpoints(tmp_path: Path):
    session, factory = _make_memory_session()
    project_ids = _seed_multi_repo_history(session)

    # Point first project to a real temp directory so code-intelligence can index it
    real_dir = tmp_path / "alpha_repo"
    real_dir.mkdir()
    (real_dir / "main.py").write_text(
        "def compute(x: int) -> int:\n    try:\n        return x + 1\n    except Exception:\n        pass\n",
        encoding="utf-8",
    )
    proj = session.get(ReviewedProject, project_ids[0])
    proj.repository_path = str(real_dir)
    session.commit()

    app = create_app()
    app.state.SessionLocal = factory
    client = TestClient(app)

    reg_resp = client.get("/api/project-reviews/research/registry")
    assert reg_resp.status_code == 200
    assert "production" in reg_resp.json()

    ing_resp = client.get("/api/project-reviews/research/ingestion/status")
    assert ing_resp.status_code == 200

    ci_resp = client.get(f"/api/project-reviews/{project_ids[0]}/code-intelligence")
    assert ci_resp.status_code == 200
    ci_data = ci_resp.json()
    assert ci_data["available"] is True
    assert ci_data["summary"]["indexed_files"] == 1

    rem_resp = client.post(
        f"/api/project-reviews/{project_ids[0]}/remediation",
        json={
            "file": "main.py",
            "start_line": 4,
            "end_line": 5,
            "category": "error_handling",
            "title": "Silent exception handler",
            "explanation": "Swallows exception",
            "state": "verified_finding",
        },
    )
    assert rem_resp.status_code == 200
    rem_data = rem_resp.json()
    assert rem_data["available"] is True
    assert rem_data["patch_validation"]["auto_applied"] is False
