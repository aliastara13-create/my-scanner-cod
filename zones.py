# -*- coding: utf-8 -*-
# zones.py — Visual Zone Recognition + Liquidity (D-zone feature, stdlib only)
# detect_1h_zones(candles_1h): Supply = last bearish candle before a strong bearish move;
#                              Demand = last bullish candle before a strong bullish move.
#   Strong move: price displacement >= 1 ATR within <= 2 candles toward the new trend.
#   Zone range = origin candle wick range [low..high].
#   Validation: broken (close beyond zone by a body close) -> invalid; retests counted after
#               the move window; keep only zones with retests <= 1 (untested or max 1 retest).
#   Strength (0-100) = 0.4*impulse + 0.3*volume + 0.3*freshness:
#       impulse  = min(1, move_atr/2)
#       volume   = min(1, vol_of_origin / (2*SMA20(volume)))
#       freshness= max(0, 1 - bars_since/24)
#   Output: up to 3 SUPPLY + 3 DEMAND, strongest first; overlapping zones deduped (keep strongest).
# detect_liquidity_levels(candles_by_tf): PDH/PDL from last closed daily candle, PWH/PWL from
#       last closed weekly candle, h4_high/h4_low = last confirmed 4H pivot (2-bar confirm).
# candles: {"time" (seconds), "open", "high", "low", "close", "volume"} oldest -> newest.
import json
import time as _time
import urllib.request

ENDPOINTS = [
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://data-api.binance.vision",
]

ZONE_MAX_PER_KIND = 3
IMPULSE_MIN_ATR = 1.0       # locked default (user)
IMPULSE_MAX_CANDLES = 2
RETEST_LIMIT = 1
FRESHNESS_WINDOW = 24       # bars; older zones decay to 0 freshness
MAX_ORIGINS_BACK = 200      # ignore zones older than this many bars
WEIGHT_IMPULSE, WEIGHT_VOLUME, WEIGHT_FRESHNESS = 0.4, 0.3, 0.3


def fetch_klines(symbol, interval, limit, timeout=15):
    """On-demand klines fetch with endpoint fallbacks (no background jobs; request-time only)."""
    for host in ENDPOINTS:
        try:
            url = "%s/api/v3/klines?symbol=%s&interval=%s&limit=%d" % (host, symbol, interval, int(limit))
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            print("[zones] fetch %s (%s): %s" % (host, symbol, e))
    return None


def klines_to_candles(klines):
    """Binance klines -> candle dicts (time in SECONDS, matching /api/chart)."""
    return [{"time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in klines]


def _true_ranges(candles):
    trs = []
    prev_close = candles[0]["close"] if candles else 0.0
    for c in candles:
        tr = max(c["high"] - c["low"], abs(c["high"] - prev_close), abs(c["low"] - prev_close))
        trs.append(tr)
        prev_close = c["close"]
    return trs


def _atr_at(candles, trs, i, window=14):
    start = max(0, i - window + 1)
    seg = trs[start:i + 1]
    if not seg:
        return 0.0
    return sum(seg) / len(seg)


def _volume_sma20(candles, i):
    if i < 0:
        return 0.0
    seg = candles[max(0, i - 19):i + 1]
    if not seg:
        return 0.0
    return sum(c["volume"] for c in seg) / len(seg)


def _origin_zones(candles):
    """Yield raw zone dicts (kind, i, move_candles, move_atr, top, bottom) before validation."""
    n = len(candles)
    if n < 30:
        return
    trs = _true_ranges(candles)
    for i in range(max(20, n - 1 - MAX_ORIGINS_BACK), n - 2):
        c = candles[i]
        atr = _atr_at(candles, trs, i)
        if atr <= 0:
            continue
        is_bearish = c["close"] < c["open"]
        is_bullish = not is_bearish
        nxt = candles[i + 1:i + 1 + IMPULSE_MAX_CANDLES]
        if not nxt:
            continue
        if is_bearish:
            move = c["close"] - min(x["low"] for x in nxt)
        else:
            move = max(x["high"] for x in nxt) - c["close"]
        if move < IMPULSE_MIN_ATR * atr:
            continue
        yield {
            "kind": "SUPPLY" if is_bearish else "DEMAND",
            "i": i,
            "time": c["time"],
            "top": c["high"],
            "bottom": c["low"],
            "move_atr": move / atr,
            "impulse_orig": c,
        }


def detect_1h_zones(candles_1h):
    """zones.py core: valid Supply/Demand list with strength scoring (see module header)."""
    if not candles_1h or len(candles_1h) < 30:
        return []
    n = len(candles_1h)
    raw = list(_origin_zones(candles_1h))
    scored = []
    for z in raw:
        i = z["i"]
        origin_vol = z["impulse_orig"]["volume"]
        sma20 = _volume_sma20(candles_1h, i)
        bars_since = (n - 1) - i
        impulse = min(1.0, z["move_atr"] / 2.0)
        volume = min(1.0, origin_vol / (2.0 * sma20)) if sma20 > 0 else 0.0
        freshness = max(0.0, 1.0 - bars_since / FRESHNESS_WINDOW)
        strength = 100.0 * (WEIGHT_IMPULSE * impulse + WEIGHT_VOLUME * volume +
                            WEIGHT_FRESHNESS * freshness)
        scored.append({
            "kind": z["kind"], "top": z["top"], "bottom": z["bottom"], "time": z["time"],
            "move_atr": round(z["move_atr"], 3),
            "strength": round(strength, 1),
            "parts": {"impulse": round(impulse, 3), "volume": round(volume, 3),
                      "freshness": round(freshness, 3)},
            "i": i,
        })
    valid = []
    for z in scored:
        i = z.pop("i")
        top, bottom = z["top"], z["bottom"]
        move_end = min(n - 1, i + IMPULSE_MAX_CANDLES)
        retests = 0
        broken = False
        for j in range(i + 1, n):
            c = candles_1h[j]
            if j > move_end:  # after the impulse window: wick entering the zone counts as a retest
                if z["kind"] == "SUPPLY" and c["high"] >= bottom:
                    retests += 1
                elif z["kind"] == "DEMAND" and c["low"] <= top:
                    retests += 1
            if z["kind"] == "SUPPLY" and c["close"] > top:  # price closed through resistance
                broken = True
                break
            if z["kind"] == "DEMAND" and c["close"] < bottom:  # price closed through support
                broken = True
                break
        if broken:
            continue
        if retests > RETEST_LIMIT:
            continue
        z["retests"] = retests
        z["ended_at"] = None  # active: frontend extends to right edge
        valid.append(z)
    # per-kind strongest-first + overlap dedupe (>=60% overlap of the smaller span -> same zone)
    out = []
    for kind in ("SUPPLY", "DEMAND"):
        picked = []
        for z in sorted([v for v in valid if v["kind"] == kind], key=lambda x: -x["strength"]):
            span = z["top"] - z["bottom"]
            clash = False
            for p in picked:
                ov = min(z["top"], p["top"]) - max(z["bottom"], p["bottom"])
                if span > 0 and ov > 0.6 * min(span, p["top"] - p["bottom"]):
                    clash = True
                    break
            if not clash:
                picked.append(z)
            if len(picked) >= ZONE_MAX_PER_KIND:
                break
        out.extend(picked)
    out.sort(key=lambda x: (x["kind"], -x["strength"]))  # per-kind strongest-first
    return out


def _last_confirmed_pivot(hi, lo, kind, back=2):
    """Last confirmed pivot (2-bar confirm on both sides). kind: 'high'|'low'.
    hi/lo: parallel arrays of price floats, oldest->newest. Returns price or None."""
    n = len(hi)
    if kind == "high":
        for i in range(n - 1 - back, back - 1, -1):
            if hi[i] == max(hi[i - back:i + back + 1]):
                return hi[i]
    else:
        for i in range(n - 1 - back, back - 1, -1):
            if lo[i] == min(lo[i - back:i + back + 1]):
                return lo[i]
    return None


def detect_liquidity_levels(candles_by_tf):
    """PDH/PDL (last closed daily), PWH/PWL (last closed weekly), h4_high/h4_low (last confirmed 4H pivot).
    candles_by_tf: {"1D": [...], "1W": [...], "4H": [...]} — missing key -> None field."""
    out = {"pdh": None, "pdl": None, "pwh": None, "pwl": None, "h4_high": None, "h4_low": None}
    d = candles_by_tf.get("1D")
    if d and len(d) >= 2:
        prev_day = d[-2]  # [-1] is the OPEN (current) candle
        out["pdh"], out["pdl"] = prev_day["high"], prev_day["low"]
    w = candles_by_tf.get("1W")
    if w and len(w) >= 2:
        prev_week = w[-2]
        out["pwh"], out["pwl"] = prev_week["high"], prev_week["low"]
    h4 = candles_by_tf.get("4H")
    if h4:
        hi = [c["high"] for c in h4]
        lo = [c["low"] for c in h4]
        out["h4_high"] = _last_confirmed_pivot(hi, lo, "high")
        out["h4_low"] = _last_confirmed_pivot(hi, lo, "low")
    return out
