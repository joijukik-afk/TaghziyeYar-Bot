"""Guardrails that prevent unsafe nutrition advice."""

from dataclasses import dataclass


@dataclass
class GuardrailResult:
    allowed: bool
    reason_fa: str
    referral_fa: str = ""


def check_safety(
    age: int | None,
    weight_kg: float | None,
    height_cm: float | None,
    gender: str | None,
    medical_notes: str | None,
) -> GuardrailResult:
    """Return whether we are allowed to give numeric diet targets."""

    # Children and teenagers
    if age is not None and age < 18:
        return GuardrailResult(
            allowed=False,
            reason_fa="برای افراد زیر ۱۸ سال برنامه غذایی شخصی ارائه نمی‌شه.",
            referral_fa="لطفاً با پزشک اطفال یا متخصص تغذیه کودکان مشورت کن.",
        )

    # Very old users
    if age is not None and age > 80:
        return GuardrailResult(
            allowed=False,
            reason_fa="برای افراد بالای ۸۰ سال، توصیه باید زیر نظر پزشک باشه.",
            referral_fa="لطفاً با پزشک متخصص مشورت کن.",
        )

    # Extreme underweight
    if weight_kg is not None and height_cm:
        h_m = height_cm / 100.0
        if h_m > 0:
            bmi = weight_kg / (h_m * h_m)
            if bmi < 16.0:
                return GuardrailResult(
                    allowed=False,
                    reason_fa="BMI تو در محدوده خطرناکه.",
                    referral_fa="لطفاً فوراً با پزشک متخصص مشورت کن.",
                )

    # Mentioned medical conditions → be cautious
    if medical_notes:
        lowered = medical_notes.lower()
        risky = [
            "دیابت", "diabetes",
            "کلیه", "kidney",
            "کبد", "liver",
            "قلب", "heart",
            "فشار خون", "blood pressure",
            "بارداری", "pregnan",
            "شیردهی", "breastfeed",
            "سرطان", "cancer",
            "اختلال خوردن", "eating disorder",
            "تیروئید", "thyroid",
        ]
        for word in risky:
            if word in lowered:
                return GuardrailResult(
                    allowed=False,
                    reason_fa="با توجه به شرایط پزشکی که ذکر کردی، توصیه عمومی کافی نیست.",
                    referral_fa="لطفاً با پزشک یا متخصص تغذیه مشورت کن.",
                )

    return GuardrailResult(allowed=True, reason_fa="")


def safety_disclaimer() -> str:
    return (
        "⚕️ **یادآوری مهم**\n"
        "این اطلاعات جنبه عمومی داره و جایگزین مشاوره پزشک یا متخصص تغذیه نیست.\n"
        "برای شرایط خاص پزشکی، بارداری، شیردهی یا کودکان، حتماً با متخصص مشورت کن."
    )
