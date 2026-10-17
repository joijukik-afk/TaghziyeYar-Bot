import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # تنظیمات اصلی ربات
    bot_token: str = Field(..., env="BOT_TOKEN")
    admin_ids: str = Field("", env="ADMIN_IDS") # آیدی ادمین‌ها با کاما جدا شود
    
    # تنظیمات دیتابیس
    database_url: str = Field("sqlite+aiosqlite:///./taghziye_yar.db", env="DATABASE_URL")
    
    # تنظیمات هوش مصنوعی (اصلاح شده از deepseek به groq)
    groq_api_key: str = Field(..., env="GROQ_API_KEY")
    groq_model: str = Field("llama3-70b-8192", env="GROQ_MODEL")
    
    # تنظیمات عکس
    unsplash_access_key: str = Field("", env="UNSPLASH_ACCESS_KEY")
    
    # تنظیمات امنیتی و استقرار (Render)
    webhook_url: str = Field("", env="WEBHOOK_URL") # آدرس Render شما مثل https://mybot.onrender.com
    port: int = Field(8080, env="PORT")
    rate_limit_seconds: int = Field(3, env="RATE_LIMIT_SECONDS") # فاصله مجاز بین پیام‌های هر کاربر

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def admin_id_list(self) -> list[int]:
        if not self.admin_ids:
            return []
        return [int(x.strip()) for x in self.admin_ids.split(",") if x.strip().isdigit()]

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_id_list

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
