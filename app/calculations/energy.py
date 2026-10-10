"""BMR / TDEE estimation using Mifflin-St Jeor formula."""

from dataclasses import dataclass


# Activity multipliers (moderate scientific consensus)
ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "high": 1.725,
}

ACTIVITY_LABELS_FA = {
    "sedentary": "کم‌تحرک",
    "light": "فعالیت سبک",
    "moderate": "فعالیت متوسط",
    "high": "فعالیت زیاد",
}


@dataclass
class EnergyResult:
    bmr: float
    tdee: float
    activity_level: str
    formula: str


def calculate_bmr(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str,
) -> float:
    """Mifflin-St Jeor BMR.

    gender: "male" or "female".
    """
    if gender == "male":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161
    return round(bmr, 0)


def calculate_tdee(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str,
    activity_level: str,
) -> EnergyResult:
    """Total Daily Energy Expenditure."""
    if activity_level not in ACTIVITY_FACTORS:
        raise ValueError(f"unknown activity level: {activity_level}")

    bmr = calculate_bmr(weight_kg, height_cm, age, gender)
    factor = ACTIVITY_FACTORS[activity_level]
    tdee = round(bmr * factor, 0)
    return EnergyResult(
        bmr=bmr,
        tdee=tdee,
        activity_level=activity_level,
        formula="Mifflin-St Jeor",
    )


def suggested_calorie_target(
    tdee: float,
    goal: str,
    weight_kg: float,
) -> tuple[int, str]:
    """Suggest a safe daily calorie target based on the user's goal.

    Returns (calories, note_fa).
    The safety rules are conservative on purpose.
    """
    if goal == "lose":
        # Aim for ~0.5 kg/week loss (about 15-20% deficit)
        target = tdee * 0.80
        note = "کاهش وزن آرام و پایدار (حدود ۰.۵ کیلو در هفته)"
    elif goal == "gain":
        target = tdee * 1.15
        note = "افزایش وزن تدریجی"
    elif goal == "muscle":
        target = tdee * 1.10
        note = "عضله‌سازی همراه با تمرین منظم"
    else:
        target = tdee
        note = "حفظ وزن فعلی"

    # Never go below a safe floor
    absolute_floor = 1200 if weight_kg < 60 else 1500
    if target < absolute_floor:
        target = absolute_floor
        note += " (کف ایمن اعمال شد)"

    return int(round(target)), note


def format_energy_report(result: EnergyResult, target: int, note: str) -> str:
    activity_fa = ACTIVITY_LABELS_FA.get(result.activity_level, result.activity_level)
    return (
        f"🔥 **نیاز کالری روزانه**\n\n"
        f"• متابولیسم پایه (BMR): **{int(result.bmr)}** کالری\n"
        f"• فعالیت: {activity_fa}\n"
        f"• کل مصرف روزانه (TDEE): **{int(result.tdee)}** کالری\n"
        f"• هدف پیشنهادی: **{target}** کالری\n"
        f"• توضیح: {note}\n\n"
        f"ℹ️ فرمول: {result.formula}\n"
        f"اعداد تخمینی هستند و با گذشت زمان و تغییر وزن، بازنگری می‌شن."
    )
