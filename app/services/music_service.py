"""موتور جستجوی KOMA (نسخه نهایی و ضدخطا - جستجو با soundcloud-v2، دانلود با Cobalt API)"""

import os
import random
import hashlib
import logging
import tempfile
import asyncio
from typing import Optional, List, Dict
from datetime import datetime, timezone
import httpx
from telegram import Bot
from telegram.constants import ParseMode

# ایمپورت کتابخانه soundcloud-v2
try:
    from soundcloud import SoundCloud
    SC_V2_AVAILABLE = True
except ImportError:
    SC_V2_AVAILABLE = False

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

# لیست عبارات جستجوی پیش‌فرض برای دستور /koma
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

# آدرس API رایگان Cobalt
COBALT_API_URL = "https://api.cobalt.tools/"

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

# ==================== جستجو با soundcloud-v2 ====================
def _search_soundcloud(query: str, limit: int = 10) -> List[Dict]:
    """جستجو در ساندکلود با کتابخانه soundcloud-v2 (بدون نیاز به API Key)"""
    global LAST_ERROR
    if not SC_V2_AVAILABLE:
        LAST_ERROR = "کتابخانه soundcloud-v2 نصب نشده است."
        return []

    try:
        # نمونه‌سازی از کلاینت (نیازی به توکن احراز هویت برای جستجو نیست)
        sc = SoundCloud()
        
        # جستجوی آهنگ‌ها
        search_results = sc.search_tracks(query, limit=limit)
        
        results = []
        for track in search_results.collection:
            # ساخت لینک کامل آهنگ
            track_url = track.permalink_url
            if not track_url or 'soundcloud.com' not in track_url:
                continue
            
            results.append({
                "id": str(track.id),
                "title": track.title or "Unknown Title",
                "artist": track.user.username if track.user else "Unknown Artist",
                "url": track_url,
                "source": "SoundCloud"
            })
        
        if not results:
            LAST_ERROR = f"هیچ نتیجه‌ای برای «{query}» یافت نشد."
        return results
    except Exception as e:
        LAST_ERROR = f"خطای جستجو (soundcloud-v2): {str(e)[:120]}"
        logger.error(f"SoundCloud search failed for '{query}': {e}")
        return []

# ==================== دانلود با Cobalt API ====================
async def _download_with_cobalt(url: str) -> Optional[Dict]:
    """دانلود فایل صوتی با استفاده از API رایگان Cobalt"""
    global LAST_ERROR
    
    payload = {
        "url": url,
        "downloadMode": "audio",  # فقط فایل صوتی می‌خواهیم
        "audioFormat": "mp3"
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # ۱. ارسال درخواست به Cobalt برای دریافت لینک دانلود مستقیم
            logger.info(f"Sending request to Cobalt for: {url}")
            response = await client.post(COBALT_API_URL, json=payload, headers=headers)
            
            if response.status_code != 200:
                LAST_ERROR = f"خطای Cobalt (کد {response.status_code}): {response.text[:100]}"
                return None
            
            data = response.json()
            
            # بررسی وضعیت پاسخ
            if data.get("status") == "error":
                error_code = data.get("error", {}).get("code", "unknown")
                LAST_ERROR = f"Cobalt error: {error_code}"
                return None
            
            # ۲. دریافت لینک دانلود
            download_url = data.get("url")
            if not download_url:
                LAST_ERROR = "Cobalt لینک دانلودی برنگرداند."
                return None
            
            # ۳. دانلود فایل از لینک مستقیم
            logger.info(f"Downloading from Cobalt URL...")
            audio_response = await client.get(download_url)
            audio_response.raise_for_status()
            
            # ۴. ذخیره در فایل موقت
            fd, temp_path = tempfile.mkstemp(suffix=".mp3", prefix="koma_cobalt_")
            with os.fdopen(fd, 'wb') as f:
                f.write(audio_response.content)
            
            size = os.path.getsize(temp_path)
            if size < MIN_SIZE or size > MAX_SIZE:
                LAST_ERROR = f"حجم فایل غیرمجاز است: {size} بایت."
                os.remove(temp_path)
                return None
            
            # ۵. محاسبه هش
            sha = hashlib.sha256()
            with open(temp_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha.update(chunk)
            
            # ۶. استخراج عنوان و هنرمند از نام فایل (اگر موجود باشد)
            # Cobalt معمولاً نام فایل را در هدر Content-Disposition برمی‌گرداند
            content_disposition = audio_response.headers.get("content-disposition", "")
            filename = "audio.mp3"
            if "filename=" in content_disposition:
                filename = content_disposition.split("filename=")[-1].strip('"')
            
            title = os.path.splitext(filename)[0] or "Unknown Title"
            artist = "Unknown Artist"
            if " - " in title:
                parts = title.split(" - ", 1)
                artist, title = parts[0].strip(), parts[1].strip()
            
            return {
                "path": temp_path,
                "hash": sha.hexdigest(),
                "size": size,
                "title": title,
                "artist": artist
            }
            
    except httpx.TimeoutException:
        LAST_ERROR = "درخواست به Cobalt با تایم‌اوت مواجه شد."
        return None
    except Exception as e:
        LAST_ERROR = f"خطای دانلود با Cobalt: {str(e)[:120]}"
        logger.error(f"Cobalt download failed for {url}: {e}")
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
        try: os.remove(dl["path"])
        except Exception: pass

# ==================== توابع اصلی ====================
async def fetch_and_send_music(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    """دستور /koma - جستجو و دانلود با Cobalt"""
    query = random.choice(SEARCH_QUERIES)
    candidates = await asyncio.to_thread(_search_soundcloud, query, 5)
    
    if not candidates:
        return False

    random.shuffle(candidates)
    attempts = 0
    for item in candidates:
        if attempts >= 3: break
        attempts += 1

        if await _is_used(item["id"]): continue

        dl = await _download_with_cobalt(item["url"])
        if dl and await _send_and_record_audio(bot, chat_id, thread_id, item, dl):
            return True

    return False

async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str, thread_id: int = None) -> bool:
    """دستور /music - جستجوی دقیق و دانلود با Cobalt"""
    item = None
    dl = None

    if query.startswith(("http://", "https://")):
        if "soundcloud.com" not in query:
            global LAST_ERROR
            LAST_ERROR = "لینک وارد شده مربوط به ساندکلود نیست."
            return False
        url_hash = hashlib.md5(query.encode()).hexdigest()
        dl = await _download_with_cobalt(query)
        if dl:
            item = {"id": url_hash, "title": dl.get("title", "Unknown"), "artist": dl.get("artist", "Unknown")}
    else:
        sc_results = await asyncio.to_thread(_search_soundcloud, query, 10)
        if not sc_results:
            return False
            
        # انتخاب بهترین تطابق بر اساس کلمات جستجو
        query_words = query.lower().split()
        def score_match(c):
            title_lower = c["title"].lower()
            return sum(1 for word in query_words if word in title_lower)
            
        sc_results.sort(key=score_match, reverse=True)
        
        for c in sc_results[:3]:  # حداکثر ۳ نتیجه اول را امتحان کن
            if await _is_used(c["id"]): continue
            dl = await _download_with_cobalt(c["url"])
            if dl:
                item = c
                break

    if not dl or not item:
        return False
        
    return await _send_and_record_audio(bot, chat_id, thread_id, item, dl)
