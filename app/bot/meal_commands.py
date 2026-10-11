"""Meal planning commands using AI."""

import logging
from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from app.bot import messages as msg
from app.database import repository as repo
from app.services.ai_service import get_ai_service
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

_daily_plans: dict[int, dict] = {}


async def _get_profile_summary(user_id: int) -> str:
    db_user = await repo.get_user_by_telegram_id(user_id)
    if not db_user:
        return ""
    profile = await repo.get_profile(db_user.id)
    if not profile or not profile.setup_complete:
        return ""
    parts = []
    if profile.age:
        parts.append(f"سن: {profile.age}")
    if profile.gender:
        parts.append("جنسیت: " + ("مرد" if profile.gender == "male" else "زن"))
    if profile.height_cm:
        parts.append(f"قد: {profile.height_cm:.0f}cm")
    if profile.weight_kg:
        parts.append(f"وزن: {profile.weight_kg:.1f}kg")
    if profile.goal:
        goal_fa = {
            "lose": "کاهش وزن", "gain": "افزایش وزن",
            "muscle": "عضله‌سازی", "maintain": "حفظ وزن",
            "quality": "بهبود کیفیت تغذیه", "sport": "هدف ورزشی",
        }.get(profile.goal, profile.goal)
        parts.append(f"هدف: {goal_fa}")
    if profile.activity_level:
        act_fa = {
            "sedentary": "کم‌تحرک", "light": "سبک",
            "moderate": "متوسط", "high": "زیاد",
        }.get(profile.activity_level, profile.activity_level)
        parts.append(f"فعالیت: {act_fa}")
    if profile.allergies:
        parts.append(f"حساسیت: {profile.allergies}")
    if profile.dislikes:
        parts.append(f"نمی‌خوره: {profile.dislikes}")
    return "، ".join(parts)


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    user = update.effective_user
    profile_summary = await _get_profile_summary(user.id)
    if not profile_summary:
        await update.message.reply_text(
            with_signature(msg.NOT_SETUP_YET), parse_mode="Markdown"
        )
        return
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )
    except Exception:
        pass
    prompt = (
        f"برای کاربر با این مشخصات، یه برنامه غذایی یک‌روزه کامل بساز:\n\n"
        f"{profile_summary}\n\n"
        f"وعده‌ها: صبحانه، میان‌وعده، ناهار، عصرانه، شام.\n"
        f"برای هر وعده: نام غذا + مقدار + کالری و پروتئین تقریبی.\n"
        f"غذاها ایرانی و در دسترس باشن.\n"
        f"در آخر جمع کل کالری و پروتئین روز.\n"
        f"خلاصه و خوانا باشه، حداکثر ۱۵ خط."
    )
    ai = get_ai_service()
    reply, _ = await ai.ask(
        user_message=prompt,
        user_name=user.first_name or "",
        user_profile_summary=profile_summary,
        user_id=user.id,
    )
    if not reply:
        reply = "متأسفانه نتونستم برنامه بسازم. دوباره تلاش کن."
    _daily_plans[user.id] = {"date": date.today().isoformat(), "plan": reply}
    text = f"🍽 **برنامه غذایی امروز**\n\n{reply}\n\n_برای دیدن مجدد: /today_"
    await update.message.reply_text(with_signature(text), parse_mode="Markdown")


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    user = update.effective_user
    cached = _daily_plans.get(user.id)
    if not cached or cached.get("date") != date.today().isoformat():
        await update.message.reply_text(
            with_signature(
                "📅 **برنامه امروز**\n\nهنوز برنامه‌ای نساختی.\nبرای ساخت: /plan"
            ),
            parse_mode="Markdown",
        )
        return
    text = f"🍽 **برنامه امروز**\n\n{cached['plan']}"
    await update.message.reply_text(with_signature(text), parse_mode="Markdown")


async def cmd_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    user = update.effective_user
    profile_summary = await _get_profile_summary(user.id)
    if not profile_summary:
        await update.message.reply_text(
            with_signature(msg.NOT_SETUP_YET), parse_mode="Markdown"
        )
        return
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )
    except Exception:
        pass
    cached = _daily_plans.get(user.id)
    plan_context = ""
    if cached and cached.get("date") == date.today().isoformat():
        plan_context = f"\nبرنامه امروز کاربر:\n{cached['plan']}\n"
    prompt = (
        f"یه فهرست خرید هفتگی برای این کاربر بساز:\n\n"
        f"{profile_summary}{plan_context}\n"
        f"دسته‌ها: پروتئین، سبزیجات، میوه، غلات، لبنیات، چربی سالم.\n"
        f"برای هر مورد: نام + مقدار تقریبی.\n"
        f"فشرده بنویس (حداکثر ۱۵ خط)."
    )
    ai = get_ai_service()
    reply, _ = await ai.ask(
        user_message=prompt,
        user_name=user.first_name or "",
        user_profile_summary=profile_summary,
        user_id=user.id,
    )
    if not reply:
        reply = "متأسفانه نتونستم فهرست بسازم. دوباره تلاش کن."
    text = f"🛒 **فهرست خرید هفتگی**\n\n{reply}"
    await update.message.reply_text(with_signature(text), parse_mode="Markdown")


async def cmd_food(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    if not context.args:
        await update.message.reply_text(
            with_signature(
                "🍎 **ارزش غذایی غذا**\n\n"
                "اسم غذا رو بعد از دستور بنویس.\n"
                "مثال:\n`/food تخم مرغ`\n`/food عدس`"
            ),
            parse_mode="Markdown",
        )
        return
    food_name = " ".join(context.args).strip()[:100]
    user = update.effective_user
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )
    except Exception:
        pass
    prompt = (
        f"ارزش غذایی ۱۰۰ گرم از این غذا رو بده:\n«{food_name}»\n\n"
        f"بنویس (هر کدوم یه خط):\n"
        f"• کالری\n• پروتئین\n• کربوهیدرات\n• چربی\n• فیبر\n"
        f"• یه نکته کوتاه تغذیه‌ای\n\nحداکثر ۸ خط."
    )
    ai = get_ai_service()
    reply, _ = await ai.ask(
        user_message=prompt,
        user_name=user.first_name or "",
        user_id=user.id,
    )
    if not reply:
        reply = "متأسفانه نتونستم اطلاعات بگیرم."
    text = f"🥗 **ارزش غذایی: {food_name}**\n\n{reply}"
    await update.message.reply_text(with_signature(text), parse_mode="Markdown")
