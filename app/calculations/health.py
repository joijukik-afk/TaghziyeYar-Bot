"""Additional health calculations: ideal weight, body fat, water, fiber."""

from dataclasses import dataclass


@dataclass
class IdealWeightResult:
    devine: float
    robinson: float
    miller: float
    hamwi: float
    average: float
    bmi_range_low: float
    bmi_range_high: float


def calculate_ideal_weight(height_cm: float, gender: str) -> IdealWeightResult:
    if height_cm <= 0 or height_cm > 260:
        raise ValueError("height out of range")

    h_in = height_cm / 2.54
    is_male = gender == "male"

    devine = (50.0 if is_male else 45.5) + 2.3 * (h_in - 60)
    robinson = (52.0 if is_male else 49.0) + (1.9 if is_male else 1.7) * (h_in - 60)
    miller = (56.2 if is_male else 53.1) + (1.41 if is_male else 1.36) * (h_in - 60)
    hamwi = (48.0 if is_male else 45.5) + (2.7 if is_male else 2.2) * (h_in - 60)

    avg = (devine + robinson + miller + hamwi) / 4.0

    h_m = height_cm / 100.0
    bmi_low = 18.5 * h_m * h_m
    bmi_high = 24.9 * h_m * h_m

    return IdealWeightResult(
        devine=round(devine, 1),
        robinson=round(robinson, 1),
        miller=round(miller, 1),
        hamwi=round(hamwi, 1),
        average=round(avg, 1),
        bmi_range_low=round(bmi_low, 1),
        bmi_range_high=round(bmi_high, 1),
    )


@dataclass
class BodyFatResult:
    percent: float
    category: str
    category_fa: str


def estimate_body_fat(bmi: float, age: int, gender: str) -> BodyFatResult:
    if gender == "male":
        bf = (1.20 * bmi) + (0.23 * age) - 16.2
    else:
        bf = (1.20 * bmi) + (0.23 * age) - 5.4

    bf = round(bf, 1)

    if gender == "male":
        if bf < 6:
            cat, fa = "essential", "چربی ضروری"
        elif bf < 14:
            cat, fa = "athletic", "ورزشکاری"
        elif bf < 18:
            cat, fa = "fit", "خوب"
        elif bf < 25:
            cat, fa = "average", "متوسط"
        else:
            cat, fa = "high", "بالا"
    else:
        if bf < 14:
            cat, fa = "essential", "چربی ضروری"
        elif bf < 21:
            cat, fa = "athletic", "ورزشکاری"
        elif bf < 25:
            cat, fa = "fit", "خوب"
        elif bf < 32:
            cat, fa = "average", "متوسط"
        else:
            cat, fa = "high", "بالا"

    return BodyFatResult(percent=bf, category=cat, category_fa=fa)


def calculate_water_intake(weight_kg: float, activity: str = "moderate") -> tuple[int, int]:
    if weight_kg <= 0:
        return 1500, 2000
    base = weight_kg * 30
    if activity == "high":
        base += 500
    elif activity == "moderate":
        base += 300
    return int(base * 0.9), int(base * 1.2)


def calculate_fiber(calories: int) -> tuple[int, int]:
    if calories <= 0:
        return 20, 30
    base = calories / 1000 * 14
    return int(base * 0.9), int(base * 1.1)
