from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import entities  # noqa: F401
from app.services.project_review_persistence import compare_reviews, fingerprint_event, persist_analysis, project_history


def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def analysis(path, events):
    return {"project": {"path": path, "file_count": 2, "commit_count": 1, "bugfix_commit_count": 0}, "events": events, "next_failure_predictions": [{"category": "testing", "probability": .6, "confidence": .7, "historical_support": 1}]}


def event(category, severity="high", evidence=None):
    return {"category": category, "severity": severity, "confidence": .9, "evidence": evidence or f"{category} evidence", "analyzer_source": "test", "remediation": "Fix it", "status": "open"}


def test_fingerprint_is_deterministic():
    assert fingerprint_event(event("security")) == fingerprint_event(event("security"))
    assert fingerprint_event(event("security")) != fingerprint_event(event("testing"))


def test_reviews_history_and_comparison_detects_resolved_persistent_and_new():
    db = session()
    first = persist_analysis(db, analysis("/repo/demo", [event("security"), event("testing", "medium")]))
    second = persist_analysis(db, analysis("/repo/demo", [event("security"), event("dependency")]))
    assert first["review_number"] == 1
    assert second["review_number"] == 2
    history = project_history(db, first["project_id"])
    assert [item["review_number"] for item in history["reviews"]] == [1, 2]
    comparison = compare_reviews(db, first["project_id"])
    assert {item["category"] for item in comparison["resolved_findings"]} == {"testing"}
    assert {item["category"] for item in comparison["persistent_findings"]} == {"security"}
    assert {item["category"] for item in comparison["newly_introduced_findings"]} == {"dependency"}
    assert comparison["metric_changes"]["medium"]["delta"] == -1


def test_first_review_comparison_is_explicitly_empty():
    db = session()
    saved = persist_analysis(db, analysis("/repo/only", [event("testing")]))
    comparison = compare_reviews(db, saved["project_id"])
    assert comparison["previous"] is None
    assert "at least two" in comparison["summary"]
