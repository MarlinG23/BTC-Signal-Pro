"""
Application configuration loaded from environment variables / .env file.

All settings are validated by Pydantic at startup.  Missing required
settings raise a descriptive error before the server starts.
"""

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/btc_signals"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        """Normalise DATABASE_URL for SQLAlchemy asyncpg.

        Railway injects postgres:// or postgresql://.
        Railway internal hostnames (*.railway.internal) do not use SSL —
        asyncpg's default SSL negotiation raises TargetServerAttributeNotMatched
        against them, so we explicitly disable SSL for internal URLs.
        """
        import re

        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)

        # Strip any existing ssl/sslmode query params so we control them
        v = re.sub(r"[?&]sslmode=[^&]*", "", v)
        v = re.sub(r"[?&]ssl=[^&]*", "", v)
        # Clean up dangling ? or & left after stripping
        v = re.sub(r"\?&", "?", v)
        v = re.sub(r"[?&]$", "", v)

        # Railway internal networking doesn't support SSL
        if "railway.internal" in v:
            sep = "&" if "?" in v else "?"
            v = f"{v}{sep}ssl=false"

        return v

    # ── Binance ───────────────────────────────────────────────────────────
    BINANCE_API_KEY: str = ""
    BINANCE_API_SECRET: str = ""
    BINANCE_TESTNET: bool = False

    # ── Firebase ──────────────────────────────────────────────────────────
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_PRIVATE_KEY_ID: str = ""
    FIREBASE_PRIVATE_KEY: str = ""
    FIREBASE_CLIENT_EMAIL: str = ""
    FIREBASE_CLIENT_ID: str = ""

    # ── News APIs ─────────────────────────────────────────────────────────
    COINDESK_API_KEY: str = ""
    GLASSNODE_API_KEY: str = ""
    COINGLASS_API_KEY: str = ""

    # ── App ───────────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    APP_HOST: str = "0.0.0.0"
    # Comma-separated list of allowed CORS origins.
    # Defaults to "*" so Railway split-service deployments work without
    # manual configuration.  Set an explicit value in production to lock
    # this down (e.g. "https://frontend-production-9f903.up.railway.app").
    CORS_ORIGINS: str = "*"

    # ── Signal thresholds ─────────────────────────────────────────────────
    SIGNAL_CONFIDENCE_THRESHOLD: float = 70.0
    SIGNAL_MIN_INDICATORS: int = 3

    # ── Alert thresholds ─────────────────────────────────────────────────
    LIQUIDATION_ALERT_THRESHOLD_M: float = 500.0

    @field_validator("APP_ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "production", "test"}
        if v not in allowed:
            raise ValueError(f"APP_ENV must be one of {allowed}")
        return v

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS comma-separated string into a list.

        A value of "*" is returned as-is so FastAPI's CORSMiddleware
        accepts requests from any origin.
        """
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def firebase_credentials(self) -> dict:
        """Build the Firebase credential dict from individual env vars."""
        return {
            "type": "service_account",
            "project_id": self.FIREBASE_PROJECT_ID,
            "private_key_id": self.FIREBASE_PRIVATE_KEY_ID,
            "private_key": self.FIREBASE_PRIVATE_KEY.replace("\\n", "\n"),
            "client_email": self.FIREBASE_CLIENT_EMAIL,
            "client_id": self.FIREBASE_CLIENT_ID,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()


# Module-level convenience alias used throughout the application
settings: Settings = get_settings()
