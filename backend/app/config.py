"""Backend settings (env vars, see .env.example). VLM settings live in po_extractor.Settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

import po_extractor

DEFAULT_JWT_SECRET = "change-this-long-random-string"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    database_url: str
    app_username: str
    app_password: SecretStr
    jwt_secret: SecretStr
    jwt_expire_minutes: int = 480
    upload_dir: Path = Path("/data/uploads")
    max_upload_mb: int = 20
    customer_master_path: Path = Path("/data/master/fictional_customer_master.xlsx")
    item_master_path: Path = Path("/data/master/fictional_item_master.xlsx")
    debug: bool = False
    log_level: Optional[str] = None

    @property
    def effective_log_level(self) -> str:
        return (self.log_level or ("DEBUG" if self.debug else "INFO")).upper()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()  # type: ignore[call-arg]


@lru_cache
def get_po_settings() -> po_extractor.Settings:
    return po_extractor.Settings()
