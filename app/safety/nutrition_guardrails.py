"""Guardrails that prevent unsafe nutrition advice."""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GuardrailResult:
    allowed: bool
    reason_fa: str
    referral_fa: str = ""
    code: str = ""  # 👈 برای لاگ و ممیزی (بدون افشای اطلاعات کاربر)


# ============================================================
# کلمات کلیدی ریسک (با پوشش صیغه‌های مختلف فارسی)
# ============================================================
_PREGNANCY_TERMS = [
    "باردار",     # بارداری، باردارم، باردار هستم
    "حامله",      # حامله، حامله‌ام
    "جنین",       # جنین دارم
    "pregnan",    # pregnancy, pregnant
]
_BREASTFEEDING_TERMS = [
    "شیردهی", "شیرده", "شیر می‌دم", "شیر میدم",
    "شیردادن", "نوزاد", "نوزادم", "شیرخوار",
    "breastfeed", "lactat",
]
_CHRONIC_DISEASE_TERMS = [
    "دیابت", "قند خون", "diabetes",
    "کلیه", "kidney",
    "کبد", "liver",
    "قلب", "heart",
    "فشار خون", "blood pressure",
    "سرطان", "cancer",
    "تیروئید", "thyroid",
    "کلسترول", "cholesterol",
    "میکروب روده", "gut",
]
_EATING_DISORDER_TERMS = [
    "اختلال خوردن", "بولیمیا", "آنورکسیا", "پراشتهایی",
    "eating disorder", "bulimia", "anorexia",
]

# 👈 لیست واحد برای بررسی سریع
_ALL_RISKY_TERMS = (
    [(t, "PREGNANCY") for t in _PREGNANCY_TERMS]
    + [(t, "BREASTFEEDING") for t in _BREASTFEEDING_TERMS]
    + [(t, "CHRONIC_DISEASE") for t in _CHRONIC_DISEASE_TERMS]
    + [(t, "EATING_DISORDER") for t in _EATING_DISORDER_TERMS]
)


def _detect_risky_condition(medical_notes: str) -> str | None:
    """تشخیص هوشمند شرایط پزشکی پرخطر. کد وضعیت را برمی‌گرداند یا None."""
    text = medical_notes.strip()
    if not text:
        return None

    # 👈 استفاده از regex برای تطابق مرز کلمه (جلوگیری از False Positive)
    for term, code in _ALL_RISKY_TERMS:
        # برای کلمات فارسی، جستجوی ساده کافی است چون مرز کلمه ندارند
        # برای کلمات انگلیسی، مرز کلمه بررسی می‌شود
        if term.isascii():
            if re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE):
                return code
        else:
            if term in text:
                return code
    return None


def _safe_float(v) -> float | None:
    """تبدیل امن به float (برگرداندن None در صورت خطا)"""
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def check_safety(
    age: int | None,
    weight_kg: float | None,
    height_cm: float | None,
    gender: str | None,
    medical_notes: str | None,
) -> GuardrailResult:
    """
    بررسی ایمنی برای ارائه اهداف غذایی عددی.
    اصل: Fail-Safe — اگر داده‌ها ناقص باشند، محتاطانه عمل می‌کنیم.
    """

    # 👈 ۱. اولویت اول: شرایط پزشکی حاد (بارداری، شیردهی، بیماری‌های مزمن)
    if medical_notes:
        risky_code = _detect_risky_condition(medical_notes)
        if risky_code == "PREGNANCY":
            logger.info("Guardrail triggered: PREGNANCY")
            return GuardrailResult(
                allowed=False,
                reason_fa="دوره بارداری نیازمند نظارت تخصصی بر تغذیه است.",
                referral_fa="لطفاً با پزشک متخصص زنان یا متخصص تغذیه بارداری مشورت کن.",
                code="PREGNANCY",
            )
        if risky_code == "BREASTFEEDING":
            logger.info("Guardrail triggered: BREASTFEEDING")
            return GuardrailResult(
                allowed=False,
                reason_fa="دوره شیردهی نیازمند برنامه تغذیه اختصاصی است.",
                referral_fa="لطفاً با پزشک یا مشاور شیردهی مشورت کن.",
                code="BREASTFEEDING",
            )
        if risky_code == "EATING_DISORDER":
            logger.info("Guardrail triggered: EATING_DISORDER")
            return GuardrailResult(
                allowed=False,
                reason_fa="با توجه به سابقه اختلال خوردن، توصیه عددی امن نیست.",
                referral_fa="لطفاً با روانپزشک یا متخصص تغذیه اختلالات خوردن مشورت کن.",
                code="EATING_DISORDER",
            )
        if risky_code == "CHRONIC_DISEASE":
            logger.info("Guardrail triggered: CHRONIC_DISEASE")
            return GuardrailResult(
                allowed=False,
                reason_fa="با توجه به شرایط پزشکی ذکر شده، توصیه عمومی کافی نیست.",
                referral_fa="لطفاً با پزشک یا متخصص تغذیه مشورت کن.",
                code="CHRONIC_DISEASE",
            )

    # 👈 ۲. محدوده سنی
    if age is not None:
        if age < 18:
            return GuardrailResult(
                allowed=False,
                reason_fa="برای افراد زیر ۱۸ سال برنامه غذایی شخصی ارائه نمی‌شه.",
                referral_fa="لطفاً با پزشک اطفال یا متخصص تغذیه کودکان مشورت کن.",
                code="UNDER_18",
            )
        if age > 80:
            return GuardrailResult(
                allowed=False,
                reason_fa="برای افراد بالای ۸۰ سال، توصیه باید زیر نظر پزشک باشه.",
                referral_fa="لطفاً با پزشک متخصص مشورت کن.",
                code="OVER_80",
            )

    # 👈 ۳. بررسی BMI (هم کمبود شدید، هم چاقی مفرط)
    w = _safe_float(weight_kg)
    h = _safe_float(height_cm)
    if w is not None and h is not None and h > 0:
        bmi = w / ((h / 100.0) ** 2)
        if bmi < 16.0:
            return GuardrailResult(
                allowed=False,
                reason_fa=f"شاخص توده بدنی (BMI) شما {bmi:.1f} است که در محدوده خطرناک کمبود وزن قرار دارد.",
                referral_fa="لطفاً فوراً با پزشک متخصص تغذیه مشورت کن.",
                code="BMI_UNDERWEIGHT",
            )
        if bmi >= 40.0:
            logger.info("Guardrail triggered: BMI_SEVERE_OBESITY")
            return GuardrailResult(
                allowed=False,
                reason_fa=f"شاخص توده بدنی (BMI) شما {bmi:.1f} است که در محدوده چاقی مفرط قرار دارد.",
                referral_fa="برنامه‌ریزی برای این وضعیت نیازمند نظارت پزشک متخصص است.",
                code="BMI_SEVERE_OBESITY",
            )

    # 👈 ۴. سن نامشخص (ناقص بودن پروفایل) — محتاطانه
    if age is None:
        logger.warning("Guardrail: age is None (incomplete profile)")
        return GuardrailResult(
            allowed=False,
            reason_fa="برای ارائه توصیه دقیق، ابتدا پروفایل خود را کامل کن.",
            referral_fa="لطفاً دستور /setup را اجرا کن.",
            code="INCOMPLETE_PROFILE",
        )

    return GuardrailResult(allowed=True, reason_fa="", code="OK")


def safety_disclaimer() -> str:
    """👈 تغییر به HTML برای هماهنگی با کل پروژه"""
    return (
        "⚕️ <b>یادآوری مهم</b>\n"
        "این اطلاعات جنبه عمومی داره و جایگزین مشاوره پزشک یا متخصص تغذیه نیست.\n"
        "برای شرایط خاص پزشکی، بارداری، شیردهی یا کودکان، حتماً با متخصص مشورت کن."
    )
