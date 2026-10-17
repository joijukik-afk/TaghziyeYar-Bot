"""Central configuration read from environment variables / .env file."""

from functools import lru_cache
from pydantic import Field, AliasChoices
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
    admin_ids: str = ""

    # AI (Groq / DeepSeek) - حالا با هر دو نام کار می‌کند
    groq_api_key: str = Field(
        default="", 
        validation_alias=AliasChoices("GROQ_API_KEY", "DEEPSEEK_API_KEY")
    )
    groq_model: str = Field(
        default="llama3-70b-8192", 
        validation_alias=AliasChoices("GROQ_MODEL", "DEEPSEEK_MODEL")
    )
    
    # Unsplash
    unsplash_access_key: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./taghziye_yar.db"

    # General
    log_level: str = "INFO"
    mock_mode: bool = False

    # Branding
    bot_display_name: str = "تغذیه‌یار"
    signature: str = "🥗 متخصص علی اکبر ابراهیم پور"

    @property
    def admin_id_list(self) -> list[int]:
        if not self.admin_ids:
            return []
        result: list[int] = []
        for part in self.admin_ids.split(","):
            part = part.strip()
            if part.isdigit():
                result.append(int(part))
        return result

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_id_list


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
