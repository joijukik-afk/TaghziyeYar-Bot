"""موتور جستجوی KOMA (نسخه حرفه‌ای - دقیق، سریع و مقاوم)"""

import os
import random
import hashlib
import logging
import tempfile
import asyncio
from typing import Optional, List, Dict
from datetime import datetime, timezone
from urllib.parse import quote
import yt_dlp
from telegram import Bot
from telegram.constants import ParseMode
from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

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

# ==================== جستجو و دانلود ====================
def _search_soundcloud(query: str, max_results: int = 10, newest_first: bool = False) -> List[Dict]:
    """
    جستجو در ساندکلود.
    - برای جدیدترین‌ها از ytsearchdate استفاده می‌کند (قابلیت بومی yt-dlp).
    - برای نتایج عادی از scsearch استفاده می‌کند.
    """
    if newest_first:
        search_url = f"ytsearchdate{max_results}:{query} soundcloud"
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'extract_flat': True,
            'noplaylist': True, 'ignoreerrors': True,
        }
    else:
        search_url = f"scsearch{max_results}:{query}"
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'extract_flat': True,
            'noplaylist': True, 'ignoreerrors': True,
            'extractor_args': {'soundcloud': {'formats': ['*_mp3', 'http_aac']}},
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_url, download=False)
            if not info: return []
            
            results = []
            entries = info.get('entries', []) if 'entries' in info else [info]
            for e in entries:
                if not e: continue
                track_url = e.get('url') or e.get('webpage_url')
                if track_url and ('soundcloud.com' in track_url):
                    results.append({
                        "id": str(e.get('id', '')),
                        "title": e.get('title', 'Unknown'),
                        "artist": e.get('uploader', 'Unknown Artist'),
                        "url": track_url,
                        "source": "SoundCloud"
                    })
            return results[:max_results]
    except Exception as e:
        logger.warning(f"Search failed for '{query}': {e}")
        return []

def _download_soundcloud(url: str, output_template: str) -> Optional[dict]:
    """دانلود از ساندکلود با تنظیمات بهینه و کاهش خطای 403"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128'
        }],
        'outtmpl': output_template + '.%(ext)s',
        'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'ignoreerrors': True, 'no_color': True,
        'retries': 2, 'fragment_retries': 2,
        'socket_timeout': 20,
        'extractor_args': {'soundcloud': {'formats': ['*_mp3', 'http_aac']}},
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info: return None

            if 'requested_downloads' in info and info['requested_downloads']:
                mp3_path = info['requested_downloads'][0].get('filepath')
            else:
                mp3_path = output_template + '.mp3'

            if not mp3_path or not os.path.exists(mp3_path):
                return None

            size = os.path.getsize(mp3_path)
            if size < MIN_SIZE or size > MAX_SIZE:
                os.remove(mp3_path)
                return None

            sha = hashlib.sha256()
            with open(mp3_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha.update(chunk)

            return {
                "path": mp3_path, "hash": sha.hexdigest(), "size": size,
                "title": info.get('title', 'Unknown'),
                "artist": info.get('uploader', 'Unknown Artist')
            }
    except Exception as e:
        logger.error(f"Download error for {url}: {e}")
        mp3_check = output_template + '.mp3'
        if os.path.exists(mp3_check): os.remove(mp3_check)
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
        logger.error(f"send_audio failed: {e}")
        return False
    finally:
        try:
            os.remove(dl["path"])
        except Exception:
            pass

# ==================== توابع اصلی ====================
async def fetch_and_send_music(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    """دستور /koma - اول جدیدترین‌های ساندکلود، سپس قدیمی‌ترها"""
    query = random.choice(SEARCH_QUERIES)

    # مرحله 1: جستجوی جدیدترین‌ها
    logger.info(f"Searching NEWEST for: {query}")
    new_candidates = await asyncio.to_thread(_search_soundcloud, query, 5, True)

    attempts = 0
    for item in new_candidates:
        if attempts >= 3: break
        attempts += 1
        output = os.path.join(tempfile.gettempdir(), f"koma_new_{item['id']}")
        dl = await asyncio.to_thread(_download_soundcloud, item["url"], output)
        if dl and await _send_and_record_audio(bot, chat_id, thread_id, item, dl):
            return True

    # مرحله 2: اگر جدیدها ناموفق بودند، سراغ قدیمی‌ترها برو
    logger.info(f"No working NEW tracks. Falling back to OLDER tracks for: {query}")
    old_candidates = await asyncio.to_thread(_search_soundcloud, query, 5, False)

    attempts = 0
    for item in old_candidates:
        if attempts >= 3: break
        attempts += 1
        output = os.path.join(tempfile.gettempdir(), f"koma_old_{item['id']}")
        dl = await asyncio.to_thread(_download_soundcloud, item["url"], output)
        if dl and await _send_and_record_audio(bot, chat_id, thread_id, item, dl):
            return True

    return False

async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str, thread_id: int = None) -> bool:
    """دستور /music - جستجوی دقیق با استفاده از الگوریتم تطابق فازی RapidFuzz"""
    if query.startswith(("http://", "https://")):
        if "soundcloud.com" not in query: return False
        url_hash = hashlib.md5(query.encode()).hexdigest()
        output = os.path.join(tempfile.gettempdir(), f"koma_link_{url_hash}")
        dl = await asyncio.to_thread(_download_soundcloud, query, output)
        if dl:
            return await _send_and_record_audio(bot, chat_id, thread_id, {"id": url_hash}, dl)
        return False

    # جستجوی اولیه در ساندکلود
    logger.info(f"Searching for query: '{query}'")
    results = await asyncio.to_thread(_search_soundcloud, query, 15, False)
    if not results:
        return False

    # رتبه‌بندی نتایج با RapidFuzz برای پیدا کردن دقیق‌ترین تطابق
    choices = [f"{r['title']} {r['artist']}" for r in results]
    best_matches = process.extract(
        query, choices, scorer=fuzz.WRatio, limit=5, score_cutoff=60
    )

    # اگر هیچ نتیجه‌ای امتیاز حداقلی را کسب نکرد، از نتایج عادی استفاده کن
    if not best_matches:
        candidates = results[:5]
    else:
        candidates = [results[idx] for _, _, idx in best_matches]

    # تلاش برای دانلود و ارسال بهترین تطابق‌ها
    attempts = 0
    for c in candidates:
        if attempts >= 3: break
        attempts += 1

        if await _is_used(c["id"]): continue

        output = os.path.join(tempfile.gettempdir(), f"music_{c['id']}")
        dl = await asyncio.to_thread(_download_soundcloud, c["url"], output)
        if dl and await _send_and_record_audio(bot, chat_id, thread_id, c, dl):
            return True

    # اگر همه جدیدها ناموفق بودند، یک بار دیگر از نتایج قدیمی‌تر امتحان کن
    logger.info(f"No new exact match for '{query}'. Retrying with fallback.")
    fallback_results = await asyncio.to_thread(_search_soundcloud, query, 10, True)
    fallback_choices = [f"{r['title']} {r['artist']}" for r in fallback_results]
    fallback_best = process.extract(query, fallback_choices, scorer=fuzz.WRatio, limit=3, score_cutoff=50)
    
    fallback_candidates = [fallback_results[idx] for _, _, idx in fallback_best] if fallback_best else fallback_results[:3]

    for c in fallback_candidates:
        if await _is_used(c["id"]): continue
        output = os.path.join(tempfile.gettempdir(), f"music_fb_{c['id']}")
        dl = await asyncio.to_thread(_download_soundcloud, c["url"], output)
        if dl and await _send_and_record_audio(bot, chat_id, thread_id, c, dl):
            return True

    return False
