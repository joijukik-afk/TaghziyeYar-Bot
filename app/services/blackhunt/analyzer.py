"""تحلیل‌گر — محاسبات تخفیف واقعی، امتیازدهی و حذف تکراری."""
import datetime, re
from typing import List
from app.services.blackhunt.models import DealResult, SearchIntent

def _median(values: List[int]) -> float:
    if not values: return 0
    s = sorted(values); n = len(s)
    return (s[n//2-1] + s[n//2]) / 2 if n % 2 == 0 else float(s[n//2])

def _normalize_key(title: str) -> str:
    t = (title or "").lower().strip()
    for w in ("خرید","قیمت","تخفیف","فروش","اصل","اورجینال"): t = t.replace(w, "")
    return re.sub(r"\s+", " ", t)[:50]

def analyze_deals(deals: List[DealResult]) -> List[DealResult]:
    if not deals: return deals
    groups = {}
    for d in deals: groups.setdefault(_normalize_key(d.product_name), []).append(d)
    for group in groups.values():
        prices = [d.current_price for d in group if d.current_price]
        if len(prices) >= 2:
            median = _median(prices)
            for d in group:
                if d.current_price and median and median > d.current_price:
                    d.real_discount_percent = round((1 - d.current_price / median) * 100)
                    d.marketplace_median = int(median)
    for d in deals:
        d.deal_score = _score(d)
        d.confidence_score = _confidence(d)
        d.discount_status = _classify(d)
        d.verified_at = datetime.datetime.now().isoformat(timespec="seconds")
    deals.sort(key=lambda x: (-x.deal_score, -(x.real_discount_percent or 0)))
    return deals

def _score(d: DealResult) -> float:
    score = 0.0
    if d.real_discount_percent: score += min(d.real_discount_percent, 50) * 0.8
    elif d.listed_discount_percent: score += min(d.listed_discount_percent, 50) * 0.4
    if d.rating: score += (d.rating / 5.0) * 20
    if d.availability == "موجود": score += 20
    elif d.availability == "ناموجود": score -= 10
    if d.current_price and d.listed_old_price: score += 20
    elif d.current_price: score += 10
    return max(0.0, min(100.0, round(score, 1)))

def _confidence(d: DealResult) -> float:
    conf = 50.0
    if d.source_provider.startswith("mcp_"): conf += 30
    if d.current_price: conf += 10
    if d.listed_old_price: conf += 5
    if d.real_discount_percent: conf += 5
    return min(100.0, round(conf, 1))

def _classify(d: DealResult) -> str:
    listed = d.listed_discount_percent or 0; real = d.real_discount_percent
    if real is not None:
        if real >= listed * 0.7: return "verified"
        if real >= listed * 0.3: return "likely"
        return "fake"
    if d.current_price and d.listed_old_price: return "likely"
    return "insufficient_data"

def deduplicate(deals: List[DealResult]) -> List[DealResult]:
    seen = set(); out = []
    for d in deals:
        if d.product_url in seen: continue
        seen.add(d.product_url); out.append(d)
    return out

def filter_by_intent(deals: List[DealResult], intent: SearchIntent) -> List[DealResult]:
    out = []
    for d in deals:
        if intent.min_discount:
            pct = d.real_discount_percent or d.listed_discount_percent or 0
            if pct < intent.min_discount: continue
        if intent.price_max and d.current_price and d.current_price > intent.price_max: continue
        if intent.price_min and d.current_price and d.current_price < intent.price_min: continue
        if intent.must_be_in_stock and d.availability == "ناموجود": continue
        out.append(d)
    return out
