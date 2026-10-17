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
        validation_alias=AliasChoices("GROQ_API_KEY", "DEEPSEEK_API_KEY", "deepseek_api_key", "groq_api_key")
    )
    groq_model: str = Field(
        default="llama3-70b-8192", 
        validation_alias=AliasChoices("GROQ_MODEL", "DEEPSEEK_MODEL", "deepseek_model", "groq_model")
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

    # 🛡️ Security & Render
    webhook_url: str = ""  
    port: int = 8080       
    rate_limit_seconds: float = 2.0  

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

    # =====================================================================
    # 🔄 سازگاری با کدهای قبلی (حیاتی برای ai_service.py و auto_content.py)
    # =====================================================================
    @property
    def deepseek_api_key(self) -> str:
        return self.groq_api_key

    @property
    def deepseek_model(self) -> str:
        return self.groq_model

    @property
    def deepseek_base_url(self) -> str:
        return "https://api.groq.com/openai/v1"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
