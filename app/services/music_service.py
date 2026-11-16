"""موتور جستجوی KOMA (نسخه مقاوم - بدون کش + شبیه‌سازی مرورگر + تلاش خودکار)"""

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

PROXY_URL = os.environ.get("MUSIC_PROXY_URL", "").strip()
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

# ==================== تنظیمات مشترک yt-dlp ====================
def _get_base_ydl_opts(use_proxy=True) -> dict:
    """تنظیمات پایه برای شبیه‌سازی مرورگر و جلوگیری از کش"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'no_cache_dir': True,  # 👈 بسیار مهم: جلوگیری از استفاده از client_id قدیمی
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        }
    }
    if use_proxy and PROXY_URL:
        opts['proxy'] = PROXY_URL
    return opts

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

# ==================== جستجو و دانلود ====================
def _search_soundcloud(query: str, max_results: int = 10) -> List[Dict]:
    global LAST_ERROR
    
    # تلاش اول: با پروکسی (اگر تنظیم شده باشد)
    # تلاش دوم: بدون پروکسی (اگر اولی شکست خورد)
    proxies_to_try = []
    if PROXY_URL:
        proxies_to_try.append(True)  # استفاده از پروکسی
    proxies_to_try.append(False)     # عدم استفاده از پروکسی (به عنوان جایگزین)

    for use_proxy in proxies_to_try:
        ydl_opts = _get_base_ydl_opts(use_proxy=use_proxy)
        ydl_opts.update({
            'extract_flat': True,
            'noplaylist': True,
            'ignoreerrors': True,
            'extractor_args': {
                'soundcloud': {
                    'formats': ['*_mp3', 'http_aac'],
                }
            },
        })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_url = f"scsearch{max_results}:{query}"
                logger.info(f"Trying search (proxy={use_proxy}) for: {query}")
                info = ydl.extract_info(search_url, download=False)
                
                if not info:
                    continue  # برو سراغ روش بعدی

                results = []
                entries = info.get('entries', []) if 'entries' in info else [info]
                for e in entries:
                    if not e:
                        continue
                    track_url = e.get('url') or e.get('webpage_url')
                    if track_url and ('soundcloud.com' in track_url):
                        results.append({
                            "id": str(e.get('id', '')),
                            "title": e.get('title', 'Unknown'),
                            "artist": e.get('uploader', 'Unknown Artist'),
                            "url": track_url,
                            "source": "SoundCloud"
                        })
                
                if results:
                    LAST_ERROR = f"موفق با پروکسی={use_proxy}"
                    return results[:max_results]
                else:
                    LAST_ERROR = "هیچ لینک ساندکلودی در نتایج پیدا نشد."
                    
        except Exception as e:
            LAST_ERROR = f"Search Error (proxy={use_proxy}): {str(e)[:100]}"
            logger.warning(f"Search failed (proxy={use_proxy}): {e}")
            continue  # برو سراغ روش بعدی

    return []

def _download_soundcloud(url: str, output_template: str) -> Optional[dict]:
    global LAST_ERROR
    
    proxies_to_try = []
    if PROXY_URL:
        proxies_to_try.append(True)
    proxies_to_try.append(False)

    for use_proxy in proxies_to_try:
        ydl_opts = _get_base_ydl_opts(use_proxy=use_proxy)
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128'
            }],
            'outtmpl': output_template + '.%(ext)s',
            'noplaylist': True,
            'ignoreerrors': True,
            'no_color': True,
            'retries': 2,
            'fragment_retries': 2,
            'socket_timeout': 20,
            'extractor_args': {
                'soundcloud': {
                    'formats': ['*_mp3', 'http_aac'],
                }
            },
        })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Trying download (proxy={use_proxy}) for: {url[:50]}...")
                info = ydl.extract_info(url, download=True)
                
                if not info:
                    continue

                if 'requested_downloads' in info and info['requested_downloads']:
                    mp3_path = info['requested_downloads'][0].get('filepath')
                else:
                    mp3_path = output_template + '.mp3'

                if not mp3_path or not os.path.exists(mp3_path):
                    continue

                size = os.path.getsize(mp3_path)
                if size < MIN_SIZE or size > MAX_SIZE:
                    os.remove(mp3_path)
                    continue

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
            LAST_ERROR = f"Download Error (proxy={use_proxy}): {str(e)[:100]}"
            logger.warning(f"Download failed (proxy={use_proxy}): {e}")
            mp3_check = output_template + '.mp3'
            if os.path.exists(mp3_check):
                os.remove(mp3_check)
            continue

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
        LAST_ERROR = f"ارسال تلگرام: {str(e)}"
        logger.error(f"send_audio failed: {e}")
        return False
    finally:
        try:
            os.remove(dl["path"])
        except Exception:
            pass

# ==================== توابع اصلی ====================
async def fetch_and_send_music(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    query = random.choice(SEARCH_QUERIES)
    candidates = await asyncio.to_thread(_search_soundcloud, query, 5)
    
    if not candidates:
        return False

    random.shuffle(candidates)
    attempts = 0
    for item in candidates:
        if attempts >= 3:
            break
        attempts += 1

        if await _is_used(item["id"]):
            continue

        output = os.path.join(tempfile.gettempdir(), f"koma_{item['id']}")
        dl = await asyncio.to_thread(_download_soundcloud, item["url"], output)
        if dl and await _send_and_record_audio(bot, chat_id, thread_id, item, dl):
            return True

    return False

async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str, thread_id: int = None) -> bool:
    if query.startswith(("http://", "https://")):
        if "soundcloud.com" not in query:
            global LAST_ERROR
            LAST_ERROR = "لینک ساندکلود نیست."
            return False
        url_hash = hashlib.md5(query.encode()).hexdigest()
        output = os.path.join(tempfile.gettempdir(), f"koma_link_{url_hash}")
        dl = await asyncio.to_thread(_download_soundcloud, query, output)
        if dl:
            return await _send_and_record_audio(bot, chat_id, thread_id, {"id": url_hash}, dl)
        return False

    results = await asyncio.to_thread(_search_soundcloud, query, 15)
    if not results:
        return False

    choices = [f"{r['title']} {r['artist']}" for r in results]
    best_matches = process.extract(
        query, choices, scorer=fuzz.WRatio, limit=5, score_cutoff=60
    )

    if not best_matches:
        candidates = results[:5]
    else:
        candidates = [results[idx] for _, _, idx in best_matches]

    attempts = 0
    for c in candidates:
        if attempts >= 3:
            break
        attempts += 1

        if await _is_used(c["id"]):
            continue

        output = os.path.join(tempfile.gettempdir(), f"music_{c['id']}")
        dl = await asyncio.to_thread(_download_soundcloud, c["url"], output)
        if dl and await _send_and_record_audio(bot, chat_id, thread_id, c, dl):
            return True

    fallback_results = await asyncio.to_thread(_search_soundcloud, query, 10)
    fallback_choices = [f"{r['title']} {r['artist']}" for r in fallback_results]
    fallback_best = process.extract(query, fallback_choices, scorer=fuzz.WRatio, limit=3, score_cutoff=50)

    fallback_candidates = [fallback_results[idx] for _, _, idx in fallback_best] if fallback_best else fallback_results[:3]

    for c in fallback_candidates:
        if await _is_used(c["id"]):
            continue
        output = os.path.join(tempfile.gettempdir(), f"music_fb_{c['id']}")
        dl = await asyncio.to_thread(_download_soundcloud, c["url"], output)
        if dl and await _send_and_record_audio(bot, chat_id, thread_id, c, dl):
            return True

    return False
