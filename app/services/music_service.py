"""موتور جستجوی KOMA (ساندکلود + پشتیبانی از جستجوی دستی و لینک)"""

import os
import random
import hashlib
import logging
import tempfile
import asyncio
from typing import Optional, List, Dict

import yt_dlp
from sqlalchemy import select
from telegram import Bot
from telegram.constants import ParseMode

from app.database.music_models import MusicTrack
from app.database.session import session_scope

logger = logging.getLogger(__name__)

SEARCH_QUERIES = [
    "Øneheart slowed reverb", "reidenshi slowed reverb", "dreamcore slowed reverb",
    "dark ambient music", "liminal space music", "sad slowed reverb",
    "my head is empty slowed", "analog_mannequin milk cassette", "melancholic ambient",
    "the last of us ambient guitar", "coma vibe slowed reverb", "ethereal wave slowed reverb",
    "غمگین ایرانی slowed", "snowfall slowed reverb", "distorted memories slowed"
]

MAX_SIZE = 45 * 1024 * 1024
MIN_SIZE = 1024 * 1024


async def _is_used(identifier: str, title: str, artist: str) -> bool:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack).where((MusicTrack.identifier == identifier) & (MusicTrack.is_sent == True))
        )
        if res.scalar_one_or_none() is not None: return True
        if title and artist and artist != "Unknown Artist":
            res2 = await session.execute(
                select(MusicTrack).where(
                    (MusicTrack.title.ilike(f"%{title[:15]}%")) & 
                    (MusicTrack.artist.ilike(f"%{artist[:15]}%")) & (MusicTrack.is_sent == True)
                )
            )
            if res2.scalar_one_or_none() is not None: return True
        return False


async def _record_track(data: dict, file_id: str) -> None:
    from datetime import datetime
    async with session_scope() as session:
        existing = await session.execute(select(MusicTrack).where(MusicTrack.identifier == data["identifier"]))
        track = existing.scalar_one_or_none()
        if track:
            track.telegram_file_id = file_id
            track.is_sent = True
            track.sent_at = datetime.utcnow()
        else:
            session.add(MusicTrack(
                identifier=data["identifier"], title=data["title"], artist=data["artist"],
                filename=data.get("filename", ""), file_hash=data["hash"],
                telegram_file_id=file_id, is_sent=True, sent_at=datetime.utcnow()
            ))
        await session.flush()


def _search_soundcloud(query: str, max_results: int = 8) -> List[Dict]:
    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'noplaylist': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"scsearch{max_results}:{query}", download=False)
            if not info or 'entries' not in info: return []
            results = []
            for e in info.get('entries', []):
                if not e: continue
                url = e.get('url') or e.get('webpage_url')
                if url:
                    results.append({
                        "id": str(e.get('id', '')), "title": e.get('title', 'Unknown'),
                        "artist": e.get('uploader', 'Unknown Artist'), "url": url,
                        "source": "SoundCloud", "duration": e.get('duration', 0),
                    })
            return results
    except Exception as e:
        logger.error(f"SoundCloud search failed: {e}")
        return []

def _search_youtube(query: str, max_results: int = 5) -> List[Dict]:
    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'noplaylist': True, 'extractor_args': {'youtube': {'player_client': ['ios', 'android']}}}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            if not info or 'entries' not in info: return []
            results = []
            for e in info.get('entries', []):
                if not e: continue
                url = e.get('url') or e.get('webpage_url')
                if url:
                    results.append({
                        "id": str(e.get('id', '')), "title": e.get('title', 'Unknown'),
                        "artist": e.get('uploader', 'Unknown Artist'), "url": url,
                        "source": "YouTube"
                    })
            return results
    except Exception as e:
        logger.error(f"YouTube search failed: {e}")
        return []


def _download_audio(url: str, output_template: str) -> Optional[dict]:
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'outtmpl': output_template, 'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'extractor_args': {'youtube': {'player_client': ['ios', 'android', 'mweb']}},
        'match_filter': yt_dlp.utils.match_filter_func("duration > 60 & duration < 1200"),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info: return None
            mp3_path = output_template + '.mp3'
            if os.path.exists(mp3_path):
                size = os.path.getsize(mp3_path)
                if not (MIN_SIZE <= size <= MAX_SIZE):
                    os.remove(mp3_path); return None
                sha = hashlib.sha256()
                with open(mp3_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(8192), b''):
                        sha.update(chunk)
                return {
                    "path": mp3_path, "hash": sha.hexdigest(), "size": size,
                    "title": info.get('title', 'Unknown'), "artist": info.get('uploader', 'Unknown Artist')
                }
    except Exception as e:
        logger.error(f"Download error for {url}: {e}")
    return None


# ==================== تابع جستجوی خودکار (دستور /koma) ====================
async def fetch_and_send_music(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    queries = random.sample(SEARCH_QUERIES, min(3, len(SEARCH_QUERIES)))
    for query in queries:
        logger.info(f"=== Auto Searching: {query} ===")
        results = await asyncio.to_thread(_search_soundcloud, query, 8)
        if not results:
            results = await asyncio.to_thread(_search_youtube, query, 5)
        if not results: continue

        random.shuffle(results)
        for item in results:
            if await _is_used(item["id"], item["title"], item["artist"]): continue
            
            output_template = os.path.join(tempfile.gettempdir(), f"koma_{item['id']}")
            dl = await asyncio.to_thread(_download_audio, item["url"], output_template)
            if not dl: continue

            try:
                with open(dl["path"], "rb") as audio:
                    sent = await bot.send_audio(
                        chat_id=chat_id, audio=audio,
                        title=dl['title'][:64], performer=dl['artist'][:64],
                        caption=f"🎵 <b>{dl['title']}</b>\n🎤 {dl['artist']}\n📦 {item['source']}\n🌌 KOMA | کُما",
                        parse_mode=ParseMode.HTML, read_timeout=120, write_timeout=120, message_thread_id=thread_id
                    )
                await _record_track({
                    "identifier": item["id"], "title": dl["title"], "artist": dl["artist"],
                    "filename": os.path.basename(dl["path"]), "hash": dl["hash"],
                }, sent.audio.file_id)
                try: os.remove(dl["path"])
                except: pass
                return True
            except Exception as e:
                logger.error(f"send_audio failed: {e}")
                try: os.remove(dl["path"])
                except: pass
    return False


# ==================== تابع جستجوی دستی (دستور /music) ====================
async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str, thread_id: int = None) -> bool:
    """
    اگر کاربر لینک بفرستد، مستقیم دانلود میکند.
    اگر اسم بفرستد، در ساندکلود و یوتیوب جستجو میکند.
    """
    item = None
    dl = None

    # ۱. چک کردن اینکه آیا ورودی یک لینک است یا نه
    if query.startswith(("http://", "https://")):
        logger.info(f"Downloading from URL: {query}")
        output_template = os.path.join(tempfile.gettempdir(), f"koma_custom_url")
        dl = await asyncio.to_thread(_download_audio, query, output_template)
        if dl:
            item = {"source": "لینک مستقیم", "id": "custom_url"}
            
    # ۲. اگر لینک نبود، جستجو میکنیم
    else:
        logger.info(f"Searching manually for: {query}")
        # اول ساندکلود
        results = await asyncio.to_thread(_search_soundcloud, query, 5)
        # اگر نبود، یوتیوب
        if not results:
            results = await asyncio.to_thread(_search_youtube, query, 5)
            
        if results:
            item = results[0] # بهترین نتیجه (اولین نتیجه)
            output_template = os.path.join(tempfile.gettempdir(), f"koma_custom_search")
            dl = await asyncio.to_thread(_download_audio, item["url"], output_template)

    if not dl or not item:
        return False

    # ارسال به تلگرام
    try:
        with open(dl["path"], "rb") as audio:
            sent = await bot.send_audio(
                chat_id=chat_id, audio=audio,
                title=dl['title'][:64], performer=dl['artist'][:64],
                caption=f"🎵 <b>{dl['title']}</b>\n🎤 {dl['artist']}\n📦 {item['source']}\n🌌 KOMA | کُما",
                parse_mode=ParseMode.HTML, read_timeout=120, write_timeout=120, message_thread_id=thread_id
            )
        
        # ثبت در دیتابیس (برای اینکه دفعه بعد تو جستجوی اتوماتیک دوباره نیاد)
        await _record_track({
            "identifier": item["id"], "title": dl["title"], "artist": dl["artist"],
            "filename": os.path.basename(dl["path"]), "hash": dl["hash"],
        }, sent.audio.file_id)

        try: os.remove(dl["path"])
        except: pass
        return True
    except Exception as e:
        logger.error(f"send_audio failed: {e}")
        try: os.remove(dl["path"])
        except: pass
        return False
