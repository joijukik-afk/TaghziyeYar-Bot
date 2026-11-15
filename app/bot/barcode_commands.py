"""Barcode Scanner for Nutrition Facts (Using OpenFoodFacts API)."""
import io
import logging
import httpx
from PIL import Image
from pyzbar.pyzbar import decode
from telegram import Update
from telegram.ext import ContextTypes
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

async def cmd_barcode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
        
    photo = None
    if update.message.photo:
        photo = update.message.photo[-1]
    elif update.message.reply_to_message and update.message.reply_to_message.photo:
        photo = update.message.reply_to_message.photo[-1]
        
    if not photo:
        return await update.message.reply_text(
            with_signature("⚠️ لطفاً یک عکس از بارکد مواد غذایی بفرستید یا روی آن ریپلای کنید."),
            parse_mode="HTML"
        )

    status_msg = await update.message.reply_text("🔍 در حال اسکن بارکد...")

    try:
        file = await context.bot.get_file(photo.file_id)
        img_bytes = await file.download_as_bytearray()
        img = Image.open(io.BytesIO(img_bytes))

        decoded_objects = decode(img)
        if not decoded_objects:
            return await status_msg.edit_text("❌ بارکدی در عکس پیدا نشد. لطفاً عکس واضح‌تری بفرستید.")

        barcode = decoded_objects[0].data.decode("utf-8")
        await status_msg.edit_text(f"✅ بارکد پیدا شد: <code>{barcode}</code>\n⏳ در حال دریافت اطلاعات تغذیه‌ای...", parse_mode="HTML")

        url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            data = resp.json()

        if data.get("status") != 1:
            return await status_msg.edit_text("❌ اطلاعاتی برای این بارکد در دیتابیس جهانی پیدا نشد.")

        product = data.get("product", {})
        name = product.get("product_name", "نامشخص")
        nutriments = product.get("nutriments", {})
        
        calories = nutriments.get("energy-kcal_100g", "نامشخص")
        protein = nutriments.get("proteins_100g", "نامشخص")
        carbs = nutriments.get("carbohydrates_100g", "نامشخص")
        fat = nutriments.get("fat_100g", "نامشخص")

        text = (
            f"📦 <b>اطلاعات محصول:</b> {name}\n"
            f"🔢 <b>بارکد:</b> <code>{barcode}</code>\n\n"
            f"🍽 <b>ارزش غذایی در هر ۱۰۰ گرم:</b>\n"
            f"🔥 کالری: {calories} kcal\n"
            f"🥩 پروتئین: {protein} g\n"
            f"🍞 کربوهیدرات: {carbs} g\n"
            f"🧈 چربی: {fat} g\n\n"
            f"📊 منبع: OpenFoodFacts"
        )
        await status_msg.edit_text(with_signature(text), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Barcode scan error: {e}", exc_info=True)
        await status_msg.edit_text("❌ متأسفانه در اسکن بارکد خطایی رخ داد.")
