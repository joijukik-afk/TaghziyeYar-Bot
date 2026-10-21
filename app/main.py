"""Bot entry point. Wires together all handlers and starts polling."""

import asyncio
import io
import logging
import os
import re
import time
import threading
from functools import wraps
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
from app.bot.content import get_fact, get_myth, get_tip
from app.config import get_settings
from app.database import repository as repo
from app.database.session import create_all, dispose_engine, init_engine
from app.services.ai_service import get_ai_service
from app.services.auto_content import broadcast_auto_content, post_auto_content
from app.services.card_generator import generate_ai_health_card
from app.services.image_generator import generate_group_cover
from app.services.news_service import get_global_magazine_news
from app.utils.message_formatter import with_signature

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=get_settings().log_level)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
#  🚫 Global Ban System
# ---------------------------------------------------------------------------
async def check_user_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user and await repo.is_user_banned(user.id): 
        raise ApplicationHandlerStop

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
_user_last_message_time = {}

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
        if not update.effective_user: return await func(update, context, *args, **kwargs)
        if time.time() - _user_last_message_time.get(update.effective_user.id, 0) < 2.0: return 
        _user_last_message_time[update.effective_user.id] = time.time()
        return await func(update, context, *args, **kwargs)
    return wrapper

# ---------------------------------------------------------------------------
#  🤖 Auto-post Job (تایمر ضد اسپم)
# ---------------------------------------------------------------------------
async def _auto_post_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        last_time = await repo.get_last_post_time()
        now = time.time()
        
        if last_time > 0 and (now - last_time < 28800):
            logger.info("⏳ هنوز ۸ ساعت از پست قبلی نگذشته. زمان باقی‌مانده: %.1f ساعت", (28800 - (now - last_time)) / 3600)
            return

        specific_chat = os.environ.get("AUTO_POST_CHAT_ID", "").strip()
        if specific_chat:
            try: 
                ok = await post_auto_content(context.bot, int(specific_chat))
                if ok: 
                    await repo.set_last_post_time(time.time())
                    logger.info("✅ پست خودکار ارسال شد به گروه مشخص.")
            except Exception as e: 
                logger.warning("خطا در ارسال به %s: %s", specific_chat, e)
            return

        sent = await broadcast_auto_content(context.bot)
        if sent > 0: 
            await repo.set_last_post_time(time.time())
            logger.info("✅ پست خودکار به %d گروه ارسال شد.", sent)
        else:
            logger.warning("⚠️ پستی ارسال نشد (شاید AI خطا داد یا گروهی نیست).")
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
    if f"@{context.bot.username or ''}" in (update.message.text or ""): return True
    replied = update.message.reply_to_message
    return replied and replied.from_user and replied.from_user.id == context.bot.id

def clean_mention(text: str, bot_username: str) -> str: 
    return text.replace(f"@{bot_username}", "").strip()

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
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
    if update.message: await update.message.reply_text(with_signature(msg.WELCOME), reply_markup=main_menu_keyboard())

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

@private_only
@rate_limited
async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    user = update.effective_user
    if not user or not update.message: return
    db_user = await repo.get_user_by_telegram_id(user.id)
    if not db_user: return
    profile = await repo.get_profile(db_user.id)
    if not profile or not profile.setup_complete:
        await update.message.reply_text(with_signature(msg.NOT_SETUP_YET)); return
    lines = ["👤 پروفایل من\n"]
    if profile.age: lines.append(f"• سن: {profile.age} سال")
    if profile.gender: lines.append("• جنسیت: " + ("مرد" if profile.gender == "male" else "زن"))
    if profile.height_cm: lines.append(f"• قد: {profile.height_cm:.0f} سانتی‌متر")
    if profile.weight_kg: lines.append(f"• وزن: {profile.weight_kg:.1f} کیلوگرم")
    if profile.goal: lines.append(f"• هدف: {profile.goal}")
    lines.append("\n✏️ برای ویرایش، /setup رو بزن.")
    await update.message.reply_text(with_signature("\n".join(lines)))

# 👇 دستور کارت گرافیکی (با دسترسی نامحدود برای ادمین) 👇
@private_only
@rate_limited
async def cmd_mycard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    user = update.effective_user
    if not user or not update.message: return
    
    # بررسی ادمین بودن (صاحب ربات)
    is_admin = get_settings().is_admin(user.id)
    
    # اگر ادمین نبود، محدودیت یک‌بار اعمال می‌شود
    if not is_admin:
        can_generate = await repo.check_and_mark_card_generated(user.id)
        if not can_generate:
            return await update.message.reply_text(
                "⚠️ شما قبلاً کارت دیجیتال خود را دریافت کرده‌اید.\n"
                "طبق قوانین ربات، هر کاربر فقط یک بار می‌تواند این کارت اختصاصی را بسازد."
            )

    db_user = await repo.get_user_by_telegram_id(user.id)
    if not db_user: return
    
    profile = await repo.get_profile(db_user.id)
    if not profile or not profile.setup_complete:
        return await update.message.reply_text("⚠️ اول باید با /setup اطلاعاتت رو کامل کنی.")
    
    status_msg = await update.message.reply_text("🧠 هوش مصنوعی در حال طراحی پس‌زمینه و کارت اختصاصی شماست... (حدود ۱۰ ثانیه)")
    
    weight = profile.weight_kg or 0
    height_m = (profile.height_cm or 1) / 100
    bmi_val = round(weight / (height_m ** 2), 1) if height_m > 0 else 0
    
    if bmi_val < 18.5: bmi_status = "کمبود وزن"
    elif bmi_val < 25: bmi_status = "نرمال ✅"
    elif bmi_val < 30: bmi_status = "اضافه وزن"
    else: bmi_status = "چاقی"
    
    goal_fa = {
        "lose": "کاهش وزن ⬇️", "gain": "افزایش وزن ⬆️",
        "muscle": "عضله‌سازی 💪", "maintain": "حفظ وزن ⚖️",
        "quality": "تغذیه سالم 🥗", "sport": "هدف ورزشی 🏃"
    }.get(profile.goal or "", "نامشخص")
    
    try:
        card_img = await generate_ai_health_card(
            name=user.first_name or "کاربر",
            age=str(profile.age or "-"),
            weight=str(weight),
            height=str(profile.height_cm or "-"),
            bmi=str(bmi_val),
            bmi_status=bmi_status,
            goal=goal_fa
        )
        
        if card_img.getbuffer().nbytes == 0:
             return await status_msg.edit_text("❌ خطا در ساخت کارت. لطفاً دوباره تلاش کنید.")
        
        await update.message.reply_photo(
            photo=card_img,
            caption="🪪 <b>کارت دیجیتال سلامت شما</b>\n\nاین کارت مخصوص شماست. 🚀",
            parse_mode="HTML"
        )
        await status_msg.delete()
    except Exception as e:
        logger.error("Error generating card: %s", e)
        await status_msg.edit_text("❌ متأسفانه در ساخت کارت خطایی پیش آمد.")
# 👆 پایان دستور کارت 👆

@private_only
@rate_limited
async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await wizard.start_setup(update, context)

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        context.user_data["awaiting_weight"] = False
        await wizard.cancel_setup(update, context)

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
#  Text -> AI
# ---------------------------------------------------------------------------
@rate_limited
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text: return
    await ensure_user_and_group(update)
    if not is_for_me(update, context): return
    text = clean_mention(update.message.text, context.bot.username or "")
    if not text: return
    if is_group(update):
        if context.user_data.get("awaiting_weight") or context.user_data.get("setup_step", "IDLE") != "IDLE":
            await update.message.reply_text("🛡️ ثبت اطلاعات در گروه ممنوع است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔒 چت خصوصی", url=f"https://t.me/{context.bot.username}?start=private_setup")]])); return
    else:
        if await wizard.handle_setup_input(update, context) or await pcmd.handle_weight_input(update, context): return

    user = update.effective_user; profile_summary = ""
    if user and not is_group(update):
        db_user = await repo.get_user_by_telegram_id(user.id)
        if db_user:
            profile = await repo.get_profile(db_user.id)
            if profile and profile.setup_complete:
                parts = []
                if profile.age: parts.append(f"سن: {profile.age}")
                if profile.height_cm: parts.append(f"قد: {profile.height_cm:.0f}")
                if profile.weight_kg: parts.append(f"وزن: {profile.weight_kg:.1f}")
                if profile.goal: parts.append(f"هدف: {profile.goal}")
                profile_summary = "، ".join(parts)
    try: await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except: pass
    ai = get_ai_service()
    reply, _ = await ai.ask(user_message=text, user_name=(user.first_name or "") if user else "", user_profile_summary=profile_summary, user_id=user.id if user else 0)
    await _send_html_safe(bot=context.bot, chat_id=update.effective_chat.id, text=reply or "پاسخی دریافت نشد.", reply_to=update.message.message_id)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    await query.answer(); data = query.data or ""
    if data == "gq_next" and update.effective_chat: await gquiz.send_quiz_from_callback(context=context, chat_id=update.effective_chat.id, chat_title=update.effective_chat.title or ""); return
    if data == "menu_quiz": await query.edit_message_text(with_signature("🎮 برای شروع: /quiz")); return
    if data == "menu_lb": await query.edit_message_text(with_signature("🏆 جدول: /leaderboard")); return
    if data == "menu_help": await query.edit_message_text(with_signature(msg.HELP)); return
    if data == "menu_tip": await query.edit_message_text(with_signature(f"💡 نکته:\n\n{get_tip()}")); return
    if data == "menu_fact": await query.edit_message_text(with_signature(f"🍎 فکت:\n\n{get_fact()}")); return
    if data == "menu_myth": m, t = get_myth(); await query.edit_message_text(with_signature(f"❌ {m}\n\n✅ {t}")); return
    hints = {"menu_plan": "🍽 /plan", "menu_today": "📅 /today", "menu_shopping": "🛒 /shopping", "menu_food": "🥗 /food", "menu_ideal": "🎯 /ideal (پیوی)", "menu_weight": "⚖️ /weight (پیوی)", "menu_calories": "🔥 /calories (پیوی)", "menu_protein": "🥩 /protein (پیوی)", "menu_macros": "🧮 /macros (پیوی)", "menu_progress": "📊 /progress (پیوی)", "menu_profile": "👤 /profile (پیوی)", "menu_ai": "💬 پیام بفرست."}
    text = hints.get(data, msg.UNKNOWN_COMMAND)
    if is_group(update) and data in ["menu_weight", "menu_calories", "menu_protein", "menu_macros", "menu_progress", "menu_profile", "menu_ideal"]:
        kb = [[InlineKeyboardButton("🔒 ورود به چت خصوصی", url=f"https://t.me/{context.bot.username}?start=private_setup")]]
        await query.edit_message_text(with_signature("🛡️ این بخش خصوصی است."), reply_markup=InlineKeyboardMarkup(kb)); return
    await query.edit_message_text(with_signature(text))

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Exception", exc_info=context.error)

# ---------------------------------------------------------------------------
#  Admin Commands
# ---------------------------------------------------------------------------
async def cmd_broadcast_covers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id): return
    groups = await repo.list_all_groups()
    if not groups: return await update.message.reply_text("هیچ گروهی نیست.")
    status_msg = await update.message.reply_text(f"⏳ در حال ساخت کاور برای {len(groups)} گروه...")
    success, dead = 0, 0
    for g in groups:
        try:
            photo = await generate_group_cover(g.title or "Nutrition Group")
            await context.bot.send_photo(chat_id=g.chat_id, photo=photo, caption=f"🎨 کاور اختصاصی گروه <b>{g.title}</b>", parse_mode="HTML")
            success += 1; await asyncio.sleep(3) 
        except Forbidden: await repo.deactivate_group(chat_id=g.chat_id); dead += 1
        except Exception: pass
    await status_msg.edit_text(f"✅ کاور برای {success} از {len(groups)} گروه ارسال شد.\n🧹 {dead} گروه حذف شد.")

async def cmd_leave_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user, chat = update.effective_user, update.effective_chat
    if not user or not get_settings().is_admin(user.id): return
    if chat.type == ChatType.PRIVATE:
        if not context.args: return await update.message.reply_text("⚠️ مثال: `/leavegroup Asli`", parse_mode="Markdown")
        query = " ".join(context.args).strip(); groups = await repo.list_all_groups()
        target = next((g for g in groups if str(g.chat_id) == query or (g.title and query.lower() in g.title.lower())), None)
        if not target: return await update.message.reply_text("❌ گروه پیدا نشد.")
        try:
            await context.bot.leave_chat(chat_id=target.chat_id); await repo.deactivate_group(chat_id=target.chat_id)
            await update.message.reply_text(f"✅ ربات از «{target.title}» خارج شد.")
        except Exception as e: await update.message.reply_text(f"❌ خطا: {e}")
    else:
        await update.message.reply_text("🚪 در حال خروج...")
        try: await context.bot.leave_chat(chat_id=chat.id); await repo.deactivate_group(chat_id=chat.id)
        except: pass

async def cmd_send_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id): return
    if not update.message.reply_to_message: return await update.message.reply_text("⚠️ روی پیام ریپلای کنید.")
    if not context.args: return await update.message.reply_text("⚠️ مثال: `/sendto Asli`", parse_mode="Markdown")
    query = " ".join(context.args).strip(); groups = await repo.list_all_groups()
    target = next((g for g in groups if str(g.chat_id) == query or (g.title and query.lower() in g.title.lower())), None)
    if not target: return await update.message.reply_text("❌ گروه پیدا نشد.")
    try:
        await context.bot.copy_message(chat_id=target.chat_id, from_chat_id=update.message.chat_id, message_id=update.message.reply_to_message.message_id)
        await update.message.reply_text(f"✅ پیام به «{target.title}» ارسال شد.")
    except Forbidden: await repo.deactivate_group(chat_id=target.chat_id); await update.message.reply_text(f"❌ ربات در گروه نیست.")
    except Exception as e: await update.message.reply_text(f"❌ خطا: {e}")

async def cmd_global_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id): return
    if not context.args: return await update.message.reply_text("⚠️ مثال: `/globalnews Asli`", parse_mode="Markdown")
    query = " ".join(context.args).strip(); groups = await repo.list_all_groups()
    target = next((g for g in groups if str(g.chat_id) == query or (g.title and query.lower() in g.title.lower())), None)
    if not target: return await update.message.reply_text("❌ گروه پیدا نشد.")
    status_msg = await update.message.reply_text("⏳ در حال استخراج...")
    result = await get_global_magazine_news()
    if not result: return await status_msg.edit_text("❌ خبری دریافت نشد.")
    text, image_url = result; await status_msg.edit_text("⏳ در حال ارسال...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(image_url); resp.raise_for_status()
            photo = io.BytesIO(resp.content); photo.name = 'news.jpg'
        await context.bot.send_photo(chat_id=target.chat_id, photo=photo, caption=text, parse_mode="HTML")
        await status_msg.edit_text(f"✅ خبر منتشر شد.")
    except Exception as e:
        try: await context.bot.send_message(chat_id=target.chat_id, text=text, parse_mode="HTML"); await status_msg.edit_text("✅ خبر ارسال شد (بدون عکس).")
        except Exception as e2: await status_msg.edit_text(f"❌ خطا: {e2}")

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id): return
    target_id, target_name, group_to_notify = None, "کاربر", None
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        if replied.forward_from_chat: group_to_notify = replied.forward_from_chat.id
        if replied.forward_from: target_id, target_name = replied.forward_from.id, replied.forward_from.first_name or "کاربر"
        elif replied.from_user: target_id, target_name = replied.from_user.id, replied.from_user.first_name or "کاربر"
    if not target_id and context.args:
        arg = context.args[0]
        if arg.startswith("@"):
            db_user = await repo.get_user_by_username(arg)
            if db_user: target_id, target_name = db_user.telegram_id, db_user.first_name or db_user.username or "کاربر"
        else:
            try: target_id, target_name = int(arg), str(arg)
            except: pass
    if not target_id: return await update.message.reply_text("⚠️ راهنما:\n`/ban @username Asli`", parse_mode="Markdown")
    if not group_to_notify and len(context.args) > 1:
        group_query = " ".join(context.args[1:]).strip(); groups = await repo.list_all_groups()
        target_group = next((g for g in groups if str(g.chat_id) == group_query or (g.title and group_query.lower() in g.title.lower())), None)
        if target_group: group_to_notify = target_group.chat_id
    elif not group_to_notify and update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP): group_to_notify = update.effective_chat.id
    try:
        await repo.ban_user(target_id, "نقض قوانین")
        await update.message.reply_text(f"✅ کاربر <b>{target_name}</b> مسدود شد.", parse_mode="HTML")
        try: await context.bot.send_message(chat_id=target_id, text="🚫 <b>دسترسی شما مسدود شد</b>\n\n@AliAkbaro0", parse_mode="HTML")
        except: pass
        if group_to_notify:
            try: await context.bot.send_message(chat_id=group_to_notify, text=f"🚫 <b>اخطار مدیریتی</b>\n\nکاربر <b>{target_name}</b> مسدود شد.", parse_mode="HTML")
            except: pass
    except Exception as e: await update.message.reply_text(f"❌ خطای دیتابیسی: `{e}`", parse_mode="Markdown")

async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id): return
    if not context.args: return await update.message.reply_text("⚠️ `/unban 123456789`", parse_mode="Markdown")
    arg = context.args[0]; target_id = None
    if arg.startswith("@"):
        db_user = await repo.get_user_by_username(arg)
        if db_user: target_id = db_user.telegram_id
    else:
        try: target_id = int(arg)
        except: pass
    if not target_id: return await update.message.reply_text("❌ کاربر پیدا نشد.")
    await repo.unban_user(target_id)
    await update.message.reply_text(f"✅ مسدودی `{target_id}` برداشته شد.", parse_mode="Markdown")

async def cmd_forcepost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id): return
    
    status = await update.message.reply_text("🔄 در حال ساخت و ارسال پست فوری به همه گروه‌ها...")
    try:
        sent = await broadcast_auto_content(context.bot)
        if sent > 0:
            await repo.set_last_post_time(time.time())
            await status.edit_text(f"✅ پست فوری با موفقیت به {sent} گروه ارسال شد و تایمر ۸ ساعته ریست شد.")
        else:
            await status.edit_text("⚠️ متأسفانه پست ساخته نشد یا هیچ گروه فعالی پیدا نشد.")
    except Exception as e:
        await status.edit_text(f"❌ خطای فنی: {e}")

# ---------------------------------------------------------------------------
#  Lifecycle
# ---------------------------------------------------------------------------
async def post_init(application: Application) -> None:
    init_engine()
    import app.database.models
    import app.database.quiz_models 
    await create_all()
    me = await application.bot.get_me()
    logger.info("Bot started as @%s", me.username)
    
    try:
        short_desc = "زیر نظر متخصص تغذیه علی اکبر ابراهیم پور | پشتیبانی: @AliAkbaro0"
        await application.bot.set_my_short_description(short_description=short_desc)
        
        full_desc = (
            "🌱 دستیار هوشمند تغذیه و سلامت\n\n"
            "👨‍⚕️ زیر نظر کارشناس و متخصص تغذیه: علی اکبر ابراهیم پور\n"
            "📞 پشتیبانی: @AliAkbaro0\n\n"
            "📊 محاسبه BMI و کالری\n"
            "🍽 ساخت برنامه غذایی با هوش مصنوعی\n"
            "🎮 کوییز و بازی‌های گروهی"
        )
        await application.bot.set_my_description(description=full_desc)
        logger.info("✅ Bio and description updated successfully.")
    except Exception as e:
        logger.warning("خطا در تنظیم بیو: %s", e)
    
    try:
        from app.bot.commands_setup import setup_commands
        await setup_commands(application.bot)
    except: pass
    
    if application.job_queue is not None:
        try: first = int(os.environ.get("AUTO_POST_FIRST_DELAY", "600")) 
        except: first = 600
        application.job_queue.run_repeating(_auto_post_job, interval=600, first=first, name="auto_nutrition_post")

async def post_shutdown(application: Application) -> None: await dispose_engine()

def build_application() -> Application:
    settings = get_settings()
    app = (ApplicationBuilder().token(settings.telegram_bot_token).post_init(post_init).post_shutdown(post_shutdown).build())
    
    app.add_handler(TypeHandler(Update, check_user_ban), group=-1)

    app.add_handler(CommandHandler("start", cmd_start)); app.add_handler(CommandHandler("help", cmd_help)); app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("about", cmd_about)); app.add_handler(CommandHandler("privacy", cmd_privacy)); app.add_handler(CommandHandler("settings", cmd_settings))
    
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("mycard", cmd_mycard)) # 👈 دستور کارت
    app.add_handler(CommandHandler("setup", cmd_setup)); app.add_handler(CommandHandler("cancel", cmd_cancel))
    
    app.add_handler(CommandHandler("bmi", cmd_bmi)); app.add_handler(CommandHandler("calories", cmd_calories)); app.add_handler(CommandHandler("weight", cmd_weight))
    app.add_handler(CommandHandler("progress", cmd_progress)); app.add_handler(CommandHandler("macros", cmd_macros)); app.add_handler(CommandHandler("protein", cmd_protein))
    app.add_handler(CommandHandler("ideal", cmd_ideal)); app.add_handler(CommandHandler("bodyfat", cmd_bodyfat)); app.add_handler(CommandHandler("bmr", cmd_bmr))
    app.add_handler(CommandHandler("tip", cmd_tip)); app.add_handler(CommandHandler("fact", cmd_fact)); app.add_handler(CommandHandler("myth", cmd_myth)); app.add_handler(CommandHandler("water", cmd_water))
    app.add_handler(CommandHandler("plan", cmd_plan)); app.add_handler(CommandHandler("today", cmd_today)); app.add_handler(CommandHandler("shopping", cmd_shopping)); app.add_handler(CommandHandler("food", cmd_food))
    app.add_handler(CommandHandler("quiz", gquiz.cmd_quiz)); app.add_handler(CommandHandler("leaderboard", gquiz.cmd_leaderboard)); app.add_handler(CommandHandler("mystats", gquiz.cmd_mystats))
    app.add_handler(PollAnswerHandler(gquiz.on_poll_answer)); app.add_handler(CallbackQueryHandler(gquiz.on_inline_answer, pattern=r"^gq_\d+$"))
    
    app.add_handler(CommandHandler("snake", snake_game.cmd_snake))
    app.add_handler(CallbackQueryHandler(snake_game.handle_snake, pattern=r"^snake_"))
    
    app.add_handler(ChatMemberHandler(gmanager.on_bot_added, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler("setgroup", gmanager.cmd_setgroup)); app.add_handler(CommandHandler("groups", gmanager.cmd_groups)); app.add_handler(CommandHandler("unsetgroup", gmanager.cmd_unsetgroup))
    app.add_handler(CommandHandler("broadcast_covers", cmd_broadcast_covers)); app.add_handler(CommandHandler("leave", cmd_leave_group)); app.add_handler(CommandHandler("leavegroup", cmd_leave_group))
    app.add_handler(CommandHandler("sendto", cmd_send_to_group)); app.add_handler(CommandHandler("globalnews", cmd_global_news)); app.add_handler(CommandHandler("ban", cmd_ban)); app.add_handler(CommandHandler("unban", cmd_unban))
    app.add_handler(CommandHandler("forcepost", cmd_forcepost))
    
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.ALL, gmanager.on_group_message), group=1)
    
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(on_error)
    return app

def main() -> None:
    settings = get_settings(); application = build_application()
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    if render_url:
        port = int(os.environ.get("PORT", "8080")); url_path = application.bot.token; secret = settings.webhook_secret_token
        application.run_webhook(listen="0.0.0.0", port=port, url_path=url_path, webhook_url=f"{render_url}/{url_path}", allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, secret_token=secret if secret else None)
    else:
        _start_health_server(); application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
