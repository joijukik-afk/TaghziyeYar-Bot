"""BMI calculation with clear interpretation and limits."""

from dataclasses import dataclass


@dataclass
class BMIResult:
    value: float
    category: str          # "underweight" | "normal" | "overweight" | "obese_1" | "obese_2" | "obese_3"
    category_fa: str
    description: str


def _category(bmi: float) -> tuple[str, str, str]:
    """Return (code, Persian label, short description)."""
    if bmi < 16.0:
        return "severe_thin", "لاغری شدید", "نیاز به بررسی فوری پزشکی"
    if bmi < 18.5:
        return "underweight", "کمبود وزن", "کمی کمتر از محدوده سالم"
    if bmi < 25.0:
        return "normal", "وزن نرمال", "در محدوده سالم"
    if bmi < 30.0:
        return "overweight", "اضافه وزن", "کمی بالاتر از محدوده سالم"
    if bmi < 35.0:
        return "obese_1", "چاقی درجه ۱", "نیاز به تغییر سبک زندگی"
    if bmi < 40.0:
        return "obese_2", "چاقی درجه ۲", "نیاز به پیگیری جدی"
    return "obese_3", "چاقی درجه ۳", "نیاز به پیگیری تخصصی"


def calculate_bmi(weight_kg: float, height_cm: float) -> BMIResult:
    """Calculate BMI.

    Raises ValueError on invalid inputs.
    """
    if weight_kg <= 0 or weight_kg > 500:
        raise ValueError("weight out of range (0-500 kg)")
    if height_cm <= 0 or height_cm > 260:
        raise ValueError("height out of range (0-260 cm)")

    h_m = height_cm / 100.0
    bmi = weight_kg / (h_m * h_m)
    bmi = round(bmi, 1)

    code, label, desc = _category(bmi)
    return BMIResult(value=bmi, category=code, category_fa=label, description=desc)


def format_bmi_report(result: BMIResult) -> str:
    """Persian human-readable report (no signature yet)."""
    return (
        f"📊 **نتیجه BMI**\n\n"
        f"• مقدار: **{result.value}**\n"
        f"• وضعیت: **{result.category_fa}**\n"
        f"• توضیح: {result.description}\n\n"
        f"ℹ️ BMI فقط یک تخمین اولیه است و برای ورزشکاران "
        f"یا افراد با توده عضلانی بالا دقیق نیست."
    )
