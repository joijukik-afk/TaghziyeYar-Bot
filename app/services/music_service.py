"""سرویس دریافت آهنگ از چندین منبع (YouTube, SoundCloud, Bandcamp) با yt-dlp"""

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

# 👇 کوئری‌های دقیق برای سبک‌های KOMA
SEARCH_QUERIES = [
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

# منابع جستجو و پیشوندهای مربوطه در yt-dlp
# ytsearch = YouTube, scsearch = SoundCloud, bcsearch = Bandcamp
SOURCES = [
    ("ytsearch", "YouTube"),
    ("scsearch", "SoundCloud"),
    ("bcsearch", "Bandcamp"),
]

MAX_SIZE = 45 * 1024 * 1024
MIN_SIZE = 1024 * 1024
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

def _extract_search_results(query: str, source_prefix: str, max_results: int = 3) -> List[Dict]:
    """جستجو در یک منبع خاص با yt-dlp و برگرداندن متادیتا (بدون دانلود)"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True, # فقط متادیتا، بدون دانلود
    }
    
    if os.path.exists(COOKIE_FILE):
        ydl_opts['cookiefile'] = COOKIE_FILE

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_query = f"{source_prefix}{max_results}:{query}"
            info = ydl.extract_info(search_query, download=False)
            entries = info.get('entries', [])
            
            results = []
            for entry in entries:
                if entry:
                    results.append({
                        "id": entry.get('id'),
                        "title": entry.get('title', 'Unknown'),
                        "uploader": entry.get('uploader', 'Unknown Artist'),
                        "url": entry.get('url') or entry.get('webpage_url'),
                        "source": source_prefix,
                        "extractor": entry.get('extractor_key', source_prefix),
                    })
            return results
    except Exception as e:
        logger.warning(f"Search failed for {source_prefix} with query '{query}': {e}")
        return []

def _download_audio(url: str, output_template: str) -> Optional[dict]:
    """دانلود فایل صوتی از URL داده شده (با تنظیمات ضد مسدودسازی)"""
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
                'player_client': ['tv', 'mweb'],
            }
        },
    }
    
    if os.path.exists(COOKIE_FILE):
        ydl_opts['cookiefile'] = COOKIE_FILE

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
                    "source": info.get('extractor_key', 'unknown'),
                }
    except Exception as e:
        logger.error(f"Download error for {url}: {e}")
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
    """تابع اصلی: جستجوی چندمنبعی، دانلود و ارسال آهنگ"""
    
    # ۱. انتخاب یک کوئری تصادفی
    query = random.choice(SEARCH_QUERIES)
    logger.info(f"Searching for: {query}")
    
    # ۲. جستجو در همه منابع به صورت موازی (با asyncio.gather)
    search_tasks = []
    for prefix, _ in SOURCES:
        task = asyncio.to_thread(_extract_search_results, query, prefix, 3)
        search_tasks.append(task)
    
    all_results = await asyncio.gather(*search_tasks)
    
    # ۳. ترکیب و فیلتر نتایج
    candidates = []
    for result_list in all_results:
        for item in result_list:
            if item and item.get('id'):
                candidates.append(item)
    
    if not candidates:
        logger.warning(f"No results found across all sources for: {query}")
        return False
    
    # ۴. اولویت‌بندی: جدیدترین‌ها (بر اساس اطلاعات موجود) و سپس تصادفی
    # (چون استخراج تاریخ انتشار دقیق از همه منابع ممکن نیست، اینجا یک فیلتر کلی داریم)
    # می‌توانید منطق مرتب‌سازی را در آینده دقیق‌تر کنید.
    random.shuffle(candidates)
    
    # ۵. تلاش برای دانلود و ارسال
    for item in candidates:
        video_id = item['id']
        
        # چک کردن تکراری بودن
        if await _is_used(video_id):
            continue
        
        url = item['url']
        if not url:
            continue
            
        logger.info(f"Attempting to download: {item['title']} from {item['source']}")
        
        tmp_dir = tempfile.gettempdir()
        output_template = os.path.join(tmp_dir, f"koma_{video_id}")
        
        # دانلود در Thread جداگانه
        download_result = await asyncio.to_thread(_download_audio, url, output_template)
        
        if not download_result:
            continue
            
        # ارسال به تلگرام
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
                        f"📦 منبع: {download_result['source']}\n"
                        f"🌌 KOMA | کُما"
                    ),
                    parse_mode=ParseMode.HTML,
                    read_timeout=120, write_timeout=120, connect_timeout=30,
                )
            
            await _record_track(download_result, sent.audio.file_id)
            
            # پاکسازی فایل موقت
            try: os.remove(download_result['path'])
            except: pass
            return True
            
        except Exception as e:
            logger.error(f"send_audio failed: {e}")
            try: os.remove(download_result['path'])
            except: pass
            
    return False
