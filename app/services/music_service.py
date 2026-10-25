"""موتور جستجوی ۵ منبعی KOMA (Audius + SoundCloud + YouTube + Bandcamp + Archive)"""

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

SEARCH_QUERIES = [
    "Øneheart slowed reverb",
    "reidenshi slowed reverb",
    "dreamcore slowed reverb",
    "dark ambient music",
    "liminal space music",
    "sad slowed reverb",
    "my head is empty slowed",
    "analog_mannequin milk cassette",
    "melancholic ambient",
    "the last of us ambient guitar",
    "غمگین ایرانی slowed"
]

ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"
MAX_SIZE = 45 * 1024 * 1024
MIN_SIZE = 1024 * 1024

async def _is_used(identifier: str, title: str, artist: str) -> bool:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack).where((MusicTrack.identifier == identifier) & (MusicTrack.is_sent == True))
        )
        if res.scalar_one_or_none() is not None:
            return True
        if title and artist and artist != "Unknown Artist":
            res2 = await session.execute(
                select(MusicTrack).where(
                    (MusicTrack.title.ilike(f"%{title[:15]}%")) & 
                    (MusicTrack.artist.ilike(f"%{artist[:15]}%")) &
                    (MusicTrack.is_sent == True)
                )
            )
            if res2.scalar_one_or_none() is not None:
                return True
        return False

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
                identifier=data["identifier"], title=data["title"], artist=data["artist"],
                filename=data.get("filename", ""), file_hash=data["hash"],
                telegram_file_id=file_id, is_sent=True, sent_at=datetime.utcnow()
            ))
        await session.flush()

# ==================== ۱. Audius API ====================
async def _search_audius(query: str) -> List[Dict]:
    url = "https://discoveryprovider.audius.co/v1/tracks/search"
    params = {"query": query, "app_name": "KOMA"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                tracks = data.get("data", [])
                logger.info(f"Audius: {len(tracks)} results for '{query}'")
                return [{
                    "id": f"audius_{t.get('id')}",
                    "title": t.get("title", "Unknown"),
                    "artist": t.get("user", {}).get("name", "Unknown Artist"),
                    "source": "Audius",
                    "stream_url": f"https://discoveryprovider.audius.co/v1/tracks/{t['id']}/stream?app_name=KOMA"
                } for t in tracks if t.get("is_streamable")]
    except Exception as e:
        logger.warning(f"Audius search failed: {e}")
    return []

# ==================== ۲. yt-dlp (YouTube, SoundCloud, Bandcamp) ====================
def _search_with_ytdlp(query: str, source_prefix: str) -> List[Dict]:
    ydl_opts = {
        'quiet': True, 'no_warnings': True, 'extract_flat': True, 'noplaylist': True,
        'extractor_args': {'youtube': {'player_client': ['ios', 'android', 'mweb']}}
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"{source_prefix}5:{query}", download=False)
            res = []
            for e in info.get('entries', []):
                if not e: continue
                url = e.get('url') or e.get('webpage_url')
                if url:
                    res.append({
                        "id": str(e.get('id')),
                        "title": e.get('title', 'Unknown'),
                        "artist": e.get('uploader', 'Unknown Artist'),
                        "url": url,
                        "source": source_prefix.replace("search", "").capitalize()
                    })
            logger.info(f"{source_prefix}: {len(res)} results for '{query}'")
            return res
    except Exception as e:
        logger.warning(f"{source_prefix} search failed: {e}")
        return []

# ==================== ۳. Archive.org ====================
async def _search_archive(query: str) -> List[Dict]:
    q = f'mediatype:audio AND format:MP3 AND ({query}) AND length:[180 TO 7200]'
    params = {"q": q, "fl[]": ["identifier", "title", "creator"], "sort[]": "downloads desc", "rows": 3, "output": "json"}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(ARCHIVE_SEARCH_URL, params=params, timeout=10.0)
            docs = r.json().get("response", {}).get("docs", [])
            logger.info(f"Archive: {len(docs)} results for '{query}'")
            return [{"id": d.get("identifier"), "title": d.get("title", "Unknown"), "artist": d.get("creator", "Unknown Artist"), "source": "Archive.org"} for d in docs]
    except Exception as e:
        logger.warning(f"Archive search failed: {e}")
        return []

# ==================== دانلود ====================
def _download_ytdlp(url: str, output_template: str) -> Optional[dict]:
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'outtmpl': output_template, 'quiet': True, 'no_warnings': True,
        'extractor_args': {'youtube': {'player_client': ['ios', 'android', 'mweb']}},
        'match_filter': yt_dlp.utils.match_filter_func("duration > 60 & duration < 1200"),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info: return None
            mp3_path = output_template + '.mp3'
            if os.path.exists(mp3_path):
                size = os.path.getsize(mp3_path)
                if not (MIN_SIZE <= size <= MAX_SIZE):
                    os.remove(mp3_path); return None
                sha = hashlib.sha256()
                with open(mp3_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(8192), b''):
                        sha.update(chunk)
                return {
                    "path": mp3_path, "hash": sha.hexdigest(), "size": size,
                    "title": info.get('title', 'Unknown'), "artist": info.get('uploader', 'Unknown Artist')
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
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return {"path": output_path, "hash": sha.hexdigest(), "size": total}
    except Exception as e:
        logger.error(f"Audius download error: {e}")
    return None

# ==================== تابع اصلی ====================
async def fetch_and_send_music(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    # ۳ کوئری تصادفی برای شانس بیشتر
    queries = random.sample(SEARCH_QUERIES, min(3, len(SEARCH_QUERIES)))
    
    for query in queries:
        logger.info(f"=== Searching for: {query} ===")
        
        # جستجوی موازی در همه منابع
        audius_task = _search_audius(query)
        archive_task = _search_archive(query)
        
        audius_res, archive_res = await asyncio.gather(audius_task, archive_task)
        
        yt_res = await asyncio.to_thread(_search_with_ytdlp, query, "ytsearch")
        sc_res = await asyncio.to_thread(_search_with_ytdlp, query, "scsearch")
        bc_res = await asyncio.to_thread(_search_with_ytdlp, query, "bcsearch")

        # اولویت‌بندی: Audius > SoundCloud > YouTube > Bandcamp > Archive
        candidates = []
        candidates.extend(audius_res)
        candidates.extend(sc_res)
        candidates.extend(yt_res)
        candidates.extend(bc_res)
        candidates.extend(archive_res)

        if not candidates:
            continue

        random.shuffle(candidates)

        for item in candidates:
            identifier = item["id"]
            title = item["title"]
            artist = item["artist"]

            if await _is_used(identifier, title, artist):
                continue

            logger.info(f"Attempting to download: {title} from {item['source']}")
            dl = None

            if item["source"] == "Audius":
                output_path = os.path.join(tempfile.gettempdir(), f"koma_{identifier}.mp3")
                dl = await _download_audius(item["stream_url"], output_path)
                if dl: dl["title"] = title; dl["artist"] = artist
            elif item["source"] in ["Youtube", "Soundcloud", "Bandcamp"]:
                url = item.get("url")
                if not url: continue
                output_template = os.path.join(tempfile.gettempdir(), f"koma_{identifier}")
                dl = await asyncio.to_thread(_download_ytdlp, url, output_template)
                if dl: dl["title"] = dl.get("title", title); dl["artist"] = dl.get("artist", artist)
            elif item["source"] == "Archive.org":
                continue

            if not dl: continue

            try:
                with open(dl["path"], "rb") as audio:
                    sent = await bot.send_audio(
                        chat_id=chat_id, audio=audio,
                        title=dl['title'][:64], performer=dl['artist'][:64],
                        caption=f"🎵 <b>{dl['title']}</b>\n🎤 {dl['artist']}\n📦 {item['source']}\n🌌 KOMA | کُما",
                        parse_mode=ParseMode.HTML,
                        read_timeout=120, write_timeout=120, connect_timeout=30,
                        message_thread_id=thread_id
                    )

                await _record_track({
                    "identifier": identifier, "title": dl["title"], "artist": dl["artist"],
                    "filename": os.path.basename(dl["path"]), "hash": dl["hash"],
                }, sent.audio.file_id)

                try: os.remove(dl["path"])
                except: pass
                return True

            except Exception as e:
                logger.error(f"send_audio failed: {e}")
                try: os.remove(dl["path"])
                except: pass

    return False
