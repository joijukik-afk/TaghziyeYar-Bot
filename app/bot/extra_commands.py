"""Extra commands: tip, fact, myth, water, macros, protein, ideal, bodyfat, bmr."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.bot import messages as msg
from app.bot.content import get_fact, get_myth, get_tip
from app.calculations.bmi import calculate_bmi
from app.calculations.energy import calculate_bmr, calculate_tdee, suggested_calorie_target
from app.calculations.health import (
    calculate_fiber,
    calculate_ideal_weight,
    calculate_water_intake,
    estimate_body_fat,
)
from app.calculations.macros import calculate_macros, format_macros_report
from app.database import repository as repo
from app.safety.input_validation import parse_int
from app.safety.nutrition_guardrails import check_safety
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)


async def cmd_tip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        with_signature(f"💡 **نکته تغذیه‌ای**\n\n{get_tip()}"),
        parse_mode="Markdown",
    )


async def cmd_fact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        with_signature(f"🍎 **فکت جالب**\n\n{get_fact()}"),
        parse_mode="Markdown",
    )


async def cmd_myth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    myth, truth = get_myth()
    await update.message.reply_text(
        with_signature(f"❌ **باور اشتباه**\n\n{myth}\n\n✅ **واقعیت**\n{truth}"),
        parse_mode="Markdown",
    )


async def cmd_water(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if context.args:
        try:
            glasses = parse_int(" ".join(context.args), 0, 30)
        except ValueError as e:
            await update.message.reply_text(
                with_signature(f"⚠️ {e}\n\nمثال: `/water 5`"),
                parse_mode="Markdown",
            )
            return
    else:
        glasses = 1
    await update.message.reply_text(
        with_signature(
            f"💧 **ثبت شد!**\n\n• {glasses} لیوان آب ثبت شد.\n\nℹ️ برای محاسبه نیازت: /ideal"
        ),
        parse_mode="Markdown",
    )


async def _load_profile(update: Update):
    user = update.effective_user
    if user is None or update.message is None:
        return None, None
    db_user = await repo.get_user_by_telegram_id(user.id)
    if db_user is None:
        await update.message.reply_text(with_signature(msg.ERROR_GENERIC))
        return None, None
    profile = await repo.get_profile(db_user.id)
    if profile is None or not profile.setup_complete:
        await update.message.reply_text(
            with_signature(msg.NOT_SETUP_YET), parse_mode="Markdown"
        )
        return None, None
    return db_user, profile


async def cmd_macros(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user, profile = await _load_profile(update)
    if db_user is None or profile is None or update.message is None:
        return
    guard = check_safety(
        age=profile.age, weight_kg=profile.weight_kg,
        height_cm=profile.height_cm, gender=profile.gender,
        medical_notes=profile.medical_notes,
    )
    if not guard.allowed:
        await update.message.reply_text(
            with_signature(f"⚠️ {guard.reason_fa}\n\n{guard.referral_fa}")
        )
        return
    energy = calculate_tdee(
        weight_kg=profile.weight_kg, height_cm=profile.height_cm,
        age=profile.age, gender=profile.gender,
        activity_level=profile.activity_level,
    )
    target, _ = suggested_calorie_target(energy.tdee, profile.goal, profile.weight_kg)
    macros = calculate_macros(target, profile.goal, profile.weight_kg)
    await update.message.reply_text(
        with_signature(format_macros_report(macros)), parse_mode="Markdown"
    )


async def cmd_protein(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user, profile = await _load_profile(update)
    if db_user is None or profile is None or update.message is None:
        return
    w = profile.weight_kg or 70.0
    if profile.activity_level == "high":
        lo, hi, label = 1.6 * w, 2.0 * w, "فعالیت بالا / ورزشکار"
    elif profile.activity_level == "moderate":
        lo, hi, label = 1.2 * w, 1.6 * w, "فعالیت متوسط"
    elif profile.activity_level == "light":
        lo, hi, label = 1.0 * w, 1.2 * w, "فعالیت سبک"
    else:
        lo, hi, label = 0.8 * w, 1.0 * w, "کم‌تحرک"
    if profile.goal in ("muscle", "sport"):
        lo = max(lo, 1.6 * w)
        hi = max(hi, 2.0 * w)
    text = (
        f"🥩 **نیاز پروتئین روزانه**\n\n"
        f"• وضعیت: {label}\n• وزن: {w:.1f} کیلوگرم\n"
        f"• نیاز: **{lo:.0f} تا {hi:.0f} گرم**\n\n"
        f"**منابع خوب:**\n"
        f"• 🥚 تخم‌مرغ (~۶ گرم)\n"
        f"• 🍗 سینه مرغ (۱۰۰گرم ~۳۰گرم)\n"
        f"• 🥛 ماست یونانی (۲۰۰گرم ~۲۰گرم)\n"
        f"• 🫘 عدس پخته (پیمانه ~۱۸گرم)\n\n"
        f"ℹ️ اعداد تخمینی."
    )
    await update.message.reply_text(with_signature(text), parse_mode="Markdown")


async def cmd_ideal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user, profile = await _load_profile(update)
    if db_user is None or profile is None or update.message is None:
        return
    ideal = calculate_ideal_weight(profile.height_cm, profile.gender)
    water_lo, water_hi = calculate_water_intake(profile.weight_kg or 70, profile.activity_level or "moderate")
    energy = calculate_tdee(
        weight_kg=profile.weight_kg, height_cm=profile.height_cm,
        age=profile.age, gender=profile.gender,
        activity_level=profile.activity_level,
    )
    fiber_lo, fiber_hi = calculate_fiber(int(energy.tdee))
    text = (
        f"🎯 **تحلیل جامع سلامتی**\n\n"
        f"**⚖️ وزن ایده‌آل (قد {profile.height_cm:.0f}):**\n"
        f"• میانگین: **{ideal.average} کیلوگرم**\n"
        f"• محدوده سالم: {ideal.bmi_range_low:.1f} تا {ideal.bmi_range_high:.1f} کیلوگرم\n\n"
        f"**💧 نیاز آب روزانه:**\n"
        f"• {water_lo} تا {water_hi} میلی‌لیتر (~{water_lo // 250} تا {water_hi // 250} لیوان)\n\n"
        f"**🌾 نیاز فیبر روزانه:**\n"
        f"• {fiber_lo} تا {fiber_hi} گرم\n\n"
        f"ℹ️ وزن ایده‌آل یکی از معیارهاست."
    )
    await update.message.reply_text(with_signature(text), parse_mode="Markdown")


async def cmd_bodyfat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user, profile = await _load_profile(update)
    if db_user is None or profile is None or update.message is None:
        return
    bmi_res = calculate_bmi(profile.weight_kg, profile.height_cm)
    bf = estimate_body_fat(bmi_res.value, profile.age, profile.gender)
    text = (
        f"📊 **تخمین چربی بدن**\n\n"
        f"• درصد چربی: **{bf.percent}%**\n"
        f"• دسته: **{bf.category_fa}**\n\n"
        f"⚠️ این تخمین از روی BMI و سنـه."
    )
    await update.message.reply_text(with_signature(text), parse_mode="Markdown")


async def cmd_bmr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user, profile = await _load_profile(update)
    if db_user is None or profile is None or update.message is None:
        return
    bmr = calculate_bmr(
        weight_kg=profile.weight_kg, height_cm=profile.height_cm,
        age=profile.age, gender=profile.gender,
    )
    text = (
        f"⚡ **متابولیسم پایه (BMR)**\n\n"
        f"• مقدار: **{int(bmr)} کالری**\n\n"
        f"این یعنی اگه تمام روز دراز بکشی، بدنت این مقدار می‌سوزونه.\n\n"
        f"ℹ️ فرمول: Mifflin-St Jeor"
    )
    await update.message.reply_text(with_signature(text), parse_mode="Markdown")
