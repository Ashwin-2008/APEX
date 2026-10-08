from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import entities  # noqa: F401
from app.services.mistiq_apr_research_service import research_status
from backend.ml.mistiq_apr.constants import (
    MIN_DISTINCT_CATEGORIES_FOR_EVALUATION,
    MIN_DISTINCT_TIMEPOINTS_FOR_EVALUATION,
    MIN_OBSERVATIONS_FOR_EVALUATION,
)
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


def test_research_status_publishes_evaluation_requirements_from_constants():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    status = research_status(sessionmaker(bind=engine)())

    requirements = status["evaluation_requirements"]
    assert requirements["min_observations"] == MIN_OBSERVATIONS_FOR_EVALUATION
    assert requirements["min_distinct_categories"] == MIN_DISTINCT_CATEGORIES_FOR_EVALUATION
    assert requirements["min_distinct_timepoints"] == MIN_DISTINCT_TIMEPOINTS_FOR_EVALUATION
    assert status["training_observations"] < requirements["min_observations"]
    assert status["distinct_timepoints"] < requirements["min_distinct_timepoints"]
