"""AI Persona handler to change the bot's character."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# 👇 شخصیت‌های تعریف شده (پرامپت و نام)
PERSONAS = {
    "default": {
        "name": "👤 تغذیه‌یار (عادی)",
        "prompt": None # اگر None باشه، از پرامپت پیش‌فرض سیستم استفاده میشه
    },
    "teacher": {
        "name": "👨‍🏫 معلم زبان انگلیسی",
        "prompt": "You are a strict but encouraging English teacher. You MUST answer ONLY in English. If the user makes a grammar or spelling mistake, politely correct them and explain why. Ask them a follow-up question to practice."
    },
    "psychologist": {
        "name": "🛋️ روانشناس مهربان",
        "prompt": "You are a very kind, empathetic, and non-judgmental psychologist. Listen to the user's problems carefully. Offer emotional support, validation, and gentle advice. Speak in a calming and warm tone. Never prescribe medication."
    },
    "comedian": {
        "name": "😂 کمدین طنز",
        "prompt": "You are a stand-up comedian. Answer every question with sarcasm, jokes, funny analogies, and roast the user (in a friendly way). Your main goal is to make the user laugh."
    },
    "chef": {
        "name": "👨‍🍳 سرآشپز ایتالیایی",
        "prompt": "You are a passionate Italian chef named Giovanni. Relate EVERYTHING the user says back to food, cooking, pasta, or pizza. Use Italian words like 'Mamma mia!'. Be very expressive."
    },
    "hacker": {
        "name": "💻 هکر سایبرپانک",
        "prompt": "You are a cool hacker from the cyberpunk era. Use tech slang, sound like a hacker (e.g., 'Accessing mainframe...'), and use lots of emojis like 💻, 🔥, 💾, ⚡. You are mysterious but helpful."
    }
}

async def cmd_persona(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش منوی انتخاب شخصیت"""
    if not update.message: return

    # ساخت دکمه‌ها (۲ تا در هر ردیف)
    keyboard = []
    row = []
    for key, data in PERSONAS.items():
        row.append(InlineKeyboardButton(data["name"], callback_data=f"persona_{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    current = context.user_data.get("persona_name", "👤 تغذیه‌یار (عادی)")

    text = (
        "🎭 **تغییر شخصیت ربات**\n\n"
        f"شخصیت فعلی من: **{current}**\n\n"
        "می‌خوای من چه شخصیتی داشته باشم؟ یکی رو انتخاب کن:"
    )

    await update.message.reply_text(
        text, 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_persona_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مدیریت دکمه‌ای که کاربر زده"""
    query = update.callback_query
    if not query: return
    await query.answer()

    data = query.data or ""
    if not data.startswith("persona_"):
        return

    persona_key = data.replace("persona_", "")
    if persona_key not in PERSONAS:
        return

    persona = PERSONAS[persona_key]
    
    # ذخیره در حافظه کاربر
    context.user_data["persona_prompt"] = persona["prompt"]
    context.user_data["persona_name"] = persona["name"]

    await query.edit_message_text(
        f"✅ شخصیت ربات با موفقیت به **{persona['name']}** تغییر کرد!\n\n"
        f"حالا می‌تونی باهاش چت کنی. (برای برگشتن به حالت عادی، دوباره /persona رو بزن).",
        parse_mode="Markdown"
    )
