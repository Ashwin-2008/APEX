import os
import json
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


def _load_env_file() -> None:
    """Load the project .env so secrets stay out of source.

    Real environment variables always win over .env values.
    """
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return
    load_dotenv(env_path, override=False)


_load_env_file()


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
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    llm_enabled: bool = os.getenv("LLM_ENABLED", "false").lower() in {"1", "true", "yes"}
    monitor_debounce_seconds: float = max(2.0, min(5.0, float(os.getenv("MONITOR_DEBOUNCE_SECONDS", "3"))))
    secret_key: str = os.getenv("SECRET_KEY", "apex_secret_key_change_in_production_2026")
    token_expire_seconds: int = int(os.getenv("TOKEN_EXPIRE_SECONDS", str(86400 * 7)))
    environment: str = os.getenv("ENVIRONMENT", os.getenv("APEX_ENV", "development")).strip().lower()
    initial_admin_username: str = os.getenv("APEX_INITIAL_ADMIN_USERNAME", "apex_admin").strip()
    initial_admin_password: str = os.getenv("APEX_INITIAL_ADMIN_PASSWORD", "").strip()
    initial_admin_email: str = os.getenv("APEX_INITIAL_ADMIN_EMAIL", "admin@apex.local").strip()
    sandbox_mode: str = os.getenv("APEX_SANDBOX_MODE", "docker" if os.getenv("ENVIRONMENT", "").lower() == "production" else "local_dev").strip().lower()
    sandbox_image: str = os.getenv("APEX_SANDBOX_IMAGE", "python:3.11-slim").strip()
    rate_limit_login_per_minute: int = max(1, int(os.getenv("APEX_RATE_LIMIT_LOGIN_PER_MINUTE", "10" if os.getenv("ENVIRONMENT", "").lower() == "production" else "60")))
    rate_limit_register_per_minute: int = max(1, int(os.getenv("APEX_RATE_LIMIT_REGISTER_PER_MINUTE", "5" if os.getenv("ENVIRONMENT", "").lower() == "production" else "60")))
    rate_limit_ip_per_minute: int = max(5, int(os.getenv("APEX_RATE_LIMIT_IP_PER_MINUTE", "30" if os.getenv("ENVIRONMENT", "").lower() == "production" else "120")))

    def validate_production_security(self) -> None:
        """Validate critical production security invariants at startup."""
        if self.environment == "production":
            insecure_secrets = {
                "apex_secret_key_change_in_production_2026",
                "secret",
                "change-me",
                "changeme",
                "default",
            }
            if not self.secret_key or self.secret_key in insecure_secrets or len(self.secret_key) < 32:
                raise RuntimeError(
                    "PRODUCTION SECURITY VIOLATION: SECRET_KEY must be set to a cryptographically strong string of at least 32 characters in production."
                )
            if not self.initial_admin_password:
                raise RuntimeError(
                    "PRODUCTION SECURITY VIOLATION: APEX_INITIAL_ADMIN_PASSWORD must be explicitly provided in production mode."
                )
            insecure_passwords = {"ApexPassword123!", "password", "admin", "12345678", "admin123"}
            if self.initial_admin_password in insecure_passwords or len(self.initial_admin_password) < 12:
                raise RuntimeError(
                    "PRODUCTION SECURITY VIOLATION: APEX_INITIAL_ADMIN_PASSWORD cannot be set to a default or weak password (min length 12 required in production)."
                )
            if self.sandbox_mode != "docker":
                raise RuntimeError(
                    "PRODUCTION SECURITY VIOLATION: APEX_SANDBOX_MODE must be set to 'docker' in production. Host execution is strictly forbidden."
                )


settings = Settings()
