"""Application configuration, loaded from environment variables / .env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = BASE_DIR.parent


def _load_dotenv() -> None:
    """Minimal .env loader (avoids an extra dependency)."""
    for candidate in (REPO_ROOT / ".env", BASE_DIR / ".env"):
        if not candidate.exists():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


class Settings:
    """Runtime settings. Secrets are never logged or returned by the API."""

    def __init__(self) -> None:
        self.app_name: str = "NyayaSahayak"
        self.api_prefix: str = "/api"

        self.mongodb_uri: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.mongodb_db_name: str = os.getenv("MONGODB_DB_NAME", "nyayasahayak_db")
        self.data_dir: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
        self.uploads_dir: Path = self.data_dir / "uploads"
        self.reports_dir: Path = self.data_dir / "reports"

        self.secret_key: str = os.getenv("SECRET_KEY", "dev-only-insecure-secret-change-me")
        self.algorithm: str = "HS256"
        self.access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

        # AI provider. "gemini" is the default; "rule_based" runs the deterministic
        # extractors only (used automatically when no API key is configured).
        self.ai_provider: str = os.getenv("AI_PROVIDER", "gemini").lower()
        self.ai_model: str = os.getenv("AI_MODEL", "gemini-2.0-flash")
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "") or os.getenv("AI_API_KEY", "")
        self.gemini_base_url: str = os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
        )
        self.ai_timeout_seconds: float = float(os.getenv("AI_TIMEOUT_SECONDS", "90"))

        self.authority_corpus_dir: Path = Path(
            os.getenv("AUTHORITY_CORPUS_DIR", str(REPO_ROOT / "legal_data" / "authorities"))
        )
        self.authority_service_url: str = os.getenv("AUTHORITY_SERVICE_URL", "")
        self.mcp_server_name: str = os.getenv("MCP_SERVER_NAME", "nyayasahayak")
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

        self.max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "25"))
        self.cors_origins: list[str] = [
            o.strip()
            for o in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173",
            ).split(",")
            if o.strip()
        ]

        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    @property
    def ai_configured(self) -> bool:
        """True when a real model can actually be called."""
        return self.ai_provider == "gemini" and bool(self.gemini_api_key)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
