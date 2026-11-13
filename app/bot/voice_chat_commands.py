"""Voice chat handler: Responds to /voice, auto-replies, and smart voice requests."""

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
    """پاکسازی متن از ایموجی‌ها و کاراکترهای عجیب برای تلفظ دقیق"""
    text = re.sub(r'<[^>]+>', '', text)
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F" u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF" u"\U0001F1E0-\U0001F1FF" "]+", flags=re.UNICODE)
    text = emoji_pattern.sub(r'', text)
    text = text.replace("*", "").replace("#", "").replace("_", "").replace("~", "").replace("`", "")
    return text.strip()

async def generate_and_send_voice(bot, chat_id: int, text: str, voice_type: str = "male"):
    """تبدیل متن به صدا و ارسال (با نمایش خطا در صورت بروز مشکل)"""
    voice_id = "fa-IR-FaridNeural" if voice_type == "male" else "fa-IR-DilaraNeural"
    
    output_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
    output_ogg = output_mp3.replace(".mp3", ".ogg")

    try:
        clean_text = clean_text_for_tts(text)
        if not clean_text:
            await bot.send_message(chat_id=chat_id, text="⚠️ متنی برای خواندن پیدا نشد.")
            return 

        # ۱. ساخت فایل صوتی
        communicate = edge_tts.Communicate(clean_text, voice_id)
        await communicate.save(output_mp3)

        # ۲. تبدیل به ویس تلگرام (با ffmpeg)
        process = await asyncio.create_subprocess_shell(
            f'ffmpeg -y -i "{output_mp3}" -c:a libopus -b:a 64k "{output_ogg}"',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode('utf-8')[-200:]
            raise Exception(f"FFmpeg Error: {error_msg}")

        # ۳. ارسال
        with open(output_ogg, "rb") as voice:
            await bot.send_voice(chat_id=chat_id, voice=voice)
            
    except Exception as e:
        logger.error(f"Voice Generation Error: {e}")
        # 👇 اگر خطایی داد، به کاربر نشون میده
        await bot.send_message(chat_id=chat_id, text=f"❌ خطا در ساخت ویس:\n<code>{str(e)[:300]}</code>", parse_mode="HTML")
    finally:
        for path in [output_mp3, output_ogg]:
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass


async def _process_voice_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, voice_file_id: str, status_msg_id: int):
    """هسته پردازش صدا برای /voice و ویس خودکار"""
    input_ogg = input_mp3 = None
    try:
        # ۱. دانلود و تبدیل
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

        # ۲. تبدیل صدا به متن
        ai_service = get_ai_service()
        user_text = await ai_service.transcribe_audio(input_mp3)

        if not user_text:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg_id, text="❌ صدای شما شنیده نشد.")
            return

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id, message_id=status_msg_id, 
            text=f"🗣️ **شما گفتید:**\n{user_text}\n\n🧠 در حال فکر کردن..."
        )

        # 👇 ۳. گرفتن اسم کاربر و حافظه مشترک
        user = update.effective_user
        user_name = user.first_name if user else "کاربر"
        user_id = user.id if user else 0
        chat_history = context.user_data.get("chat_history", [])

        # ۴. هوش مصنوعی جواب رو می‌سازه (با پاس دادن اسم و حافظه)
        ai_reply_tuple = await ai_service.ask(
            user_message=user_text,
            user_name=user_name,
            user_id=user_id,
            custom_system_prompt=VOICE_SYSTEM_PROMPT,
            chat_history=chat_history # 👈 حافظه پاس داده میشه
        )
        ai_reply_text = ai_reply_tuple[0] if isinstance(ai_reply_tuple, tuple) else str(ai_reply_tuple)

        # 👇 ۵. ذخیره در حافظه مشترک
        chat_history.append({"role": "user", "content": user_text})
        chat_history.append({"role": "assistant", "content": ai_reply_text})
        if len(chat_history) > 10:
            chat_history = chat_history[-10:]
        context.user_data["chat_history"] = chat_history

        # ۶. ساخت ویس و ارسال
        await generate_and_send_voice(context.bot, update.effective_chat.id, ai_reply_text, "male")
        
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=status_msg_id)
        except: pass

    except Exception as e:
        logger.error(f"Voice Chat Error: {e}")
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg_id, text=f"❌ خطا در پردازش صدا:\n{str(e)[:200]}")
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
