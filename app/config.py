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

    # ============================================================
    # Telegram
    # ============================================================
    telegram_bot_token: str
    admin_ids: list[int] = Field(default_factory=list)

    # ============================================================
    # Security / Webhook
    # ============================================================
    webhook_secret_token: str = Field(default="")
    webhook_path: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ============================================================
    # AI Services (اصلاح‌شده برای پشتیبانی از DEEPSEEK قبلی)
    # ============================================================
    groq_api_key: str = Field(
        default="",
        # 👈 این بخش باعث می‌شود هم GROQ_API_KEY و هم DEEPSEEK_API_KEY خوانده شوند
        validation_alias=AliasChoices(
            "GROQ_API_KEY", "DEEPSEEK_API_KEY", 
            "groq_api_key", "deepseek_api_key"
        ),
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        validation_alias=AliasChoices(
            "GROQ_MODEL", "DEEPSEEK_MODEL", 
            "groq_model", "deepseek_model"
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
    # Validators
    # ============================================================
    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        """
        پشتیبانی از سه حالت ورودی برای ادمین آیدی:
        - int (مثل 6409367884)
        - str (مثل "123,456")
        - list (مثل [123, 456])
        """
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

    # ============================================================
    # Helper Methods
    # ============================================================
    def is_admin(self, user_id: int) -> bool:
        """بررسی اینکه آیا کاربر ادمین است یا نه"""
        return user_id in self.admin_ids

    @property
    def groq_base_url(self) -> str:
        return "https://api.groq.com/openai/v1"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """دریافت تنظیمات با کش (فقط یک بار خوانده می‌شود)"""
    return Settings()
