"""سرویس دریافت آهنگ از Internet Archive (تضمینی، بدون نیاز به API Key و یوتیوب)"""

import os
import random
import hashlib
import logging
import tempfile
from typing import Optional

import httpx
from sqlalchemy import select
from telegram import Bot
from telegram.constants import ParseMode

from app.database.music_models import MusicTrack
from app.database.session import session_scope

logger = logging.getLogger(__name__)

SEARCH_URL = "https://archive.org/advancedsearch.php"
META_URL = "https://archive.org/metadata/{identifier}"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"

# 👇 ترفند اصلی: جستجو در آهنگ‌های واقعی که بین ۳ تا ۱۰ دقیقه هستن!
QUERIES = [
    'mediatype:audio AND (subject:dreamcore OR subject:weirdcore) AND length:[180 TO 600]',
    'mediatype:audio AND (subject:"dark ambient" OR subject:"dark ambient music") AND length:[180 TO 600]',
    'mediatype:audio AND (subject:"slowed reverb" OR subject:"slowed and reverb") AND length:[180 TO 600]',
    'mediatype:audio AND (subject:"post apocalyptic" OR subject:melancholic) AND length:[180 TO 600]',
    'mediatype:audio AND (subject:liminal OR subject:"liminal space") AND length:[180 TO 600]',
    'mediatype:audio AND (subject:"ethereal wave" OR subject:ethereal) AND length:[180 TO 600]'
]

# فایل‌های بین ۲ مگابایت تا ۴۵ مگابایت (تضمینی که آهنگ هست، نه یک فایل ۱۰ ثانیه‌ای)
MAX_SIZE = 45 * 1024 * 1024
MIN_SIZE = 2 * 1024 * 1024

async def _is_used(identifier: str) -> bool:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack).where(
                (MusicTrack.identifier == identifier) & (MusicTrack.is_sent == True)
            )
        )
        return res.scalar_one_or_none() is not None

async def _find_mp3(client: httpx.AsyncClient, identifier: str) -> Optional[dict]:
    try:
        res = await client.get(META_URL.format(identifier=identifier), timeout=15.0)
        meta = res.json()
    except: return None

    for f in meta.get("files", []):
        if f.get("name", "").lower().endswith(".mp3"):
            size = int(f.get("size", 0))
            if MIN_SIZE <= size <= MAX_SIZE:
                return {"name": f["name"], "size": size}
    return None

async def _download(client: httpx.AsyncClient, identifier: str, filename: str) -> Optional[dict]:
    url = DOWNLOAD_URL.format(identifier=identifier, filename=filename)
    local_path = os.path.join(tempfile.gettempdir(), f"koma_{identifier}.mp3")

    try:
        async with client.stream("GET", url, timeout=60.0, follow_redirects=True) as resp:
            resp.raise_for_status()
            sha = hashlib.sha256()
            total = 0
            with open(local_path, "wb") as f:
                async for chunk in resp.aiter_bytes(8192):
                    total += len(chunk)
                    if total > MAX_SIZE:
                        f.close(); os.remove(local_path); return None
                    f.write(chunk); sha.update(chunk)
    except: 
        if os.path.exists(local_path): os.remove(local_path)
        return None

    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return {"path": local_path, "hash": sha.hexdigest(), "size": total}
    return None

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
                filename=data["filename"], file_hash=data["file_hash"],
                telegram_file_id=file_id, is_sent=True, sent_at=datetime.utcnow()
            ))
        await session.flush()

async def fetch_and_send_music(bot: Bot, chat_id: int, status_msg) -> bool:
    headers = {"User-Agent": "KOMA-Bot/1.0"}
    async with httpx.AsyncClient(headers=headers) as client:
        for attempt in range(3):
            try:
                query = random.choice(QUERIES)
                params = {
                    "q": query,
                    "fl[]": ["identifier", "title", "creator"],
                    "sort[]": "downloads desc", # 👈 فقط آهنگ‌های معروف و پرطرفدار رو اولویت بده
                    "rows": 10,
                    "output": "json",
                }
                r = await client.get(SEARCH_URL, params=params, timeout=15.0)
                docs = r.json().get("response", {}).get("docs", [])
            except Exception as e:
                logger.warning(f"Search attempt {attempt+1} failed: {e}")
                continue

            random.shuffle(docs)

            for doc in docs:
                ident = doc.get("identifier")
                if not ident or await _is_used(ident): continue

                mp3 = await _find_mp3(client, ident)
                if not mp3: continue

                dl = await _download(client, ident, mp3["name"])
                if not dl: continue

                title = doc.get("title", mp3["name"])
                if isinstance(title, list): title = title[0]
                creator = doc.get("creator", "Unknown Artist")
                if isinstance(creator, list): creator = creator[0]

                try:
                    with open(dl["path"], "rb") as audio:
                        sent = await bot.send_audio(
                            chat_id=chat_id,
                            audio=audio,
                            title=title[:64],
                            performer=creator[:64],
                            caption=(
                                f"🎵 <b>{title}</b>\n"
                                f"🎤 {creator}\n"
                                f"🌌 KOMA | کُما"
                            ),
                            parse_mode=ParseMode.HTML,
                            read_timeout=120, write_timeout=120
                        )
                    
                    await _record_track({
                        "identifier": ident, "title": title, "artist": creator,
                        "filename": mp3["name"], "file_hash": dl["hash"]
                    }, sent.audio.file_id)
                    
                    try: os.remove(dl["path"])
                    except: pass
                    return True
                except Exception as e:
                    logger.error(f"send_audio failed: {e}")
                    try: os.remove(dl["path"])
                    except: pass
                    
    return False
