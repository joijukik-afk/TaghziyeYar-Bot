"""Multi-Voice TTS and Voice Reply handler."""

import os
import logging
import tempfile
import edge_tts
from pydub import AudioSegment
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

# لیست صداهای موجود
VOICES = {
    "fa_farid": {"name": "👨 مرد فارسی", "id": "fa-IR-FaridNeural"},
    "fa_dilara": {"name": "👩 زن فارسی", "id": "fa-IR-DilaraNeural"},
    "en_guy": {"name": "👨 مرد انگلیسی", "id": "en-US-GuyNeural"},
    "en_aria": {"name": "👩 زن انگلیسی", "id": "en-US-AriaNeural"},
    "fa_child": {"name": "🧒 بچگانه", "id": "fa-IR-DilaraNeural", "rate": "+20%"}, # تغییر لحن با سرعت
}

def get_voice_keyboard() -> InlineKeyboardMarkup:
    """ساخت کیبورد انتخاب صدا"""
    keyboard = []
    row = []
    for key, data in VOICES.items():
        row.append(InlineKeyboardButton(data["name"], callback_data=f"voicegen_{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

async def _generate_and_send_voice(bot, chat_id: int, text: str, voice_key: str, status_msg_id: int = None):
    """تبدیل متن به صدا و ارسال"""
    voice_data = VOICES.get(voice_key, VOICES["fa_farid"])
    voice_id = voice_data["id"]
    rate = voice_data.get("rate", "+0%")

    output_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
    output_ogg = output_mp3.replace(".mp3", ".ogg")

    try:
        # ۱. تبدیل متن به صدا
        communicate = edge_tts.Communicate(text, voice_id, rate=rate)
        await communicate.save(output_mp3)

        # ۲. تبدیل به فرمت ویس تلگرام (OGG)
        audio = AudioSegment.from_mp3(output_mp3)
        audio.export(output_ogg, format="ogg", codec="libopus")

        # ۳. ارسال
        with open(output_ogg, "rb") as voice:
            await bot.send_voice(
                chat_id=chat_id, 
                voice=voice, 
                caption=f"🎙️ صدا: {voice_data['name']}\n\n{text[:100]}..."
            )
        
        if status_msg_id:
            try: await bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
            except: pass

    except Exception as e:
        logger.error(f"Multi-Voice Error: {e}")
        if status_msg_id:
            try: await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text="❌ خطا در تولید صدا.")
            except: pass
    finally:
        for path in [output_mp3, output_ogg]:
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass

async def cmd_say(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /say برای تبدیل متن به صدا با انتخاب صدا"""
    if not update.message or not update.effective_chat: return

    text = ""
    # ۱. اگر متن همراه دستور بود
    if context.args:
        text = " ".join(context.args)
    # ۲. اگر روی یک پیام متنی ریپلای کرده بود
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    # ۳. اگر روی یک ویس ریپلای کرده بود (این همون بخش جادوییه!)
    elif update.message.reply_to_message and update.message.reply_to_message.voice:
        status = await update.message.reply_text("🎧 در حال گوش دادن به ویس...")
        try:
            voice_file = await context.bot.get_file(update.message.reply_to_message.voice.file_id)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
                await voice_file.download_to_drive(tmp.name)
                input_ogg = tmp.name
            input_mp3 = input_ogg.replace(".ogg", ".mp3")
            
            audio = AudioSegment.from_ogg(input_ogg)
            audio.export(input_mp3, format="mp3")
            
            ai = get_ai_service()
            text = await ai.transcribe_audio(input_mp3)
            
            os.remove(input_ogg); os.remove(input_mp3)
            await status.delete()
            
            if not text:
                return await update.message.reply_text("❌ صدای شما شنیده نشد.")
        except Exception as e:
            logger.error(f"Voice transcribe error: {e}")
            return await update.message.reply_text("❌ خطا در پردازش ویس.")

    if not text:
        return await update.message.reply_text("⚠️ لطفاً یک متن بنویسید، یا روی یک متن/ویس ریپلای کنید و /say بزنید.")

    # ذخیره متن در حافظه برای استفاده در دکمه‌ها
    context.user_data["say_text"] = text[:1000] # محدودیت طول
    
    await update.message.reply_text(
        "🎙️ **انتخاب صدا**\n\nاین متن رو با چه صدایی برات بفرستم؟", 
        reply_markup=get_voice_keyboard(),
        parse_mode="Markdown"
    )

async def handle_voice_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مدیریت دکمه‌های انتخاب صدا"""
    query = update.callback_query
    if not query: return
    await query.answer()

    data = query.data or ""
    if not data.startswith("voicegen_"): return

    voice_key = data.replace("voicegen_", "")
    text = context.user_data.get("say_text")

    if not text:
        return await query.edit_message_text("❌ متن پیدا نشد. لطفاً دوباره دستور را بزنید.")

    await query.edit_message_text("⏳ در حال ساخت صدا...")
    await _generate_and_send_voice(query.bot, query.message.chat_id, text, voice_key, query.message.message_id)
