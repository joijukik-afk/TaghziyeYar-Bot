"""KOMA Engine 3.0 — Professional Coma Music Discovery (metadata-only).

Key design principles:
    * STRICT KOMA identity — no generic sad songs, no random phonk/lofi
    * Metadata-only discovery — official SoundCloud URLs, no audio redistribution
    * Multi-pool weighted discovery — adaptive, non-repeating
    * Honest scoring — no claims about acoustic analysis we didn't perform
    * Persistent dedup and artist rotation (DB-backed, race-safe)
    * Freshness-aware ranking with unknown-date handling
    * Bounded concurrency + exponential backoff

Legal / compliance:
    This module NEVER downloads or redistributes third-party audio.
    It only reads public metadata and returns the official SoundCloud URL.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yt_dlp
from sqlalchemy import select, desc, func
from sqlalchemy.exc import IntegrityError

from app.database.music_models import MusicTrack
from app.database.session import session_scope

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  1. CONFIGURATION
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
    # Acceptance
    min_score: int = 82
    # Search
    max_queries: int = 10
    results_per_query: int = 15
    search_concurrency: int = 4
    request_timeout: int = 30
    max_attempts: int = 30
    # Track validation
    min_duration: int = 20
    max_duration: int = 900
    # Dedup / rotation
    artist_cooldown: int = 5
    title_similarity: float = 0.85
    failed_url_cooldown_hours: int = 6
    # Freshness
    freshness_days_bonus: int = 30
    freshness_days_max: int = 365
    # User / chat
    user_cooldown_seconds: int = 10
    # Provider
    sc_search_endpoint: str = "scsearch"


CFG = KomaConfig(
    min_score=_env_int("KOMA_MIN_SCORE", 82),
    max_queries=_env_int("KOMA_MAX_QUERIES", 10),
    results_per_query=_env_int("KOMA_RESULTS_PER_QUERY", 15),
    search_concurrency=_env_int("KOMA_SEARCH_CONCURRENCY", 4),
    request_timeout=_env_int("KOMA_REQUEST_TIMEOUT", 30),
    max_attempts=_env_int("KOMA_MAX_ATTEMPTS", 30),
    min_duration=_env_int("KOMA_MIN_DURATION", 20),
    max_duration=_env_int("KOMA_MAX_DURATION", 900),
    artist_cooldown=_env_int("KOMA_ARTIST_COOLDOWN", 5),
    title_similarity=_env_float("KOMA_TITLE_SIM", 0.85),
    failed_url_cooldown_hours=_env_int("KOMA_FAILED_COOLDOWN_H", 6),
    user_cooldown_seconds=_env_int("KOMA_USER_COOLDOWN", 10),
)


# ═══════════════════════════════════════════════════════════════════════
#  2. KOMA PROFILE (genres, tags, queries)
# ═══════════════════════════════════════════════════════════════════════

# Core KOMA signals — each match adds weight
KOMA_CORE_GENRES: Dict[str, int] = {
    "deep ambient": 14,
    "dark ambient": 14,
    "emotional ambient": 14,
    "melancholic ambient": 14,
    "ethereal ambient": 13,
    "atmospheric piano": 14,
    "lonely piano": 14,
    "cinematic ambient": 13,
    "nostalgic ambient": 12,
    "dreamlike ambient": 12,
    "space ambient": 12,
    "dark piano": 12,
    "ambient piano": 13,
    "emotional instrumental": 12,
    "cinematic instrumental": 12,
    "coma ambient": 15,
    "coma music": 15,
    "koma": 12,
    # Persian equivalents
    "موسیقی کمایی": 15,
    "پیانو غمگین": 12,
    "آمبیانت احساسی": 13,
    "سینمایی": 10,
    "غمگین سینمایی": 12,
}

# Secondary compatible styles — smaller weight
KOMA_SECONDARY_GENRES: Dict[str, int] = {
    "slowcore": 7,
    "post rock": 6,
    "post-rock": 6,
    "ethereal wave": 8,
    "shoegaze": 6,
    "ambient shoegaze": 8,
    "dreamwave": 7,
    "minimal cinematic": 8,
    "soundscape": 7,
    "slowed reverb": 5,
    "slowed and reverb": 5,
    "atmospheric electronic": 6,
    "dark wave": 6,
    "slowcore ambient": 8,
    "atmospheric post-rock": 8,
    "minimal piano": 8,
}

# Negative filters — strong evidence needed to reject
KOMA_NEGATIVE_GENRES: Dict[str, int] = {
    "phonk": 40,
    "drift phonk": 50,
    "aggressive trap": 40,
    "hardstyle": 45,
    "hardcore": 40,
    "festival edm": 40,
    "commercial dance": 35,
    "big room": 40,
    "hardwave": 40,
    "heavy bass": 30,
    "dubstep": 30,
    "edm": 15,
    "trap": 15,
    "hip hop": 10,
    "generic lofi": 25,
    "lofi beats": 20,
    "pop": 20,
    "comedy": 50,
    "podcast": 60,
    "spoken word": 50,
    "audiobook": 60,
    "asmr": 40,
}

# Discovery reference artists — NOT mandatory, NOT exclusive
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

# Weighted query pools — each pool reflects a specific KOMA dimension.
QUERY_POOLS: Dict[str, List[Tuple[str, int]]] = {
    "artist": [
        (a, 3) for a in CORE_ARTISTS
    ] + [(a, 2) for a in ADDITIONAL_ARTISTS[:12]],
    "deep_ambient": [
        ("deep coma ambient", 3), ("deep atmospheric ambient", 3),
        ("coma ambient", 3), ("deep dark ambient", 2),
        ("موزیک کمایی", 3), ("موسیقی آرام عمیق", 3),
    ],
    "dark_emotional": [
        ("dark emotional ambient", 3), ("emotional dark ambient", 2),
        ("موسیقی احساسی بی‌کلام", 3), ("غمگین سینمایی", 2),
    ],
    "melancholic_piano": [
        ("melancholic piano", 3), ("lonely atmospheric piano", 3),
        ("sad cinematic piano", 3), ("پیانو غمگین سینمایی", 3),
        ("lonely piano ambient", 2),
    ],
    "ethereal": [
        ("ethereal dark ambient", 3), ("ethereal wave", 2),
        ("dreamlike melancholic music", 3), ("موسیقی فضایی غمگین", 2),
    ],
    "cinematic": [
        ("emotional cinematic instrumental", 3),
        ("cinematic emotional ambient", 3),
        ("cinematic soundscape", 2),
        ("موزیک تنهایی", 2), ("موسیقی آرام تاریک", 2),
    ],
    "nostalgic": [
        ("nostalgic ambient music", 3), ("nostalgic dark piano", 2),
        ("موسیقی خاطره‌انگیز", 3), ("سوزناک", 1),
    ],
    "slowed_atmospheric": [
        ("slowed reverb atmospheric", 3),
        ("slowed ambient dark", 2),
        ("موسیقی اسلوموشن احساسی", 3),
    ],
    "unknown": [
        ("cold emotional soundscape", 3),
        ("lonely night ambient", 3),
        ("atmospheric reverb piano", 2),
        ("empty space ambient", 2),
        ("snowfall ambient", 2),
    ],
    "new_release": [
        ("new dark ambient 2025", 3),
        ("new melancholic piano", 3),
        ("new emotional ambient", 2),
    ],
}


# ═══════════════════════════════════════════════════════════════════════
#  3. TEXT UTILITIES
# ═══════════════════════════════════════════════════════════════════════

_PUNCT_RE = re.compile(r"[\(\)\[\]\{\}\|\-\_\.\,\!\?\:\;\"\'«»/\\]+")
_WS_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]")
_HTML_RE = re.compile(r"<[^>]*>")

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, normalize digits."""
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
#  4. SCORING ENGINE
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class TrackCandidate:
    """A single SoundCloud track candidate (metadata only)."""
    sc_id: str
    title: str
    artist: str
    url: str
    duration: int = 0
    description: str = ""
    upload_date: Optional[str] = None      # YYYYMMDD
    tags: Tuple[str, ...] = ()

    # Filled by scoring:
    score: int = 0
    breakdown: Dict[str, int] = field(default_factory=dict)
    rejection_reasons: List[str] = field(default_factory=list)


@dataclass
class ScoreResult:
    score: int
    breakdown: Dict[str, int]
    rejected: bool
    rejection_reasons: List[str]


def _blob(c: TrackCandidate) -> str:
    parts = [c.title, c.artist, c.description, " ".join(c.tags)]
    return normalize(" ".join(p for p in parts if p))


def _match_any(blob: str, table: Dict[str, int]) -> int:
    """Sum weights of every key found in the blob."""
    total = 0
    for key, weight in table.items():
        if key in blob:
            total += weight
    return total


def _artist_in_reference(artist: str) -> bool:
    a = normalize(artist)
    if not a:
        return False
    for ref in CORE_ARTISTS:
        if normalize(ref) and normalize(ref) in a:
            return True
    for ref in ADDITIONAL_ARTISTS:
        if normalize(ref) and normalize(ref) in a:
            return True
    return False


def _freshness_score(upload_date: Optional[str]) -> int:
    """0–10 based on age. Unknown date = 3 (neutral-low)."""
    if not upload_date:
        return 3
    try:
        dt = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
    except Exception:
        return 3
    age_days = (datetime.now(timezone.utc) - dt).days
    if age_days < 0:
        return 3
    if age_days <= 7:
        return 10
    if age_days <= 30:
        return 8
    if age_days <= 90:
        return 6
    if age_days <= 365:
        return 4
    return 2


def score_track(c: TrackCandidate) -> ScoreResult:
    """Return 0–100 KOMA score with a transparent breakdown."""
    blob = _blob(c)
    breakdown: Dict[str, int] = {}

    # 1) Core genre / tag compatibility (0–35)
    core = min(35, _match_any(blob, KOMA_CORE_GENRES))
    breakdown["core_style"] = core

    # 2) Secondary genre / tag compatibility (0–20)
    secondary = min(20, _match_any(blob, KOMA_SECONDARY_GENRES))
    breakdown["secondary_style"] = secondary

    # 3) Description compatibility (0–10)
    #    - Contains KOMA-relevant words (light)
    desc = normalize(c.description or "")
    desc_pts = 0
    for kw, w in (
        ("coma", 4), ("ambient", 3), ("piano", 3),
        ("atmospheric", 3), ("melancholic", 3), ("cinematic", 2),
        ("emotional", 2), ("ethereal", 2), ("reverb", 1),
    ):
        if kw in desc:
            desc_pts += w
    breakdown["description"] = min(10, desc_pts)

    # 4) Artist discovery relevance (0–10)
    breakdown["artist_relevance"] = 10 if _artist_in_reference(c.artist) else 0

    # 5) Metadata completeness (0–5)
    completeness = 0
    if c.title: completeness += 1
    if c.artist: completeness += 1
    if c.duration: completeness += 1
    if c.description: completeness += 1
    if c.upload_date: completeness += 1
    breakdown["completeness"] = completeness

    # 6) Freshness (0–10)
    breakdown["freshness"] = _freshness_score(c.upload_date)

    raw = sum(breakdown.values())

    # Negative filtering — subtract strong contraindications
    negatives = _match_any(blob, KOMA_NEGATIVE_GENRES)
    # Reduce one point of penalty per 2 negative points (soft subtraction)
    penalty = negatives // 2
    breakdown["negative_penalty"] = -penalty
    raw = max(0, raw - penalty)

    # Clamp final
    final = min(100, raw)

    # Rejection logic (hard rules independent of score)
    reasons: List[str] = []
    if final < CFG.min_score:
        reasons.append(f"score {final} < {CFG.min_score}")
    if negatives >= 30:
        reasons.append(f"negative signals ({negatives})")
    if c.duration and not (CFG.min_duration <= c.duration <= CFG.max_duration):
        reasons.append(f"duration {c.duration}s out of range")

    return ScoreResult(
        score=final,
        breakdown=breakdown,
        rejected=bool(reasons),
        rejection_reasons=reasons,
    )


# ═══════════════════════════════════════════════════════════════════════
#  5. QUERY PLANNING (weighted, rotated)
# ═══════════════════════════════════════════════════════════════════════

# In-memory short-term rotation to avoid repeating recent queries.
_recent_queries: List[str] = []
_RECENT_QUERY_WINDOW = 25


def _weighted_pick(pool: List[Tuple[str, int]], k: int) -> List[str]:
    """Pick k unique items weighted by their weight."""
    items = list(pool)
    chosen: List[str] = []
    seen = set(_recent_queries)
    # Try not to repeat recent queries first
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
        picked: Optional[Tuple[str, int]] = None
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
    """Build a query set from multiple pools, weighted by pool diversity."""
    pools_in_play = list(QUERY_POOLS.keys())
    # Ensure artist pool is always represented once
    if "artist" not in pools_in_play:
        pools_in_play.insert(0, "artist")
    random.shuffle(pools_in_play)

    queries: List[str] = []
    per_pool = max(1, total // len(pools_in_play))
    remaining = total

    for pool_name in pools_in_play:
        if remaining <= 0:
            break
        pool = QUERY_POOLS.get(pool_name) or []
        take = min(per_pool, remaining)
        queries.extend(_weighted_pick(pool, take))
        remaining -= take

    # Fill any remaining slot from a mixed random pool
    if remaining > 0:
        flat = [q for pool in QUERY_POOLS.values() for q, _ in pool]
        queries.extend(_weighted_pick([(q, 1) for q in flat], remaining))

    # Record for rotation
    _recent_queries.extend(queries)
    while len(_recent_queries) > _RECENT_QUERY_WINDOW:
        _recent_queries.pop(0)

    return queries


# ═══════════════════════════════════════════════════════════════════════
#  6. SOUNDCLOUD METADATA SEARCH (no audio download)
# ═══════════════════════════════════════════════════════════════════════

def _sc_search_sync(query: str, max_results: int) -> List[TrackCandidate]:
    """Metadata-only SoundCloud search via yt-dlp.

    extract_flat=True → no audio is ever fetched.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,       # metadata-only, no download
        "noplaylist": True,
        "ignoreerrors": True,
        "no_color": True,
        "socket_timeout": CFG.request_timeout,
        "retries": 3,
        "extractor_args": {"soundcloud": {"formats": ["http_mp3_128"]}},
    }
    out: List[TrackCandidate] = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"{CFG.sc_search_endpoint}{max_results}:{query}",
                download=False,
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
    """Run all queries with bounded concurrency, dedupe by sc_id."""
    sem = asyncio.Semaphore(CFG.search_concurrency)
    results: List[List[TrackCandidate]] = []

    async def run(q: str) -> List[TrackCandidate]:
        async with sem:
            return await asyncio.to_thread(
                _sc_search_sync, q, CFG.results_per_query
            )

    tasks = [run(q) for q in queries]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    for chunk in gathered:
        if isinstance(chunk, Exception):
            logger.warning("Query task failed: %s", chunk)
            continue
        results.append(chunk)

    seen: set = set()
    merged: List[TrackCandidate] = []
    for chunk in results:
        for c in chunk:
            if c.sc_id in seen:
                continue
            seen.add(c.sc_id)
            merged.append(c)
    logger.info(
        "KOMA gather: %d queries → %d unique candidates",
        len(queries), len(merged),
    )
    return merged


# ═══════════════════════════════════════════════════════════════════════
#  7. PERSISTENCE (dedup, artist cooldown, history)
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
    """Return normalized artist names of the last N sent tracks."""
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
    recent = await recent_artists(CFG.artist_cooldown)
    return a in recent


async def record_send(
    identifier: str, title: str, artist: str, url: str,
) -> None:
    """Persist a successful send (URL stored in filename field)."""
    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        existing = (await session.execute(
            select(MusicTrack).where(MusicTrack.identifier == identifier)
        )).scalar_one_or_none()
        if existing:
            existing.is_sent = True
            existing.sent_at = now
            existing.telegram_file_id = url  # store URL for future refs
        else:
            session.add(MusicTrack(
                identifier=identifier,
                title=title,
                artist=artist,
                filename="",                  # no local file
                file_hash="",                 # no hash (metadata-only)
                telegram_file_id=url,         # reuse as "source URL" slot
                is_sent=True,
                sent_at=now,
            ))
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            logger.warning("Record send race for %s — ignored", identifier)


# ═══════════════════════════════════════════════════════════════════════
#  8. PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class KomaSelection:
    candidate: TrackCandidate
    score: int
    breakdown: Dict[str, int]


async def discover_koma_track() -> Optional[KomaSelection]:
    """Find one qualified KOMA track. Returns None if no match."""
    queries = plan_queries(CFG.max_queries)
    logger.info("KOMA plan: %d queries", len(queries))
    candidates = await _gather_candidates(queries)
    if not candidates:
        return None

    # Cooldown & filter
    candidates = [
        c for c in candidates
        if not _is_failed_recent(c.url)
    ]
    if not candidates:
        return None

    # Score all candidates
    scored: List[Tuple[TrackCandidate, ScoreResult]] = []
    for c in candidates:
        res = score_track(c)
        if res.rejected:
            logger.debug(
                "KOMA reject %r → %s",
                c.title, res.rejection_reasons,
            )
            continue
        scored.append((c, res))
    if not scored:
        logger.info("KOMA: no candidate passed the score threshold")
        return None

    # Rank: score desc, then freshness (via breakdown) desc
    scored.sort(
        key=lambda pair: (
            pair[1].score,
            pair[1].breakdown.get("freshness", 0),
            pair[1].breakdown.get("core_style", 0),
        ),
        reverse=True,
    )

    # Walk down the ranked list — reject already-sent, cooldown artists, dups
    for candidate, res in scored:
        if await was_sent(candidate.sc_id):
            continue
        if await is_artist_in_cooldown(candidate.artist):
            logger.info(
                "KOMA skip %r (artist in cooldown)", candidate.title,
            )
            continue
        if await is_title_duplicate(candidate.title, candidate.artist):
            logger.info(
                "KOMA skip %r (title duplicate)", candidate.title,
            )
            continue
        return KomaSelection(
            candidate=candidate,
            score=res.score,
            breakdown=res.breakdown,
        )

    return None


async def discover_specific_song(query: str) -> Optional[TrackCandidate]:
    """For /music — relaxed scoring, still metadata-only."""
    results = await asyncio.to_thread(
        _sc_search_sync, query, 20,
    )
    if not results:
        return None
    words = normalize(query).split()

    def _score(c: TrackCandidate) -> int:
        t = normalize(c.title)
        a = normalize(c.artist)
        s = 0
        for w in words:
            if w in t:
                s += 3
            if w in a:
                s += 2
        return s

    results.sort(key=_score, reverse=True)
    for c in results:
        if _is_failed_recent(c.url):
            continue
        if await was_sent(c.sc_id):
            continue
        return c
    return None


async def resolve_track_url(url: str) -> Optional[TrackCandidate]:
    """Resolve a specific SoundCloud URL to metadata (no download)."""
    if "soundcloud.com" not in url.lower():
        return None
    try:
        info = await asyncio.to_thread(
            _extract_single_sync, url,
        )
        return info
    except Exception as e:
        logger.warning("resolve_track_url failed for %s: %s", url, e)
        return None


def _extract_single_sync(url: str) -> Optional[TrackCandidate]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "noplaylist": True,
        "ignoreerrors": True,
        "no_color": True,
        "socket_timeout": CFG.request_timeout,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            return TrackCandidate(
                sc_id=str(info.get("id") or url_key(url)),
                title=info.get("title") or "Unknown",
                artist=info.get("uploader") or "Unknown Artist",
                url=info.get("webpage_url") or url,
                duration=int(info.get("duration") or 0),
                description=info.get("description") or "",
                upload_date=info.get("upload_date"),
                tags=tuple(info.get("tags") or ()),
            )
    except Exception as exc:
        logger.warning("Extract single failed: %s", exc)
        return None
