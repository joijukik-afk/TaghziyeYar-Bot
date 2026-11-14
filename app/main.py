"""Bot entry point. Wires together all handlers and starts polling."""

import asyncio
import io
import logging
import os
import re
import time
import threading
import datetime
import json
from functools import wraps
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, User
from telegram.constants import ChatType
from telegram.error import Forbidden
from telegram.ext import (
    Application, ApplicationBuilder, CallbackQueryHandler, ChatMemberHandler,
    CommandHandler, ContextTypes, MessageHandler, PollAnswerHandler,
    TypeHandler, ApplicationHandlerStop, filters,
)

from app.bot import extra_commands as ecmd
from app.bot import group_manager as gmanager
from app.bot import group_quiz as gquiz
from app.bot import meal_commands as mcmd
from app.bot import messages as msg
from app.bot import profile_commands as pcmd
from app.bot import setup_wizard as wizard
from app.bot import snake_game
from app.bot import koma_commands as kcmd
from app.bot import proxy_commands as prox_cmd
from app.bot import config_commands as conf_cmd
from app.bot import tts_commands as tts_cmd
from app.bot import translate_commands as trans_cmd
from app.bot import search_commands as search_cmd
from app.bot import voice_chat_commands as voice_cmd
from app.bot import image_commands as img_cmd
from app.bot import persona_commands as persona_cmd
from app.bot import vision_commands as vision_cmd 
from app.bot.content import get_fact, get_myth, get_tip
from app.config import get_settings
from app.database import repository as repo
from app.database.session import create_all, dispose_engine, init_engine, session_scope
from app.database.group_models import GroupMember
from app.database.state_repository import get_user_state, save_user_state
from app.services.ai_service import get_ai_service, VOICE_SYSTEM_PROMPT 
from app.services.auto_content import broadcast_auto_content, post_auto_content
from app.services.card_generator import generate_ai_health_card
from app.services.image_generator import generate_group_cover
from app.services.news_service import get_global_magazine_news
from app.services.web_search_service import get_web_search_service
from app.utils.message_formatter import with_signature

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=get_settings().log_level)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
#  Helper: Dynamic Admin Check & Monitoring
# ---------------------------------------------------------------------------
async def is_admin_user(user_id: int) -> bool:
    if get_settings().is_admin(user_id): return True
    dyn_admins = await repo.get_dynamic_admins()
    return user_id in dyn_admins

async def notify_owner(context: ContextTypes.DEFAULT_TYPE, actor: User, action: str):
    settings = get_settings()
    owner_id = None
    if hasattr(settings, 'admin_ids') and settings.admin_ids:
        owner_id = settings.admin_ids[0] if isinstance(settings.admin_ids, list) else int(str(settings.admin_ids).split(',')[0])
    elif hasattr(settings, 'admin_id'):
        owner_id = settings.admin_id
        
    if not owner_id or actor.id == owner_id: return  
    
    text = (
        f"🔔 <b>گزارش لحظه‌ای مدیریت:</b>\n\n"
        f"👤 <b>ادمین:</b> <a href='tg://user?id={actor.id}'>{actor.full_name}</a> (ID: <code>{actor.id}</code>)\n"
        f"📝 <b>عملیات:</b> {action}"
    )
    try:
        await context.bot.send_message(chat_id=owner_id, text=text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to send monitor msg to owner: {e}")

# ---------------------------------------------------------------------------
#  🚫 Global Ban System
# ---------------------------------------------------------------------------
async def check_user_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user and await repo.is_user_banned(user.id): 
        raise ApplicationHandlerStop

async def save_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if user and chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        await repo.save_group_member(chat.id, user.id, user.first_name or "کاربر", user.username)

async def track_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    if update.message and update.message.new_chat_members:
        for member in update.message.new_chat_members:
            if member.is_bot: continue
            await repo.save_group_member(chat.id, member.id, member.first_name or "کاربر", member.username)

# ---------------------------------------------------------------------------
#  Health server
# ---------------------------------------------------------------------------
class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
        self.wfile.write(b"TaghziyeYar bot is running")
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def log_message(self, format, *args): pass

def _start_health_server() -> None:
    server = HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

# ---------------------------------------------------------------------------
#  Security & Rate Limits
# ---------------------------------------------------------------------------
_user_last_message_time: dict = {}
_last_cleanup = time.time()

def _cleanup_old_rate_limits():
    global _last_cleanup
    if time.time() - _last_cleanup < 3600: return
    now = time.time()
    to_remove = [uid for uid, ts in _user_last_message_time.items() if now - ts > 3600]
    for uid in to_remove:
        _user_last_message_time.pop(uid, None)
    _last_cleanup = now

def private_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if is_group(update):
            keyboard = [[InlineKeyboardButton("🔒 ورود به چت خصوصی", url=f"https://t.me/{context.bot.username}?start=private_setup")]]
            if update.message: await update.message.reply_text("🛡️ این بخش فقط در چت خصوصی کار می‌کند.", reply_markup=InlineKeyboardMarkup(keyboard))
            elif update.callback_query: await update.callback_query.answer("لطفاً به چت خصوصی بروید.", show_alert=True)
            return 
        return await func(update, context, *args, **kwargs)
    return wrapper

def rate_limited(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        _cleanup_old_rate_limits()
        if not update.effective_user: return await func(update, context, *args, **kwargs)
        if time.time() - _user_last_message_time.get(update.effective_user.id, 0) < 0.5: return 
        _user_last_message_time[update.effective_user.id] = time.time()
        return await func(update, context, *args, **kwargs)
    return wrapper

# ---------------------------------------------------------------------------
#  🤖 Auto-post Job
# ---------------------------------------------------------------------------
async def _auto_post_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        last_time = await repo.get_last_post_time()
        now = time.time()
        if last_time > 0 and (now - last_time < 28800): return

        specific_chat = os.environ.get("AUTO_POST_CHAT_ID", "").strip()
        if specific_chat:
            try: 
                ok = await post_auto_content(context.bot, int(specific_chat))
                if ok: await repo.set_last_post_time(time.time())
            except Exception: pass
            return

        sent = await broadcast_auto_content(context.bot)
        if sent > 0: await repo.set_last_post_time(time.time())
    except Exception as e:
        logger.error("❌ خطا در _auto_post_job: %s", e)

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
def is_group(update: Update) -> bool:
    return update.effective_chat and update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

def is_for_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_group(update): return True
    if update.message is None: return False
    
    text_lower = (update.message.text or "").lower()
    if f"@{context.bot.username or ''}".lower() in text_lower: return True
    
    bot_names = ["تغذیه‌یار", "تغذیه یار", "taghziyeyar", "taghziye yar", "تغذیهیار"]
    if any(name in text_lower for name in bot_names): return True
    
    replied = update.message.reply_to_message
    return replied and replied.from_user and replied.from_user.id == context.bot.id

def clean_mention(text: str, bot_username: str) -> str: 
    text = text.replace(f"@{bot_username}", "").strip()
    bot_names = ["تغذیه‌یار", "تغذیه یار", "taghziyeyar", "taghziye yar", "تغذیهیار"]
    for name in bot_names:
        text = text.replace(name, "")
    return text.strip()

def remove_leading_greeting(text: str) -> str:
    if not text: return text
    pattern = r'^(سلام|درود|hello|hi)[\s!،.,?؟]*'
    cleaned = re.sub(pattern, '', text.strip(), flags=re.IGNORECASE).strip()
    if not cleaned:
        return "چطور می‌تونم کمکت کنم؟" 
    return cleaned[0].upper() + cleaned[1:]

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎭 تغییر شخصیت", callback_data="menu_persona"), InlineKeyboardButton("👁️ تحلیل عکس", callback_data="menu_vision")],
        [InlineKeyboardButton("🎨 تصویرسازی AI", callback_data="menu_imagine"), InlineKeyboardButton("🔍 جستجوی هوشمند", callback_data="menu_search")],
        [InlineKeyboardButton("🌐 ترجمه", callback_data="menu_translate"), InlineKeyboardButton("🔊 تبدیل متن به صدا", callback_data="menu_tts")],
        [InlineKeyboardButton("🎧 موسیقی COMA", callback_data="menu_koma"), InlineKeyboardButton("🎵 دانلود آهنگ", callback_data="menu_music")],
        [InlineKeyboardButton("🎮 کوییز زنده", callback_data="menu_quiz"), InlineKeyboardButton("🏆 جدول قهرمانان", callback_data="menu_lb")],
        [InlineKeyboardButton("🍽 برنامه غذا", callback_data="menu_plan"), InlineKeyboardButton("📅 برنامه امروز", callback_data="menu_today")],
        [InlineKeyboardButton("🛒 فهرست خرید", callback_data="menu_shopping"), InlineKeyboardButton("🥗 ارزش غذایی", callback_data="menu_food")],
        [InlineKeyboardButton("💡 نکته روز", callback_data="menu_tip"), InlineKeyboardButton("🍎 فکت", callback_data="menu_fact")],
        [InlineKeyboardButton("❌ باور اشتباه", callback_data="menu_myth"), InlineKeyboardButton("🎯 تحلیل کامل", callback_data="menu_ideal")],
        [InlineKeyboardButton("⚖️ ثبت وزن", callback_data="menu_weight"), InlineKeyboardButton("🔥 کالری", callback_data="menu_calories")],
        [InlineKeyboardButton("🥩 پروتئین", callback_data="menu_protein"), InlineKeyboardButton("🧮 درشت‌مغذی", callback_data="menu_macros")],
        [InlineKeyboardButton("📊 پیشرفت", callback_data="menu_progress"), InlineKeyboardButton("👤 پروفایل", callback_data="menu_profile")],
        [InlineKeyboardButton("💬 سوال از AI", callback_data="menu_ai"), InlineKeyboardButton("📖 راهنما", callback_data="menu_help")],
    ])

async def ensure_user_and_group(update: Update) -> None:
    user, chat = update.effective_user, update.effective_chat
    if user: await repo.get_or_create_user(telegram_id=user.id, username=user.username, first_name=user.first_name, last_name=user.last_name)
    if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP): await repo.get_or_create_group(chat_id=chat.id, title=chat.title)

async def _send_html_safe(bot, chat_id: int, text: str, reply_to: int | None = None) -> None:
    try: await bot.send_message(chat_id=chat_id, text=with_signature(text), parse_mode="HTML", reply_to_message_id=reply_to)
    except: 
        try: await bot.send_message(chat_id=chat_id, text=with_signature(re.sub(r"<[^>]+>", "", text)), reply_to_message_id=reply_to)
        except: pass

# ---------------------------------------------------------------------------
#  Commands
# ---------------------------------------------------------------------------
@rate_limited
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    user = update.effective_user
    if not update.message or not user: return
    
    if context.args and context.args[0] == "mycard":
        db_user = await repo.get_user_by_telegram_id(user.id)
        profile = await repo.get_profile(db_user.id) if db_user else None
        if not profile or not profile.setup_complete:
            await update.message.reply_text(with_signature("👋 خوش آمدید!\n\nبرای دریافت **کارت دیجیتال سلامت**، ابتدا باید اطلاعات پروفایل خود را تکمیل کنید.\n\n👇 لطفاً دستور /setup را بزنید."), parse_mode="Markdown")
        else:
            await update.message.reply_text(with_signature("👋 خوش آمدید!\n\nشما اطلاعات پروفایل خود را تکمیل کرده‌اید. برای دریافت کارت خود، روی دستور /mycard کلیک کنید."))
        return
    await update.message.reply_text(with_signature(msg.WELCOME), reply_markup=main_menu_keyboard())

@rate_limited
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    if update.message: await update.message.reply_text(with_signature(msg.HELP))

@rate_limited
async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    if update.message: await update.message.reply_text(with_signature(msg.MENU_TEXT), reply_markup=main_menu_keyboard())

async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message: await update.message.reply_text(with_signature(msg.ABOUT))

async def cmd_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message: await update.message.reply_text(with_signature(msg.PRIVACY))

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message: await update.message.reply_text(with_signature(msg.SETTINGS_TEXT))

async def cmd_tagall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("🚨 TAGALL RECEIVED!")
    if not update.message or not update.effective_chat: return
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP): return

    try: status_msg = await update.message.reply_text("⏳ در حال پردازش /tagall...")
    except: return

    try:
        is_admin = await is_admin_user(user.id)
        if not is_admin:
            await status_msg.edit_text("⛔️ این دستور فقط برای ادمین‌ها است.")
            return
    except Exception as e:
        await status_msg.edit_text(f"❌ خطا در بررسی ادمین: {e}")
        return

    count = 20; custom_text = "🔔 توجه!"
    if context.args:
        args = list(context.args)
        if args[0].isdigit(): count = min(int(args[0]), 100); args.pop(0)
        if args: custom_text = " ".join(args)

    try: members = await repo.get_group_members(chat.id, limit=count)
    except Exception as e:
        await status_msg.edit_text(f"❌ خطا در دیتابیس: {e}")
        return

    if not members:
        await status_msg.edit_text("⚠️ <b>هیچ عضوی توی دیتابیس پیدا نشد.</b>\n\nربات فقط اعضایی رو می‌شناسه که پیام دادن.", parse_mode="HTML")
        return

    mentions = []
    for m in members:
        safe_name = (m.first_name or "کاربر").replace("<", "").replace(">", "")
        if m.username: mentions.append(f"@{m.username}")
        else: mentions.append(f'<a href="tg://user?id={m.user_id}">{safe_name}</a>')

    chunks = [mentions[i:i + 20] for i in range(0, len(mentions), 20)]
    await status_msg.edit_text(f"⏳ در حال تگ کردن {len(members)} نفر...")

    for i, chunk in enumerate(chunks):
        text = " ".join(chunk)
        if i == 0: text = f"{custom_text}\n\n{text}"
        try:
            await context.bot.send_message(chat_id=chat.id, text=text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            try: await context.bot.send_message(chat_id=chat.id, text=" ".join([m.first_name for m in members[i*20:(i+1)*20]]))
            except: pass
        await asyncio.sleep(1.5)

    try: await status_msg.delete()
    except: pass

@private_only
@rate_limited
async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    user = update.effective_user
    if not user or not update.message: return
    db_user = await repo.get_user_by_telegram_id(user.id)
    if not db_user: return
    profile = await repo.get_profile(db_user.id)
    if not profile or not profile.setup_complete: await update.message.reply_text(with_signature(msg.NOT_SETUP_YET)); return
    lines = ["👤 پروفایل من\n"]
    if profile.age: lines.append(f"• سن: {profile.age} سال")
    if profile.gender: lines.append("• جنسیت: " + ("مرد" if profile.gender == "male" else "زن"))
    if profile.height_cm: lines.append(f"• قد: {profile.height_cm:.0f} سانتی‌متر")
    if profile.weight_kg: lines.append(f"• وزن: {profile.weight_kg:.1f} کیلوگرم")
    if profile.goal: lines.append(f"• هدف: {profile.goal}")
    lines.append("\n✏️ برای ویرایش، /setup رو بزن.")
    await update.message.reply_text(with_signature("\n".join(lines)))

@private_only
@rate_limited
async def cmd_mycard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    user = update.effective_user
    if not user or not update.message: return
    is_admin = await is_admin_user(user.id)
    if not is_admin:
        can_generate = await repo.check_and_mark_card_generated(user.id)
        if not can_generate: return await update.message.reply_text("⚠️ شما قبلاً کارت دیجیتال خود را دریافت کرده‌اید.")
    else: await notify_owner(context, user, "درخواست ساخت کارت دیجیتال سلامت (دسترسی نامحدود)")
    db_user = await repo.get_user_by_telegram_id(user.id)
    if not db_user: return
    profile = await repo.get_profile(db_user.id)
    if not profile or not profile.setup_complete: return await update.message.reply_text("⚠️ اول باید با /setup اطلاعاتت رو کامل کنی.")
    status_msg = await update.message.reply_text("🧠 در حال طراحی کارت اختصاصی شماست...")
    weight = profile.weight_kg or 0; height_m = (profile.height_cm or 1) / 100
    bmi_val = round(weight / (height_m ** 2), 1) if height_m > 0 else 0
    if bmi_val < 18.5: bmi_status = "کمبود وزن"
    elif bmi_val < 25: bmi_status = "نرمال ✅"
    elif bmi_val < 30: bmi_status = "اضافه وزن"
    else: bmi_status = "چاقی"
    goal_fa = {"lose": "کاهش وزن ⬇️", "gain": "افزایش وزن ⬆️", "muscle": "عضله‌سازی 💪", "maintain": "حفظ وزن ⚖️", "quality": "تغذیه سالم 🥗", "sport": "هدف ورزشی 🏃"}.get(profile.goal or "", "نامشخص")
    try:
        card_img = await generate_ai_health_card(name=user.first_name or "کاربر", age=str(int(profile.age)) if profile.age else "-", weight=str(int(weight)) if float(weight).is_integer() else str(weight), height=str(int(profile.height_cm)) if profile.height_cm else "-", bmi=str(bmi_val), bmi_status=bmi_status, goal=goal_fa)
        if card_img.getbuffer().nbytes == 0: return await status_msg.edit_text("❌ خطا در ساخت کارت.")
        await update.message.reply_photo(photo=card_img, caption="🪪 <b>کارت دیجیتال سلامت شما</b>\n\nاین کارت مخصوص شماست. 🚀", parse_mode="HTML")
        await status_msg.delete()
    except Exception as e:
        logger.error("Error generating card: %s", e, exc_info=True)
        await status_msg.edit_text(f"❌ متأسفانه خطایی پیش آمد.\n\nخطا: `{e}`", parse_mode="Markdown")

@private_only
@rate_limited
async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await wizard.start_setup(update, context)

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message: context.user_data["awaiting_weight"] = False; await wizard.cancel_setup(update, context)

@private_only
@rate_limited
async def cmd_bmi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await pcmd.cmd_bmi(update, context)
@private_only
@rate_limited
async def cmd_calories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await pcmd.cmd_calories(update, context)
@private_only
@rate_limited
async def cmd_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await pcmd.cmd_weight(update, context)
@private_only
@rate_limited
async def cmd_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await pcmd.cmd_progress(update, context)

@rate_limited
async def cmd_tip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await ecmd.cmd_tip(update, context)
@rate_limited
async def cmd_fact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await ecmd.cmd_fact(update, context)
@rate_limited
async def cmd_myth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await ecmd.cmd_myth(update, context)
@rate_limited
async def cmd_water(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await ecmd.cmd_water(update, context)

@private_only
@rate_limited
async def cmd_macros(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await ecmd.cmd_macros(update, context)
@private_only
@rate_limited
async def cmd_protein(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await ecmd.cmd_protein(update, context)
@private_only
@rate_limited
async def cmd_ideal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await ecmd.cmd_ideal(update, context)
@private_only
@rate_limited
async def cmd_bodyfat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await ecmd.cmd_bodyfat(update, context)
@private_only
@rate_limited
async def cmd_bmr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await ecmd.cmd_bmr(update, context)

@rate_limited
async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await mcmd.cmd_plan(update, context)
@rate_limited
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await mcmd.cmd_today(update, context)
@rate_limited
async def cmd_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await mcmd.cmd_shopping(update, context)
@rate_limited
async def cmd_food(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await ensure_user_and_group(update); await mcmd.cmd_food(update, context)

# ---------------------------------------------------------------------------
#  Smart Reminder
# ---------------------------------------------------------------------------
async def _send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    await context.bot.send_message(chat_id=job.chat_id, text=job.data["text"])

async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message: return
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("⚠️ فرمت: `/remind 10m آب بخورم`", parse_mode="Markdown")
    
    time_str = args[0]
    text = " ".join(args[1:])
    
    match = re.match(r"(\d+)([smh])", time_str.lower())
    if not match:
        return await update.message.reply_text("⚠️ زمان اشتباه است. از `s`، `m` یا `h` استفاده کن.", parse_mode="Markdown")
    
    amount = int(match.group(1)); unit = match.group(2)
    seconds = amount if unit == "s" else amount * 60 if unit == "m" else amount * 3600
    
    context.job_queue.run_once(_send_reminder, when=seconds, chat_id=update.effective_chat.id, data={"text": f"⏰ **یادآوری:**\n{text}"})
    await update.message.reply_text(f"✅ ثبت شد! بعد از {amount}{unit} یادآوری می‌کنم.")

# ---------------------------------------------------------------------------
#  Text -> AI (Smart Memory, Context & Voice)
# ---------------------------------------------------------------------------
async def _process_ai_response(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str, reply_context: str):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    
    try:
        state = await get_user_state(user.id)
        chat_history = json.loads(state.chat_history_json) if state else []
        persona_key = state.persona_key if state else "default"
        persona_data = persona_cmd.PERSONAS.get(persona_key, {})
        persona_prompt = persona_data.get("prompt")
        
        text_lower = user_text.lower()
        voice_triggers = ["ویس", "صوتی", "صدا", "بخون", "ضبط کن"]
        is_voice_request = any(w in text_lower for w in voice_triggers)
        voice_type = "male"
        if any(w in text_lower for w in ["زن", "خانم", "دختر", "دیلارا"]): voice_type = "female"
        
        clean_text = user_text
        if is_voice_request:
            for w in ["با صدای زن", "با صدای مرد", "با صدای", "با ویس", "ویس بفرست", "صوتی بگو", "صدا بگو"]:
                clean_text = clean_text.replace(w, "")
            clean_text = clean_text.strip() or user_text

        # 👇👇👇 لیست بسیار گسترده کلمات کلیدی برای سرچ خودکار 👇👇👇
        search_triggers = [
            "قیمت", "دلار", "طلا", "بیت کوین", "اخبار", "امروز", "جدید", "چیست", "چیه", 
            "تخفیف", "کد", "اسنپ فود", "اسنپ‌فود", "دیجی کالا", "دیجی‌کالا", "رستوران", 
            "نتیجه بازی", "فیلم", "سریال", "بازی", "آب و هوا", "شغل", "استخدام", "کجا", "چطور"
        ]
        needs_search = any(w in text_lower for w in search_triggers) and not is_voice_request
        
        search_context = ""
        if needs_search:
            try:
                status_msg = await context.bot.send_message(chat_id=chat_id, text="🔍 دارم از اینترنت چک می‌کنم...")
                search_service = get_web_search_service()
                search_context = await search_service.search_and_answer(clean_text, user.id)
                await status_msg.delete()
            except Exception as e:
                logger.error(f"Search error: {e}")

        final_input = f"{reply_context}{clean_text}"
        if search_context:
            final_input = f"اطلاعات جدید از وب:\n{search_context}\n\nسوال: {clean_text}\n\n(با توجه به اطلاعات جدید جواب بده)"

        if is_voice_request:
            final_prompt = f"You are acting as: {persona_prompt}. CRITICAL: Only natural Persian text, NO emojis, NO English, NO markdown." if persona_prompt else VOICE_SYSTEM_PROMPT
        else:
            final_prompt = persona_prompt

        ai = get_ai_service()
        reply, status = await ai.ask(
            user_message=final_input, 
            user_name=(user.first_name or "") if user else "", 
            user_id=user.id,
            custom_system_prompt=final_prompt,
            chat_history=chat_history 
        )
        
        if reply:
            reply = remove_leading_greeting(reply)
        
        chat_history.append({"role": "user", "content": clean_text})
        chat_history.append({"role": "assistant", "content": reply})
        if len(chat_history) > 10: chat_history = chat_history[-10:]
        await save_user_state(user.id, persona_key, chat_history)

        if is_voice_request and reply:
            await voice_cmd.generate_and_send_voice(context.bot, chat_id, reply, voice_type)
        else:
            await _send_html_safe(bot=context.bot, chat_id=chat_id, text=reply or "پاسخی دریافت نشد.", reply_to=message_id)
            
    except Exception as e:
        logger.error(f"AI Processing Error: {e}")
        try:
            await context.bot.send_message(chat_id=chat_id, text="❌ خطایی پیش آمد. دوباره تلاش کنید.")
        except: pass

@rate_limited
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text: return
    await ensure_user_and_group(update)
    if not is_for_me(update, context): return
    
    original_text = clean_mention(update.message.text, context.bot.username or "")
    if not original_text: return
    
    user = update.effective_user
    
    greetings = ["سلام", "درود", "hi", "hello", "سلم", "سلام خوبی", "سلام خسته نباشی"]
    user_greeted = original_text.strip().lower() in greetings
    
    if user_greeted:
        current_time = time.time()
        last_interaction = context.user_data.get("last_interaction", 0)
        if current_time - last_interaction > 600:
            import random
            replies = ["سلام! 👋 چطور می‌تونم امروز بهت کمک کنم؟", "سلام جان! 🌱 چه خبر؟", "درود! 🤖 امروز چی می‌خوای یاد بگیری؟"]
            context.user_data["last_interaction"] = current_time
            return await update.message.reply_text(with_signature(random.choice(replies)))
    context.user_data["last_interaction"] = time.time()

    if is_group(update):
        if context.user_data.get("awaiting_weight") or context.user_data.get("setup_step", "IDLE") != "IDLE":
            await update.message.reply_text("🛡️ ثبت اطلاعات در گروه ممنوع است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔒 چت خصوصی", url=f"https://t.me/{context.bot.username}?start=private_setup")]])); return
    else:
        if await wizard.handle_setup_input(update, context) or await pcmd.handle_weight_input(update, context): return

    reply_context = ""
    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        if replied_user:
            reply_context = f"[کاربر در حال ریپلای کردن به {replied_user.first_name} است] "

    asyncio.create_task(_process_ai_response(update, context, original_text, reply_context))

# ... (بقیه کدها: handle_callback, cmd_addadmin, cmd_remind, post_init و ... دقیقاً مثل فایل قبلی که فرستادم) ...
# (برای جلوگیری از طولانی شدن، فقط توابع تغییر یافته رو گذاشتم. بقیه فایل main.py رو همون قبلی بذار)
