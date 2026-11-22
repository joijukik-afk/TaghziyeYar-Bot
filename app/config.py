"""Central configuration read from environment variables / .env file."""

import uuid
from functools import lru_cache
from typing import List

from pydantic import Field, AliasChoices, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ============================================================
    # Telegram
    # ============================================================
    telegram_bot_token: str
    admin_ids: List[int] = Field(default_factory=list)

    # ============================================================
    # Security / Webhook
    # ============================================================
    webhook_secret_token: str = Field(default="")
    webhook_path: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ============================================================
    # AI Services
    # ============================================================
    groq_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "GROQ_API_KEY", "DEEPSEEK_API_KEY",
            "groq_api_key", "deepseek_api_key",
        ),
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        validation_alias=AliasChoices(
            "GROQ_MODEL", "DEEPSEEK_MODEL",
            "groq_model", "deepseek_model",
        ),
    )
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
    )
    tavily_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("TAVILY_API_KEY", "tavily_api_key"),
    )

    # ============================================================
    # Media
    # ============================================================
    unsplash_access_key: str = Field(
        default="",
        validation_alias=AliasChoices("UNSPLASH_ACCESS_KEY", "unsplash_access_key"),
    )
    pollinations_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("POLLINATIONS_API_KEY", "pollinations_api_key"),
    )

    # ============================================================
    # Database
    # ============================================================
    database_url: str

    # ============================================================
    # General
    # ============================================================
    log_level: str = "INFO"
    mock_mode: bool = False

    # ============================================================
    # Branding
    # ============================================================
    bot_display_name: str = "تغذیه‌یار"
    signature: str = "🌱 تغذیه‌یار | دستیار هوشمند شما"

    # ============================================================
    # Server
    # ============================================================
    webhook_url: str = ""
    port: int = Field(
        default=8080,
        validation_alias=AliasChoices("PORT", "port"),
    )
    rate_limit_seconds: float = 2.0

    # ============================================================
    # MCP Endpoints (backward compatibility - not used)
    # ============================================================
    mcp_digikala_url: str = Field(
        default="http://localhost:8000/mcp",
        validation_alias=AliasChoices(
            "MCP_DIGIKALA_URL", "DIGIKALA_MCP_URL", "mcp_digikala_url",
        ),
    )
    mcp_torob_url: str = Field(
        default="http://localhost:8001/mcp",
        validation_alias=AliasChoices(
            "MCP_TOROB_URL", "TOROB_MCP_URL", "mcp_torob_url",
        ),
    )
    mcp_snappshop_url: str = Field(
        default="http://localhost:8002/mcp",
        validation_alias=AliasChoices(
            "MCP_SNAPP_SHOP_URL", "MCP_SNAPP_SHOP", "SNAPP_SHOP_MCP_URL",
            "mcp_snappshop_url",
        ),
    )

    # ============================================================
    # MCP Toggles (backward compatibility - not used)
    # ============================================================
    mcp_digikala_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("MCP_DIGIKALA_ENABLED", "mcp_digikala_enabled"),
    )
    mcp_torob_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("MCP_TOROB_ENABLED", "mcp_torob_enabled"),
    )
    mcp_snappshop_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("MCP_SNAPP_SHOP_ENABLED", "mcp_snappshop_enabled"),
    )
    mcp_timeout_seconds: float = Field(
        default=20.0,
        validation_alias=AliasChoices("MCP_TIMEOUT_SECONDS", "mcp_timeout_seconds"),
    )
    mcp_connect_timeout_seconds: float = Field(
        default=10.0,
        validation_alias=AliasChoices(
            "MCP_CONNECT_TIMEOUT_SECONDS", "mcp_connect_timeout_seconds",
        ),
    )
    mcp_healthcheck_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "MCP_HEALTHCHECK_ENABLED", "mcp_healthcheck_enabled",
        ),
    )

    # ============================================================
    # BlackHunt / AutoHunter
    # ============================================================
    auto_hunter_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("AUTO_HUNTER_ENABLED", "auto_hunter_enabled"),
    )
    auto_hunter_min_discount: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "AUTO_HUNTER_MIN_DISCOUNT", "auto_hunter_min_discount",
        ),
    )
    auto_hunter_interval_seconds: int = Field(
        default=300,
        validation_alias=AliasChoices(
            "AUTO_HUNTER_INTERVAL_SECONDS", "auto_hunter_interval_seconds",
        ),
    )
    auto_hunter_max_results_per_store: int = Field(
        default=6,
        validation_alias=AliasChoices(
            "AUTO_HUNTER_MAX_RESULTS_PER_STORE",
            "auto_hunter_max_results_per_store",
        ),
    )
    auto_hunter_query: str = Field(
        default="تخفیف بلک فرایدی",
        validation_alias=AliasChoices(
            "AUTO_HUNTER_QUERY", "auto_hunter_query",
        ),
    )

    # ============================================================
    # Validators
    # ============================================================
    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, list):
            result = []
            for item in v:
                try:
                    result.append(int(item))
                except (ValueError, TypeError):
                    continue
            return result
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                return []
            result = []
            for part in stripped.split(","):
                part = part.strip()
                if part.isdigit():
                    result.append(int(part))
            return result
        return []

    @field_validator(
        "mcp_digikala_url", "mcp_torob_url", "mcp_snappshop_url",
        mode="before",
    )
    @classmethod
    def normalize_mcp_url(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return v
            if not v.startswith(("http://", "https://")):
                v = "http://" + v
            return v
        return v

    @field_validator("auto_hunter_min_discount")
    @classmethod
    def validate_discount_range(cls, v: int) -> int:
        if not (0 <= v <= 100):
            raise ValueError(
                "auto_hunter_min_discount must be between 0 and 100"
            )
        return v

    @field_validator("auto_hunter_interval_seconds")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        if v < 30:
            raise ValueError(
                "auto_hunter_interval_seconds must be >= 30"
            )
        return v

    # ============================================================
    # Helper Methods
    # ============================================================
    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    @property
    def groq_base_url(self) -> str:
        return "https://api.groq.com/openai/v1"

    @property
    def enabled_mcp_stores(self) -> List[str]:
        stores: List[str] = []
        if self.mcp_digikala_enabled:
            stores.append("digikala")
        if self.mcp_torob_enabled:
            stores.append("torob")
        if self.mcp_snappshop_enabled:
            stores.append("snappshop")
        return stores

    def mcp_endpoint_for(self, store: str) -> str:
        mapping = {
            "digikala": self.mcp_digikala_url,
            "torob": self.mcp_torob_url,
            "snappshop": self.mcp_snappshop_url,
            "snapp_shop": self.mcp_snappshop_url,
        }
        key = (store or "").lower().replace("-", "_")
        if key not in mapping:
            raise ValueError(f"Unknown MCP store: {store}")
        return mapping[key]

    def is_mcp_store_enabled(self, store: str) -> bool:
        key = (store or "").lower().replace("-", "_")
        return {
            "digikala": self.mcp_digikala_enabled,
            "torob": self.mcp_torob_enabled,
            "snappshop": self.mcp_snappshop_enabled,
            "snapp_shop": self.mcp_snappshop_enabled,
        }.get(key, False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
