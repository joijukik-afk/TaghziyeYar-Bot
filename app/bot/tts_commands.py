"""Simple TTS Command (Fast with ffmpeg)."""

import os
import logging
import tempfile
import asyncio
import edge_tts
from telegram import Update
from telegram.ext import ContextTypes
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

async def cmd_tts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat: return

    text = ""

    # ۱. متن همراه دستور: /tts سلام خوبی؟
    if context.args:
        text = " ".join(context.args)

    # ۲. ریپلای روی پیام متنی
    elif update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text

    # ۳. ریپلای روی ویس (اول تبدیل به متن، بعد می‌خونه)
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

    if not text:
        return await update.message.reply_text(
            "🔊 **راهنمای دستور TTS**\n\n"
            "📝 **روش ۱ - متن مستقیم:**\n"
            "`/tts سلام خوبی؟`\n\n"
            "📎 **روش ۲ - ریپلای روی متن:**\n"
            "روی یک پیام متنی ریپلای کنید و بزنید `/tts`\n\n"
            "🎙️ **روش ۳ - ریپلای روی ویس:**\n"
            "روی یک پیام صوتی ریپلای کنید و بزنید `/tts`",
            parse_mode="Markdown"
        )

    status_msg = await update.message.reply_text("⏳ در حال ساخت صدا...")

    output_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
    output_ogg = output_mp3.replace(".mp3", ".ogg")

    try:
        # تولید صدا با صدای پیش‌فرض (مرد فارسی)
        communicate = edge_tts.Communicate(text, "fa-IR-FaridNeural")
        await communicate.save(output_mp3)

        # تبدیل سریع به OGG
        process = await asyncio.create_subprocess_shell(
            f'ffmpeg -y -i "{output_mp3}" -c:a libopus -b:a 64k "{output_ogg}"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()

        with open(output_ogg, "rb") as voice:
            await update.message.reply_voice(
                voice=voice,
                caption=f"🔊 {text[:100]}..."
            )

        await status_msg.delete()

    except Exception as e:
        logger.error(f"TTS Error: {e}")
        await status_msg.edit_text("❌ خطا در تولید صدا.")
    finally:
        for path in [output_mp3, output_ogg]:
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass
