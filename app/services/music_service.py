"""موتور جستجوی KOMA (نسخه مستقیم scdl - بدون خطای آرگومان)"""

import os
import random
import hashlib
import logging
import tempfile
import asyncio
import subprocess
from typing import Optional, Dict
from datetime import datetime, timezone
from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

LAST_ERROR = "بدون خطای مشخص"

try:
    from sqlalchemy import select
    from app.database.music_models import MusicTrack
    from app.database.session import session_scope
    DB_ENABLED = True
except Exception as e:
    logger.warning(f"Database disabled: {e}")
    DB_ENABLED = False

MAX_SIZE = 45 * 1024 * 1024
MIN_SIZE = 100 * 1024

SEARCH_QUERIES = [
    "øneheart", "oneheart slowed", "reidenshi", "dreamcore", "dark ambient melancholic",
    "sad ambient", "slowed reverb aesthetic", "my head is empty", "daniel.mp3",
    "sad piano reverb", "غمگین ایرانی", "غمگین slowed", "sad boy lofi", "shoegaze ambient",
    "liminal space ambient", "ethereal wave", "atmospheric wave", "cinematic ambient",
    "space ambient", "emotional ambient", "sleepcore", "dreamwave", "chillwave",
    "slowcore", "downtempo ambient", "ambient lo-fi", "distorted memories",
    "nostalgic ambient", "lonely piano ambient", "melancholic piano",
    "dark piano ambient", "dark cinematic piano", "midnight ambient",
    "احساسی slowed", "آرام slowed", "تنها slowed", "غمگین ریورب",
    "sad girl lofi", "post rock ambient", "dark wave slowed", "comatose ambient",
    "analog mannequin", "coma music", "koma music", "coma vibe", "coma aesthetic",
]

# ==================== دیتابیس ====================
async def _is_used(identifier: str) -> bool:
    if not DB_ENABLED: return False
    try:
        async with session_scope() as session:
            res = await session.execute(
                select(MusicTrack).where(
                    MusicTrack.identifier == identifier,
                    MusicTrack.is_sent == True
                )
            )
            return res.scalar_one_or_none() is not None
    except Exception:
        return False

async def _record_track(data: dict, file_id: str) -> None:
    if not DB_ENABLED: return
    try:
        now_utc = datetime.now(timezone.utc)
        async with session_scope() as session:
            existing = await session.execute(
                select(MusicTrack).where(MusicTrack.identifier == data["identifier"])
            )
            track = existing.scalar_one_or_none()
            if track:
                track.telegram_file_id = file_id
                track.is_sent = True
                track.sent_at = now_utc
            else:
                session.add(MusicTrack(
                    identifier=data["identifier"], title=data["title"], artist=data["artist"],
                    filename=data.get("filename", ""), file_hash=data["hash"],
                    telegram_file_id=file_id, is_sent=True, sent_at=now_utc
                ))
            await session.flush()
    except Exception as e:
        logger.error(f"DB Record Error: {e}")

# ==================== دانلود مستقیم با scdl ====================
def _download_scdl_query(query: str) -> Optional[Dict]:
    """جستجو و دانلود مستقیم با ابزار scdl"""
    global LAST_ERROR
    download_dir = tempfile.mkdtemp(prefix="koma_scdl_")
    
    cmd = [
        "scdl",
        "-s", query,          # جستجو با عبارت
        "-o", download_dir,   # مسیر ذخیره
        "--onlymp3",          # فقط فایل mp3
        "--overwrite"         # بازنویسی در صورت وجود
    ]

    try:
        logger.info(f"Running scdl for query: {query}")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=90
        )
        
        if result.returncode != 0:
            LAST_ERROR = f"خطای scdl: {result.stderr[:150] or result.stdout[:150]}"
            return None

        # پیدا کردن فایل MP3 در مسیر دانلود
        mp3_file = None
        for f in os.listdir(download_dir):
            if f.lower().endswith('.mp3'):
                mp3_file = os.path.join(download_dir, f)
                break

        if not mp3_file or not os.path.exists(mp3_file):
            LAST_ERROR = "فایل MP3 پس از دانلود یافت نشد."
            return None

        size = os.path.getsize(mp3_file)
        if size < MIN_SIZE or size > MAX_SIZE:
            LAST_ERROR = f"حجم فایل غیرمجاز است: {size} بایت."
            os.remove(mp3_file)
            return None

        sha = hashlib.sha256()
        with open(mp3_file, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha.update(chunk)

        base_name = os.path.splitext(os.path.basename(mp3_file))[0]
        title, artist = base_name, "Unknown Artist"
        if " - " in base_name:
            parts = base_name.split(" - ", 1)
            artist, title = parts[0].strip(), parts[1].strip()

        return {
            "path": mp3_file,
            "hash": sha.hexdigest(),
            "size": size,
            "title": title,
            "artist": artist
        }

    except subprocess.TimeoutExpired:
        LAST_ERROR = "زمان اجرای scdl (۹۰ ثانیه) به پایان رسید."
        return None
    except Exception as e:
        LAST_ERROR = f"خطای غیرمنتظره در scdl: {str(e)[:120]}"
        return None

# ==================== ارسال ====================
async def _send_and_record_audio(bot: Bot, chat_id: int, thread_id: int, item: dict, dl: dict) -> bool:
    try:
        send_kwargs = {
            "chat_id": chat_id,
            "title": dl.get('title', item.get('title', 'Unknown'))[:64],
            "performer": dl.get('artist', item.get('artist', 'Unknown Artist'))[:64],
            "caption": f"🎵 <b>{dl.get('title', item.get('title', 'Unknown'))}</b>\n🎤 {dl.get('artist', item.get('artist', 'Unknown Artist'))}\n📦 SoundCloud\n🌌 KOMA | کُما",
            "parse_mode": ParseMode.HTML,
            "read_timeout": 180,
            "write_timeout": 180
        }
        if thread_id:
            send_kwargs["message_thread_id"] = thread_id

        with open(dl["path"], "rb") as audio:
            sent = await bot.send_audio(audio=audio, **send_kwargs)

        await _record_track({
            "identifier": item.get("id", hashlib.md5(dl["path"].encode()).hexdigest()),
            "title": dl.get("title", item.get("title", "Unknown")),
            "artist": dl.get("artist", item.get("artist", "Unknown Artist")),
            "filename": os.path.basename(dl["path"]),
            "hash": dl["hash"],
        }, sent.audio.file_id)

        return True
    except Exception as e:
        global LAST_ERROR
        LAST_ERROR = f"ارسال تلگرام: {str(e)[:100]}"
        logger.error(f"send_audio failed: {e}")
        return False
    finally:
        try:
            os.remove(dl["path"])
        except Exception:
            pass

# ==================== توابع اصلی ====================
async def fetch_and_send_music(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    """دستور /koma - انتخاب یک عبارت تصادفی و دانلود"""
    query = random.choice(SEARCH_QUERIES)
    dl = await asyncio.to_thread(_download_scdl_query, query)
    
    if dl and await _send_and_record_audio(bot, chat_id, thread_id, {"id": hashlib.md5(query.encode()).hexdigest()}, dl):
        return True
    return False

async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str, thread_id: int = None) -> bool:
    """دستور /music - جستجوی دقیق عبارت کاربر"""
    if query.startswith(("http://", "https://")):
        if "soundcloud.com" not in query:
            global LAST_ERROR
            LAST_ERROR = "لینک وارد شده مربوط به ساندکلود نیست."
            return False
        dl = await asyncio.to_thread(_download_scdl_query, query)
        if dl:
            return await _send_and_record_audio(bot, chat_id, thread_id, {"id": hashlib.md5(query.encode()).hexdigest()}, dl)
        return False

    # جستجوی متنی با scdl
    dl = await asyncio.to_thread(_download_scdl_query, query)
    if dl and await _send_and_record_audio(bot, chat_id, thread_id, {"id": hashlib.md5(query.encode()).hexdigest()}, dl):
        return True

    return False
