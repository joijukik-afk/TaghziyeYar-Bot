"""موتور جستجوی KOMA (نسخه نهایی - yt-dlp با شبیه‌سازی مرورگر)"""

import os
import random
import hashlib
import logging
import tempfile
import asyncio
from typing import Optional, List, Dict
from datetime import datetime, timezone
import yt_dlp
from telegram import Bot
from telegram.constants import ParseMode
from rapidfuzz import fuzz, process

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

def _get_ydl_opts(extract_flat=False) -> dict:
    """تنظیمات بهینه yt-dlp برای دور زدن بلاک ساندکلود در سرورهای ابری"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'ignoreerrors': True,
        'no_color': True,
        'no_cache_dir': True,
        'impersonate': 'chrome',  # 👈 کلید اصلی: شبیه‌سازی مرورگر کروم
        'socket_timeout': 30,
        'retries': 2,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        },
        'extractor_args': {'soundcloud': {'formats': ['*_mp3', 'http_aac']}}
    }
    if extract_flat:
        opts['extract_flat'] = True
    return opts

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

# ==================== جستجو و دانلود (yt-dlp) ====================
def _search_soundcloud(query: str, max_results: int = 10) -> List[Dict]:
    global LAST_ERROR
    try:
        with yt_dlp.YoutubeDL(_get_ydl_opts(extract_flat=True)) as ydl:
            info = ydl.extract_info(f"scsearch{max_results}:{query}", download=False)
            if not info:
                LAST_ERROR = "نتیجه جستجو خالی بود."
                return []
            results = []
            for e in info.get('entries', []):
                if not e: continue
                url = e.get('url') or e.get('webpage_url')
                if url and 'soundcloud.com' in url:
                    results.append({
                        "id": str(e.get('id', '')),
                        "title": e.get('title', 'Unknown'),
                        "artist": e.get('uploader', 'Unknown Artist'),
                        "url": url,
                        "source": "SoundCloud"
                    })
            return results
    except Exception as e:
        LAST_ERROR = f"خطای جستجو: {str(e)[:100]}"
        logger.warning(f"SC search failed for '{query}': {e}")
        return []

def _download_soundcloud(url: str, output_template: str) -> Optional[dict]:
    global LAST_ERROR
    opts = _get_ydl_opts()
    opts.update({
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128'
        }],
        'outtmpl': output_template + '.%(ext)s',
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                LAST_ERROR = "دانلود اطلاعاتی برنگرداند."
                return None
            if 'requested_downloads' in info and info['requested_downloads']:
                mp3_path = info['requested_downloads'][0].get('filepath')
            else:
                mp3_path = output_template + '.mp3'
            if not mp3_path or not os.path.exists(mp3_path):
                LAST_ERROR = "فایل MP3 پیدا نشد."
                return None
            size = os.path.getsize(mp3_path)
            if size < MIN_SIZE or size > MAX_SIZE:
                LAST_ERROR = f"حجم فایل نامعتبر است: {size} بایت"
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
        LAST_ERROR = f"خطای دانلود: {str(e)[:100]}"
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
        global LAST_ERROR
        LAST_ERROR = f"ارسال تلگرام: {str(e)[:100]}"
        logger.error(f"send_audio failed: {e}")
        return False
    finally:
        try: os.remove(dl["path"])
        except Exception: pass

# ==================== توابع اصلی ====================
async def fetch_and_send_music(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    queries = random.sample(SEARCH_QUERIES, 2)
    all_candidates = []
    for query in queries:
        results = await asyncio.to_thread(_search_soundcloud, query, 5)
        all_candidates.extend(results)
    if not all_candidates: return False
    random.shuffle(all_candidates)
    for item in all_candidates[:3]:
        if await _is_used(item["id"]): continue
        output_template = os.path.join(tempfile.gettempdir(), f"koma_sc_{item['id']}")
        dl = await asyncio.to_thread(_download_soundcloud, item["url"], output_template)
        if dl and await _send_and_record_audio(bot, chat_id, thread_id, item, dl):
            return True
    return False

async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str, thread_id: int = None) -> bool:
    item, dl = None, None
    if query.startswith(("http://", "https://")):
        if "soundcloud.com" not in query:
            global LAST_ERROR
            LAST_ERROR = "لینک وارد شده مربوط به ساندکلود نیست."
            return False
        url_hash = hashlib.md5(query.encode()).hexdigest()
        if await _is_used(url_hash): return False
        output_template = os.path.join(tempfile.gettempdir(), f"koma_link_{url_hash}")
        dl = await asyncio.to_thread(_download_soundcloud, query, output_template)
        if dl: item = {"id": url_hash, "title": dl["title"], "artist": dl["artist"]}
    else:
        sc_results = await asyncio.to_thread(_search_soundcloud, query, 10)
        if not sc_results: return False
        choices = [f"{r['title']} {r['artist']}" for r in sc_results]
        best_matches = process.extract(query, choices, scorer=fuzz.WRatio, limit=3, score_cutoff=60)
        candidates = [sc_results[idx] for _, _, idx in best_matches] if best_matches else sc_results[:3]
        for c in candidates:
            if await _is_used(c["id"]): continue
            output_template = os.path.join(tempfile.gettempdir(), f"koma_search_{c['id']}")
            dl = await asyncio.to_thread(_download_soundcloud, c["url"], output_template)
            if dl:
                item = c
                break
    if not dl or not item: return False
    return await _send_and_record_audio(bot, chat_id, thread_id, item, dl)
