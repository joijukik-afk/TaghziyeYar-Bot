"""دستور /tts برای تبدیل متن به ویس واقعی تلگرام"""

import os
import logging
import tempfile
import subprocess
import edge_tts
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "fa-IR-FaridNeural" 

async def cmd_tts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    
    text = ""
    if context.args:
        text = " ".join(context.args).strip()
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text.strip()
    
    if not text:
        return await update.message.reply_text(
            "📝 **راهنما:**\n\n"
            "متن خود را بعد از دستور بنویسید:\n"
            "`/tts سلام چطوری؟`\n\n"
            "یا روی یک پیام ریپلای کنید و `/tts` بزنید.",
            parse_mode="Markdown"
        )
    
    if len(text) > 500:
        return await update.message.reply_text("⚠️ متن شما طولانی است. لطفاً متن را کوتاه‌تر کنید (حداکثر ۵۰۰ کاراکتر).")

    status_msg = await update.message.reply_text("🎙️ در حال تبدیل متن به ویس...")
    
    tmp_mp3 = os.path.join(tempfile.gettempdir(), f"tts_{update.effective_user.id}.mp3")
    tmp_ogg = os.path.join(tempfile.gettempdir(), f"tts_{update.effective_user.id}.ogg")
    
    try:
        # تبدیل متن به صدا
        communicate = edge_tts.Communicate(text, DEFAULT_VOICE)
        await communicate.save(tmp_mp3)
        
        # تبدیل به فرمت OGG برای ویس تلگرام
        subprocess.run(
            ["ffmpeg", "-i", tmp_mp3, "-c:a", "libopus", "-b:a", "64k", "-y", tmp_ogg],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        if not os.path.exists(tmp_ogg):
            raise Exception("خطا در تبدیل فرمت صدا")

        with open(tmp_ogg, "rb") as audio:
            await update.message.reply_voice(
                voice=audio,
                caption=f"🎧 **متن شما:**\n{text[:200]}..." if len(text) > 200 else f"🎧 **متن شما:**\n{text}",
                read_timeout=120
            )
        
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"TTS error: {e}", exc_info=True)
        await status_msg.edit_text("⚠️ متأسفانه در تبدیل متن به صدا خطایی رخ داد.")
        
    finally:
        if os.path.exists(tmp_mp3):
            try: os.remove(tmp_mp3)
            except: pass
        if os.path.exists(tmp_ogg):
            try: os.remove(tmp_ogg)
            except: pass
