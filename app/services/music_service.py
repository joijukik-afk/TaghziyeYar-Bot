"""موتور کشف و دانلود موسیقی KOMA (با مدیریت خطای دقیق)"""

import os
import random
import hashlib
import logging
import tempfile
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict
import yt_dlp
from sqlalchemy import select
from telegram import Bot
from telegram.constants import ParseMode

from app.database.music_models import MusicTrack
from app.database.session import session_scope
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

MAX_SIZE = 45 * 1024 * 1024
MIN_SIZE = 100 * 1024

COMA_SYSTEM_PROMPT = """
# COMA MUSIC DISCOVERY SYSTEM 🖤
تو یک سیستم تخصصی کشف موسیقی در SoundCloud هستی.
وظیفه تو پیدا کردن آهنگ‌های خاص، جدید، کمترشناخته‌شده و باکیفیت در سبک COMA MUSIC و تمام سبک‌های نزدیک به آن است.

## فرمت پاسخ (بسیار مهم!)
فقط از تگ‌های HTML مثل <b> و <a href="..."> برای لینک‌ها استفاده کن. پاسخ باید فوق‌العاده جذاب و رویایی باشه. اگر آهنگ‌های مناسب کم بود، تعداد کمتری بفرست.
"""

# ==================== دیتابیس ====================
async def _is_used(identifier: str) -> bool:
    async with session_scope() as session:
        res = await session.execute(
            select(MusicTrack).where((MusicTrack.identifier == identifier) & (MusicTrack.is_sent == True))
        )
        return res.scalar_one_or_none() is not None

async def _record_tracks(identifiers: List[str]) -> None:
    async with session_scope() as session:
        for ident in identifiers:
            existing = await session.execute(select(MusicTrack).where(MusicTrack.identifier == ident))
            if not existing.scalar_one_or_none():
                session.add(MusicTrack(
                    identifier=ident, title="COMA Discovery", artist="Various",
                    filename="", file_hash="", telegram_file_id="", is_sent=True, sent_at=datetime.now(timezone.utc)
                ))
        await session.flush()

# ==================== جستجو ====================
def _search_metadata_sync(query: str, max_results: int = 10) -> List[Dict]:
    ydl_opts = {
        'quiet': True, 
        'no_warnings': True, 
        'extract_flat': True, 
        'noplaylist': True,
        'socket_timeout': 10, 
        'ignoreerrors': True,
        'no_cache_dir': True,
        'impersonate': 'chrome', # برای عبور از بلاک در جستجو
    }
    results = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"scsearch{max_results}:{query}", download=False)
            for e in info.get('entries', []) or []:
                if not e: continue
                url = e.get('webpage_url') or e.get('url')
                if url and "soundcloud.com" in url:
                    results.append({
                        "id": f"sc_{e.get('id')}", "title": e.get('title', 'Unknown'),
                        "artist": e.get('uploader', 'Unknown Artist'), "url": url,
                        "source": "SoundCloud", "upload_date": e.get('upload_date', 'جدید'),
                        "genre": e.get('genre', 'COMA Vibe')
                    })
    except Exception as e:
        logger.warning(f"SC Search Error: {e}")
    return results

async def _search_metadata(query: str, max_results: int = 10) -> List[Dict]:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_search_metadata_sync, query, max_results), timeout=15.0)
    except asyncio.TimeoutError:
        return []
    except Exception:
        return []

# ==================== دانلود (با خطای دقیق) ====================
def _download_audio_sync(url: str, output_template: str) -> tuple[Optional[dict], str]:
    """خروجی: (دیکشنری آهنگ، پیام خطا)"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '128'}],
        'outtmpl': output_template + '.%(ext)s',
        'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'socket_timeout': 20, 'retries': 2,
        'no_cache_dir': True,
        'impersonate': 'chrome', # تنظیم ضدبلاک
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info: 
                return None, "اطلاعات آهنگ دریافت نشد (ممکن است IP بلاک شده باشد)."
            
            mp3_path = output_template + '.mp3'
            if not os.path.exists(mp3_path):
                base = os.path.basename(output_template)
                for f in os.listdir(tempfile.gettempdir()):
                    if f.startswith(base) and f.endswith('.mp3'):
                        mp3_path = os.path.join(tempfile.gettempdir(), f)
                        break
            
            if not os.path.exists(mp3_path): 
                return None, "فایل MP3 ساخته نشد (خطا در FFmpeg)."
            
            size = os.path.getsize(mp3_path)
            if size < MIN_SIZE: 
                os.remove(mp3_path)
                return None, "حجم فایل دانلود شده بسیار کم است."
                
            if size > MAX_SIZE:
                os.remove(mp3_path)
                return None, "حجم فایل بیشتر از ۴۵ مگابایت است."
            
            sha = hashlib.sha256()
            with open(mp3_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha.update(chunk)
            
            return {
                "path": mp3_path, "hash": sha.hexdigest(), "size": size,
                "title": info.get('title', 'Unknown'),
                "artist": info.get('uploader', 'Unknown Artist')
            }, ""
    except Exception as e:
        err_msg = str(e)
        if "403" in err_msg or "Forbidden" in err_msg:
            return None, "سرور SoundCloud درخواست را رد کرد (403 Forbidden). سرورهای رایگان Render بلاک هستند."
        elif "timed out" in err_msg.lower():
            return None, "دانلود با تایم‌اوت مواجه شد (اینترنت سرور ضعیف است)."
        else:
            return None, f"خطای داخلی: {err_msg[:100]}"

async def _download_audio(url: str, output_template: str) -> tuple[Optional[dict], str]:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_download_audio_sync, url, output_template), timeout=45.0)
    except asyncio.TimeoutError:
        return None, "زمان دانلود به پایان رسید (بیشتر از ۴۵ ثانیه)."

# ==================== منطق اصلی COMA ====================
async def fetch_and_send_music(bot: Bot, chat_id: int, thread_id: int = None) -> bool:
    queries = ["øneheart type beat", "dreamcore slowed reverb", "liminal space ambient", "dark ambient melancholic"]
    random.shuffle(queries)
    
    all_results = []
    for q in queries[:2]:
        res = await _search_metadata(q, 8)
        all_results.extend(res)
        if len(all_results) >= 10: break

    if not all_results: return False

    unique_results = []
    seen_ids = set()
    for r in all_results:
        if r["id"] in seen_ids or await _is_used(r["id"]): continue
        seen_ids.add(r["id"])
        unique_results.append(r)

    if not unique_results: return False

    results_text = "".join([f"{i+1}. Artist: {r['artist']} | Title: {r['title']} | URL: {r['url']}\n" for i, r in enumerate(unique_results[:10])])
    prompt = f"این آهنگ‌ها رو پیدا کردم. با توجه به پرامپت COMA بهترین‌ها رو انتخاب کن:\n\n{results_text}"

    ai_service = get_ai_service()
    ai_reply_tuple = await ai_service.ask(user_message=prompt, user_name="COMA DJ", user_id=0, custom_system_prompt=COMA_SYSTEM_PROMPT)
    ai_reply = ai_reply_tuple[0] if isinstance(ai_reply_tuple, tuple) else str(ai_reply_tuple)

    if not ai_reply: return False

    final_text = f"🌌 <b>COMA MUSIC DISCOVERY</b> 🖤\n\n{ai_reply}"
    
    try:
        await bot.send_message(chat_id=chat_id, text=final_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, message_thread_id=thread_id)
        await _record_tracks([r["id"] for r in unique_results[:10]])
        return True
    except Exception:
        return False


async def fetch_and_send_custom_music(bot: Bot, chat_id: int, query: str, thread_id: int = None) -> tuple[bool, str]:
    """دانلود آهنگ خاص (برمی‌گرداند: (موفقیت؟، پیام خطا))"""
    item = None
    dl = None

    if query.startswith(("http://", "https://")):
        url_hash = hashlib.md5(query.encode()).hexdigest()
        if await _is_used(url_hash): return False, "این لینک قبلاً ارسال شده است."
            
        output_template = os.path.join(tempfile.gettempdir(), f"koma_link_{url_hash}")
        dl, err = await _download_audio(query, output_template)
        if dl: item = {"source": "لینک", "id": url_hash}
        else: return False, err
    else:
        candidates = await _search_metadata(query, 5)
        if not candidates: return False, "هیچ آهنگی با این اسم پیدا نشد."
        
        err_msg = ""
        for c in candidates:
            if await _is_used(c["id"]): continue
            output_template = os.path.join(tempfile.gettempdir(), f"koma_search_{c['id']}")
            dl, err_msg = await _download_audio(c["url"], output_template)
            if dl:
                item = c
                break

    if not dl or not item: 
        return False, err_msg or "دانلود ناموفق بود (احتمالاً IP سرور بلاک است)."
        
    try:
        with open(dl["path"], "rb") as audio:
            sent = await bot.send_audio(
                chat_id=chat_id, audio=audio,
                title=dl.get('title', 'Unknown')[:64], 
                performer=dl.get('artist', 'Unknown Artist')[:64],
                caption=f"🎵 <b>{dl.get('title', 'Unknown')}</b>\n🎤 {dl.get('artist', 'Unknown Artist')}\n🌌 KOMA",
                parse_mode=ParseMode.HTML, read_timeout=120, write_timeout=120, message_thread_id=thread_id
            )
        
        async with session_scope() as session:
            session.add(MusicTrack(
                identifier=item["id"], title=dl.get("title", "Unknown"), artist=dl.get("artist", "Unknown"),
                filename=os.path.basename(dl["path"]), file_hash=dl["hash"],
                telegram_file_id=sent.audio.file_id, is_sent=True, sent_at=datetime.now(timezone.utc)
            ))
            await session.flush()
        
        try: os.remove(dl["path"])
        except: pass
        return True, ""
    except Exception as e:
        logger.error(f"send_audio failed: {e}")
        try: os.remove(dl["path"])
        except: pass
        return False, f"خطا در ارسال به تلگرام: {str(e)[:50]}"
