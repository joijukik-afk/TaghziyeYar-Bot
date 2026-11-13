"""Voice chat handler: Voice -> Text -> AI -> Instant Voice Reply."""

import os
import logging
import tempfile
import asyncio
import edge_tts
from telegram import Update
from telegram.ext import ContextTypes
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

VOICE_SYSTEM_PROMPT = (
    "تو یک دستیار صوتی فوق‌العاده باهوش، صمیمی و احساساتی هستی. "
    "کاربر با تو حرف می‌زند و تو باید با لحنی طبیعی، دوستانه و پر از احساس پاسخ دهی. "
    "پاسخ‌های تو باید کوتاه و مفید باشند (حداکثر ۳ تا ۴ جمله) چون قرار است به صدا تبدیل شوند. "
    "از ایموجی‌ها و علامت‌های نگارشی عجیب استفاده نکن. "
)

async def _process_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, voice_file_id: str, status_msg_id: int):
    input_ogg_path = input_mp3_path = output_mp3 = output_ogg = None
    try:
        # ۱. دانلود فایل صوتی
        voice_file = await context.bot.get_file(voice_file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp_file:
            await voice_file.download_to_drive(tmp_file.name)
            input_ogg_path = tmp_file.name

        # تبدیل به mp3 برای Whisper
        input_mp3_path = input_ogg_path.replace(".ogg", ".mp3")
        process = await asyncio.create_subprocess_shell(
            f'ffmpeg -y -i "{input_ogg_path}" "{input_mp3_path}"',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()

        # ۲. تبدیل صدا به متن
        ai_service = get_ai_service()
        user_text = await ai_service.transcribe_audio(input_mp3_path)

        if not user_text:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg_id, text="❌ صدای شما شنیده نشد.")
            return

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id, message_id=status_msg_id, 
            text=f"🗣️ **شما گفتید:**\n{user_text}\n\n🧠 در حال فکر کردن..."
        )

        # ۳. هوش مصنوعی جواب رو می‌سازه
        ai_reply_tuple = await ai_service.ask(
            user_message=user_text,
            user_name=update.effective_user.first_name if update.effective_user else "کاربر",
            user_id=update.effective_user.id if update.effective_user else 0,
            custom_system_prompt=VOICE_SYSTEM_PROMPT
        )
        ai_reply_text = ai_reply_tuple[0] if isinstance(ai_reply_tuple, tuple) else str(ai_reply_tuple)

        # ۴. تبدیل فوری جواب به ویس (با صدای مرد فارسی)
        output_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
        output_ogg = output_mp3.replace(".mp3", ".ogg")

        communicate = edge_tts.Communicate(ai_reply_text, "fa-IR-FaridNeural")
        await communicate.save(output_mp3)

        # تبدیل به OGG با ffmpeg مستقیم
        process2 = await asyncio.create_subprocess_shell(
            f'ffmpeg -y -i "{output_mp3}" -c:a libopus -b:a 64k "{output_ogg}"',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process2.communicate()

        # ۵. ارسال ویس
        with open(output_ogg, "rb") as voice:
            await context.bot.send_voice(
                chat_id=update.effective_chat.id,
                voice=voice,
                caption=f"🤖 **جواب من:**\n{ai_reply_text}"
            )
        
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=status_msg_id)
        except: pass

    except Exception as e:
        logger.error(f"Voice Chat Error: {e}")
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg_id, text="❌ خطا در پردازش صدا.")
    finally:
        for path in [input_ogg_path, input_mp3_path, output_mp3, output_ogg]:
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """وقتی کاربر فقط یک ویس می‌فرسته"""
    if not update.message or not update.message.voice: return
    status_msg = await update.message.reply_text("🎧 در حال گوش دادن...")
    await _process_voice(update, context, update.message.voice.file_id, status_msg.message_id)

async def cmd_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """وقتی کاربر روی یک ویس ریپلای می‌کنه و می‌نویسه /voice"""
    if not update.message or not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ روی یک ویس ریپلای کنید و دستور /voice را بزنید.")
    replied = update.message.reply_to_message
    if not replied.voice:
        return await update.message.reply_text("⚠️ پیامی که ریپلای کردید، ویس نیست.")
    status_msg = await update.message.reply_text("🎧 در حال گوش دادن...")
    await _process_voice(update, context, replied.voice.file_id, status_msg.message_id)
