"""KOMA Engine 3.2 — Audio delivery + strict filtering.

Sends actual audio files (like v2.1) BUT adds:
    * KOMA scoring (title + artist + description)
    * Hard reject (phonk/EDM/trap/etc.)
    * Artist cooldown (DB-backed)
    * Title dedup
    * Freshness-aware selection
    * Bounded concurrency
    * Fallback threshold so it always finds SOMETHING valid
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import yt_dlp
from sqlalchemy import select, desc
from sqlalchemy.exc import IntegrityError
from telegram import Bot

from app.database.music_models import MusicTrack
from app.database.session import session_scope

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  CONFIG
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


@dataclass(frozen=True)
class KomaConfig:
    # Acceptance thresholds
    min_score: int = 30
    fallback_min_score: int = 15
    # Search
    max_queries: int = 10
    results_per_query: int = 15
    search_concurrency: int = 4
    request_timeout: int = 30
    max_attempts: int = 30
    # Download
    max_size_bytes: int = 49 * 1024 * 1024
    min_size_bytes: int = 100 * 1024
    min_duration: int = 20
    max_duration: int = 900
    # Dedup / rotation
    artist_cooldown: int = 3
    title_similarity: float = 0.85
    failed_url_cooldown_hours: int = 6
    # User cooldown
    user_cooldown_seconds: int = 10


CFG = KomaConfig(
    min_score=_env_int("KOMA_MIN_SCORE", 30),
    fallback_min_score=_env_int("KOMA_FALLBACK_MIN_SCORE", 15),
    max_queries=_env_int("KOMA_MAX_QUERIES", 10),
    results_per_query=_env_int("KOMA_RESULTS_PER_QUERY", 15),
    search_concurrency=_env_int("KOMA_SEARCH_CONCURRENCY", 4),
    request_timeout=_env_int("KOMA_REQUEST_TIMEOUT", 30),
    max_attempts=_env_int("KOMA_MAX_ATTEMPTS", 30),
    min_duration=_env_int("KOMA_MIN_DURATION", 20),
    max_duration=_env_int("KOMA_MAX_DURATION", 900),
    artist_cooldown=_env_int("KOMA_ARTIST_COOLDOWN", 3),
    title_similarity=_env_float("KOMA_TITLE_SIM", 0.85),
    failed_url_cooldown_hours=_env_int("KOMA_FAILED_COOLDOWN_H", 6),
    user_cooldown_seconds=_env_int("KOMA_USER_COOLDOWN", 10),
)


# Optional SoundCloud OAuth token (helps with 401/429)
SOUNDCLOUD_OAUTH_TOKEN = os.getenv("SOUNDCLOUD_OAUTH_TOKEN", "").strip()


# ═══════════════════════════════════════════════════════════════════════
#  KOMA PROFILE
# ═══════════════════════════════════════════════════════════════════════

KOMA_KEYWORDS: Dict[str, int] = {
    # Strong identity words
    "coma": 20, "koma": 20, "کما": 20, "کمایی": 20,
    "dark ambient": 20, "deep ambient": 20,
    "emotional ambient": 20, "melancholic ambient": 20,
    "ethereal": 12, "atmospheric": 10,
    "dark piano": 18, "sad piano": 15, "lonely piano": 15,
    "atmospheric piano": 18, "cinematic": 10,
    "melancholic": 12, "nostalgic": 12,
    "dreamlike": 12, "lonely": 10,
    "slowed": 10, "reverb": 8,
    "ambient": 10, "piano": 10,
    "غمگین": 15, "غمگین": 15, "غمگين": 15,
    "احساسی": 10, "آرام": 8, "تنها": 10,
    "پیانو": 12, "سینمایی": 10, "خاطره": 8,
}

KOMA_NEGATIVE: Dict[str, int] = {
    "phonk": 60, "drift phonk": 70, "trap": 40,
    "hardstyle": 60, "hardcore": 50, "dubstep": 50,
    "edm": 40, "festival": 40, "hardwave": 50,
    "lofi": 25, "lofi beats": 30, "generic lofi": 30,
    "hip hop": 25, "hip-hop": 25, "rap": 25, "rapper": 30,
    "pop": 25, "dance": 20, "house": 15, "techno": 15,
    "podcast": 70, "comedy": 70, "asmr": 50,
    "audiobook": 70, "spoken word": 60, "interview": 50,
    "rock": 15, "metal": 30, "punk": 25,
}

# Hard-reject keywords (block regardless of score)
HARD_BLOCK: Tuple[str, ...] = (
    "phonk", "drift phonk", "hardstyle", "dubstep",
    "podcast", "comedy", "asmr", "audiobook", "spoken word",
)

CORE_ARTISTS: Tuple[str, ...] = (
    "øneheart", "oneheart", "reidenshi", "daniel.mp3", "antent",
    "my head is empty", ".diedlonely", "diedlonely", "leadwave",
    "ødyzon", "odyzon", "analog_mannequin", "analog mannequin",
    "tilekid", "bonjr",
)

ADDITIONAL_ARTISTS: Tuple[str, ...] = (
    "hisohkah", "alvedon", "willix", "futureville", "nectry", "unnholy",
    "hozuki", "pæntient", "enouement", "no mind state", "lmnl",
    "lowonlife", "flawed mangoes", "harris cole", "aso", "carl borg",
    "kazukii", "emile mosseri", "izzamuzzic", "hotel pools", "cody",
    "swik", "nate2timez", "richome", "ashess", "eleftherios",
    "next to blue", "cornwave",
)

QUERY_POOLS: Dict[str, List[Tuple[str, int]]] = {
    "artist": [(a, 3) for a in CORE_ARTISTS] + [(a, 2) for a in ADDITIONAL_ARTISTS[:15]],
    "deep_ambient": [
        ("deep coma ambient", 3), ("deep atmospheric ambient", 3),
        ("coma ambient", 3), ("deep dark ambient", 2),
        ("موسیقی کمایی", 3), ("موسیقی آرام عمیق", 3),
    ],
    "dark_emotional": [
        ("dark emotional ambient", 3), ("emotional dark ambient", 2),
        ("موسیقی احساسی بی‌کلام", 3), ("غمگین سینمایی", 2),
    ],
    "melancholic_piano": [
        ("melancholic piano", 3), ("lonely atmospheric piano", 3),
        ("sad cinematic piano", 3), ("پیانو غمگین سینمایی", 3),
    ],
    "ethereal": [
        ("ethereal dark ambient", 3), ("ethereal wave", 2),
        ("dreamlike melancholic music", 3),
    ],
    "cinematic": [
        ("emotional cinematic instrumental", 3),
        ("cinematic emotional ambient", 3),
        ("cinematic soundscape", 2),
    ],
    "nostalgic": [
        ("nostalgic ambient music", 3), ("nostalgic dark piano", 2),
        ("موسیقی خاطره‌انگیز", 3),
    ],
    "slowed_atmospheric": [
        ("slowed reverb atmospheric", 3), ("slowed ambient dark", 2),
        ("موسیقی اسلوموشن احساسی", 3),
    ],
    "unknown": [
        ("cold emotional soundscape", 3), ("lonely night ambient", 3),
        ("atmospheric reverb piano", 2), ("empty space ambient", 2),
    ],
    "new_release": [
        ("new dark ambient 2025", 3), ("new melancholic piano", 3),
    ],
}


# ═══════════════════════════════════════════════════════════════════════
#  UTILITIES
# ═══════════════════════════════════════════════════════════════════════

_PUNCT_RE = re.compile(r"[\(\)\[\]\{\}\|\-\_\.\,\!\?\:\;\"\'«»/\\]+")
_WS_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]")
_HTML_RE = re.compile(r"<[^>]*>")
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize(text: str) -> str:
    if not text:
        return ""
    text = str(text).lower().strip().translate(_PERSIAN_DIGITS)
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def sanitize(text: str, max_len: int = 64) -> str:
    if not text:
        return "Unknown"
    text = _CTRL_RE.sub("", str(text))
    text = _HTML_RE.sub("", text).strip()
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text or "Unknown"


def url_key(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════════
#  SCORING
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class TrackCandidate:
    sc_id: str
    title: str
    artist: str
    url: str
    duration: int = 0
    description: str = ""
    upload_date: Optional[str] = None
    tags: Tuple[str, ...] = ()
    score: int = 0
    breakdown: Dict[str, int] = field(default_factory=dict)


def _artist_in_reference(artist: str) -> bool:
    a = normalize(artist)
    if not a:
        return False
    for ref in CORE_ARTISTS + ADDITIONAL_ARTISTS:
        nref = normalize(ref)
        if nref and nref in a:
            return True
    return False


def _match_sum(blob: str, table: Dict[str, int]) -> int:
    return sum(w for k, w in table.items() if k in blob)


def hard_reject(c: TrackCandidate) -> bool:
    blob = normalize(f"{c.title} {c.artist}")
    if any(kw in blob for kw in HARD_BLOCK):
        return True
    if c.duration and not (CFG.min_duration <= c.duration <= CFG.max_duration):
        return True
    return False


def score_track(c: TrackCandidate) -> Tuple[int, Dict[str, int]]:
    """Return (0–100 score, breakdown)."""
    title_blob = normalize(c.title)
    artist_blob = normalize(c.artist)
    desc_blob = normalize(c.description or "")
    tags_blob = normalize(" ".join(c.tags or ()))
    full_blob = f"{title_blob} {artist_blob} {desc_blob} {tags_blob}"

    breakdown: Dict[str, int] = {}

    # 1. Artist in reference list — biggest signal (0–40)
    breakdown["artist_ref"] = 40 if _artist_in_reference(c.artist) else 0

    # 2. Title keywords (0–40)
    title_pts = min(40, _match_sum(title_blob, KOMA_KEYWORDS))
    breakdown["title_keywords"] = title_pts

    # 3. Description / tags (0–15)
    desc_pts = min(15, _match_sum(f"{desc_blob} {tags_blob}", KOMA_KEYWORDS))
    breakdown["desc_tags"] = desc_pts

    # 4. Duration appropriate (0–5)
    breakdown["duration"] = 5 if (c.duration and CFG.min_duration <= c.duration <= CFG.max_duration) else 0

    # Penalty for negatives
    negatives = _match_sum(full_blob, KOMA_NEGATIVE)
    penalty = negatives // 2
    breakdown["negative_penalty"] = -penalty

    score = max(0, min(100, sum(breakdown.values())))
    return score, breakdown


# ═══════════════════════════════════════════════════════════════════════
#  QUERY PLANNING
# ═══════════════════════════════════════════════════════════════════════

_recent_queries: List[str] = []
_RECENT_QUERY_WINDOW = 25


def _weighted_pick(pool: List[Tuple[str, int]], k: int) -> List[str]:
    items = list(pool)
    chosen: List[str] = []
    seen = set(_recent_queries)
    for _ in range(k):
        if not items:
            break
        available = [(q, w) for (q, w) in items if q not in seen]
        source = available or items
        total = sum(w for _, w in source)
        if total <= 0:
            break
        r = random.uniform(0, total)
        acc = 0.0
        picked = None
        for q, w in source:
            acc += w
            if r <= acc:
                picked = (q, w)
                break
        if picked is None:
            picked = source[-1]
        chosen.append(picked[0])
        items.remove(picked)
        seen.add(picked[0])
    return chosen


def plan_queries(total: int) -> List[str]:
    pools = list(QUERY_POOLS.keys())
    if "artist" not in pools:
        pools.insert(0, "artist")
    random.shuffle(pools)

    queries: List[str] = []
    per_pool = max(1, total // len(pools))
    remaining = total

    for pool_name in pools:
        if remaining <= 0:
            break
        pool = QUERY_POOLS.get(pool_name) or []
        take = min(per_pool, remaining)
        queries.extend(_weighted_pick(pool, take))
        remaining -= take

    if remaining > 0:
        flat = [q for pool in QUERY_POOLS.values() for q, _ in pool]
        queries.extend(_weighted_pick([(q, 1) for q in flat], remaining))

    _recent_queries.extend(queries)
    while len(_recent_queries) > _RECENT_QUERY_WINDOW:
        _recent_queries.pop(0)
    return queries


# ═══════════════════════════════════════════════════════════════════════
#  SOUNDCLOUD SEARCH
# ═══════════════════════════════════════════════════════════════════════

def _auth_opts() -> Dict[str, str]:
    if SOUNDCLOUD_OAUTH_TOKEN:
        return {"username": "oauth", "password": SOUNDCLOUD_OAUTH_TOKEN}
    return {}


def _sc_search_sync(query: str, max_results: int) -> List[TrackCandidate]:
    opts = {
        "quiet": True, "no_warnings": True, "extract_flat": True,
        "noplaylist": True, "ignoreerrors": True, "no_color": True,
        "socket_timeout": CFG.request_timeout, "retries": 3,
        **_auth_opts(),
    }
    out: List[TrackCandidate] = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"scsearch{max_results}:{query}", download=False,
            )
            for e in (info or {}).get("entries") or []:
                if not e:
                    continue
                url = e.get("url") or e.get("webpage_url")
                if not url or not e.get("id"):
                    continue
                dur = int(e.get("duration") or 0)
                if dur and not (CFG.min_duration <= dur <= CFG.max_duration):
                    continue
                out.append(TrackCandidate(
                    sc_id=str(e["id"]),
                    title=e.get("title") or "Unknown",
                    artist=e.get("uploader") or "Unknown Artist",
                    url=url,
                    duration=dur,
                    description=e.get("description") or "",
                    upload_date=e.get("upload_date"),
                    tags=tuple(e.get("tags") or ()),
                ))
    except Exception as exc:
        logger.warning("SC search failed for %r: %s", query, exc)
    return out


async def _gather_candidates(queries: List[str]) -> List[TrackCandidate]:
    sem = asyncio.Semaphore(CFG.search_concurrency)
    async def run(q):
        async with sem:
            return await asyncio.to_thread(_sc_search_sync, q, CFG.results_per_query)
    tasks = [run(q) for q in queries]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    seen, merged = set(), []
    for chunk in gathered:
        if isinstance(chunk, Exception):
            logger.warning("Query task failed: %s", chunk)
            continue
        for c in chunk:
            if c.sc_id in seen:
                continue
            seen.add(c.sc_id)
            merged.append(c)
    logger.info("KOMA gather: %d queries → %d candidates", len(queries), len(merged))
    return merged


# ═══════════════════════════════════════════════════════════════════════
#  DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════

def _download_soundcloud(url: str, output_template: str) -> Optional[dict]:
    """Try multiple quality levels, return download info or None."""
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
            "retries": 3, "fragment_retries": 3,
            "socket_timeout": 60,
            **_auth_opts(),
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
                if size < CFG.min_size_bytes or size > CFG.max_size_bytes:
                    try: os.remove(mp3)
                    except Exception: pass
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
        except Exception as e:
            logger.warning("Download fail (q=%s) for %s: %s", quality, url, e)
            p = output_template + ".mp3"
            if os.path.exists(p):
                try: os.remove(p)
                except Exception: pass
            continue
    return None


# ═══════════════════════════════════════════════════════════════════════
#  PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════

_failed_urls: Dict[str, float] = {}


def _is_failed_recent(url: str) -> bool:
    ts = _failed_urls.get(url_key(url))
    if not ts:
        return False
    return (time.time() - ts) < CFG.failed_url_cooldown_hours * 3600


def _mark_failed(url: str) -> None:
    _failed_urls[url_key(url)] = time.time()
    cutoff = time.time() - CFG.failed_url_cooldown_hours * 3600
    for k in [k for k, v in _failed_urls.items() if v < cutoff]:
        _failed_urls.pop(k, None)


async def was_sent(identifier: str) -> bool:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack.id).where(
                MusicTrack.identifier == identifier,
                MusicTrack.is_sent.is_(True),
            ).limit(1)
        )
        return res.scalar_one_or_none() is not None


async def recent_artists(limit: int) -> List[str]:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack.artist)
            .where(MusicTrack.is_sent.is_(True))
            .order_by(desc(MusicTrack.sent_at))
            .limit(limit)
        )
        return [normalize(a or "") for a in res.scalars().all()]


async def recent_tracks(limit: int) -> List[MusicTrack]:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack)
            .where(MusicTrack.is_sent.is_(True))
            .order_by(desc(MusicTrack.sent_at))
            .limit(limit)
        )
        return list(res.scalars().all())


async def is_title_duplicate(title: str, artist: str) -> bool:
    for t in await recent_tracks(50):
        sim = title_similarity(title, t.title or "")
        same_artist = normalize(artist) == normalize(t.artist or "")
        if same_artist and sim >= CFG.title_similarity:
            return True
        if sim >= 0.95:
            return True
    return False


async def is_artist_in_cooldown(artist: str) -> bool:
    a = normalize(artist)
    if not a:
        return False
    return a in await recent_artists(CFG.artist_cooldown)


async def record_send(identifier: str, title: str, artist: str,
                      url: str, filename: str = "", file_hash: str = "",
                      file_id: str = "") -> None:
    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        existing = (await session.execute(
            select(MusicTrack).where(MusicTrack.identifier == identifier)
        )).scalar_one_or_none()
        if existing:
            existing.is_sent = True
            existing.sent_at = now
            if file_id:
                existing.telegram_file_id = file_id
        else:
            session.add(MusicTrack(
                identifier=identifier, title=title, artist=artist,
                filename=filename, file_hash=file_hash,
                telegram_file_id=file_id or url,
                is_sent=True, sent_at=now,
            ))
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()


# ═══════════════════════════════════════════════════════════════════════
#  SEND
# ═══════════════════════════════════════════════════════════════════════

async def _send_audio(bot: Bot, chat_id: int, thread_id: Optional[int],
                      item: TrackCandidate, dl: dict) -> bool:
    title = sanitize(dl.get("title") or item.title, 64)
    artist = sanitize(dl.get("artist") or item.artist, 64)
    caption = f"🎵 {title}\n🎤 {artist}\n📀 SoundCloud\n🖤 KOMA | کُما"
    try:
        with open(dl["path"], "rb") as audio:
            sent = await bot.send_audio(
                chat_id=chat_id, audio=audio,
                title=title, performer=artist, caption=caption,
                read_timeout=300, write_timeout=300,
                message_thread_id=thread_id,
            )
        await record_send(
            identifier=item.sc_id,
            title=dl.get("title") or item.title,
            artist=dl.get("artist") or item.artist,
            url=item.url,
            filename=os.path.basename(dl["path"]),
            file_hash=dl["hash"],
            file_id=sent.audio.file_id if sent.audio else "",
        )
        return True
    except Exception as e:
        logger.error("send_audio failed: %s", e)
        return False
    finally:
        try: os.remove(dl["path"])
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

async def fetch_and_send_music(bot: Bot, chat_id: int,
                               thread_id: int = None) -> bool:
    """KOMA: find ONE qualified track, download audio, send it."""
    queries = plan_queries(CFG.max_queries)
    candidates = await _gather_candidates(queries)
    if not candidates:
        return False

    # Filter failed URLs
    candidates = [c for c in candidates if not _is_failed_recent(c.url)]
    if not candidates:
        return False

    # Hard reject + score
    scored: List[Tuple[TrackCandidate, int]] = []
    for c in candidates:
        if hard_reject(c):
            continue
        s, _ = score_track(c)
        scored.append((c, s))

    if not scored:
        return False

    scored.sort(key=lambda p: p[1], reverse=True)

    # Pass 1: strict
    for candidate, score in scored:
        if score < CFG.min_score:
            continue
        if await was_sent(candidate.sc_id):
            continue
        if await is_artist_in_cooldown(candidate.artist):
            logger.info("KOMA skip %r (artist cooldown)", candidate.title)
            continue
        if await is_title_duplicate(candidate.title, candidate.artist):
            logger.info("KOMA skip %r (title dup)", candidate.title)
            continue

        out = os.path.join(tempfile.gettempdir(), f"koma_{candidate.sc_id}")
        dl = await asyncio.to_thread(_download_soundcloud, candidate.url, out)
        if not dl:
            _mark_failed(candidate.url)
            continue
        if await _send_audio(bot, chat_id, thread_id, candidate, dl):
            logger.info("KOMA strict send: %r (score=%d)", candidate.title, score)
            return True
        _mark_failed(candidate.url)

    # Pass 2: fallback (still filtered, just lower threshold)
    for candidate, score in scored:
        if score < CFG.fallback_min_score:
            continue
        if await was_sent(candidate.sc_id):
            continue
        if await is_artist_in_cooldown(candidate.artist):
            continue
        if await is_title_duplicate(candidate.title, candidate.artist):
            continue

        out = os.path.join(tempfile.gettempdir(), f"koma_{candidate.sc_id}")
        dl = await asyncio.to_thread(_download_soundcloud, candidate.url, out)
        if not dl:
            _mark_failed(candidate.url)
            continue
        if await _send_audio(bot, chat_id, thread_id, candidate, dl):
            logger.info("KOMA fallback send: %r (score=%d)", candidate.title, score)
            return True
        _mark_failed(candidate.url)

    return False


async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str,
                                      thread_id: int = None) -> bool:
    """Music: exact search or URL. Sends audio file."""
    # Direct URL
    if query.startswith(("http://", "https://")):
        if "soundcloud.com" not in query:
            return False
        h = url_key(query)
        if await was_sent(h):
            return False
        out = os.path.join(tempfile.gettempdir(), f"koma_link_{h}")
        dl = await asyncio.to_thread(_download_soundcloud, query, out)
        if not dl:
            return False
        item = TrackCandidate(
            sc_id=h, title=dl["title"], artist=dl["artist"], url=query,
            duration=dl.get("duration", 0),
        )
        return await _send_audio(bot, chat_id, thread_id, item, dl)

    # Text search
    results = await asyncio.to_thread(_sc_search_sync, query, 20)
    if not results:
        return False

    words = normalize(query).split()

    def _score(c: TrackCandidate) -> int:
        t, a = normalize(c.title), normalize(c.artist)
        s = 0
        for w in words:
            if w in t: s += 2
            if w in a: s += 1
        return s

    results.sort(key=_score, reverse=True)

    for c in results:
        if await was_sent(c.sc_id):
            continue
        out = os.path.join(tempfile.gettempdir(), f"koma_q_{c.sc_id}")
        dl = await asyncio.to_thread(_download_soundcloud, c.url, out)
        if not dl:
            _mark_failed(c.url)
            continue
        if await _send_audio(bot, chat_id, thread_id, c, dl):
            return True
    return False


def get_koma_config() -> KomaConfig:
    return CFG


async def resolve_track_url(url: str) -> Optional[TrackCandidate]:
    if "soundcloud.com" not in url.lower():
        return None
    try:
        return await asyncio.to_thread(_sc_search_sync, url, 1) and None
    except Exception:
        return None
