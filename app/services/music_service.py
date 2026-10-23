"""موتور جستجوی چندمنبعی KOMA (SoundCloud, Bandcamp, Archive.org)"""

import os
import random
import hashlib
import logging
import tempfile
import asyncio
from typing import Optional, List, Dict

import httpx
import yt_dlp
from sqlalchemy import select
from telegram import Bot
from telegram.constants import ParseMode

from app.database.music_models import MusicTrack
from app.database.session import session_scope

logger = logging.getLogger(__name__)

# 👇 لیست دقیق سبک‌ها و هنرمندان درخواستی شما
SEARCH_QUERIES = [
    # هنرمندان معروف و درخواستی
    "Øneheart slowed reverb",
    "reidenshi slowed reverb",
    "my head is empty slowed reverb",
    "daniel.mp3 slowed reverb",
    "analog_mannequin slowed reverb",
    "TileKid slowed reverb",
    "Bonjr slowed reverb",
    ".diedlonely slowed reverb",
    "Lloyd Vaan slowed reverb",
    
    # سبک‌های خاص درخواستی
    "dark dreamy slowed reverb",
    "coma vibe slowed reverb",
    "dreamcore slowed reverb",
    "ethereal wave slowed reverb",
    "liminal dreamcore slowed reverb",
    "dreamcore ambient slowed reverb",
    
    # آهنگ‌های غمگین و ایرانی
    "sad slowed reverb playlist",
    "melancholic ambient slowed reverb",
    "غمگین ایرانی slowed reverb",
    "dark snowy night slowed reverb",
    
    # نسخه‌های طولانی و ریمیکس
    "snowfall extended slowed reverb",
    "dreamcore slowed reverb remix"
]

ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"
ARCHIVE_META_URL = "https://archive.org/metadata/{identifier}"
ARCHIVE_DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"

MAX_SIZE = 45 * 1024 * 1024
MIN_SIZE = 1024 * 1024

async def _is_used(video_id: str) -> bool:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack).where(
                (MusicTrack.identifier == video_id) & (MusicTrack.is_sent == True)
            )
        )
        return res.scalar_one_or_none() is not None

async def _record_track(data: dict, file_id: str) -> None:
    from datetime import datetime
    async with session_scope() as session:
        existing = await session.execute(
            select(MusicTrack).where(MusicTrack.identifier == data["identifier"])
        )
        track = existing.scalar_one_or_none()
        if track:
            track.telegram_file_id = file_id
            track.is_sent = True
            track.sent_at = datetime.utcnow()
        else:
            session.add(MusicTrack(
                identifier=data["identifier"],
                title=data["title"],
                artist=data["artist"],
                filename=data.get("filename", ""),
                file_hash=data["hash"],
                telegram_file_id=file_id,
                is_sent=True,
                sent_at=datetime.utcnow()
            ))
        await session.flush()

def _download_with_ytdlp(url: str, output_template: str) -> Optional[dict]:
    """دانلود از SoundCloud یا Bandcamp"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            mp3_path = output_template + '.mp3'
            if os.path.exists(mp3_path):
                size = os.path.getsize(mp3_path)
                if not (MIN_SIZE <= size <= MAX_SIZE):
                    os.remove(mp3_path)
                    return None
                sha = hashlib.sha256()
                with open(mp3_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(8192), b''):
                        sha.update(chunk)
                return {
                    "path": mp3_path,
                    "hash": sha.hexdigest(),
                    "size": size,
                    "title": info.get('title', 'Unknown'),
                    "artist": info.get('uploader', 'Unknown Artist'),
                    "video_id": info.get('id'),
                }
    except Exception as e:
        logger.error(f"yt-dlp download error for {url}: {e}")
    return None

def _search_soundcloud(query: str, max_results: int = 5) -> List[Dict]:
    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"scsearch{max_results}:{query}", download=False)
            return [{
                "id": e.get('id'),
                "title": e.get('title', 'Unknown'),
                "uploader": e.get('uploader', 'Unknown Artist'),
                "url": e.get('url') or e.get('webpage_url'),
                "source": "SoundCloud",
            } for e in info.get('entries', []) if e]
    except Exception as e:
        logger.warning(f"SoundCloud search failed: {e}")
        return []

def _search_bandcamp(query: str, max_results: int = 5) -> List[Dict]:
    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"bcsearch{max_results}:{query}", download=False)
            return [{
                "id": e.get('id'),
                "title": e.get('title', 'Unknown'),
                "uploader": e.get('uploader', 'Unknown Artist'),
                "url": e.get('url') or e.get('webpage_url'),
                "source": "Bandcamp",
            } for e in info.get('entries', []) if e]
    except Exception as e:
        logger.warning(f"Bandcamp search failed: {e}")
        return []

async def _search_archive(query: str, max_results: int = 5) -> List[Dict]:
    q = f'mediatype:audio AND format:MP3 AND ({query}) AND length:[180 TO 7200]'
    params = {
        "q": q,
        "fl[]": ["identifier", "title", "creator"],
        "sort[]": "downloads desc",
        "rows": max_results,
        "output": "json",
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(ARCHIVE_SEARCH_URL, params=params, timeout=15.0)
            docs = r.json().get("response", {}).get("docs", [])
            return [{
                "id": d.get("identifier"),
                "title": d.get("title", "Unknown"),
                "uploader": d.get("creator", "Unknown Artist"),
                "url": None,
                "source": "Archive.org",
            } for d in docs]
    except Exception as e:
        logger.warning(f"Archive.org search failed: {e}")
        return []

async def _download_from_archive(identifier: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(ARCHIVE_META_URL.format(identifier=identifier), timeout=15.0)
            meta = r.json()
        files = meta.get("files", [])
        mp3 = None
        for f in files:
            if f.get("name", "").lower().endswith(".mp3"):
                size = int(f.get("size", 0))
                if MIN_SIZE <= size <= MAX_SIZE:
                    mp3 = {"name": f["name"], "size": size}
                    break
        if not mp3:
            return None

        url = ARCHIVE_DOWNLOAD_URL.format(identifier=identifier, filename=mp3["name"])
        local_path = os.path.join(tempfile.gettempdir(), f"koma_{identifier}.mp3")

        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url, timeout=60.0, follow_redirects=True) as resp:
                resp.raise_for_status()
                sha = hashlib.sha256()
                total = 0
                with open(local_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        total += len(chunk)
                        if total > MAX_SIZE:
                            f.close()
                            os.remove(local_path)
                            return None
                        f.write(chunk)
                        sha.update(chunk)

        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            return {"path": local_path, "hash": sha.hexdigest(), "size": total}
    except Exception as e:
        logger.error(f"Archive download failed: {e}")
        if os.path.exists(local_path):
            try: os.remove(local_path)
            except: pass
    return None

async def fetch_and_send_music(bot: Bot, chat_id: int) -> bool:
    query = random.choice(SEARCH_QUERIES)
    logger.info(f"Searching all sources for: {query}")

    sc_task = asyncio.to_thread(_search_soundcloud, query, 5)
    bc_task = asyncio.to_thread(_search_bandcamp, query, 5)
    ar_task = _search_archive(query, 5)

    sc_results, bc_results, ar_results = await asyncio.gather(sc_task, bc_task, ar_task)

    candidates = []
    for res_list, source in [(sc_results, "SoundCloud"), (bc_results, "Bandcamp"), (ar_results, "Archive.org")]:
        for item in res_list:
            if item and item.get("id"):
                item["source"] = source
                candidates.append(item)

    if not candidates:
        logger.warning(f"No results found for: {query}")
        return False

    random.shuffle(candidates)

    for item in candidates:
        identifier = item["id"]
        if await _is_used(identifier):
            continue

        logger.info(f"Attempting to download: {item['title']} from {item['source']}")

        if item["source"] == "Archive.org":
            dl = await _download_from_archive(identifier)
            if not dl: continue
            title = item["title"]
            artist = item["uploader"]
        else:
            url = item.get("url")
            if not url: continue
            output_template = os.path.join(tempfile.gettempdir(), f"koma_{identifier}")
            dl = await asyncio.to_thread(_download_with_ytdlp, url, output_template)
            if not dl: continue
            title = dl["title"]
            artist = dl["artist"]

        if not dl: continue

        try:
            with open(dl["path"], "rb") as audio:
                sent = await bot.send_audio(
                    chat_id=chat_id,
                    audio=audio,
                    title=title[:64],
                    performer=artist[:64],
                    caption=(
                        f"🎵 <b>{title}</b>\n"
                        f"🎤 {artist}\n"
                        f"📦 منبع: {item['source']}\n"
                        f"🌌 KOMA | کُما"
                    ),
                    parse_mode=ParseMode.HTML,
                    read_timeout=120, write_timeout=120, connect_timeout=30,
                )

            await _record_track({
                "identifier": identifier,
                "title": title,
                "artist": artist,
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

    return False
