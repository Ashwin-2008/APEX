from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import entities  # noqa: F401
from app.services.mistiq_apr_research_service import research_status
from backend.ml.mistiq_apr.dataset import build_observations
from backend.ml.mistiq_apr.evaluation import evaluate_temporal


def test_empty_research_dataset_is_explicitly_insufficient():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    assert build_observations(session) == []
    status = research_status(session)
    assert status["status"] == "INSUFFICIENT DATA FOR VALID MODEL EVALUATION"
    assert evaluate_temporal([])["status"] == "INSUFFICIENT DATA FOR VALID MODEL EVALUATION"
