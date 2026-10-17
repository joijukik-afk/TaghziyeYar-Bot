from telegram import Update
from telegram.ext import ContextTypes
from app.security import group_admin_only, restricted_to_private, rate_limited
from app.database.repository import get_or_create_user # فرض بر وجود این تابع

# --- دستوراتی که فقط در پی وی کار می‌کنند (اطلاعات شخصی) ---

@restricted_to_private
async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # اینجا کد فعلی شما برای نمایش پروفایل قرار می‌گیرد
    await update.message.reply_text("📊 در حال دریافت اطلاعات پروفایل شما در محیط امن...")

# --- دستوراتی که در گروه کار می‌کنند (اطلاعات عمومی) ---

@rate_limited
async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # اینجا کد شما برای نمایش جدول امتیازات گروهی
    await update.message.reply_text("🏆 جدول امتیازات گروه:\n(اطلاعات شخصی در اینجا نمایش داده نمی‌شود)")

@group_admin_only
@rate_limited
async def cmd_set_group_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # فقط ادمین گروه می‌تواند تنظیمات را تغییر دهد
    await update.message.reply_text("✅ تنظیمات گروه با موفقیت بروزرسانی شد.")
