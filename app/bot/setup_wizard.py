"""Multi-step profile setup wizard."""

import logging

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from app.bot import messages as msg
from app.database import repository as repo
from app.safety.input_validation import (
    AGE_MAX,
    AGE_MIN,
    HEIGHT_MAX,
    HEIGHT_MIN,
    WEIGHT_MAX,
    WEIGHT_MIN,
    parse_float,
    parse_int,
    validate_activity,
    validate_gender,
    validate_goal,
)
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)


# ----- step constants -----
STEP_IDLE = 0
STEP_AGE = 1
STEP_GENDER = 2
STEP_HEIGHT = 3
STEP_WEIGHT = 4
STEP_TARGET_WEIGHT = 5
STEP_GOAL = 6
STEP_ACTIVITY = 7
STEP_MEDICAL = 8
STEP_DONE = 99


QUESTIONS = {
    STEP_AGE: (
        "1️⃣ **سن** خودت رو به سال بنویس.\n"
        "مثال: ۲۸\n\n"
        "📌 سن باید بین ۱۸ تا ۸۰ سال باشه."
    ),
    STEP_GENDER: "2️⃣ **جنسیت** خودت رو انتخاب کن:",
    STEP_HEIGHT: (
        "3️⃣ **قد** خودت رو به سانتی‌متر بنویس.\n"
        "مثال: ۱۷۵\n\n"
        "📌 قد باید بین ۱۰۰ تا ۲۳۰ سانتی‌متر باشه."
    ),
    STEP_WEIGHT: (
        "4️⃣ **وزن فعلی** خودت رو به کیلوگرم بنویس.\n"
        "مثال: ۷۵\n\n"
        "📌 وزن باید بین ۳۰ تا ۳۰۰ کیلوگرم باشه."
    ),
    STEP_TARGET_WEIGHT: (
        "5️⃣ **وزن هدف** خودت رو به کیلوگرم بنویس.\n"
        "مثال: ۷۰\n\n"
        "📌 اگه وزن هدف مشخصی نداری، عدد 0 رو بفرست."
    ),
    STEP_GOAL: "6️⃣ **هدف اصلی** خودت رو انتخاب کن:",
    STEP_ACTIVITY: "7️⃣ **سطح فعالیت روزانه** خودت رو انتخاب کن:",
    STEP_MEDICAL: (
        "8️⃣ اگه **بیماری یا شرایط خاص پزشکی** داری بنویس.\n"
        "مثال: دیابت، فشار خون، بارداری\n\n"
        "📌 اگه نداری، بنویس: هیچ\n"
        "🔒 این اطلاعات محرمانه می‌مونه و برای ایمنی توصیه‌هاست."
    ),
}


def _rows(items: list[str], per_row: int) -> list[list[str]]:
    return [items[i : i + per_row] for i in range(0, len(items), per_row)]


def _kb(items: list[str], per_row: int = 2, hint: str | None = None) -> ReplyKeyboardMarkup:
    rows = _rows(items, per_row)
    if hint:
        rows.append([hint])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


async def start_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return
    db_user = await repo.get_user_by_telegram_id(user.id)
    if db_user is None:
        await update.message.reply_text(with_signature(msg.ERROR_GENERIC))
        return

    await repo.update_profile(
        db_user.id,
        setup_step=STEP_AGE,
        setup_complete=False,
    )

    await update.message.reply_text(
        with_signature(
            "👋 **راه‌اندازی پروفایل**\n\n"
            "چند سوال کوتاه می‌پرسم تا بتونم برنامه مناسب تو بسازم.\n"
            "🔒 جواب‌ها فقط برای خودت ذخیره می‌شن.\n\n"
            "برای لغو هر وقت خواستی /cancel رو بزن."
        ),
        parse_mode="Markdown",
    )
    await _ask(update, context, STEP_AGE)


async def _ask(update: Update, context: ContextTypes.DEFAULT_TYPE, step: int) -> None:
    text = QUESTIONS.get(step, "")
    if not text or update.message is None:
        return

    kb = None
    if step == STEP_GENDER:
        kb = _kb(["مرد", "زن"], 2, "لغو /cancel")
    elif step == STEP_GOAL:
        kb = _kb(
            ["کاهش وزن", "افزایش وزن", "عضله‌سازی", "حفظ وزن", "بهبود کیفیت", "هدف ورزشی"],
            2,
            "لغو /cancel",
        )
    elif step == STEP_ACTIVITY:
        kb = _kb(
            ["کم‌تحرک", "فعالیت سبک", "فعالیت متوسط", "فعالیت زیاد"],
            2,
            "لغو /cancel",
        )

    await update.message.reply_text(
        with_signature(text),
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def handle_setup_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Return True if handled, False otherwise."""
    user = update.effective_user
    if user is None or update.message is None or update.message.text is None:
        return False

    db_user = await repo.get_user_by_telegram_id(user.id)
    if db_user is None:
        return False

    profile = await repo.get_profile(db_user.id)
    if profile is None or profile.setup_complete:
        return False
    if profile.setup_step == STEP_IDLE:
        return False

    step = profile.setup_step
    text = update.message.text.strip()

    try:
        if step == STEP_AGE:
            age = parse_int(text, AGE_MIN, AGE_MAX)
            await repo.update_profile(db_user.id, age=age, setup_step=STEP_GENDER)
            await _ask(update, context, STEP_GENDER)

        elif step == STEP_GENDER:
            gender = validate_gender(text)
            if gender is None:
                raise ValueError("جنسیت نامعتبر. یکی از دکمه‌ها رو بزن.")
            await repo.update_profile(db_user.id, gender=gender, setup_step=STEP_HEIGHT)
            await _ask(update, context, STEP_HEIGHT)

        elif step == STEP_HEIGHT:
            h = parse_float(text, HEIGHT_MIN, HEIGHT_MAX)
            await repo.update_profile(db_user.id, height_cm=h, setup_step=STEP_WEIGHT)
            await _ask(update, context, STEP_WEIGHT)

        elif step == STEP_WEIGHT:
            w = parse_float(text, WEIGHT_MIN, WEIGHT_MAX)
            await repo.update_profile(db_user.id, weight_kg=w, setup_step=STEP_TARGET_WEIGHT)
            await repo.log_weight(db_user.id, w)
            await _ask(update, context, STEP_TARGET_WEIGHT)

        elif step == STEP_TARGET_WEIGHT:
            if text in ("۰", "0", "هیچ", "ندارم", "-"):
                target = None
            else:
                target = parse_float(text, WEIGHT_MIN, WEIGHT_MAX)
            await repo.update_profile(
                db_user.id, target_weight_kg=target, setup_step=STEP_GOAL
            )
            await _ask(update, context, STEP_GOAL)

        elif step == STEP_GOAL:
            goal = validate_goal(text)
            if goal is None:
                raise ValueError("هدف نامعتبر. یکی از دکمه‌ها رو بزن.")
            await repo.update_profile(db_user.id, goal=goal, setup_step=STEP_ACTIVITY)
            await _ask(update, context, STEP_ACTIVITY)

        elif step == STEP_ACTIVITY:
            activity = validate_activity(text)
            if activity is None:
                raise ValueError("سطح فعالیت نامعتبر. یکی از دکمه‌ها رو بزن.")
            await repo.update_profile(
                db_user.id, activity_level=activity, setup_step=STEP_MEDICAL
            )
            await _ask(update, context, STEP_MEDICAL)

        elif step == STEP_MEDICAL:
            notes = None if text in ("هیچ", "هیچی", "ندارم", "-", "خیر") else text
            await repo.update_profile(
                db_user.id,
                medical_notes=notes,
                setup_step=STEP_DONE,
                setup_complete=True,
            )
            await update.message.reply_text(
                with_signature(
                    "✅ **پروفایل با موفقیت ساخته شد!**\n\n"
                    "حالا می‌تونی از این دستورات استفاده کنی:\n\n"
                    "📊 /bmi — محاسبه BMI\n"
                    "🔥 /calories — کالری روزانه + درشت‌مغذی‌ها\n"
                    "👤 /profile — مشاهده پروفایل\n"
                    "⚖️ /weight — ثبت وزن جدید\n"
                    "🏠 /menu — منوی اصلی\n\n"
                    "برای شروع، /bmi رو بزن."
                ),
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove(),
            )
            return True

        else:
            return False

    except ValueError as e:
        await update.message.reply_text(
            with_signature(f"⚠️ {e}\n\nلطفاً دوباره وارد کن یا /cancel بزن."),
        )

    return True


async def cancel_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return
    db_user = await repo.get_user_by_telegram_id(user.id)
    if db_user is None:
        return
    await repo.update_profile(db_user.id, setup_step=STEP_IDLE)
    await update.message.reply_text(
        with_signature("✅ راه‌اندازی لغو شد. هر وقت خواستی /setup رو بزن."),
        reply_markup=ReplyKeyboardRemove(),
    )
