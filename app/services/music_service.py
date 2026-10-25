"""موتور جستجوی چندمنبعی KOMA (YouTube + SoundCloud) با رفع خطای پیدا نشدن آهنگ"""

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

# 👇 لیست جستجوها (کمی ساده‌تر و بهینه‌تر شد تا حتماً نتیجه بده)
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
    "غمگین ایرانی slowed"
]

MAX_SIZE = 45 * 1024 * 1024
MIN_SIZE = 1024 * 1024

async def _is_used(identifier: str, title: str, artist: str) -> bool:
    """چک کردن تکراری بودن بر اساس آیدی و اسم"""
    async with session_scope() as session:
        # چک با آیدی
        res = await session.execute(
            select(MusicTrack).where(
                (MusicTrack.identifier == identifier) & (MusicTrack.is_sent == True)
            )
        )
        if res.scalar_one_or_none() is not None:
            return True
            
        # چک با اسم (اگر خواننده ناشناس نبود)
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

def _download_with_ytdlp(url: str, output_template: str) -> Optional[dict]:
    """دانلود از YouTube یا SoundCloud"""
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
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'mweb'], # دور زدن بلاک
            }
        },
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
                    "video_id": info.get('id'),
                }
    except Exception as e:
        logger.error(f"Download error for {url}: {e}")
    return None

def _search_media(query: str, source: str, max_results: int = 5) -> List[Dict]:
    """جستجو در یوتیوب یا ساندکلود"""
    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'noplaylist': True}
    
    if source == "YouTube":
        ydl_opts['extractor_args'] = {'youtube': {'player_client': ['ios', 'android']}}

    search_prefix = "ytsearch" if source == "YouTube" else "scsearch"
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"{search_prefix}{max_results}:{query}", download=False)
            results = []
            for e in info.get('entries', []):
                if not e: continue
                
                # 👇 رفع مشکل لینک: گاهی لینک در webpage_url هست
                url = e.get('url') or e.get('webpage_url')
                
                if url:
                    results.append({
                        "id": e.get('id'),
                        "title": e.get('title', 'Unknown'),
                        "uploader": e.get('uploader', 'Unknown Artist'),
                        "url": url,
                        "source": source,
                    })
            return results
    except Exception as e:
        logger.warning(f"{source} search failed: {e}")
        return []

async def fetch_and_send_music(bot: Bot, chat_id: int) -> bool:
    # انتخاب ۳ کوئری تصادفی برای تست
    queries = random.sample(SEARCH_QUERIES, min(3, len(SEARCH_QUERIES)))
    
    for query in queries:
        logger.info(f"Searching all sources for: {query}")

        # اولویت با یوتیوب هست چون آرشیو کامل‌تری داره
        yt_results = await asyncio.to_thread(_search_media, query, "YouTube", 5)
        sc_results = await asyncio.to_thread(_search_media, query, "SoundCloud", 5)

        candidates = []
        for res_list, source in [(yt_results, "YouTube"), (sc_results, "SoundCloud")]:
            for item in res_list:
                item["source"] = source
                candidates.append(item)

        if not candidates:
            logger.warning(f"No results found for: {query}")
            continue # برو سراغ کوئری بعدی

        random.shuffle(candidates)

        for item in candidates:
            identifier = item["id"]
            title = item["title"]
            artist = item["uploader"]

            if await _is_used(identifier, title, artist):
                continue

            logger.info(f"Attempting to download: {title} from {item['source']}")
            
            url = item.get("url")
            if not url: continue
            
            output_template = os.path.join(tempfile.gettempdir(), f"koma_{identifier}")
            dl = await asyncio.to_thread(_download_with_ytdlp, url, output_template)
            
            if not dl: continue

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
                            f"📦 منبع: {item['source']}\n"
                            f"🌌 KOMA | کُما"
                        ),
                        parse_mode=ParseMode.HTML,
                        read_timeout=120, write_timeout=120, connect_timeout=30,
                    )

                await _record_track({
                    "identifier": identifier,
                    "title": dl["title"],
                    "artist": dl["artist"],
                    "filename": os.path.basename(dl["path"]),
                    "hash": dl["hash"],
                }, sent.audio.file_id)

                try: os.remove(dl["path"])
                except: pass
                return True

            except Exception as e:
                logger.error(f"send_audio failed: {e}")
                try: os.remove(dl["path"])
                except: pass

    return False
