from sqlalchemy import create_engine, inspect, text

from app.db.base import Base
from app.models import entities  # noqa: F401
from app.db.session import migrate_sqlite_schema


def test_database_initialization() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    assert set(Base.metadata.tables) == {
        "students", "questions", "attempts", "mistake_events",
        "learner_states", "predictions", "recommendations",
        "reviewed_projects", "project_reviews", "project_findings", "project_predictions",
        "project_requirements", "requirement_coverage",
        "users", "notifications", "activity_events",
    }


def test_recommendation_migration_adds_phase7_columns_to_existing_database() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE recommendations (id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL, prediction_id INTEGER, type VARCHAR(100) NOT NULL, reason TEXT NOT NULL, created_at DATETIME NOT NULL)"))
        connection.execute(text("CREATE TABLE attempts (attempt_id INTEGER PRIMARY KEY, idempotency_key VARCHAR(100))"))
        connection.execute(text("CREATE TABLE mistake_events (mistake_event_id INTEGER PRIMARY KEY, attempt_id INTEGER)"))
        connection.execute(text("CREATE TABLE predictions (id INTEGER PRIMARY KEY, source_attempt_id INTEGER)"))
    migrate_sqlite_schema(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("recommendations")}
    assert {"question_id", "score", "score_components", "completed_at"} <= columns
