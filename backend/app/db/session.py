from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models import entities  # noqa: F401 - register model metadata

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        migrate_sqlite_schema(engine)


def migrate_sqlite_schema(database_engine) -> None:
    """Apply additive/rename migrations from the original Phase 0 SQLite schema."""
    renames = {
        "questions": (("id", "question_id"),),
        "attempts": (("id", "attempt_id"),),
        "mistake_events": (("id", "mistake_event_id"),),
    }
    with database_engine.begin() as connection:
        inspector = inspect(connection)
        for table, pairs in renames.items():
            if table not in inspector.get_table_names():
                continue
            present = {column["name"] for column in inspector.get_columns(table)}
            for old, new in pairs:
                if old in present and new not in present:
                    connection.execute(text(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"'))
                    present.remove(old); present.add(new)
        additive = {
            "project_findings": {"detected_at": "DATETIME", "updated_at": "DATETIME", "resolved_at": "DATETIME", "resolution_evidence": "TEXT", "related_commit": "VARCHAR(80)"},
            "reviewed_projects": {"source_type": "VARCHAR(20) NOT NULL DEFAULT 'local'", "repository_url": "VARCHAR(1000)", "branch": "VARCHAR(200)", "current_commit_sha": "VARCHAR(80)", "monitoring_status": "VARCHAR(30) NOT NULL DEFAULT 'paused'", "last_analyzed_at": "DATETIME"},
            "questions": {"error_mapping": "JSON NOT NULL DEFAULT '{}'"},
            "attempts": {"idempotency_key": "VARCHAR(100)"},
            "learner_states": {
                "attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "relevant_mistake_count": "INTEGER NOT NULL DEFAULT 0",
            },
            "predictions": {
                "data_reliability": "FLOAT NOT NULL DEFAULT 0",
                "status": "VARCHAR(40) NOT NULL DEFAULT 'NORMAL_OPERATION'",
                "model_name": "VARCHAR(100) NOT NULL DEFAULT 'MISTIQ-AMPA'",
                "model_version": "VARCHAR(40) NOT NULL DEFAULT '1.0'",
                "context_question_id": "INTEGER REFERENCES questions(question_id)",
                "source_attempt_id": "INTEGER REFERENCES attempts(attempt_id)",
                "explanation": "JSON",
            },
            "recommendations": {
                "question_id": "INTEGER REFERENCES questions(question_id)",
                "score": "FLOAT",
                "score_components": "JSON",
                "completed_at": "DATETIME",
            },
        }
        for table, columns in additive.items():
            if table not in inspect(connection).get_table_names():
                continue
            present = {column["name"] for column in inspect(connection).get_columns(table)}
            for column, ddl in columns.items():
                if column not in present:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_attempt_idempotency_key ON attempts(idempotency_key)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_mistake_attempt ON mistake_events(attempt_id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_prediction_source_attempt ON predictions(source_attempt_id)"))
