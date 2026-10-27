"""Application configuration and structured logging.

Only non-secret settings are represented here. Cloud and AI credentials are kept
in Streamlit session memory and are intentionally excluded from logs/reports.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import logging
import os
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    app_name: str = "Multi-Cloud AI"
    environment: str = "production"
    log_level: str = "INFO"
    max_upload_mb: int = 200
    max_discovery_resources: int = 10000
    require_login: bool = False

    def to_dict(self):
        return asdict(self)


def load_settings() -> AppSettings:
    def _int(name: str, default: int) -> int:
        try:
            return max(1, int(os.getenv(name, str(default))))
        except (TypeError, ValueError):
            return default

    env = (os.getenv("MULTICLOUD_ENV") or "production").strip().lower()
    level = (os.getenv("MULTICLOUD_LOG_LEVEL") or "INFO").strip().upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        level = "INFO"
    return AppSettings(
        environment=env,
        log_level=level,
        max_upload_mb=_int("MULTICLOUD_MAX_UPLOAD_MB", 200),
        max_discovery_resources=_int("MULTICLOUD_MAX_DISCOVERY_RESOURCES", 10000),
        require_login=(os.getenv("MULTICLOUD_REQUIRE_LOGIN", "").lower() in {"1", "true"}),
    )


def configure_logging(settings: AppSettings | None = None) -> logging.Logger:
    settings = settings or load_settings()
    logger = logging.getLogger("multicloud_ai")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    logger.propagate = False
    return logger


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]
