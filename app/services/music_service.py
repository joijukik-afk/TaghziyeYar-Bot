"""سرویس دریافت آهنگ از یوتیوب با yt-dlp (مقاوم‌سازی شده در برابر مسدودسازی)"""

import os
import random
import hashlib
import logging
import tempfile
import asyncio
from typing import Optional

import yt_dlp
from sqlalchemy import select
from telegram import Bot
from telegram.constants import ParseMode

from app.database.music_models import MusicTrack
from app.database.session import session_scope

logger = logging.getLogger(__name__)

# سبک‌های دقیق مد نظر شما
YOUTUBE_QUERIES = [
    "Øneheart snowfall slowed reverb",
    "dreamcore playlist slowed reverb",
    "dark ambient music mix",
    "the last of us ambient guitar",
    "liminal space music",
    "ethereal ambient mix",
    "sad ambient music",
    "slowed + reverb playlist",
    "weirdcore playlist",
    "melancholic ambient",
    "post apocalyptic ambient",
    "acoustic ambient guitar",
]

MAX_SIZE = 45 * 1024 * 1024
MIN_SIZE = 1024 * 1024

# مسیر فایل کوکی (اگر وجود داشته باشد)
COOKIE_FILE = os.getenv("YTDLP_COOKIE_FILE", "cookies.txt")

async def _is_used(video_id: str) -> bool:
    """چک کن این آهنگ قبلاً ارسال شده یا نه"""
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack).where(
                (MusicTrack.identifier == video_id) & (MusicTrack.is_sent == True)
            )
        )
        return res.scalar_one_or_none() is not None

def _download_youtube_audio(url: str, output_template: str) -> Optional[dict]:
    """دانلود فایل صوتی از یوتیوب با تنظیمات ضد مسدودسازی"""
    
    # تنظیمات پایه برای دانلود
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
        # 👇 کلاینت‌های جایگزین برای دور زدن مسدودسازی
        'extractor_args': {
            'youtube': {
                'player_client': ['tv', 'mweb'],
            }
        },
    }
    
    # اگر فایل کوکی وجود داشت، از آن استفاده کن (مهم‌ترین راه‌حل)
    if os.path.exists(COOKIE_FILE):
        ydl_opts['cookiefile'] = COOKIE_FILE
        logger.info(f"Using cookie file: {COOKIE_FILE}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
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
        logger.error(f"yt-dlp download error for {url}: {e}")
    return None

async def _record_track(data: dict, file_id: str) -> None:
    """ثبت آهنگ در دیتابیس"""
    from datetime import datetime
    async with session_scope() as session:
        existing = await session.execute(
            select(MusicTrack).where(MusicTrack.identifier == data["video_id"])
        )
        track = existing.scalar_one_or_none()
        if track:
            track.telegram_file_id = file_id
            track.is_sent = True
            track.sent_at = datetime.utcnow()
        else:
            session.add(MusicTrack(
                identifier=data["video_id"],
                title=data["title"],
                artist=data["artist"],
                filename=f"{data['video_id']}.mp3",
                file_hash=data["hash"],
                telegram_file_id=file_id,
                is_sent=True,
                sent_at=datetime.utcnow()
            ))
        await session.flush()

async def fetch_and_send_music(bot: Bot, chat_id: int, status_msg) -> bool:
    query = random.choice(YOUTUBE_QUERIES)
    logger.info(f"Searching YouTube for: {query}")
    
    # جستجو در یوتیوب
    ydl_opts_search = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
    try:
        def _search():
            with yt_dlp.YoutubeDL(ydl_opts_search) as ydl:
                return ydl.extract_info(f"ytsearch5:{query}", download=False).get('entries', [])
        
        entries = await asyncio.to_thread(_search)
    except Exception as e:
        logger.error(f"YouTube search error: {e}")
        return False
    
    if not entries: return False
    
    # تلاش برای دانلود نتایج
    for entry in entries:
        video_id = entry.get('id')
        if not video_id or await _is_used(video_id): continue
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        logger.info(f"Attempting to download: {entry.get('title')}")
        
        tmp_dir = tempfile.gettempdir()
        output_template = os.path.join(tmp_dir, f"koma_{video_id}")
        
        download_result = await asyncio.to_thread(_download_youtube_audio, url, output_template)
        
        if not download_result:
            continue
            
        try:
            with open(download_result['path'], 'rb') as audio:
                sent = await bot.send_audio(
                    chat_id=chat_id,
                    audio=audio,
                    title=download_result['title'][:64],
                    performer=download_result['artist'][:64],
                    caption=(
                        f"🎵 <b>{download_result['title']}</b>\n"
                        f"🎤 {download_result['artist']}\n"
                        f"🌌 KOMA | کُما"
                    ),
                    parse_mode=ParseMode.HTML,
                    read_timeout=120, write_timeout=120, connect_timeout=30,
                )
            
            await _record_track(download_result, sent.audio.file_id)
            
            try: os.remove(download_result['path'])
            except: pass
            return True
            
        except Exception as e:
            logger.error(f"send_audio failed: {e}")
            try: os.remove(download_result['path'])
            except: pass
            
    return False
