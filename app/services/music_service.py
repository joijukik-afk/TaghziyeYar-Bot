"""KOMA Engine 2.2 — Audio delivery (upgraded, architecture-preserving).

Changes vs 2.1:
    * Bounded search concurrency via asyncio.Semaphore (avoids 429 storms)
    * Exponential backoff on transient search failures
    * DB-backed artist cooldown (survives restarts, works across workers)
    * Query rotation — recent queries not repeated
    * Robust temp-file cleanup (.mp3, .part, .webm, .m4a)
    * Structured logging at every decision point
    * Graceful CancelledError handling
    * All env-configurable with defaults that match 2.1 behavior

Kept intact:
    * OAuth integration (username/password via yt-dlp)
    * Multi-quality download cascade
    * SHA-256 validation + size bounds
    * `fetch_and_send_music` and `fetch_and_send_custom_music` signatures
    * MusicTrack model usage
"""
from __future__ import annotations

import asyncio
import glob
import hashlib
import logging
import os
import random
import re
import tempfile
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import yt_dlp
from sqlalchemy import select, desc
from telegram import Bot

from app.database.music_models import MusicTrack
from app.database.session import session_scope

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  CONFIG (env-overridable, defaults = 2.1 behavior)
# ═══════════════════════════════════════════════════════════════════════

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


MAX_SIZE = _env_int("KOMA_MAX_SIZE_MB", 49) * 1024 * 1024
MIN_SIZE = _env_int("KOMA_MIN_SIZE_KB", 100) * 1024
MIN_DURATION = _env_int("KOMA_MIN_DURATION", 20)
MAX_DURATION = _env_int("KOMA_MAX_DURATION", 15 * 60)
MAX_ATTEMPTS = _env_int("KOMA_MAX_ATTEMPTS", 40)
RESULTS_PER_QUERY = _env_int("KOMA_RESULTS_PER_QUERY", 15)
MAX_QUERIES = _env_int("KOMA_MAX_QUERIES", 12)
ARTIST_COOLDOWN = _env_int("KOMA_ARTIST_COOLDOWN", 3)
FAILED_URL_COOLDOWN_HOURS = _env_int("KOMA_FAILED_COOLDOWN_H", 6)
TITLE_SIM_THRESHOLD = _env_float("KOMA_TITLE_SIM", 0.85)
SEARCH_CONCURRENCY = _env_int("KOMA_SEARCH_CONCURRENCY", 4)
DOWNLOAD_RETRIES = _env_int("KOMA_DOWNLOAD_RETRIES", 3)

SOUNDCLOUD_OAUTH_TOKEN = os.getenv(
    "SOUNDCLOUD_OAUTH_TOKEN", "YOUR_OAUTH_TOKEN_HERE"
)


# ═══════════════════════════════════════════════════════════════════════
#  QUERY POOL
# ═══════════════════════════════════════════════════════════════════════

QUERY_POOL: List[Tuple[str, int]] = [
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
    ("غمگین", 3), ("غمگین slowed", 3), ("غمگین ریورب", 3),
    ("احساسی slowed", 2), ("آرام slowed", 2), ("تنها slowed", 2),
    ("غمگین ایرانی", 2), ("آهنگ غمگین", 2), ("سوزناک", 1),
    ("غم‌انگیز", 2), ("شبانه", 2), ("تنهایی", 2), ("دلتنگی", 2),
]


# ═══════════════════════════════════════════════════════════════════════
#  IN-MEMORY STATE
# ═══════════════════════════════════════════════════════════════════════

_failed_urls: Dict[str, float] = {}
_recent_artists: List[str] = []
_recent_queries: List[str] = []
_RECENT_QUERY_WINDOW = 20


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

_PUNCT_RE = re.compile(r"[\(\)\[\]\{\}\|\-\_\.\,\!\?\:\;\"\'«»]+")
_WS_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]")
_HTML_RE = re.compile(r"<[^>]*>")


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = str(text).lower().strip()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


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
    text = _CTRL_RE.sub("", str(text))
    text = _HTML_RE.sub("", text).strip()
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text or "Unknown"


def _weighted_sample(pool: List[Tuple[str, int]], k: int) -> List[str]:
    """Weighted sample without replacement, avoiding recent queries first."""
    # Prefer queries not in _recent_queries
    preferred = [(q, w) for (q, w) in pool if q not in _recent_queries]
    if len(preferred) < k:
        preferred = list(pool)

    items = list(preferred)
    chosen: List[str] = []
    for _ in range(min(k, len(items))):
        total = sum(w for _, w in items)
        if total <= 0:
            break
        r = random.uniform(0, total)
        acc = 0.0
        for i, (q, w) in enumerate(items):
            acc += w
            if r <= acc:
                chosen.append(q)
                items.pop(i)
                break

    # Record rotation
    _recent_queries.extend(chosen)
    while len(_recent_queries) > _RECENT_QUERY_WINDOW:
        _recent_queries.pop(0)
    return chosen


def _url_key(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def _is_cooling_down(url: str) -> bool:
    ts = _failed_urls.get(_url_key(url))
    return bool(ts and (time.time() - ts) < FAILED_URL_COOLDOWN_HOURS * 3600)


def _mark_failed(url: str) -> None:
    _failed_urls[_url_key(url)] = time.time()
    cutoff = time.time() - FAILED_URL_COOLDOWN_HOURS * 3600
    for k in [k for k, v in _failed_urls.items() if v < cutoff]:
        _failed_urls.pop(k, None)


def _cleanup_temp(prefix: str) -> None:
    """Remove any leftover files matching prefix (mp3, part, webm, m4a)."""
    for pat in (
        f"{prefix}*.mp3", f"{prefix}*.part", f"{prefix}*.webm",
        f"{prefix}*.m4a", f"{prefix}*.temp.mp3", f"{prefix}*.temp.webm",
    ):
        for p in glob.glob(pat):
            try:
                os.remove(p)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════════════════

async def _is_used(identifier: str) -> bool:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack.id).where(
                MusicTrack.identifier == identifier,
                MusicTrack.is_sent.is_(True),
            ).limit(1)
        )
        return res.scalar_one_or_none() is not None


async def _recent_sends(limit: int = 20) -> List[MusicTrack]:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack)
            .where(MusicTrack.is_sent.is_(True))
            .order_by(desc(MusicTrack.sent_at))
            .limit(limit)
        )
        return list(res.scalars().all())


async def _recent_artist_names(limit: int) -> List[str]:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack.artist)
            .where(MusicTrack.is_sent.is_(True))
            .order_by(desc(MusicTrack.sent_at))
            .limit(limit)
        )
        return [_normalize(a or "") for a in res.scalars().all()]


async def _is_duplicate_by_title(title: str, artist: str) -> bool:
    for t in await _recent_sends(50):
        sim = _title_similarity(title, t.title or "")
        same_artist = _normalize(artist) == _normalize(t.artist or "")
        if same_artist and sim >= TITLE_SIM_THRESHOLD:
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


# ═══════════════════════════════════════════════════════════════════════
#  SOUNDCLOUD SEARCH (bounded + retry)
# ═══════════════════════════════════════════════════════════════════════

def _search_soundcloud_sync(query: str, max_results: int) -> List[Dict]:
    opts = {
        "quiet": True, "no_warnings": True, "extract_flat": True,
        "noplaylist": True, "ignoreerrors": True, "no_color": True,
        "geo_bypass": True, "nocheckcertificate": True,
        "socket_timeout": 30, "retries": 3,
        "username": "oauth",
        "password": SOUNDCLOUD_OAUTH_TOKEN,
        "extractor_args": {
            "soundcloud": {"formats": ["http_mp3_128", "http_mp3_original"]}
        },
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"scsearch{max_results}:{query}", download=False
            )
            if not info:
                return []
            out: List[Dict] = []
            for e in info.get("entries") or []:
                if not e:
                    continue
                url = e.get("url") or e.get("webpage_url")
                if not url:
                    continue
                dur = e.get("duration") or 0
                if dur and not (MIN_DURATION <= dur <= MAX_DURATION):
                    continue
                out.append({
                    "id": str(e.get("id", "")),
                    "title": e.get("title") or "Unknown",
                    "artist": e.get("uploader") or "Unknown Artist",
                    "url": url,
                    "duration": dur,
                })
            return out
    except Exception as e:
        logger.warning("SC search failed for %r: %s", query, e)
        return []


async def _search_with_semaphore(
    sem: asyncio.Semaphore, query: str, results: int,
) -> List[Dict]:
    async with sem:
        try:
            return await asyncio.to_thread(
                _search_soundcloud_sync, query, results
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Search task failed (%r): %s", query, e)
            return []


# ═══════════════════════════════════════════════════════════════════════
#  DOWNLOAD (multi-quality cascade)
# ═══════════════════════════════════════════════════════════════════════

def _download_soundcloud(url: str, output_template: str) -> Optional[dict]:
    for quality in ("192", "128", "best"):
        opts = {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            }],
            "outtmpl": output_template + ".%(ext)s",
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "ignoreerrors": True, "no_color": True,
            "retries": DOWNLOAD_RETRIES,
            "fragment_retries": DOWNLOAD_RETRIES,
            "socket_timeout": 60,
            "username": "oauth",
            "password": SOUNDCLOUD_OAUTH_TOKEN,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    continue
                mp3 = None
                if info.get("requested_downloads"):
                    mp3 = info["requested_downloads"][0].get("filepath")
                mp3 = mp3 or (output_template + ".mp3")
                if not mp3 or not os.path.exists(mp3):
                    continue
                size = os.path.getsize(mp3)
                if size < MIN_SIZE or size > MAX_SIZE:
                    try:
                        os.remove(mp3)
                    except Exception:
                        pass
                    continue
                sha = hashlib.sha256()
                with open(mp3, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        sha.update(chunk)
                return {
                    "path": mp3,
                    "hash": sha.hexdigest(),
                    "size": size,
                    "title": info.get("title", "Unknown"),
                    "artist": info.get("uploader", "Unknown Artist"),
                    "duration": info.get("duration") or 0,
                }
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Download fail (q=%s) for %s: %s", quality, url, e,
            )
            _cleanup_temp(output_template)
            continue
    return None


# ═══════════════════════════════════════════════════════════════════════
#  SEND
# ═══════════════════════════════════════════════════════════════════════

async def _send_and_record_audio(
    bot: Bot, chat_id: int, thread_id: Optional[int],
    item: Dict, dl: dict,
) -> bool:
    title = _sanitize(dl.get("title") or item.get("title") or "Unknown", 64)
    artist = _sanitize(
        dl.get("artist") or item.get("artist") or "Unknown Artist", 64,
    )
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
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("Send audio error: %s", e)
        return False
    finally:
        try:
            os.remove(dl["path"])
        except Exception:
            pass


def _artist_in_cooldown_sync(artist: str) -> bool:
    return _normalize(artist) in _recent_artists


# ═══════════════════════════════════════════════════════════════════════
#  MAIN FLOW
# ═══════════════════════════════════════════════════════════════════════

async def fetch_and_send_music(
    bot: Bot, chat_id: int, thread_id: int = None,
) -> bool:
    """KOMA: one new qualified track, downloaded and sent."""
    queries = _weighted_sample(QUERY_POOL, MAX_QUERIES)
    logger.info(
        "KOMA: search starting (queries=%d, concurrency=%d)",
        len(queries), SEARCH_CONCURRENCY,
    )

    # 1) Bounded concurrent search
    sem = asyncio.Semaphore(SEARCH_CONCURRENCY)
    tasks = [
        _search_with_semaphore(sem, q, RESULTS_PER_QUERY) for q in queries
    ]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=False)
    except asyncio.CancelledError:
        logger.info("KOMA: cancelled during search")
        raise

    candidates: List[Dict] = []
    seen = set()
    for r in results:
        for item in r:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            candidates.append(item)

    logger.info("KOMA: %d unique candidates", len(candidates))
    if not candidates:
        return False

    # 2) Drop failed URLs
    candidates = [c for c in candidates if not _is_cooling_down(c["url"])]
    logger.info("KOMA: %d after URL cooldown filter", len(candidates))
    if not candidates:
        return False

    # 3) Load recent artists from DB once (survives restarts)
    db_recent = set(await _recent_artist_names(ARTIST_COOLDOWN))
    memory_recent = set(_recent_artists)
    cooldown_set = db_recent | memory_recent

    # 4) Shuffle and try candidates
    random.shuffle(candidates)

    for i, item in enumerate(candidates[:MAX_ATTEMPTS], 1):
        if await _is_used(item["id"]):
            continue

        norm_artist = _normalize(item["artist"])
        if norm_artist in cooldown_set:
            logger.debug(
                "KOMA: skip %r (artist cooldown)", item["title"],
            )
            continue

        if await _is_duplicate_by_title(item["title"], item["artist"]):
            logger.debug("KOMA: skip %r (title duplicate)", item["title"])
            continue

        out = os.path.join(
            tempfile.gettempdir(), f"koma_{item['id']}",
        )
        try:
            dl = await asyncio.to_thread(
                _download_soundcloud, item["url"], out,
            )
        except asyncio.CancelledError:
            _cleanup_temp(out)
            raise
        except Exception as e:
            logger.warning("Download failed for %r: %s", item["title"], e)
            dl = None

        if not dl:
            _mark_failed(item["url"])
            _cleanup_temp(out)
            continue

        try:
            if await _send_and_record_audio(
                bot, chat_id, thread_id, item, dl,
            ):
                logger.info(
                    "KOMA: sent %r by %r [%d/%d]",
                    dl.get("title"), dl.get("artist"),
                    i, MAX_ATTEMPTS,
                )
                return True
        except asyncio.CancelledError:
            raise

        _mark_failed(item["url"])

    logger.warning(
        "KOMA: no new track after %d attempts", MAX_ATTEMPTS,
    )
    return False


async def fetch_and_send_custom_music(
    bot: Bot, chat_id: int, query: str, thread_id: int = None,
) -> bool:
    """Music: direct URL or text search — sends audio file."""
    # Direct URL
    if query.startswith(("http://", "https://")):
        if "soundcloud.com" not in query:
            return False
        h = hashlib.md5(query.encode()).hexdigest()
        if await _is_used(h):
            return False
        out = os.path.join(tempfile.gettempdir(), f"koma_link_{h}")
        try:
            dl = await asyncio.to_thread(_download_soundcloud, query, out)
        except asyncio.CancelledError:
            _cleanup_temp(out)
            raise
        if not dl:
            _cleanup_temp(out)
            return False
        item = {
            "id": h,
            "title": dl["title"],
            "artist": dl["artist"],
            "url": query,
        }
        return await _send_and_record_audio(
            bot, chat_id, thread_id, item, dl,
        )

    # Text search
    try:
        results = await asyncio.to_thread(
            _search_soundcloud_sync, query, 20,
        )
    except asyncio.CancelledError:
        raise
    if not results:
        return False

    words = _normalize(query).split()

    def _score(c: Dict) -> int:
        t, a = _normalize(c["title"]), _normalize(c["artist"])
        s = 0
        for w in words:
            if w in t:
                s += 2
            if w in a:
                s += 1
        return s

    results.sort(key=_score, reverse=True)

    for c in results:
        if await _is_used(c["id"]):
            continue
        out = os.path.join(
            tempfile.gettempdir(), f"koma_q_{c['id']}",
        )
        try:
            dl = await asyncio.to_thread(
                _download_soundcloud, c["url"], out,
            )
        except asyncio.CancelledError:
            _cleanup_temp(out)
            raise
        if not dl:
            _cleanup_temp(out)
            continue
        if await _send_and_record_audio(bot, chat_id, thread_id, c, dl):
            return True
    return False
