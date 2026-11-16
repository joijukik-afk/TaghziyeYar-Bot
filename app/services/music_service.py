"""موتور جستجوی KOMA (فقط ساندکلود - بدون آرشیو و کاملاً جدید)"""

import os
import random
import hashlib
import logging
import tempfile
import asyncio
from typing import Optional, List, Dict
from datetime import datetime, timezone
import yt_dlp
from sqlalchemy import select
from telegram import Bot
from telegram.constants import ParseMode

from app.database.music_models import MusicTrack
from app.database.session import session_scope

logger = logging.getLogger(__name__)

MAX_SIZE = 45 * 1024 * 1024 
MIN_SIZE = 100 * 1024

# کلمات کلیدی بسیار گسترده برای پیدا کردن بهترین آهنگ‌های سبک KOMA
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
    """بررسی می‌کند که آیا این آهنگ قبلاً ارسال شده است یا خیر (جلوگیری از تکرار)"""
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack).where(
                MusicTrack.identifier == identifier, 
                MusicTrack.is_sent == True
            )
        )
        return res.scalar_one_or_none() is not None

async def _record_track(data: dict, file_id: str) -> None:
    """ثبت آهنگ در دیتابیس"""
    now_utc = datetime.now(timezone.utc)
    async with session_scope() as session:
        existing = await session.execute(select(MusicTrack).where(MusicTrack.identifier == data["identifier"]))
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

# ==================== جستجو و دانلود ====================
def _search_soundcloud(query: str, max_results: int = 10) -> List[Dict]:
    """جستجو در ساندکلود"""
    ydl_opts = {
        'quiet': True, 
        'no_warnings': True, 
        'extract_flat': True,
        'noplaylist': True, 
        'ignoreerrors': True,
        'extractor_args': {'soundcloud': {'formats': ['http_mp3_128', 'http_mp3_original']}}
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"scsearch{max_results}:{query}", download=False)
            if not info: return []
            results = []
            for e in info.get('entries', []):
                if not e: continue
                url = e.get('url') or e.get('webpage_url')
                if url:
                    results.append({
                        "id": str(e.get('id', '')), 
                        "title": e.get('title', 'Unknown'),
                        "artist": e.get('uploader', 'Unknown Artist'), 
                        "url": url,
                        "source": "SoundCloud"
                    })
            return results
    except Exception as e:
        logger.warning(f"SC search failed for '{query}': {e}")
        return []

def _download_soundcloud(url: str, output_template: str) -> Optional[dict]:
    """دانلود از ساندکلود"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128'
        }],
        'outtmpl': output_template + '.%(ext)s',
        'quiet': True, 
        'no_warnings': True, 
        'noplaylist': True,
        'ignoreerrors': True, 
        'no_color': True,
        'retries': 3,
        'fragment_retries': 3,
        'socket_timeout': 30,
        'sleep_interval': 1, # تاخیر خیلی کم چون قرار نیست از یوتیوب دانلود کنیم
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
        with open(dl["path"], "rb") as audio:
            sent = await bot.send_audio(
                chat_id=chat_id, audio=audio,
                title=dl.get('title', item.get('title', 'Unknown'))[:64],
                performer=dl.get('artist', item.get('artist', 'Unknown Artist'))[:64],
                caption=f"🎵 <b>{dl.get('title', item.get('title', 'Unknown'))}</b>\n🎤 {dl.get('artist', item.get('artist', 'Unknown Artist'))}\n📦 SoundCloud\n🌌 KOMA | کُما",
                parse_mode=ParseMode.HTML, read_timeout=180, write_timeout=180, 
                message_thread_id=thread_id
            )
        
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
        try: os.remove(dl["path"])
        except Exception: pass

async def fetch_and_send_music(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    """برای دستور /koma (بدون آرشیو، فقط آهنگ جدید و با تلاش بالا)"""
    # انتخاب ۵ کوئری تصادفی برای شانس بیشتر پیدا کردن آهنگ جدید
    queries = random.sample(SEARCH_QUERIES, min(5, len(SEARCH_QUERIES)))
    all_candidates = []
    
    for query in queries:
        results = await asyncio.to_thread(_search_soundcloud, query, 10)
        all_candidates.extend(results)
    
    if not all_candidates:
        logger.warning("No candidates found from SoundCloud.")
        return False # دیگر به آرشیو برنمی‌گردد
    
    random.shuffle(all_candidates)
    attempts = 0
    
    # تلاش حداکثر 15 باره برای پیدا کردن یک آهنگ جدید
    for item in all_candidates:
        if attempts >= min(15, len(all_candidates)): break
        attempts += 1
        
        # چک کردن اینکه قبلا فرستاده نشده باشه
        if await _is_used(item["id"]): continue
        
        output_template = os.path.join(tempfile.gettempdir(), f"koma_sc_{item['id']}")
        dl = await asyncio.to_thread(_download_soundcloud, item["url"], output_template)
        
        if not dl: continue
        
        if await _send_and_record_audio(bot, chat_id, thread_id, item, dl):
            return True
            
    logger.warning("Tried 15 times but couldn't find a NEW song. No archive fallback.")
    return False # هیچ آهنگی پیدا نشد


async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str, thread_id: int = None) -> bool:
    """برای دستور /music (جستجوی دقیق)"""
    item, dl = None, None

    if query.startswith(("http://", "https://")):
        if "soundcloud.com" not in query: return False
            
        url_hash = hashlib.md5(query.encode()).hexdigest()
        if await _is_used(url_hash): return False
            
        output_template = os.path.join(tempfile.gettempdir(), f"koma_link_{url_hash}")
        dl = await asyncio.to_thread(_download_soundcloud, query, output_template)
        if dl: item = {"source": "لینک", "id": url_hash}
    else:
        sc_results = await asyncio.to_thread(_search_soundcloud, query, 15)
        if not sc_results: return False
            
        query_words = query.lower().split()
        def score_match(c):
            title_lower = c["title"].lower()
            return sum(1 for word in query_words if word in title_lower)
            
        sc_results.sort(key=score_match, reverse=True)
        
        for c in sc_results:
            if await _is_used(c["id"]): continue
                
            output_template = os.path.join(tempfile.gettempdir(), f"koma_search_{c['id']}")
            dl = await asyncio.to_thread(_download_soundcloud, c["url"], output_template)
            if dl:
                item = c
                break

    if not dl or not item: return False
        
    return await _send_and_record_audio(bot, chat_id, thread_id, item, dl)
