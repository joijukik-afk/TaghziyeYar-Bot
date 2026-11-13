"""Advanced TTS Command with Voice Selection Menu (Fast with ffmpeg)."""

import os
import logging
import tempfile
import asyncio
import edge_tts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

# صداهای باکیفیت و واقعی
VOICES = {
    "fa_farid": {"name": "👨 مرد فارسی (فرید)", "id": "fa-IR-FaridNeural", "rate": "+0%"},
    "fa_dilara": {"name": "👩 زن فارسی (دیلارا)", "id": "fa-IR-DilaraNeural", "rate": "+0%"},
    "fa_child": {"name": "🧒 بچگانه", "id": "fa-IR-DilaraNeural", "rate": "+25%"},
    "en_guy": {"name": "👨 مرد انگلیسی (گای)", "id": "en-US-GuyNeural", "rate": "+0%"},
    "en_aria": {"name": "👩 زن انگلیسی (آریا)", "id": "en-US-AriaNeural", "rate": "+0%"},
    "en_jenny": {"name": "👩 زن انگلیسی (جنی)", "id": "en-US-JennyNeural", "rate": "+0%"},
}

def get_voice_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for key, data in VOICES.items():
        row.append(InlineKeyboardButton(data["name"], callback_data=f"tts_voice_{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

async def _generate_and_send_voice(bot, chat_id: int, text: str, voice_key: str, status_msg_id: int = None):
    voice_data = VOICES.get(voice_key, VOICES["fa_farid"])
    voice_id = voice_data["id"]
    rate = voice_data.get("rate", "+0%")

    output_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
    output_ogg = output_mp3.replace(".mp3", ".ogg")

    try:
        # ۱. تولید صدا با Edge TTS
        communicate = edge_tts.Communicate(text, voice_id, rate=rate)
        await communicate.save(output_mp3)

        # ۲. تبدیل سریع به OGG با ffmpeg
        process = await asyncio.create_subprocess_shell(
            f'ffmpeg -y -i "{output_mp3}" -c:a libopus -b:a 64k "{output_ogg}"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()

        # ۳. ارسال ویس
        with open(output_ogg, "rb") as voice:
            await bot.send_voice(
                chat_id=chat_id,
                voice=voice,
                caption=f"🔊 صدا: {voice_data['name']}\n\n{text[:100]}..."
            )

        if status_msg_id:
            try: await bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
            except: pass

    except Exception as e:
        logger.error(f"TTS Error: {e}")
        if status_msg_id:
            try: await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text="❌ خطا در تولید صدا.")
            except: pass
    finally:
        for path in [output_mp3, output_ogg]:
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass

async def cmd_tts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat: return

    text = ""

    # ۱. متن همراه دستور: /tts@TaghziyeYar_bot سلام خوبی؟
    if context.args:
        text = " ".join(context.args)

    # ۲. ریپلای روی پیام متنی
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text

    # ۳. ریپلای روی ویس (اول تبدیل به متن، بعد منوی صدا)
    elif update.message.reply_to_message and update.message.reply_to_message.voice:
        status = await update.message.reply_text("🎧 در حال گوش دادن به ویس...")
        try:
            voice_file = await context.bot.get_file(update.message.reply_to_message.voice.file_id)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
                await voice_file.download_to_drive(tmp.name)
                input_ogg = tmp.name

            input_mp3 = input_ogg.replace(".ogg", ".mp3")
            process = await asyncio.create_subprocess_shell(
                f'ffmpeg -y -i "{input_ogg}" "{input_mp3}"',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()

            ai = get_ai_service()
            text = await ai.transcribe_audio(input_mp3)

            os.remove(input_ogg)
            os.remove(input_mp3)
            await status.delete()

            if not text:
                return await update.message.reply_text("❌ صدای شما شنیده نشد.")
        except Exception as e:
            logger.error(f"Voice transcribe error: {e}")
            return await update.message.reply_text("❌ خطا در پردازش ویس.")

    # راهنما اگر متنی پیدا نشد
    if not text:
        return await update.message.reply_text(
            "🔊 **راهنمای دستور TTS**\n\n"
            "📝 **روش ۱ - متن مستقیم:**\n"
            "`/tts سلام خوبی؟`\n\n"
            "📎 **روش ۲ - ریپلای روی متن:**\n"
            "روی یک پیام متنی ریپلای کنید و بزنید `/tts`\n\n"
            "🎙️ **روش ۳ - ریپلای روی ویس:**\n"
            "روی یک پیام صوتی ریپلای کنید و بزنید `/tts`\n\n"
            "سپس از منو، صدای دلخواه خود را انتخاب کنید.",
            parse_mode="Markdown"
        )

    # ذخیره متن برای استفاده در دکمه‌ها
    context.user_data["tts_text"] = text[:1000]

    await update.message.reply_text(
        f"🔊 **متن شما:**\n_{text[:200]}..._\n\n🎙️ **صدای خود را انتخاب کنید:**",
        reply_markup=get_voice_keyboard(),
        parse_mode="Markdown"
    )

async def handle_tts_voice_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    await query.answer()

    data = query.data or ""
    if not data.startswith("tts_voice_"): return

    voice_key = data.replace("tts_voice_", "")
    text = context.user_data.get("tts_text")

    if not text:
        return await query.edit_message_text("❌ متن پیدا نشد. لطفاً دوباره دستور را بزنید.")

    await query.edit_message_text("⏳ در حال ساخت صدا...")
    await _generate_and_send_voice(query.bot, query.message.chat_id, text, voice_key, query.message.message_id)
