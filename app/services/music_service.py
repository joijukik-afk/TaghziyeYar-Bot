"""موتور جستجوی KOMA (نسخه مبتنی بر soundcloud-downloader - بدون پروکسی)"""

import os
import random
import hashlib
import logging
import tempfile
import asyncio
from typing import Optional, List, Dict
from datetime import datetime, timezone
from telegram import Bot
from telegram.constants import ParseMode

try:
    from soundcloud_downloader import SoundCloudDownloader
except ImportError:
    SoundCloudDownloader = None

from rapidfuzz import fuzz, process

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

# ==================== جستجو و دانلود با SoundCloudDownloader ====================
def _search_scdl(query: str, limit: int = 10) -> List[Dict]:
    """جستجو در ساندکلود با کتابخانه soundcloud-downloader"""
    global LAST_ERROR
    if SoundCloudDownloader is None:
        LAST_ERROR = "کتابخانه soundcloud-downloader نصب نشده است."
        return []

    try:
        downloader = SoundCloudDownloader(output_dir=tempfile.gettempdir())
        urls = downloader.search(query, limit=limit)

        results = []
        for url in urls:
            identifier = url.rstrip('/').split('/')[-1]
            results.append({
                "id": identifier,
                "title": "Unknown Title",
                "artist": "Unknown Artist",
                "url": url,
                "source": "SoundCloud"
            })

        if not results:
            LAST_ERROR = f"هیچ نتیجه‌ای برای «{query}» یافت نشد."
        return results
    except Exception as e:
        LAST_ERROR = f"خطای جستجو (scdl): {str(e)[:120]}"
        logger.error(f"scdl search failed for '{query}': {e}")
        return []

def _download_scdl(url: str) -> Optional[Dict]:
    """دانلود از ساندکلود با کتابخانه soundcloud-downloader"""
    global LAST_ERROR
    if SoundCloudDownloader is None:
        LAST_ERROR = "کتابخانه soundcloud-downloader نصب نشده است."
        return None

    try:
        download_dir = tempfile.mkdtemp(prefix="koma_scdl_")
        downloader = SoundCloudDownloader(output_dir=download_dir)
        result = downloader.download_track(url, overwrite=True)

        if not result:
            LAST_ERROR = "دانلود با scdl نتیجه‌ای برنگرداند."
            return None

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
        title = base_name
        artist = "Unknown Artist"
        if " - " in base_name:
            parts = base_name.split(" - ", 1)
            artist = parts[0].strip()
            title = parts[1].strip()

        return {
            "path": mp3_file,
            "hash": sha.hexdigest(),
            "size": size,
            "title": title,
            "artist": artist
        }
    except Exception as e:
        LAST_ERROR = f"خطای دانلود (scdl): {str(e)[:120]}"
        logger.error(f"scdl download failed for {url}: {e}")
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
            "identifier": item["id"],
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
    query = random.choice(SEARCH_QUERIES)
    candidates = await asyncio.to_thread(_search_scdl, query, 5)

    if not candidates:
        return False

    random.shuffle(candidates)
    attempts = 0
    for item in candidates:
        if attempts >= 3:
            break
        attempts += 1

        if await _is_used(item["id"]):
            continue

        dl = await asyncio.to_thread(_download_scdl, item["url"])
        if dl and await _send_and_record_audio(bot, chat_id, thread_id, item, dl):
            return True

    return False

async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str, thread_id: int = None) -> bool:
    if query.startswith(("http://", "https://")):
        if "soundcloud.com" not in query:
            global LAST_ERROR
            LAST_ERROR = "لینک وارد شده مربوط به ساندکلود نیست."
            return False
        url_hash = hashlib.md5(query.encode()).hexdigest()
        dl = await asyncio.to_thread(_download_scdl, query)
        if dl:
            return await _send_and_record_audio(bot, chat_id, thread_id, {"id": url_hash}, dl)
        return False

    results = await asyncio.to_thread(_search_scdl, query, 10)
    if not results:
        return False

    candidates = results[:3]

    attempts = 0
    for c in candidates:
        if attempts >= 3:
            break
        attempts += 1

        if await _is_used(c["id"]):
            continue

        dl = await asyncio.to_thread(_download_scdl, c["url"])
        if dl and await _send_and_record_audio(bot, chat_id, thread_id, c, dl):
            return True

    return False
