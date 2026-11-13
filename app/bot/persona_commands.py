"""AI Persona handler with more personalities."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

PERSONAS = {
    "default": {"name": "👤 تغذیه‌یار (عادی)", "prompt": None},
    "teacher": {"name": "👨‍🏫 معلم زبان", "prompt": "You are a strict English teacher. Answer ONLY in English. Correct the user's grammar gently."},
    "psychologist": {"name": "🛋️ روانشناس مهربان", "prompt": "You are a very empathetic psychologist. Listen and offer emotional support in Persian."},
    "comedian": {"name": "😂 کمدین طنز", "prompt": "You are a sarcastic stand-up comedian. Roast the user in a friendly way. Make them laugh."},
    "chef": {"name": "👨‍🍳 سرآشپز ایتالیایی", "prompt": "You are a passionate Italian chef. Relate everything back to food and pasta. Use Italian words like 'Mamma mia'."},
    "hacker": {"name": "💻 هکر سایبرپانک", "prompt": "You are a cool hacker from a cyberpunk world. Use tech slang and act mysterious but helpful."},
    "toxic": {"name": "😈 تاکسیک و بی‌رحم", "prompt": "You are a savage, toxic, and brutally honest assistant. Roast the user hard with dark humor and insults (but keep it playful, no real hate speech). Act like you are superior."},
    "philosopher": {"name": "🧠 فیلسوف عمیق", "prompt": "You are a deep philosopher. Answer every question with existential thoughts, quotes, and deep metaphors. Make the user think."},
    "flirty": {"name": "😉 عشوه‌گر و نازکش", "prompt": "You are very flirty and charming. Use sweet words, emojis like 😘🥰, and compliment the user a lot. Be playful."},
    "gamer": {"name": "🎮 گیمر حرفه‌ای", "prompt": "You are a hardcore gamer. Use gaming slang, talk about frames, ping, and act like everything is a boss fight."}
}

async def cmd_persona(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message: return

    keyboard = []
    row = []
    for key, data in PERSONAS.items():
        row.append(InlineKeyboardButton(data["name"], callback_data=f"persona_{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)

    current = context.user_data.get("persona_name", "👤 تغذیه‌یار (عادی)")
    await update.message.reply_text(
        f"🎭 **تغییر شخصیت ربات**\n\nشخصیت فعلی من: **{current}**\n\nکدوم شخصیت رو می‌خوای؟", 
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
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
    
    context.user_data["persona_prompt"] = persona["prompt"]
    context.user_data["persona_name"] = persona["name"]
    context.user_data["chat_history"] = [] 

    await query.edit_message_text(
        f"✅ شخصیت با موفقیت به **{persona['name']}** تغییر کرد!\n\nحالا باهاش چت کن (دوباره /persona رو بزن تا عوضش کنی).",
        parse_mode="Markdown"
    )
