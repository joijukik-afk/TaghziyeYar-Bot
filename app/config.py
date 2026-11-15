"""Central configuration read from environment variables / .env file."""

import uuid
from functools import lru_cache
from pydantic import Field, AliasChoices, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str
    admin_ids: list[int] = Field(default_factory=list)

    # Security / Webhook
    webhook_secret_token: str = Field(default="")
    webhook_path: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # AI Services
    groq_api_key: str = Field(default="", validation_alias=AliasChoices("GROQ_API_KEY", "groq_api_key"))
    groq_model: str = Field(default="llama-3.3-70b-versatile", validation_alias=AliasChoices("GROQ_MODEL", "groq_model"))
    openai_api_key: str = Field(default="", validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"))
    tavily_api_key: str = Field(default="", validation_alias=AliasChoices("TAVILY_API_KEY", "tavily_api_key"))

    # Media
    unsplash_access_key: str = ""
    pollinations_api_key: str = Field(default="", validation_alias=AliasChoices("POLLINATIONS_API_KEY", "pollinations_api_key"))

    # Database (اجباری - در .env مقداردهی شود)
    database_url: str

    # General
    log_level: str = "INFO"
    mock_mode: bool = False

    # Branding
    bot_display_name: str = "تغذیه‌یار"
    signature: str = "🌱 تغذیه‌یار | دستیار هوشمند شما"

    # Server
    webhook_url: str = ""
    port: int = Field(default=8080, validation_alias=AliasChoices("PORT", "port"))
    rate_limit_seconds: float = 2.0

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            return [int(i.strip()) for i in v.split(",") if i.strip().isdigit()]
        return v

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    @property
    def groq_base_url(self) -> str:
        return "https://api.groq.com/openai/v1"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
