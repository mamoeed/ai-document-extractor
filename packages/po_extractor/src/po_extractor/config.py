"""Package settings, read from environment variables (see .env.example)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that mean "not configured yet" (the .env.example placeholder).
_PLACEHOLDER_KEYS = {"", "changeme", "change-me", "your-key-here"}


class ConfigError(RuntimeError):
    """Raised for missing or invalid configuration (programmer/operator error)."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    # --- LLM / VLM ---
    deepinfra_api_key: Optional[SecretStr] = None
    deepinfra_base_url: str = "https://api.deepinfra.com/v1/openai"
    vlm_model: Optional[str] = None
    vlm_temperature: float = 0.0
    vlm_max_tokens: int = 4096
    vlm_timeout_s: float = 120.0
    vlm_max_retries: int = 2
    # Send response_format={"type": "json_object"}; disable only if a model rejects it.
    vlm_json_mode: bool = True

    # --- Extraction tuning ---
    pdf_min_text_chars_per_page: int = 50
    pdf_render_dpi: int = 200
    max_pdf_pages: int = 5
    image_max_edge_px: int = 2000
    max_text_chars: int = 60000
    confidence_threshold: float = 0.8
    sanity_checks_mode: Literal["mock", "enabled"] = "mock"

    def require_llm(self) -> None:
        """Fail fast with a clear message when the VLM is not configured."""
        key = self.deepinfra_api_key.get_secret_value().strip() if self.deepinfra_api_key else ""
        if key.lower() in _PLACEHOLDER_KEYS:
            raise ConfigError(
                "DEEPINFRA_API_KEY is missing (or still the 'changeme' placeholder). "
                "Set it in .env - get a key at https://deepinfra.com/dash/api_keys"
            )
        if not (self.vlm_model or "").strip():
            raise ConfigError(
                "VLM_MODEL is missing. Set it in .env, e.g. VLM_MODEL=Qwen/Qwen3-VL-235B-A22B-Instruct"
            )
