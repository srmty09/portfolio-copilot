import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_PLACEHOLDER_JWT_SECRETS = {"replace-with-a-long-random-secret", "change-this-secret-key", ""}
_MIN_JWT_SECRET_LENGTH = 16


class Settings:
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/portfolio_copilot"
    )
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

    FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:5500")

    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")

    # SMTP_HOST left empty means "don't actually send" -- services/email.py logs the
    # message instead, so forgot-password is fully testable without real credentials.
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "noreply@portfolio-copilot.local")
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    def __init__(self) -> None:
        if self.JWT_SECRET_KEY in _PLACEHOLDER_JWT_SECRETS or len(self.JWT_SECRET_KEY) < _MIN_JWT_SECRET_LENGTH:
            raise RuntimeError(
                "JWT_SECRET_KEY is missing, still the placeholder value, or too short "
                f"(minimum {_MIN_JWT_SECRET_LENGTH} characters). Every protected endpoint depends on "
                "this being a real secret. Set one in backend/.env, e.g.: openssl rand -hex 32"
            )
        if not self.DEEPSEEK_API_KEY:
            logger.warning(
                "DEEPSEEK_API_KEY is not set. Auth and holdings will work, but /analyze and "
                "/analyze/ask will fail as soon as they reach the LLM call. Set it in backend/.env."
            )
        if not self.GOOGLE_CLIENT_ID or not self.GOOGLE_CLIENT_SECRET:
            logger.warning(
                "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET not set -- /auth/google/login will return 503 "
                "until both are configured in backend/.env."
            )
        if not self.SMTP_HOST:
            logger.warning(
                "SMTP_HOST not set -- password reset links will be logged instead of emailed. "
                "Configure SMTP_* in backend/.env to actually send them."
            )


settings = Settings()
