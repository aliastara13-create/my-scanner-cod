# -*- coding: utf-8 -*-
# trend_lines.py v4 - valid trend lines only
# - open candle dropped (no repaint)
# - Wilder ATR series, per-pivot tolerance in ATR units
# - line invalid if any close breaks it between anchors
# - breakout = first close beyond line +/- 0.3*ATR (cross event), recent = within N bars
# - expired (old break) lines are discarded
# - slope filter = anchor move >= 1 ATR (scale independent)


def atr_series(candles, period=14):
    n = len(candles)
    if n == 0:
        return []
    tr = [candles[0]["high"] - candles[0]["low"]]
    for i in range(1, n):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    if n <= period:
        a = sum(tr) / n
        return [a] * n
    a = sum(tr[:period]) / period
    out = [a] * period
    for i in range(period, n):
        a = (a * (period - 1) + tr[i]) / period
        out.append(a)
    return out


def calculate_atr(candles, period=14):
    s = atr_series(candles, period)
    return s[-1] if s else 0


def find_pivots(candles, pivot_type="high", lookback=7):
    pivots = []
    n = len(candles)
    key = "high" if pivot_type == "high" else "low"
    for i in range(lookback, n - lookback):
        v = candles[i][key]
        if pivot_type == "high":
            ok = all(v >= candles[i - j][key] for j in range(1, lookback + 1)) and \
                 all(v > candles[i + j][key] for j in range(1, lookback + 1))
        else:
            ok = all(v <= candles[i - j][key] for j in range(1, lookback + 1)) and \
                 all(v < candles[i + j][key] for j in range(1, lookback + 1))
        if ok:
            pivots.append({"idx": i, "price": v})
    return pivots


def classify_pivots(pivots, pivot_type="high"):
    typed = []
    for i, p in enumerate(pivots):
        if i == 0:
            typed.append({**p, "type": "-"})
            continue
        up = p["price"] > pivots[i - 1]["price"]
        if pivot_type == "high":
            typed.append({**p, "type": "HH" if up else "LH"})
        else:
            typed.append({**p, "type": "HL" if up else "LL"})
    return typed


def find_best_line(candles, pivots, side, atr, min_touches=3, tol_factor=0.5,
                   break_factor=0.3, recent_bars=5, min_gap=5, max_age=250):
    """side: 'res' (downtrend line, slope<0) or 'sup' (uptrend line, slope>0)"""
    n = len(candles)
    piv = [p for p in pivots if p["idx"] >= n - max_age]
    best = None
    for a in range(len(piv)):
        for b in range(a + 1, len(piv)):
            p1, p2 = piv[a], piv[b]
            if p2["idx"] - p1["idx"] < min_gap:
                continue
            slope = (p2["price"] - p1["price"]) / (p2["idx"] - p1["idx"])
            if side == "res" and slope >= 0:
                continue
            if side == "sup" and slope <= 0:
                continue
            if abs(p2["price"] - p1["price"]) < atr[p2["idx"]]:
                continue
            icpt = p1["price"] - slope * p1["idx"]

            # first break (cross event) after first anchor
            brk = None
            for i in range(p1["idx"] + 1, n):
                y = slope * i + icpt
                c = candles[i]["close"]
                if side == "res" and c > y + break_factor * atr[i]:
                    brk = i
                    break
                if side == "sup" and c < y - break_factor * atr[i]:
                    brk = i
                    break
            if brk is not None and brk <= p2["idx"]:
                continue  # invalid: broken between anchors
            if brk is not None and (n - 1 - brk) >= recent_bars:
                continue  # expired: old break

            end = brk if brk is not None else n
            touched = []
            for p in piv:
                if p["idx"] < p1["idx"] or p["idx"] >= end:
                    continue
                lp = slope * p["idx"] + icpt
                d = abs(p["price"] - lp)
                if d <= tol_factor * atr[p["idx"]]:
                    touched.append({
                        "idx": p["idx"], "price": p["price"],
                        "dist_pct": round(d / abs(lp) * 100, 3) if lp else 0,
                        "dist_atr": round(d / atr[p["idx"]], 3),
                    })
            touches = len(touched)
            if touches < min_touches:
                continue
            extras = [t for t in touched if t["idx"] not in (p1["idx"], p2["idx"])]
            avg_atr = sum(t["dist_atr"] for t in extras) / len(extras) if extras else 0.0
            avg_pct = sum(t["dist_pct"] for t in extras) / len(extras) if extras else 0.0
            last_touch = max(t["idx"] for t in touched)
            recency = max(0.0, 1 - (n - 1 - last_touch) / max_age)
            score = touches * 12 - avg_atr * 10 + recency * 10
            score = max(0.0, min(100.0, score))
            if best is None or score > best["score"]:
                best = {
                    "slope": round(slope, 8),
                    "intercept": round(icpt, 8),
                    "touches": touches,
                    "avg_dist_pct": round(avg_pct, 3),
                    "avg_dist_atr": round(avg_atr, 3),
                    "score": round(score, 2),
                    "touched_pivots": touched,
                    "start_idx": touched[0]["idx"],
                    "break_idx": brk,
                }
    return best


def _build(best, side, candles, atr, price, all_pivots, recent_bars):
    n = len(candles)
    last = n - 1
    line_now = best["slope"] * last + best["intercept"]
    dist_pct = (price - line_now) / line_now * 100 if line_now else 0
    broken = best["break_idx"] is not None
    if broken:
        btype = "BREAKOUT" if side == "res" else "BREAKDOWN"
    else:
        btype = "ACTIVE"
    return {
        **best,
        "type": "DOWNTREND" if side == "res" else "UPTREND",
        "line_price": round(line_now, 8),
        "dist_pct": round(dist_pct, 2),
        "breakout": {
            "broken": broken,
            "recent": broken,  # expired lines are already discarded
            "type": btype,
            "break_idx": best["break_idx"],
            "bars_ago": (last - best["break_idx"]) if broken else None,
            "dist_pct": round(dist_pct, 2),
        },
        "end_idx": last,
        "all_pivots": all_pivots,
    }


def analyze_trend_lines(candles, current_price=None, lookback=7, min_touches=3,
                        atr_tol_factor=0.5, recent_bars=5, drop_open=True):
    if not candles or len(candles) < 51:
        return None
    c = candles[:-1] if drop_open else candles
    n = len(c)
    price = current_price if current_price is not None else c[-1]["close"]
    atr = atr_series(c)
    atr_now = atr[-1]

    ph = find_pivots(c, "high", lookback)
    pl = find_pivots(c, "low", lookback)
    typed_h = classify_pivots(ph, "high")
    typed_l = classify_pivots(pl, "low")

    down = None
    b = find_best_line(c, ph, "res", atr, min_touches, atr_tol_factor,
                       recent_bars=recent_bars)
    if b:
        down = _build(b, "res", c, atr, price, typed_h, recent_bars)

    up = None
    b = find_best_line(c, pl, "sup", atr, min_touches, atr_tol_factor,
                       recent_bars=recent_bars)
    if b:
        up = _build(b, "sup", c, atr, price, typed_l, recent_bars)

    signals = []
    if up and up["breakout"]["broken"]:
        signals.append({"type": "BREAKDOWN", "line": "uptrend"})
    if down and down["breakout"]["broken"]:
        signals.append({"type": "BREAKOUT", "line": "downtrend"})

    return {
        "uptrend_line": up,
        "downtrend_line": down,
        "pivot_highs_count": len(ph),
        "pivot_lows_count": len(pl),
        "typed_highs": typed_h,
        "typed_lows": typed_l,
        "atr": round(atr_now, 8),
        "lookback": lookback,
        "config": {"atr_tol_factor": atr_tol_factor, "recent_bars": recent_bars,
                   "min_touches": min_touches, "closed_candles": n},
        "summary": {
            "uptrend_strength": up["score"] if up else 0,
            "downtrend_strength": down["score"] if down else 0,
            "signals": signals,
        },
    }
