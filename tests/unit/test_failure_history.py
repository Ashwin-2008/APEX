"""Tests for the aggregated failure-history contract used by the MISTIQ-APR
Failure Intelligence panel.

The endpoint only restates persisted finding rows grouped by fingerprint: it
never recomputes evidence, statuses, or percentages.
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.main import create_app
from app.services.project_review_persistence import failure_history, persist_analysis


def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def analysis(path, events):
    return {
        "project": {"path": path, "file_count": 2, "commit_count": 1, "bugfix_commit_count": 0},
        "events": events,
        "next_failure_predictions": [],
    }


def event(category, severity="high", analyzer="test_inventory"):
    return {
        "category": category,
        "severity": severity,
        "confidence": 0.9,
        "evidence": f"{category} evidence",
        "analyzer_source": analyzer,
        "remediation": "Fix it",
        "status": "open",
    }


def test_failure_history_counts_occurrences_and_review_span():
    db = session()
    first = persist_analysis(db, analysis("/repo/demo", [event("security"), event("testing")]))
    persist_analysis(db, analysis("/repo/demo", [event("security")]))
    persist_analysis(db, analysis("/repo/demo", [event("security"), event("testing")]))

    payload = failure_history(db, first["project_id"])

    assert payload["summary"]["review_count"] == 3
    assert payload["summary"]["distinct_failure_count"] == 2
    assert payload["summary"]["open_failure_count"] == 2
    assert payload["summary"]["resolved_failure_count"] == 0
    assert payload["summary"]["categories"] == ["security", "testing"]
    assert payload["summary"]["first_review_at"] is not None
    assert payload["summary"]["last_review_at"] is not None

    by_category = {item["category"]: item for item in payload["findings"]}
    assert by_category["security"]["occurrences"] == 3
    assert by_category["security"]["review_numbers"] == [1, 2, 3]
    assert by_category["security"]["status"] == "ACTIVE"
    assert by_category["security"]["first_seen"] <= by_category["security"]["last_seen"]
    assert by_category["testing"]["occurrences"] == 2
    assert by_category["testing"]["review_numbers"] == [1, 3]
    assert payload["message"] is None


def test_failure_history_reports_resolution_lifecycle_from_persisted_rows():
    db = session()
    first = persist_analysis(db, analysis("/repo/demo", [event("testing")]))
    persist_analysis(db, analysis("/repo/demo", []), affected_files=[], affected_analyzers=["testing"], related_commit="abc123")

    payload = failure_history(db, first["project_id"])
    finding = payload["findings"][0]

    assert finding["status"] == "RESOLVED"
    assert finding["occurrences"] == 1
    assert finding["resolved_at"] is not None
    assert finding["resolution_evidence"] == "Affected scope was re-analyzed and the finding was not detected."
    assert finding["related_commit"] == "abc123"
    assert payload["summary"]["resolved_failure_count"] == 1
    assert payload["summary"]["open_failure_count"] == 0


def test_failure_history_empty_project_and_unknown_project_are_explicit():
    db = session()
    saved = persist_analysis(db, analysis("/repo/empty", []))

    payload = failure_history(db, saved["project_id"])
    assert payload["findings"] == []
    assert payload["message"] == "No persisted failure history yet."
    assert payload["summary"]["distinct_failure_count"] == 0

    try:
        failure_history(db, 999999)
    except ValueError as error:
        assert str(error) == "Project not found"
    else:
        raise AssertionError("Expected ValueError for an unknown project")


def test_failure_history_route_returns_persisted_rows_and_404s():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        first = persist_analysis(db, analysis("/repo/route", [event("security")]))
        persist_analysis(db, analysis("/repo/route", [event("security"), event("testing")]))
        project_id = first["project_id"]

    application = create_app(database_engine=engine)
    with TestClient(application) as client:
        response = client.get(f"/api/project-reviews/{project_id}/failure-history")
        assert response.status_code == 200
        payload = response.json()
        assert payload["summary"]["review_count"] == 2
        assert {item["category"] for item in payload["findings"]} == {"security", "testing"}
        assert payload["findings"][0]["evidence"]
        assert client.get("/api/project-reviews/999999/failure-history").status_code == 404
