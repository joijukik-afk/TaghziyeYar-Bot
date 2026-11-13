"""Voice chat handler: Responds to /voice and auto-replies to voice messages."""

import os
import logging
import tempfile
import asyncio
import re
import edge_tts
from telegram import Update
from telegram.ext import ContextTypes
from app.services.ai_service import get_ai_service, VOICE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

def clean_text_for_tts(text: str) -> str:
    text = re.sub(r'<[^>]+>', '', text)
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F" u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF" u"\U0001F1E0-\U0001F1FF" "]+", flags=re.UNICODE)
    text = emoji_pattern.sub(r'', text)
    text = text.replace("*", "").replace("#", "").replace("_", "").replace("~", "")
    return text.strip()

async def generate_and_send_voice(bot, chat_id: int, text: str, voice_type: str = "male"):
    voice_id = "fa-IR-FaridNeural" if voice_type == "male" else "fa-IR-DilaraNeural"
    
    output_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
    output_ogg = output_mp3.replace(".mp3", ".ogg")

    try:
        clean_text = clean_text_for_tts(text)
        if not clean_text: return 

        communicate = edge_tts.Communicate(clean_text, voice_id)
        await communicate.save(output_mp3)

        process = await asyncio.create_subprocess_shell(
            f'ffmpeg -y -i "{output_mp3}" -c:a libopus -b:a 64k "{output_ogg}"',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()

        with open(output_ogg, "rb") as voice:
            await bot.send_voice(chat_id=chat_id, voice=voice)
    except Exception as e:
        logger.error(f"Voice Generation Error: {e}")
    finally:
        for path in [output_mp3, output_ogg]:
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass


async def _process_voice_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, voice_file_id: str, status_msg_id: int):
    input_ogg = input_mp3 = None
    try:
        voice_file = await context.bot.get_file(voice_file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp_file:
            await voice_file.download_to_drive(tmp_file.name)
            input_ogg = tmp_file.name

        input_mp3 = input_ogg.replace(".ogg", ".mp3")
        process = await asyncio.create_subprocess_shell(
            f'ffmpeg -y -i "{input_ogg}" "{input_mp3}"',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()

        ai_service = get_ai_service()
        user_text = await ai_service.transcribe_audio(input_mp3)

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

        await generate_and_send_voice(context.bot, update.effective_chat.id, ai_reply_text, "male")
        
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=status_msg_id)
        except: pass

    except Exception as e:
        logger.error(f"Voice Chat Error: {e}")
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg_id, text="❌ خطا در پردازش صدا.")
    finally:
        for path in [input_ogg, input_mp3]:
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass

async def cmd_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ روی یک پیام صوتی (ویس) ریپلای کنید و دستور /voice را بزنید.")
    replied = update.message.reply_to_message
    if not replied.voice:
        return await update.message.reply_text("⚠️ پیامی که روی آن ریپلای کردید، یک فایل صوتی نیست.")
    status_msg = await update.message.reply_text("🎧 در حال گوش دادن به ویس...")
    await _process_voice_and_reply(update, context, replied.voice.file_id, status_msg.message_id)

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.voice: return
    status_msg = await update.message.reply_text("🎧 در حال گوش دادن...")
    await _process_voice_and_reply(update, context, update.message.voice.file_id, status_msg.message_id)
