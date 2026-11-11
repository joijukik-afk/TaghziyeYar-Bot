"""موتور جستجوی KOMA (ساندکلود + یوتیوب + آدیوس)"""

import os
import random
import hashlib
import logging
import tempfile
import asyncio
from typing import Optional, List, Dict
from datetime import datetime
import httpx
import yt_dlp
from sqlalchemy import select, func, and_
from telegram import Bot
from telegram.constants import ParseMode

from app.database.music_models import MusicTrack
from app.database.session import session_scope

logger = logging.getLogger(__name__)

MAX_SIZE = 45 * 1024 * 1024
MIN_SIZE = 100 * 1024  # کاهش به 100KB برای آهنگ‌های کوتاه

# 🔥 لیست بسیار متنوع از کلمات کلیدی برای کشف موسیقی جدید
SEARCH_QUERIES = [
    # COMA / øneheart / reidenshi style
    "øneheart", "oneheart", "oneheart slowed", "oneheart snow", "øneheart snow",
    "reidenshi", "reidenshi snowfall", "snowfall slowed reverb", "snowfall x",
    "dreamcore", "dreamcore slowed", "liminal space ambient", "liminal ambient",
    "dark ambient melancholic", "sad ambient", "melancholic ambient",
    "ethereal wave", "atmospheric wave", "atmospheric ambient",
    "slowed reverb aesthetic", "slowed and reverb", "slowed + reverb sad",
    "my head is empty", "my head is empty style", "daniel.mp3", "diedlonely",
    ".diedlonely", "leadwave", "antent", "hiræth", "fujiwara", "unnholy",
    "sevenlies", "statika", "futureville", "aurenth", "willix", 
    "endless withdrawal", "énouement", "unworn",
    # Ambient / Atmospheric
    "cinematic ambient", "space ambient", "emotional ambient", "sleepcore",
    "dreamwave", "chillwave", "slowcore", "downtempo ambient", "ambient lo-fi",
    "distorted memories", "nostalgic ambient", "lonely piano ambient",
    "melancholic piano", "sad piano reverb", "dark piano ambient",
    "dark cinematic piano", "horror ambient", "midnight ambient",
    # Persian / Iranian vibe
    "غمگین ایرانی", "غمگین slowed", "احساسی slowed", "آرام slowed", 
    "تنها slowed", "غمگین ریورب",
    # Other vibes
    "sad boy lofi", "sad girl lofi", "shoegaze ambient", "post rock ambient",
    "dark wave slowed", "comatose ambient", "deep ambient bass",
    "analog mannequin", "coma music", "koma music", "coma vibe", "coma aesthetic",
]

# ==================== دیتابیس ====================
async def _is_used(identifier: str) -> bool:
    """فقط بر اساس ID چک می‌کنه (ساده‌تر و موثرتر)"""
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack).where(
                MusicTrack.identifier == identifier, 
                MusicTrack.is_sent == True
            )
        )
        return res.scalar_one_or_none() is not None

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

async def _get_random_cached(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    """Fallback: اگر آهنگ جدیدی پیدا نشد، یک آهنگ تصادفی از کش بفرست"""
    try:
        async with session_scope() as session:
            res = await session.execute(
                select(MusicTrack).where(
                    and_(
                        MusicTrack.telegram_file_id != "",
                        MusicTrack.telegram_file_id.isnot(None),
                        MusicTrack.telegram_file_id != None
                    )
                ).order_by(func.random()).limit(1)
            )
            track = res.scalar_one_or_none()
            if not track or not track.telegram_file_id:
                return False
            
            await bot.send_audio(
                chat_id=chat_id, audio=track.telegram_file_id,
                title=(track.title or "Unknown")[:64],
                performer=(track.artist or "Unknown Artist")[:64],
                caption=f"🎵 <b>{track.title}</b>\n🎤 {track.artist}\n♻️ آرشیو کُما\n🌌 KOMA | کُما",
                parse_mode=ParseMode.HTML, read_timeout=120, write_timeout=120,
                message_thread_id=thread_id
            )
            return True
    except Exception as e:
        logger.error(f"Cache fallback failed: {e}")
        return False

# ==================== جستجو ====================
def _search_soundcloud(query: str, max_results: int = 10) -> List[Dict]:
    ydl_opts = {
        'quiet': True, 'no_warnings': True, 'extract_flat': True,
        'noplaylist': True, 'ignoreerrors': True,
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
                        "id": str(e.get('id', '')), "title": e.get('title', 'Unknown'),
                        "artist": e.get('uploader', 'Unknown Artist'), "url": url,
                        "source": "SoundCloud"
                    })
            return results
    except Exception as e:
        logger.warning(f"SC search failed for '{query}': {e}")
        return []

def _search_youtube(query: str, max_results: int = 10) -> List[Dict]:
    ydl_opts = {
        'quiet': True, 'no_warnings': True, 'extract_flat': True, 'noplaylist': True,
        'ignoreerrors': True,
        'extractor_args': {'youtube': {'player_client': ['ios', 'android', 'mweb', 'web']}}
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            if not info: return []
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
        logger.warning(f"YT search failed for '{query}': {e}")
        return []

async def _search_audius(query: str) -> List[Dict]:
    url = "https://discoveryprovider.audius.co/v1/tracks/search"
    params = {"query": query, "app_name": "KOMA"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                tracks = data.get("data", [])
                return [{
                    "id": f"audius_{t.get('id')}", "title": t.get("title", "Unknown"),
                    "artist": t.get("user", {}).get("name", "Unknown Artist"),
                    "source": "Audius",
                    "stream_url": f"https://discoveryprovider.audius.co/v1/tracks/{t['id']}/stream?app_name=KOMA"
                } for t in tracks if t.get("is_streamable")]
    except Exception:
        pass
    return []

# ==================== دانلود ====================
def _download_audio_ytdlp(url: str, output_template: str) -> Optional[dict]:
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
        'extractor_args': {
            'youtube': {'player_client': ['ios', 'android', 'mweb', 'web']},
        },
        'retries': 3,
        'fragment_retries': 3,
        'socket_timeout': 30,
        # ❌ حذف match_filter چون آهنگ‌های کوتاه ambient رو رد می‌کرد
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info: return None
            
            # پیدا کردن فایل mp3
            mp3_path = output_template + '.mp3'
            if not os.path.exists(mp3_path):
                base = os.path.basename(output_template)
                for f in os.listdir(tempfile.gettempdir()):
                    if f.startswith(base) and f.endswith('.mp3'):
                        mp3_path = os.path.join(tempfile.gettempdir(), f)
                        break
            
            if not os.path.exists(mp3_path):
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
    return None

async def _download_audius(stream_url: str, output_path: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", stream_url, timeout=60.0, follow_redirects=True) as resp:
                resp.raise_for_status()
                sha = hashlib.sha256()
                total = 0
                with open(output_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        total += len(chunk)
                        if total > MAX_SIZE:
                            f.close(); os.remove(output_path); return None
                        f.write(chunk); sha.update(chunk)
        if os.path.exists(output_path) and os.path.getsize(output_path) > MIN_SIZE:
            return {"path": output_path, "hash": sha.hexdigest(), "size": total}
    except Exception:
        pass
    return None

# ==================== ارسال ====================
async def fetch_and_send_music(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    """برای دستور /koma (تصادفی و هوشمند)"""
    
    # ۱. انتخاب ۳ کوئری تصادفی از لیست ۶۰+ تایی
    queries = random.sample(SEARCH_QUERIES, min(3, len(SEARCH_QUERIES)))
    
    all_candidates = []
    for query in queries:
        results = await asyncio.to_thread(_search_soundcloud, query, 8)
        if not results:
            results = await asyncio.to_thread(_search_youtube, query, 8)
        if not results:
            results = await _search_audius(query)
        all_candidates.extend(results)
    
    if not all_candidates:
        logger.warning("No candidates found from any source, trying cache...")
        return await _get_random_cached(bot, chat_id, thread_id)
    
    # ۲. خیلی تصادفی بشور تا تنوع بیشتر بشه
    random.shuffle(all_candidates)
    
    # ۳. تلاش برای دانلود
    attempts = 0
    max_attempts = min(15, len(all_candidates))  # حداکثر ۱۵ تلاش
    
    for item in all_candidates:
        if attempts >= max_attempts:
            break
        attempts += 1
        
        # چک کردن تکراری بودن
        if await _is_used(item["id"]):
            continue
        
        output_template = os.path.join(tempfile.gettempdir(), f"koma_{item['id']}")
        dl = None
        
        if item["source"] == "Audius":
            dl = await _download_audius(item["stream_url"], output_template + ".mp3")
            if dl:
                dl["title"] = item.get("title", "Unknown")
                dl["artist"] = item.get("artist", "Unknown Artist")
        else:
            dl = await asyncio.to_thread(_download_audio_ytdlp, item["url"], output_template)
        
        if not dl:
            continue  # این یکی دانلود نشد، برو بعدی
        
        # ۴. ارسال
        try:
            with open(dl["path"], "rb") as audio:
                sent = await bot.send_audio(
                    chat_id=chat_id, audio=audio,
                    title=dl.get('title', item.get('title', 'Unknown'))[:64],
                    performer=dl.get('artist', item.get('artist', 'Unknown Artist'))[:64],
                    caption=f"🎵 <b>{dl.get('title', item.get('title', 'Unknown'))}</b>\n🎤 {dl.get('artist', item.get('artist', 'Unknown Artist'))}\n📦 {item['source']}\n🌌 KOMA | کُما",
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
            
            try: os.remove(dl["path"])
            except: pass
            return True
        except Exception as e:
            logger.error(f"send_audio failed: {e}")
            try: os.remove(dl["path"])
            except: pass
    
    # اگر همه تلاش‌ها شکست خورد، از کش بفرست
    logger.warning("All attempts failed, falling back to cache...")
    return await _get_random_cached(bot, chat_id, thread_id)


async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str, thread_id: int = None) -> bool:
    """برای دستور /music (جستجوی دقیق با اسم یا لینک)"""
    item = None
    dl = None

    if query.startswith(("http://", "https://")):
        logger.info(f"Direct Link: {query}")
        url_hash = hashlib.md5(query.encode()).hexdigest()
        if await _is_used(url_hash): return False
            
        output_template = os.path.join(tempfile.gettempdir(), f"koma_link_{url_hash}")
        dl = await asyncio.to_thread(_download_audio_ytdlp, query, output_template)
        if dl:
            item = {"source": "لینک", "id": url_hash}
    else:
        logger.info(f"Searching for: {query}")
        sc_results = await asyncio.to_thread(_search_soundcloud, query, 10)
        yt_results = await asyncio.to_thread(_search_youtube, query, 10)
        audius_results = await _search_audius(query)
        
        candidates = sc_results + yt_results + audius_results
        if not candidates: return False
            
        query_words = query.lower().split()
        def score_match(c):
            title_lower = c["title"].lower()
            return sum(1 for word in query_words if word in title_lower)
            
        candidates.sort(key=score_match, reverse=True)
        
        for c in candidates:
            if await _is_used(c["id"]):
                continue
                
            output_template = os.path.join(tempfile.gettempdir(), f"koma_search_{c['id']}")
            
            if c["source"] == "Audius":
                dl = await _download_audius(c["stream_url"], output_template + ".mp3")
                if dl:
                    dl["title"] = c["title"]
                    dl["artist"] = c["artist"]
                    item = c
                    break
            else:
                dl = await asyncio.to_thread(_download_audio_ytdlp, c["url"], output_template)
                if dl:
                    item = c
                    break

    if not dl or not item: return False
        
    try:
        with open(dl["path"], "rb") as audio:
            sent = await bot.send_audio(
                chat_id=chat_id, audio=audio,
                title=dl.get('title', item.get('title', 'Unknown'))[:64], 
                performer=dl.get('artist', item.get('artist', 'Unknown Artist'))[:64],
                caption=f"🎵 <b>{dl.get('title', item.get('title', 'Unknown'))}</b>\n🎤 {dl.get('artist', item.get('artist', 'Unknown Artist'))}\n📦 {item['source']}\n🌌 KOMA | کُما",
                parse_mode=ParseMode.HTML, read_timeout=180, write_timeout=180, message_thread_id=thread_id
            )
        
        await _record_track({
            "identifier": item["id"], "title": dl.get("title", item.get("title", "Unknown")), 
            "artist": dl.get("artist", item.get("artist", "Unknown Artist")),
            "filename": os.path.basename(dl["path"]), "hash": dl["hash"]
        }, sent.audio.file_id)
        
        try: os.remove(dl["path"])
        except: pass
        return True
    except Exception as e:
        logger.error(f"send_audio failed: {e}")
        try: os.remove(dl["path"])
        except: pass
        return False
