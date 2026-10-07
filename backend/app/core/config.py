import os
import json
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./mistiq.db")
    ampa_model_path: Path = Path(os.getenv("MISTIQ_AMPA_MODEL_PATH", str(BACKEND_ROOT / "ml" / "artifacts" / "ampa.npz")))
    prediction_top_k: int = max(1, int(os.getenv("MISTIQ_PREDICTION_TOP_K", "3")))
    explanation_contribution_threshold: float = max(0.0, float(os.getenv("MISTIQ_EXPLANATION_CONTRIBUTION_THRESHOLD", "0.05")))
    recommendation_weights: dict = json.loads(os.getenv("MISTIQ_RECOMMENDATION_WEIGHTS", "{\"learning_need\":0.35,\"mistake_relevance\":0.25,\"difficulty_fit\":0.20,\"novelty\":0.10,\"retention_value\":0.10}"))
    concept_confusion_pairs: tuple = tuple(tuple(pair) for pair in json.loads(os.getenv("MISTIQ_CONCEPT_CONFUSION_PAIRS", "[[\"Precision\",\"Recall\"],[\"Ridge\",\"Lasso\"],[\"Overfitting\",\"Underfitting\"],[\"Stack\",\"Queue\"],[\"BFS\",\"DFS\"],[\"Mean\",\"Median\"],[\"Classification\",\"Regression\"]]")))
    analytics_recent_window: int = max(2, int(os.getenv("MISTIQ_ANALYTICS_RECENT_WINDOW", "10")))
    analytics_minimum_sample: int = max(2, int(os.getenv("MISTIQ_ANALYTICS_MINIMUM_SAMPLE", "3")))
    analytics_momentum_minimum: int = max(2, int(os.getenv("MISTIQ_ANALYTICS_MOMENTUM_MINIMUM", "10")))
    analytics_trend_threshold: float = max(0.0, float(os.getenv("MISTIQ_ANALYTICS_TREND_THRESHOLD", "0.05")))
    analytics_recovery_window: int = max(1, int(os.getenv("MISTIQ_ANALYTICS_RECOVERY_WINDOW", "3")))
    analytics_mistake_bucket: str = "daily" if os.getenv("MISTIQ_ANALYTICS_MISTAKE_BUCKET", "weekly").lower() == "daily" else "weekly"
    llm_provider: str = os.getenv("LLM_PROVIDER", "huggingface")
    hf_token: str = os.getenv("HF_TOKEN", "")
    hf_model: str = os.getenv("HF_MODEL", "")
    hf_provider: str = os.getenv("HF_PROVIDER", "")
    llm_enabled: bool = os.getenv("LLM_ENABLED", "false").lower() in {"1", "true", "yes"}
    monitor_debounce_seconds: float = max(2.0, min(5.0, float(os.getenv("MONITOR_DEBOUNCE_SECONDS", "3"))))


settings = Settings()
