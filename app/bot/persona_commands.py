"""AI Persona handler with DB Save."""

import logging
from typing import TypedDict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.database.state_repository import save_user_state
from app.database import repository as repo
from app.bot.personas.black_friday_persona import BLACK_FRIDAY_PERSONA

logger = logging.getLogger(__name__)


class PersonaDict(TypedDict):
    name: str
    prompt: Optional[str]


PERSONAS: dict[str, PersonaDict] = {
    "default": {"name": "👤 تغذیه‌یار (عادی)", "prompt": None},
    "teacher": {"name": "👨‍🏫 معلم زبان", "prompt": "You are a strict English teacher. Answer ONLY in English. Correct the user's grammar gently."},
    "psychologist": {"name": "🛋️ روانشناس مهربان", "prompt": "You are a very empathetic psychologist. Listen and offer emotional support in Persian."},
    "comedian": {"name": "😂 کمدین طنز", "prompt": "You are a sarcastic stand-up comedian. Roast the user in a friendly way. Make them laugh."},
    "chef": {"name": "👨‍🍳 سرآشپز ایتالیایی", "prompt": "You are a passionate Italian chef. Relate everything back to food and pasta. Use Italian words like 'Mamma mia'."},
    "hacker": {"name": "💻 هکر سایبرپانک", "prompt": "You are a cool hacker from a cyberpunk world. Use tech slang and act mysterious but helpful."},
    "toxic": {"name": "😈 تاکسیک و بی‌رحم", "prompt": "You are a savage, toxic, and brutally honest assistant. Roast the user hard with dark humor and insults (but keep it playful, no real hate speech). Act like you are superior."},
    "philosopher": {"name": "🧠 فیلسوف عمیق", "prompt": "You are a deep philosopher. Answer every question with existential thoughts, quotes, and deep metaphors. Make the user think."},
    "flirty": {"name": "😉 عشوه‌گر و نازکش", "prompt": "You are very flirty and charming. Use sweet words, emojis like 😘🥰, and compliment the user a lot. Be playful."},
    "gamer": {"name": "🎮 گیمر حرفه‌ای", "prompt": "You are a hardcore gamer. Use gaming slang, talk about frames, ping, and act like everything is a boss fight."},
    "black_friday": BLACK_FRIDAY_PERSONA,
}


async def cmd_persona(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message: return

    keyboard = []
    row = []
    for key, data in PERSONAS.items():
        if key == "black_friday":
            continue
        row.append(InlineKeyboardButton(data["name"], callback_data=f"persona_{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(BLACK_FRIDAY_PERSONA["name"], callback_data="persona_black_friday")
    ])

    current_key = context.user_data.get("persona_key", "default")
    current_name = PERSONAS.get(current_key, PERSONAS["default"])["name"]

    await update.message.reply_text(
        f"🎭 <b>تغییر شخصیت</b>\n\nشخصیت فعلی: <b>{current_name}</b>\n\nکدوم رو می‌خوای؟", 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode="HTML"
    )


async def handle_persona_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    await query.answer()

    data = query.data or ""
    if not data.startswith("persona_"): return

    persona_key = data.replace("persona_", "")
    persona = PERSONAS.get(persona_key)
    if not persona: return
    
    user = query.from_user
    
    try:
        await repo.get_or_create_user(
            telegram_id=user.id, username=user.username, first_name=user.first_name, last_name=user.last_name
        )
    except Exception as e:
        logger.error(f"Failed to ensure user in DB: {e}")
        return await query.edit_message_text("❌ خطا در ارتباط با دیتابیس. لطفاً بعداً تلاش کنید.")

    try:
        await save_user_state(user.id, persona_key, [])
    except Exception as e:
        logger.error(f"Failed to save persona to DB: {e}")
        return await query.edit_message_text("❌ خطا در ذخیره شخصیت. لطفاً بعداً تلاش کنید.")

    context.user_data["persona_key"] = persona_key
    context.user_data["persona_prompt"] = persona["prompt"]
    context.user_data["persona_name"] = persona["name"]

    await query.edit_message_text(
        f"✅ شخصیت به <b>{persona['name']}</b> تغییر کرد!\n\n(توی دیتابیس هم ذخیره شد).",
        parse_mode="HTML"
    )
