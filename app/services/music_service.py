"""موتور جستجوی KOMA (نسخه نهایی - soundcloud-v2 + Cobalt API)"""

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
from rapidfuzz import fuzz, process

# ایمپورت soundcloud-v2
try:
    from soundcloud import SoundCloud
    SC_V2_AVAILABLE = True
except ImportError:
    SC_V2_AVAILABLE = False

logger = logging.getLogger(__name__)
LAST_ERROR = "بدون خطای مشخص"

# مدیریت دیتابیس (در صورت خطا، موزیک قطع نمی‌شود)
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

# لیست عبارات جستجو برای دستور /koma
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

# 👈 لیست سرورهای جدید و فعال Cobalt
COBALT_INSTANCES = [
    "https://cobalt.lamps-dev.dev/",
    "https://cobalt.meowing.de/",
    "https://cobalt-api.kwiatekmiki.com/",
    "https://co.eepy.today/"
]

# ==================== دیتابیس ====================
async def _is_used(identifier: str) -> bool:
    if not DB_ENABLED: return False
    try:
        async with session_scope() as session:
            res = await session.execute(
                select(MusicTrack).where(MusicTrack.identifier == identifier, MusicTrack.is_sent == True)
            )
            return res.scalar_one_or_none() is not None
    except Exception:
        return False

async def _record_track(data: dict, file_id: str) -> None:
    if not DB_ENABLED: return
    try:
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
    except Exception as e:
        logger.error(f"DB Record Error: {e}")

# ==================== جستجو با soundcloud-v2 ====================
def _search_soundcloud(query: str, limit: int = 10) -> List[Dict]:
    global LAST_ERROR
    if not SC_V2_AVAILABLE:
        LAST_ERROR = "کتابخانه soundcloud-v2 نصب نشده است."
        return []

    try:
        sc = SoundCloud()
        tracks_generator = sc.search_tracks(query, limit=limit)
        
        results = []
        for track in tracks_generator:
            track_url = getattr(track, 'permalink_url', None)
            if not track_url or 'soundcloud.com' not in track_url:
                continue
            
            artist_name = "Unknown Artist"
            if hasattr(track, 'user') and track.user:
                artist_name = getattr(track.user, 'username', 'Unknown Artist')

            results.append({
                "id": str(getattr(track, 'id', '')),
                "title": getattr(track, 'title', 'Unknown Title'),
                "artist": artist_name,
                "url": track_url,
                "source": "SoundCloud"
            })
        
        if not results:
            LAST_ERROR = f"هیچ نتیجه‌ای برای «{query}» در ساندکلود یافت نشد."
        return results
    except Exception as e:
        LAST_ERROR = f"خطای جستجو (SC-v2): {str(e)[:120]}"
        logger.error(f"SoundCloud search failed for '{query}': {e}")
        return []

# ==================== دانلود با Cobalt API ====================
async def _download_with_cobalt(url: str, max_retries: int = 2) -> Optional[Dict]:
    global LAST_ERROR
    payload = {"url": url, "downloadMode": "audio", "audioFormat": "mp3"}
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    for api_url in COBALT_INSTANCES:
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    logger.info(f"Trying Cobalt: {api_url} (attempt {attempt+1}) for {url}")
                    response = await client.post(api_url, json=payload, headers=headers)
                    
                    if response.status_code != 200:
                        break # سراغ سرور بعدی برو
                    
                    data = response.json()
                    
                    if data.get("status") == "error":
                        LAST_ERROR = f"Cobalt ({api_url}): {data.get('error', {}).get('code', 'unknown')}"
                        break
                    
                    download_url = data.get("url")
                    if not download_url:
                        break
                    
                    # دانلود فایل از لینک دریافتی
                    audio_response = await client.get(download_url)
                    audio_response.raise_for_status()
                    
                    fd, temp_path = tempfile.mkstemp(suffix=".mp3", prefix="koma_")
                    with os.fdopen(fd, 'wb') as f:
                        f.write(audio_response.content)
                    
                    size = os.path.getsize(temp_path)
                    if size < MIN_SIZE or size > MAX_SIZE:
                        os.remove(temp_path)
                        break
                    
                    sha = hashlib.sha256()
                    with open(temp_path, 'rb') as f:
                        for chunk in iter(lambda: f.read(8192), b''):
                            sha.update(chunk)
                    
                    title = "Unknown Title"
                    artist = "Unknown Artist"
                    cd = audio_response.headers.get("content-disposition", "")
                    if "filename=" in cd:
                        fn = cd.split("filename=")[-1].strip('"')
                        base = os.path.splitext(fn)[0]
                        if " - " in base:
                            parts = base.split(" - ", 1)
                            artist, title = parts[0].strip(), parts[1].strip()
                        else:
                            title = base

                    return {
                        "path": temp_path, "hash": sha.hexdigest(), "size": size,
                        "title": title, "artist": artist
                    }
                    
            except Exception as e:
                LAST_ERROR = f"خطای دانلود ({api_url}): {str(e)[:80]}"
                if attempt < max_retries - 1:
                    await asyncio.sleep(1) # 1 ثانیه صبر و تلاش مجدد
                else:
                    break # سراغ سرور بعدی برو

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
    query = random.choice(SEARCH_QUERIES)
    candidates = await asyncio.to_thread(_search_soundcloud, query, 5)
    if not candidates: return False

    random.shuffle(candidates)
    for item in candidates[:3]: # حداکثر 3 تلاش
        if await _is_used(item["id"]): continue
        dl = await _download_with_cobalt(item["url"])
        if dl and await _send_and_record_audio(bot, chat_id, thread_id, item, dl):
            return True
    return False

async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str, thread_id: int = None) -> bool:
    item, dl = None, None

    if query.startswith(("http://", "https://")):
        if "soundcloud.com" not in query:
            global LAST_ERROR
            LAST_ERROR = "لینک ساندکلود نیست."
            return False
        url_hash = hashlib.md5(query.encode()).hexdigest()
        dl = await _download_with_cobalt(query)
        if dl: item = {"id": url_hash, "title": dl["title"], "artist": dl["artist"]}
    else:
        sc_results = await asyncio.to_thread(_search_soundcloud, query, 10)
        if not sc_results: return False
            
        # استفاده از RapidFuzz برای پیدا کردن دقیق‌ترین آهنگ
        choices = [f"{r['title']} {r['artist']}" for r in sc_results]
        best_matches = process.extract(query, choices, scorer=fuzz.WRatio, limit=3, score_cutoff=60)
        
        candidates = [sc_results[idx] for _, _, idx in best_matches] if best_matches else sc_results[:3]

        for c in candidates:
            if await _is_used(c["id"]): continue
            dl = await _download_with_cobalt(c["url"])
            if dl:
                item = c
                break

    if not dl or not item: return False
    return await _send_and_record_audio(bot, chat_id, thread_id, item, dl)
