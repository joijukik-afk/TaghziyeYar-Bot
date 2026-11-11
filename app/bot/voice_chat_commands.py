"""Voice chat handler: Voice -> Text -> AI -> Voice."""

import os
import logging
import tempfile
import edge_tts
from pydub import AudioSegment
from telegram import Update
from telegram.ext import ContextTypes
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

VOICE_SYSTEM_PROMPT = (
    "تو یک دستیار صوتی فوق‌العاده باهوش، صمیمی و احساساتی هستی. "
    "کاربر با تو حرف می‌زند و تو باید با لحنی طبیعی، دوستانه و پر از احساس پاسخ دهی. "
    "پاسخ‌های تو باید کوتاه و مفید باشند (حداکثر ۳ تا ۴ جمله) چون قرار است به صدا تبدیل شوند. "
    "از ایموجی‌ها و علامت‌های نگارشی عجیب استفاده نکن. "
    "اگر کاربر ناراحت بود دلداری بده، اگر شوخی کرد بخند، و اگر سوال علمی پرسید دقیق جواب بده. "
    "پاسخ‌ها باید حتماً به زبان فارسی روان باشد."
)

async def _process_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, voice_file_id: str, status_msg_id: int):
    input_ogg_path = input_mp3_path = output_mp3_path = output_ogg_path = None
    try:
        voice_file = await context.bot.get_file(voice_file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp_file:
            await voice_file.download_to_drive(tmp_file.name)
            input_ogg_path = tmp_file.name

        input_mp3_path = input_ogg_path.replace(".ogg", ".mp3")
        audio = AudioSegment.from_ogg(input_ogg_path)
        audio.export(input_mp3_path, format="mp3")

        ai_service = get_ai_service()
        user_text = await ai_service.transcribe_audio(input_mp3_path)

        if not user_text:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg_id, text="❌ صدای شما شنیده نشد.")
            return

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id, message_id=status_msg_id, 
            text=f"🗣️ **شما گفتید:**\n{user_text}\n\n🧠 در حال فکر کردن..."
        )

        ai_reply_tuple = await ai_service.ask(
            user_message=user_text,
            user_name=update.effective_user.first_name if update.effective_user else "کاربر",
            user_id=update.effective_user.id if update.effective_user else 0,
            custom_system_prompt=VOICE_SYSTEM_PROMPT
        )
        ai_reply_text = ai_reply_tuple[0] if isinstance(ai_reply_tuple, tuple) else str(ai_reply_tuple)

        output_mp3_path = input_mp3_path.replace(".mp3", "_reply.mp3")
        output_ogg_path = output_mp3_path.replace(".mp3", ".ogg")

        communicate = edge_tts.Communicate(ai_reply_text, "fa-IR-FaridNeural", rate="+10%")
        await communicate.save(output_mp3_path)

        reply_audio = AudioSegment.from_mp3(output_mp3_path)
        reply_audio.export(output_ogg_path, format="ogg", codec="libopus")

        with open(output_ogg_path, "rb") as voice_to_send:
            await context.bot.send_voice(
                chat_id=update.effective_chat.id,
                voice=voice_to_send,
                caption=f"🤖 **پاسخ دستیار:**\n{ai_reply_text}"
            )
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=status_msg_id)

    except Exception as e:
        logger.error(f"Voice Chat Error: {e}")
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg_id, text="❌ خطا در پردازش صدا.")
    finally:
        for path in [input_ogg_path, input_mp3_path, output_mp3_path, output_ogg_path]:
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.voice: return
    status_msg = await update.message.reply_text("🎧 در حال گوش دادن...")
    await _process_voice(update, context, update.message.voice.file_id, status_msg.message_id)

async def cmd_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ روی یک ویس ریپلای کنید و دستور /voice را بزنید.")
    replied = update.message.reply_to_message
    if not replied.voice:
        return await update.message.reply_text("⚠️ پیامی که ریپلای کردید، ویس نیست.")
    status_msg = await update.message.reply_text("🎧 در حال گوش دادن...")
    await _process_voice(update, context, replied.voice.file_id, status_msg.message_id)
