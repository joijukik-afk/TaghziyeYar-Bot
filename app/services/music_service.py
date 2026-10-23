"""سرویس دریافت آهنگ واقعی از Internet Archive (با تمرکز روی سبک‌های KOMA)"""

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

# 👇 کوئری‌های دقیق برای پیدا کردن حال‌وهوای مورد نظر شما (Dreamcore, Slowed, Dark Ambient)
QUERIES = [
    'collection:opensource_audio AND (subject:dreamcore OR subject:"liminal space" OR subject:weirdcore)',
    'collection:opensource_audio AND (subject:"dark ambient" OR subject:"dark ambient music")',
    'mediatype:audio AND subject:"slowed reverb" AND licenseurl:*creativecommons*',
    'collection:opensource_audio AND (subject:"ethereal" OR subject:"ethereal wave" OR subject:"dream pop")',
    'collection:opensource_audio AND (subject:"cinematic ambient" OR subject:"emotional ambient")',
    'collection:opensource_audio AND (subject:"post apocalyptic" OR subject:"melancholic" OR subject:"sad ambient")',
    'collection:opensource_audio AND (subject:"acoustic ambient" OR subject:"ambient guitar")'
]

# سایزها رو تنظیم کردیم که فقط فایل‌های موسیقی واقعی (بین 1MB تا 45MB) رو قبول کنه
MAX_SIZE = 45 * 1024 * 1024   # 45MB
MIN_SIZE = 1024 * 1024        # 1MB
MAX_DOWNLOAD_ATTEMPTS = 4


async def _is_used(identifier: str) -> bool:
    """چک کن این آهنگ قبلاً ارسال شده یا نه"""
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack).where(
                (MusicTrack.identifier == identifier) & (MusicTrack.is_sent == True)
            )
        )
        return res.scalar_one_or_none() is not None


async def _find_mp3(client: httpx.AsyncClient, identifier: str) -> Optional[dict]:
    """لیست فایل‌های یک آهنگ رو بگیر و بهترین MP3 رو انتخاب کن"""
    try:
        res = await client.get(META_URL.format(identifier=identifier), timeout=15.0)
        res.raise_for_status()
        meta = res.json()
    except Exception as e:
        logger.warning(f"metadata fail {identifier}: {e}")
        return None

    files = meta.get("files", [])
    candidates = []
    for f in files:
        name = f.get("name", "")
        if not name.lower().endswith(".mp3"):
            continue
        try:
            size = int(f.get("size", 0))
        except (TypeError, ValueError):
            size = 0
        if MIN_SIZE <= size <= MAX_SIZE:
            candidates.append({"name": name, "size": size})

    if not candidates:
        return None

    candidates.sort(key=lambda c: c["size"])
    return candidates[0]


async def _download(client: httpx.AsyncClient, identifier: str, filename: str) -> Optional[dict]:
    """دانلود فایل MP3 و محاسبه هش"""
    url = DOWNLOAD_URL.format(identifier=identifier, filename=filename)
    tmp_dir = tempfile.gettempdir()
    safe_name = filename.replace("/", "_").replace("\\", "_")
    local_path = os.path.join(tmp_dir, f"koma_{identifier}_{safe_name}")

    try:
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
    except Exception as e:
        logger.warning(f"download fail {identifier}: {e}")
        if os.path.exists(local_path):
            try: os.remove(local_path)
            except: pass
        return None

    if not os.path.exists(local_path) or os.path.getsize(local_path) == 0:
        return None

    return {"path": local_path, "hash": sha.hexdigest(), "size": total}


async def _record_track(data: dict, file_id: str, is_sent: bool = True) -> None:
    """ثبت آهنگ در دیتابیس"""
    from datetime import datetime
    async with session_scope() as session:
        existing = await session.execute(
            select(MusicTrack).where(MusicTrack.identifier == data["identifier"])
        )
        track = existing.scalar_one_or_none()
        if track:
            track.telegram_file_id = file_id
            track.is_sent = is_sent
            track.sent_at = datetime.utcnow()
        else:
            session.add(MusicTrack(
                identifier=data["identifier"],
                title=data["title"],
                artist=data["artist"],
                filename=data["filename"],
                license_url=data.get("license_url"),
                file_hash=data.get("file_hash"),
                telegram_file_id=file_id,
                is_sent=is_sent,
                sent_at=datetime.utcnow() if is_sent else None,
            ))
        await session.flush()


def _safe(text: str, limit: int = 800) -> str:
    """پاکسازی متن برای HTML"""
    if not text: return "Unknown"
    text = str(text).replace("<", "&lt;").replace(">", "&gt;")
    return text[:limit]


async def fetch_and_send_music(bot: Bot, chat_id: int, status_msg) -> bool:
    """تابع اصلی: جستجو، دانلود، اعتبارسنجی و ارسال آهنگ"""
    
    headers = {"User-Agent": "TaghziyeYar-Bot/1.0 (+https://t.me/TaghziyeYar_bot)"}

    async with httpx.AsyncClient(headers=headers) as client:
        for attempt in range(MAX_DOWNLOAD_ATTEMPTS):
            try:
                query = random.choice(QUERIES)
                params = {
                    "q": query,
                    "fl[]": ["identifier", "title", "creator", "licenseurl"],
                    "sort[]": "random",
                    "rows": 25,
                    "output": "json",
                }
                r = await client.get(SEARCH_URL, params=params, timeout=20.0)
                r.raise_for_status()
                docs = r.json().get("response", {}).get("docs", [])
            except Exception as e:
                logger.warning(f"search attempt {attempt+1} failed: {e}")
                continue

            random.shuffle(docs)

            for doc in docs[:15]:
                ident = doc.get("identifier")
                if not ident or await _is_used(ident):
                    continue

                mp3 = await _find_mp3(client, ident)
                if not mp3:
                    continue

                dl = await _download(client, ident, mp3["name"])
                if not dl:
                    continue

                title = doc.get("title") or mp3["name"]
                if isinstance(title, list): title = title[0]
                creator = doc.get("creator") or "Unknown Artist"
                if isinstance(creator, list): creator = creator[0]

                data = {
                    "identifier": ident,
                    "title": _safe(title, 250),
                    "artist": _safe(creator, 120),
                    "filename": mp3["name"],
                    "license_url": doc.get("licenseurl"),
                    "file_hash": dl["hash"],
                }

                try:
                    with open(dl["path"], "rb") as audio:
                        sent = await bot.send_audio(
                            chat_id=chat_id,
                            audio=audio,
                            title=data["title"][:64],
                            performer=data["artist"][:64],
                            caption=(
                                f"🎵 <b>{data['title']}</b>\n"
                                f"🎤 {data['artist']}\n"
                                f"🌌 منبع: Internet Archive (Creative Commons)\n"
                                f"🔗 <a href='https://archive.org/details/{ident}'>صفحه آهنگ</a>"
                            ),
                            parse_mode=ParseMode.HTML,
                            read_timeout=120,
                            write_timeout=120,
                            connect_timeout=30,
                        )
                    await _record_track(data, sent.audio.file_id, is_sent=True)
                    return True
                except Exception as e:
                    logger.error(f"send_audio fail: {e}", exc_info=True)
                    continue
                finally:
                    if os.path.exists(dl["path"]):
                        try: os.remove(dl["path"])
                        except: pass

    return False
