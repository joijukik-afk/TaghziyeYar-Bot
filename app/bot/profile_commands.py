"""Commands that use the user's profile: /bmi, /calories, /weight."""

import logging

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from app.bot import messages as msg
from app.calculations.bmi import calculate_bmi, format_bmi_report
from app.calculations.energy import (
    calculate_tdee,
    format_energy_report,
    suggested_calorie_target,
)
from app.calculations.macros import calculate_macros, format_macros_report
from app.database import repository as repo
from app.safety.input_validation import WEIGHT_MAX, WEIGHT_MIN, parse_float
from app.safety.nutrition_guardrails import check_safety
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)


async def _load_profile_or_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            with_signature(msg.NOT_SETUP_YET),
            parse_mode="Markdown",
        )
        return None, None
    return db_user, profile


async def cmd_bmi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user, profile = await _load_profile_or_warn(update, context)
    if db_user is None or profile is None or update.message is None:
        return
    try:
        result = calculate_bmi(profile.weight_kg, profile.height_cm)
    except ValueError as e:
        await update.message.reply_text(with_signature(f"⚠️ {e}"))
        return
    await update.message.reply_text(
        with_signature(format_bmi_report(result)),
        parse_mode="Markdown",
    )


async def cmd_calories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db_user, profile = await _load_profile_or_warn(update, context)
    if db_user is None or profile is None or update.message is None:
        return

    guard = check_safety(
        age=profile.age,
        weight_kg=profile.weight_kg,
        height_cm=profile.height_cm,
        gender=profile.gender,
        medical_notes=profile.medical_notes,
    )
    if not guard.allowed:
        text = f"⚠️ {guard.reason_fa}\n\n{guard.referral_fa}"
        await update.message.reply_text(with_signature(text))
        return

    energy = calculate_tdee(
        weight_kg=profile.weight_kg,
        height_cm=profile.height_cm,
        age=profile.age,
        gender=profile.gender,
        activity_level=profile.activity_level,
    )
    target, note = suggested_calorie_target(
        energy.tdee, profile.goal, profile.weight_kg
    )
    macros = calculate_macros(target, profile.goal, profile.weight_kg)

    text = format_energy_report(energy, target, note) + "\n\n" + format_macros_report(macros)
    await update.message.reply_text(with_signature(text), parse_mode="Markdown")


async def cmd_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return
    db_user = await repo.get_user_by_telegram_id(user.id)
    if db_user is None:
        return
    profile = await repo.get_profile(db_user.id)
    if profile is None or not profile.setup_complete:
        await update.message.reply_text(
            with_signature(msg.NOT_SETUP_YET),
            parse_mode="Markdown",
        )
        return

    if context.args:
        arg = " ".join(context.args)
        try:
            w = parse_float(arg, WEIGHT_MIN, WEIGHT_MAX)
            await _save_weight(update, db_user, profile, w)
            return
        except ValueError as e:
            await update.message.reply_text(
                with_signature(f"⚠️ {e}\n\nمثال: /weight 75")
            )
            return

    await update.message.reply_text(
        with_signature(
            "⚖️ **ثبت وزن جدید**\n\n"
            "وزنت رو به کیلوگرم بنویس:\n"
            "مثال: 75 یا 75.5\n\n"
            "برای لغو /cancel رو بزن."
        ),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data["awaiting_weight"] = True


async def handle_weight_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    user = update.effective_user
    if user is None or update.message is None or update.message.text is None:
        return False
    if not context.user_data.get("awaiting_weight"):
        return False
    context.user_data["awaiting_weight"] = False

    db_user = await repo.get_user_by_telegram_id(user.id)
    if db_user is None:
        return True
    profile = await repo.get_profile(db_user.id)
    if profile is None:
        return True

    try:
        w = parse_float(update.message.text, WEIGHT_MIN, WEIGHT_MAX)
    except ValueError as e:
        await update.message.reply_text(with_signature(f"⚠️ {e}"))
        return True

    await _save_weight(update, db_user, profile, w)
    return True


async def _save_weight(update, db_user, profile, w: float) -> None:
    old = profile.weight_kg or w
    await repo.log_weight(db_user.id, w)
    await repo.update_profile(db_user.id, weight_kg=w)

    delta = w - old
    delta_str = ""
    if abs(delta) >= 0.05:
        sign = "🔻" if delta < 0 else "🔺"
        delta_str = f"\n• تغییر: {sign} {abs(delta):.1f} کیلوگرم"

    await update.message.reply_text(
        with_signature(
            f"✅ **وزن ثبت شد**\n\n"
            f"• وزن جدید: {w:.1f} کیلوگرم{delta_str}"
        ),
        parse_mode="Markdown",
    )


async def cmd_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show weight history."""
    user = update.effective_user
    if user is None or update.message is None:
        return
    db_user = await repo.get_user_by_telegram_id(user.id)
    if db_user is None:
        return

    entries = await repo.list_weights(db_user.id, limit=10)
    if not entries:
        await update.message.reply_text(
            with_signature(
                "📊 **گزارش پیشرفت**\n\n"
                "هنوز وزنی ثبت نکردی.\n"
                "برای شروع، /weight رو بزن."
            ),
            parse_mode="Markdown",
        )
        return

    lines = ["📊 **روند وزن تو**\n"]
    for e in entries:
        date = e.logged_at.strftime("%Y-%m-%d")
        lines.append(f"• {date}: {e.weight_kg:.1f} کیلوگرم")

    if len(entries) >= 2:
        first = entries[-1].weight_kg
        last = entries[0].weight_kg
        diff = last - first
        sign = "🔻" if diff < 0 else "🔺" if diff > 0 else "➖"
        lines.append(f"\n📈 **مجموع تغییر:** {sign} {abs(diff):.1f} کیلوگرم")

    await update.message.reply_text(
        with_signature("\n".join(lines)),
        parse_mode="Markdown",
    )
