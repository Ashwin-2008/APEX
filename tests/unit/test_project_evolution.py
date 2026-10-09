from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import entities  # noqa: F401
from app.services.project_evolution_service import evolution, trajectory
from app.services.project_review_persistence import failure_history, persist_analysis


def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def analysis(path, events):
    return {
        "project": {"path": path, "file_count": 5, "commit_count": 3, "bugfix_commit_count": 1},
        "events": events,
        "next_failure_predictions": [{"category": "testing", "probability": 0.6, "confidence": 0.7, "historical_support": 1}],
    }


def event(category, severity="high", evidence=None, analyzer="test_inventory"):
    return {
        "category": category,
        "severity": severity,
        "confidence": 0.9,
        "evidence": evidence or f"{category} evidence",
        "analyzer_source": analyzer,
        "remediation": f"Remediate {category}",
        "status": "open",
    }


def test_evolution_empty_project_returns_honest_insufficient_state():
    db = session()
    result = evolution(db, 99999)
    assert result["insufficient_history"] is True
    assert "At least two" in result["insufficient_history_message"]
    assert result["lifecycle_counts"]["unique_findings"] == 0
    assert result["reviews_summary"] == []
    assert result["review_comparisons"] == []


def test_evolution_single_review_is_insufficient_for_trajectory():
    db = session()
    saved = persist_analysis(db, analysis("/repo/single", [event("testing", "high"), event("security", "critical")]))
    result = evolution(db, saved["project_id"])

    assert result["insufficient_history"] is True
    assert len(result["reviews_summary"]) == 1
    assert result["reviews_summary"][0]["finding_count"] == 2
    assert result["reviews_summary"][0]["critical_count"] == 1
    assert result["reviews_summary"][0]["high_count"] == 1
    assert result["review_comparisons"] == []
    assert result["lifecycle_counts"]["unique_findings"] == 2
    assert result["lifecycle_counts"]["total_occurrences"] == 2


def test_evolution_two_reviews_computes_deterministic_comparisons():
    db = session()
    # Review 1: testing (high), security (critical)
    first = persist_analysis(db, analysis("/repo/traj", [event("testing", "high"), event("security", "critical")]))
    # Review 2: security resolved, testing persistent, dependency newly introduced
    second = persist_analysis(
        db,
        analysis("/repo/traj", [event("testing", "high"), event("dependency", "medium")]),
        affected_files=["src/security.py"],
        affected_analyzers=["security"],
    )

    result = evolution(db, first["project_id"])

    assert result["insufficient_history"] is False
    assert len(result["reviews_summary"]) == 2
    assert len(result["review_comparisons"]) == 1

    comp = result["review_comparisons"][0]
    assert comp["from_review"] == 1
    assert comp["to_review"] == 2

    # Resolved: security
    resolved_cats = {f["category"] for f in comp["resolved"]}
    assert "security" in resolved_cats

    # Persistent: testing
    persistent_cats = {f["category"] for f in comp["persistent"]}
    assert "testing" in persistent_cats

    # Newly introduced: dependency
    intro_cats = {f["category"] for f in comp["newly_introduced"]}
    assert "dependency" in intro_cats

    # Severity changes: critical decreased by 1, medium increased by 1
    assert comp["severity_changes"]["critical"]["delta"] == -1
    assert comp["severity_changes"]["medium"]["delta"] == 1

    # Category changes
    assert comp["category_changes"]["security"]["delta"] == -1
    assert comp["category_changes"]["dependency"]["delta"] == 1
    assert comp["category_changes"]["testing"]["delta"] == 0

    # Lifecycle counts
    lifecycle = result["lifecycle_counts"]
    assert lifecycle["unique_findings"] == 3  # testing, security, dependency
    assert lifecycle["total_occurrences"] == 4  # rev1: 2 + rev2: 2
    assert lifecycle["active_count"] == 2  # rev2 has 2 active findings

    # Risk domains
    domain_map = {d["category"]: d for d in result["risk_domains"]}
    assert "testing" in domain_map
    assert domain_map["testing"]["total_detected"] == 1
    assert domain_map["testing"]["current_active"] == 1
    assert "security" in domain_map
    assert domain_map["security"]["current_active"] == 0


def test_failure_history_enriched_kpi_and_distribution():
    db = session()
    first = persist_analysis(db, analysis("/repo/kpi", [event("testing", "high"), event("security", "critical")]))
    persist_analysis(db, analysis("/repo/kpi", [event("testing", "high")]))

    fh = failure_history(db, first["project_id"])
    summary = fh["summary"]

    assert summary["review_count"] == 2
    assert summary["distinct_failure_count"] == 2
    assert summary["total_occurrences"] == 3
    assert summary["recurring_failure_count"] == 1  # testing occurred twice
    assert summary["recurring_categories"] == ["testing"]

    # Category distribution
    cat_dist = {c["category"]: c for c in summary["category_distribution"]}
    assert cat_dist["testing"]["distinct_count"] == 1
    assert cat_dist["testing"]["total_occurrences"] == 2
    assert cat_dist["testing"]["active_count"] == 1
    assert cat_dist["security"]["distinct_count"] == 1
    assert cat_dist["security"]["total_occurrences"] == 1
