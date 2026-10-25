"""موتور جستجوی KOMA - فقط SoundCloud (بدون محدودیت)"""

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

# 👇 لیست سبک‌هایی که خودت میخوای
SEARCH_QUERIES = [
    "Øneheart slowed reverb",
    "reidenshi slowed reverb",
    "dreamcore slowed reverb",
    "dark ambient music",
    "liminal space music",
    "sad slowed reverb",
    "my head is empty slowed",
    "analog_mannequin milk cassette",
    "melancholic ambient",
    "the last of us ambient guitar",
    "coma vibe slowed reverb",
    "ethereal wave slowed reverb",
    "غمگین ایرانی slowed",
    "snowfall slowed reverb",
    "distorted memories slowed"
]

MAX_SIZE = 45 * 1024 * 1024
MIN_SIZE = 1024 * 1024


async def _is_used(identifier: str, title: str, artist: str) -> bool:
    """چک کردن تکراری بودن"""
    async with session_scope() as session:
        # چک با آیدی
        res = await session.execute(
            select(MusicTrack).where(
                (MusicTrack.identifier == identifier) & (MusicTrack.is_sent == True)
            )
        )
        if res.scalar_one_or_none() is not None:
            return True
            
        # چک با اسم و خواننده (برای جلوگیری از ارسال تکراری)
        if title and artist and artist != "Unknown Artist":
            res2 = await session.execute(
                select(MusicTrack).where(
                    (MusicTrack.title.ilike(f"%{title[:15]}%")) & 
                    (MusicTrack.artist.ilike(f"%{artist[:15]}%")) &
                    (MusicTrack.is_sent == True)
                )
            )
            if res2.scalar_one_or_none() is not None:
                return True
        return False


async def _record_track(data: dict, file_id: str) -> None:
    from datetime import datetime
    async with session_scope() as session:
        existing = await session.execute(
            select(MusicTrack).where(MusicTrack.identifier == data["identifier"])
        )
        track = existing.scalar_one_or_none()
        if track:
            track.telegram_file_id = file_id
            track.is_sent = True
            track.sent_at = datetime.utcnow()
        else:
            session.add(MusicTrack(
                identifier=data["identifier"],
                title=data["title"],
                artist=data["artist"],
                filename=data.get("filename", ""),
                file_hash=data["hash"],
                telegram_file_id=file_id,
                is_sent=True,
                sent_at=datetime.utcnow()
            ))
        await session.flush()


def _search_soundcloud(query: str, max_results: int = 8) -> List[Dict]:
    """جستجو در ساندکلود"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'noplaylist': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"scsearch{max_results}:{query}", download=False)
            
            if not info or 'entries' not in info:
                logger.warning(f"SoundCloud search returned empty for: {query}")
                return []
                
            results = []
            for e in info.get('entries', []):
                if not e: 
                    continue
                
                url = e.get('url') or e.get('webpage_url')
                if not url:
                    continue
                    
                results.append({
                    "id": str(e.get('id', '')),
                    "title": e.get('title', 'Unknown'),
                    "artist": e.get('uploader', 'Unknown Artist'),
                    "url": url,
                    "source": "SoundCloud",
                    "duration": e.get('duration', 0),
                })
            
            logger.info(f"SoundCloud: {len(results)} results for '{query}'")
            return results
            
    except Exception as e:
        logger.error(f"SoundCloud search failed for '{query}': {e}")
        return []


def _download_from_soundcloud(url: str, output_template: str) -> Optional[dict]:
    """دانلود از ساندکلود با تنظیمات بهینه"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        # فیلتر زمان: آهنگ‌های بین 1 تا 20 دقیقه
        'match_filter': yt_dlp.utils.match_filter_func("duration > 60 & duration < 1200"),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info: 
                return None
                
            mp3_path = output_template + '.mp3'
            if os.path.exists(mp3_path):
                size = os.path.getsize(mp3_path)
                if not (MIN_SIZE <= size <= MAX_SIZE):
                    os.remove(mp3_path)
                    return None
                    
                sha = hashlib.sha256()
                with open(mp3_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(8192), b''):
                        sha.update(chunk)
                        
                return {
                    "path": mp3_path,
                    "hash": sha.hexdigest(),
                    "size": size,
                    "title": info.get('title', 'Unknown'),
                    "artist": info.get('uploader', 'Unknown Artist'),
                }
    except Exception as e:
        logger.error(f"SoundCloud download error for {url}: {e}")
    return None


async def fetch_and_send_music(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    """
    تابع اصلی: جستجو در ساندکلود، دانلود و ارسال
    بدون محدودیت، از هر 3 کوئری تصادفی استفاده می‌کنه
    """
    
    # انتخاب 3 کوئری تصادفی برای شانس بیشتر
    queries = random.sample(SEARCH_QUERIES, min(3, len(SEARCH_QUERIES)))
    
    for query in queries:
        logger.info(f"=== Searching SoundCloud for: {query} ===")
        
        # جستجو در ساندکلود
        results = await asyncio.to_thread(_search_soundcloud, query, 8)
        
        if not results:
            logger.info(f"No results for '{query}', trying next query...")
            continue
        
        # به هم ریختن نتایج
        random.shuffle(results)
        
        for item in results:
            identifier = item["id"]
            title = item["title"]
            artist = item["artist"]
            
            # چک تکراری
            if await _is_used(identifier, title, artist):
                logger.info(f"Already sent: {title}, skipping...")
                continue
            
            logger.info(f"Downloading: {title} from SoundCloud")
            
            output_template = os.path.join(tempfile.gettempdir(), f"koma_{identifier}")
            dl = await asyncio.to_thread(_download_from_soundcloud, item["url"], output_template)
            
            if not dl:
                logger.warning(f"Download failed for: {title}")
                continue
            
            # ارسال به تلگرام
            try:
                with open(dl["path"], "rb") as audio:
                    sent = await bot.send_audio(
                        chat_id=chat_id,
                        audio=audio,
                        title=dl['title'][:64],
                        performer=dl['artist'][:64],
                        caption=(
                            f"🎵 <b>{dl['title']}</b>\n"
                            f"🎤 {dl['artist']}\n"
                            f"📦 SoundCloud\n"
                            f"🌌 KOMA | کُما"
                        ),
                        parse_mode=ParseMode.HTML,
                        read_timeout=120, write_timeout=120, connect_timeout=30,
                        message_thread_id=thread_id
                    )
                
                # ثبت در دیتابیس
                await _record_track({
                    "identifier": identifier,
                    "title": dl["title"],
                    "artist": dl["artist"],
                    "filename": os.path.basename(dl["path"]),
                    "hash": dl["hash"],
                }, sent.audio.file_id)
                
                # پاک کردن فایل موقت
                try: os.remove(dl["path"])
                except: pass
                
                return True
                
            except Exception as e:
                logger.error(f"send_audio failed: {e}")
                try: os.remove(dl["path"])
                except: pass
                continue
    
    logger.warning("All queries and downloads failed. No music found.")
    return False
