"""Macronutrient split based on goal."""

from dataclasses import dataclass


@dataclass
class MacroSplit:
    protein_g: int
    carbs_g: int
    fat_g: int
    fiber_g: int
    water_ml: int


def _ratios(goal: str) -> tuple[float, float, float]:
    """Return (protein, carbs, fat) ratios that sum to 1."""
    # Conservative splits used by many sports-nutrition guidelines
    if goal in ("lose", "muscle"):
        return (0.30, 0.40, 0.30)
    if goal == "gain":
        return (0.25, 0.50, 0.25)
    if goal == "sport":
        return (0.30, 0.45, 0.25)
    return (0.20, 0.50, 0.30)


def calculate_macros(
    calories: int,
    goal: str,
    weight_kg: float,
) -> MacroSplit:
    p_ratio, c_ratio, f_ratio = _ratios(goal)

    protein_g = round(calories * p_ratio / 4)
    carbs_g = round(calories * c_ratio / 4)
    fat_g = round(calories * f_ratio / 9)

    # Fiber: 14 g per 1000 kcal (widely used guideline)
    fiber_g = max(15, round(calories / 1000 * 14))

    # Water: 30 ml per kg + activity, capped at a safe range
    water_ml = int(round(weight_kg * 30 + 500))

    return MacroSplit(
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        fiber_g=fiber_g,
        water_ml=water_ml,
    )


def format_macros_report(m: MacroSplit) -> str:
    return (
        f"🍽 **درشت‌مغذی‌های روزانه**\n\n"
        f"• پروتئین: **{m.protein_g}** گرم\n"
        f"• کربوهیدرات: **{m.carbs_g}** گرم\n"
        f"• چربی: **{m.fat_g}** گرم\n"
        f"• فیبر: **{m.fiber_g}** گرم\n"
        f"• آب: **{m.water_ml}** میلی‌لیتر\n\n"
        f"ℹ️ این اعداد تخمینی هستند و بر اساس هدف و وزن تو تنظیم می‌شن."
    )
