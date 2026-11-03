from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from app.api.router import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine as default_engine, migrate_sqlite_schema
from app.models import entities  # noqa: F401 - register model metadata
from app.services.ampa_service import AMPAService
from app.services.errors import IntegrationError

logger = logging.getLogger(__name__)


def create_app(database_engine=None, ampa_service=None) -> FastAPI:
    selected_engine = database_engine or default_engine
    if selected_engine.dialect.name == "sqlite":
        @event.listens_for(selected_engine, "connect")
        def _enable_sqlite_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    session_factory = sessionmaker(bind=selected_engine, autoflush=False, autocommit=False)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        settings.validate_production_security()
        Base.metadata.create_all(bind=selected_engine)
        if selected_engine.dialect.name == "sqlite":
            migrate_sqlite_schema(selected_engine)
        application.state.SessionLocal = session_factory
        service = ampa_service or AMPAService(settings.ampa_model_path)
        try:
            service.load_once()
            service.hydrate(session_factory)
            application.state.ampa_model_error = None
        except Exception as error:
            logger.exception("AMPA model initialization failed")
            service.available = False
            application.state.ampa_model_error = str(error)
        application.state.ampa_service = service
        yield
        selected_engine.dispose() if database_engine is not None else None

    application = FastAPI(title="MISTIQ API", version="2.0.0", lifespan=lifespan)
    application.state.SessionLocal = session_factory
    application.state.ampa_service = ampa_service
    application.state.ampa_model_error = None
    application.include_router(api_router, prefix="/api")

    @application.exception_handler(IntegrationError)
    async def integration_error_handler(_: Request, error: IntegrationError):
        return JSONResponse(status_code=error.status_code,
                            content={"error": error.code, "detail": error.message})

    @application.get("/health", tags=["health"], summary="Check backend and database readiness")
    def health(request: Request) -> dict[str, str]:
        with request.app.state.SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ok"}

    return application


app = create_app()
