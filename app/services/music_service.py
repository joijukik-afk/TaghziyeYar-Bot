"""موتور جستجوی هوشمند KOMA - نسخه 2.0

بهبودها:
- جستجوی موازی چندکوئری با وزن‌دهی
- تشخیص تکرار چندمعیاره (identifier + عنوان + آرتیست)
- تنوع آرتیست در ارسال‌های متوالی
- کش شکست‌ها با cooldown
- دانلود آبشاری کیفیت
- اعتبارسنجی حجم/مدت/بیت‌ریت
- پاکسازی متن برای ارسال ایمن
"""
import os
import re
import random
import hashlib
import logging
import tempfile
import asyncio
import time
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timezone
from difflib import SequenceMatcher

import yt_dlp
from sqlalchemy import select, desc
from telegram import Bot

from app.database.music_models import MusicTrack
from app.database.session import session_scope

logger = logging.getLogger(__name__)

# ==================== تنظیمات ====================
MAX_SIZE = 49 * 1024 * 1024          # 49 MB
MIN_SIZE = 100 * 1024                # 100 KB
MIN_DURATION = 20                    # ثانیه
MAX_DURATION = 15 * 60               # 15 دقیقه
MAX_ATTEMPTS = 40                    # حداکثر تلاش در هر اجرا
RESULTS_PER_QUERY = 15
MAX_QUERIES = 12
ARTIST_COOLDOWN = 3                  # در 3 ارسال اخیر آرتیست تکراری نشود
FAILED_URL_COOLDOWN_HOURS = 6
TITLE_SIM_THRESHOLD = 0.85           # آستانه شباهت عنوان

# ==================== مخزن کوئری با وزن ====================
QUERY_POOL: List[Tuple[str, int]] = [
    # انگلیسی - اتمسفریک
    ("øneheart", 3), ("oneheart", 2), ("reidenshi", 3),
    ("my head is empty", 2), ("daniel.mp3", 2), ("analog mannequin", 2),
    ("dreamcore", 2), ("dark ambient", 2), ("sad ambient", 2),
    ("slowed reverb", 3), ("slowed and reverb", 2),
    ("sad piano", 2), ("melancholic piano", 2), ("dark piano", 2),
    ("ethereal wave", 2), ("shoegaze ambient", 2),
    ("liminal space", 2), ("dreamwave", 2), ("slowcore", 2),
    ("atmospheric", 2), ("space ambient", 2), ("cinematic ambient", 2),
    ("lonely piano", 2), ("nostalgic", 2), ("midnight ambient", 2),
    ("coma music", 2), ("coma vibe", 2), ("koma vibe", 2),
    ("post rock ambient", 1), ("dark wave", 2), ("lofi sad", 2),
    # فارسی
    ("غمگین", 3), ("غمگین slowed", 3), ("غمگین ریورب", 3),
    ("احساسی slowed", 2), ("آرام slowed", 2), ("تنها slowed", 2),
    ("غمگین ایرانی", 2), ("آهنگ غمگین", 2), ("سوزناک", 1),
    ("غم‌انگیز", 2), ("شبانه", 2), ("تنهایی", 2), ("دلتنگی", 2),
]

# ==================== کش‌های in-memory ====================
_failed_urls: Dict[str, float] = {}
_recent_artists: List[str] = []

# ==================== ابزار کمکی ====================
def _normalize(text: str) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[\(\)\[\]\{\}\|\-\_\.\,\!\?\:\;\"\'«»]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _title_similarity(a: str, b: str) -> float:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()

def _sanitize(text: str, max_len: int = 64) -> str:
    if not text:
        return "Unknown"
    text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"<[^>]*>", "", text).strip()
    if len(text) > max_len:
        text = text[:max_len - 1] + "…"
    return text or "Unknown"

def _weighted_sample(pool: List[Tuple[str, int]], k: int) -> List[str]:
    items = list(pool)
    chosen: List[str] = []
    for _ in range(min(k, len(items))):
        total = sum(w for _, w in items)
        r = random.uniform(0, total)
        acc = 0.0
        for i, (q, w) in enumerate(items):
            acc += w
            if r <= acc:
                chosen.append(q)
                items.pop(i)
                break
    return chosen

def _url_key(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

def _is_cooling_down(url: str) -> bool:
    ts = _failed_urls.get(_url_key(url))
    return bool(ts and (time.time() - ts) < FAILED_URL_COOLDOWN_HOURS * 3600)

def _mark_failed(url: str) -> None:
    _failed_urls[_url_key(url)] = time.time()
    cutoff = time.time() - FAILED_URL_COOLDOWN_HOURS * 3600
    for k in [k for k, v in _failed_urls.items() if v < cutoff]:
        _failed_urls.pop(k, None)

# ==================== دیتابیس ====================
async def _is_used(identifier: str) -> bool:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack).where(
                MusicTrack.identifier == identifier,
                MusicTrack.is_sent == True,
            )
        )
        return res.scalar_one_or_none() is not None

async def _recent_sends(limit: int = 20) -> List[MusicTrack]:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack)
            .where(MusicTrack.is_sent == True)
            .order_by(desc(MusicTrack.sent_at))
            .limit(limit)
        )
        return list(res.scalars().all())

async def _is_duplicate_by_title(title: str, artist: str) -> bool:
    recent = await _recent_sends(50)
    for t in recent:
        sim = _title_similarity(title, t.title or "")
        same_artist = _normalize(artist) == _normalize(t.artist or "")
        if sim >= TITLE_SIM_THRESHOLD and same_artist:
            return True
        if sim >= 0.95:
            return True
    return False

async def _record_track(data: dict, file_id: str) -> None:
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
                identifier=data["identifier"],
                title=data["title"],
                artist=data["artist"],
                filename=data.get("filename", ""),
                file_hash=data["hash"],
                telegram_file_id=file_id,
                is_sent=True,
                sent_at=now_utc,
            ))
        await session.flush()

# ==================== جستجو ====================
def _search_soundcloud(query: str, max_results: int) -> List[Dict]:
    opts = {
        'quiet': True, 'no_warnings': True, 'extract_flat': True,
        'noplaylist': True, 'ignoreerrors': True, 'no_color': True,
        'geo_bypass': True, 'nocheckcertificate': True,
        'socket_timeout': 30, 'retries': 3,
        'extractor_args': {'soundcloud': {'formats': ['http_mp3_128', 'http_mp3_original']}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"scsearch{max_results}:{query}", download=False)
            if not info:
                return []
            out: List[Dict] = []
            for e in info.get('entries', []) or []:
                if not e:
                    continue
                url = e.get('url') or e.get('webpage_url')
                if not url:
                    continue
                dur = e.get('duration') or 0
                if dur and not (MIN_DURATION <= dur <= MAX_DURATION):
                    continue
                out.append({
                    "id": str(e.get('id', '')),
                    "title": e.get('title', '') or 'Unknown',
                    "artist": e.get('uploader', 'Unknown Artist'),
                    "url": url,
                    "duration": dur,
                })
            return out
    except Exception as e:
        logger.warning(f"SC search failed for '{query}': {e}")
        return []

# ==================== دانلود آبشاری ====================
def _download_soundcloud(url: str, output_template: str) -> Optional[dict]:
    for quality in ('192', '128', 'best'):
        opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': quality,
            }],
            'outtmpl': output_template + '.%(ext)s',
            'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'ignoreerrors': True, 'no_color': True,
            'retries': 3, 'fragment_retries': 3, 'socket_timeout': 60,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    continue
                mp3 = None
                if info.get('requested_downloads'):
                    mp3 = info['requested_downloads'][0].get('filepath')
                mp3 = mp3 or (output_template + '.mp3')
                if not mp3 or not os.path.exists(mp3):
                    continue
                size = os.path.getsize(mp3)
                if size < MIN_SIZE or size > MAX_SIZE:
                    os.remove(mp3)
                    continue
                sha = hashlib.sha256()
                with open(mp3, 'rb') as f:
                    for chunk in iter(lambda: f.read(8192), b''):
                        sha.update(chunk)
                return {
                    "path": mp3, "hash": sha.hexdigest(), "size": size,
                    "title": info.get('title', 'Unknown'),
                    "artist": info.get('uploader', 'Unknown Artist'),
                    "duration": info.get('duration') or 0,
                }
        except Exception as e:
            logger.warning(f"Download fail (q={quality}) for {url}: {e}")
            p = output_template + '.mp3'
            if os.path.exists(p):
                try: os.remove(p)
                except Exception: pass
            continue
    return None

# ==================== ارسال ====================
async def _send_and_record_audio(bot: Bot, chat_id: int, thread_id: Optional[int],
                                 item: dict, dl: dict) -> bool:
    title = _sanitize(dl.get('title') or item.get('title') or "Unknown", 64)
    artist = _sanitize(dl.get('artist') or item.get('artist') or "Unknown Artist", 64)
    caption = f"🎵 {title}\n🎤 {artist}\n📀 SoundCloud\n🖤 KOMA | کُما"
    try:
        with open(dl["path"], "rb") as audio:
            sent = await bot.send_audio(
                chat_id=chat_id, audio=audio,
                title=title, performer=artist, caption=caption,
                read_timeout=300, write_timeout=300,
                message_thread_id=thread_id,
            )
        await _record_track({
            "identifier": item["id"],
            "title": dl.get("title", item.get("title", "Unknown")),
            "artist": dl.get("artist", item.get("artist", "Unknown Artist")),
            "filename": os.path.basename(dl["path"]),
            "hash": dl["hash"],
        }, sent.audio.file_id)
        _recent_artists.append(_normalize(artist))
        if len(_recent_artists) > ARTIST_COOLDOWN:
            _recent_artists.pop(0)
        return True
    except Exception as e:
        logger.error(f"Send audio error: {e}")
        return False
    finally:
        try: os.remove(dl["path"])
        except Exception: pass

def _artist_in_cooldown(artist: str) -> bool:
    return _normalize(artist) in _recent_artists

# ==================== منطق اصلی ====================
async def fetch_and_send_music(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    """دستور /koma — جستجوی هوشمند و ارسال یک آهنگ جدید"""
    queries = _weighted_sample(QUERY_POOL, MAX_QUERIES)
    logger.info(f"KOMA: search with {len(queries)} queries")

    tasks = [asyncio.to_thread(_search_soundcloud, q, RESULTS_PER_QUERY) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    candidates: List[Dict] = []
    seen = set()
    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"Search exception: {r}")
            continue
        for item in r:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            candidates.append(item)

    logger.info(f"KOMA: {len(candidates)} unique candidates")
    if not candidates:
        return False

    candidates = [c for c in candidates if not _is_cooling_down(c["url"])]
    random.shuffle(candidates)
    logger.info(f"KOMA: {len(candidates)} after cooldown filter")
    if not candidates:
        return False

    for i, item in enumerate(candidates[:MAX_ATTEMPTS], 1):
        if await _is_used(item["id"]):
            continue
        if _artist_in_cooldown(item["artist"]):
            logger.info(f"KOMA: skip '{item['title']}' (artist cooldown)")
            continue
        if await _is_duplicate_by_title(item["title"], item["artist"]):
            logger.info(f"KOMA: skip '{item['title']}' (title dup)")
            continue

        out = os.path.join(tempfile.gettempdir(), f"koma_{item['id']}")
        dl = await asyncio.to_thread(_download_soundcloud, item["url"], out)
        if not dl:
            _mark_failed(item["url"])
            continue

        if await _send_and_record_audio(bot, chat_id, thread_id, item, dl):
            logger.info(f"KOMA: sent '{dl['title']}' [{i}/{MAX_ATTEMPTS}]")
            return True
        _mark_failed(item["url"])

    logger.warning("KOMA: no new song after all attempts")
    return False


async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str,
                                      thread_id: int = None) -> bool:
    """دستور /music — جستجوی دقیق یا ارسال از لینک"""
    # لینک مستقیم
    if query.startswith(("http://", "https://")):
        if "soundcloud.com" not in query:
            return False
        h = hashlib.md5(query.encode()).hexdigest()
        if await _is_used(h):
            return False
        out = os.path.join(tempfile.gettempdir(), f"koma_link_{h}")
        dl = await asyncio.to_thread(_download_soundcloud, query, out)
        if not dl:
            return False
        item = {"id": h, "title": dl["title"], "artist": dl["artist"]}
        return await _send_and_record_audio(bot, chat_id, thread_id, item, dl)

    # جستجوی متنی
    results = await asyncio.to_thread(_search_soundcloud, query, 20)
    if not results:
        return False

    words = _normalize(query).split()

    def score(c: Dict) -> int:
        t, a = _normalize(c["title"]), _normalize(c["artist"])
        s = 0
        for w in words:
            if w in t: s += 2
            if w in a: s += 1
        return s

    results.sort(key=score, reverse=True)

    for c in results:
        if await _is_used(c["id"]):
            continue
        out = os.path.join(tempfile.gettempdir(), f"koma_q_{c['id']}")
        dl = await asyncio.to_thread(_download_soundcloud, c["url"], out)
        if not dl:
            continue
        if await _send_and_record_audio(bot, chat_id, thread_id, c, dl):
            return True
    return False
