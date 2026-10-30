# -*- coding: utf-8 -*-
# position_sizing.py — Phase 29: Position Sizing Calculator
# آستانه‌های ریسک از agent_decision گرفته می‌شود (single source of truth)
from agent_decision import AgentDecision


def calculate_position_size(balance, risk_pct, entry, sl):
    """حجم پوزیشن بر اساس ریسک درصدی از موجودی.
    risk_usdt = balance * risk_pct / 100
    size_units = risk_usdt / |entry - sl|
    size_usdt  = size_units * entry
    """
    try:
        balance = float(balance)
        risk_pct = float(risk_pct)
        entry = float(entry)
        sl = float(sl)
    except (TypeError, ValueError):
        return {"size_usdt": 0.0, "size_units": 0.0, "risk_usdt": 0.0}

    risk_usdt = balance * risk_pct / 100.0
    risk_per_unit = abs(entry - sl)
    if balance <= 0 or risk_usdt <= 0 or risk_per_unit <= 0 or entry <= 0:
        return {"size_usdt": 0.0, "size_units": 0.0, "risk_usdt": 0.0}
    size_units = risk_usdt / risk_per_unit
    size_usdt = size_units * entry
    return {"size_usdt": size_usdt, "size_units": size_units, "risk_usdt": risk_usdt}


def calculate_rr(entry, sl, tp):
    """نسبت ریوارد به ریسک — همیشه مثبت"""
    try:
        entry = float(entry)
        sl = float(sl)
        tp = float(tp)
    except (TypeError, ValueError):
        return 0.0
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    return abs(tp - entry) / risk


def suggest_risk_pct(confidence):
    """پیشنهاد ریسک — دقیقاً همان آستانه‌های agent_decision.AgentDecision._calc_position:
    >=90 → 1.5% | >=80 → 1.0% | >=70 → 0.5% | کمتر → 0%
    """
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return 0.0
    return float(AgentDecision()._calc_position(c))


if __name__ == "__main__":
    print("Position sizing module ready")
