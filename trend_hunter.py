# -*- coding: utf-8 -*-
# trend_hunter.py v5
# 2 touches + price within 0.5 ATR of projected line = HUNTING
# 3 = CONFIRMED, 4+ = STRONG (ACTIVE lines only)
# TRIGGERED = recent cross-event break (closed candle), dist<5%, touches>=3
# v5: TRIGGERED lifecycle — live SL/TP check => STOPPED / TARGET_HIT (post-mortem)
import urllib.request
import json
import os
import glob
import io_atomic  # D18
import sl_tp  # D1:
import time
from datetime import datetime
from trend_lines import analyze_trend_lines

HUNTER_STATUSES = ("TRIGGERED", "STRONG", "CONFIRMED", "HUNTING", "WATCHLIST", "STOPPED", "TARGET_HIT")
RESOLVED_STATUSES = ("STOPPED", "TARGET_HIT")
HISTORY_MAX = 30

# Phase 31.5: backtest fee=0.15% (results/backtest_20261017_011014.json) -> max t per TF = +1.05 < 2
# => all trend-line TRIGGERED signals are watchlist only; no entry/SL/TP levels, no alerts
WATCHLIST_ONLY = True


def gate_status(status):
    """Phase 31.5 gate: when WATCHLIST_ONLY, fresh TRIGGERED setups become WATCHLIST (non-actionable)."""
    if WATCHLIST_ONLY and status == "TRIGGERED":
        return "WATCHLIST"
    return status


def volume_state(vol_24h, floor):
    """PH33: tri-state -- True (>= floor) / False (< floor) / None (unknown data).
    PH33B: consumers fail CLOSED on None -- WATCHLIST / stars=1 (never actionable)."""
    if vol_24h is None:
        return None
    try:
        v = float(vol_24h)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return v >= floor


# PH33: resolved lifecycles (STOPPED/TARGET_HIT) survive the volume gate
VOLUME_PRESERVE_STATUSES = set(RESOLVED_STATUSES)


def apply_volume_gate(setups, vol_map, floor):
    """PH33 volume gate (additional layer on top of the t-rule gate):
    stamp volume_24h + volume_ok on every setup; low-vol symbols (< floor)
    get all non-resolved statuses -> WATCHLIST (no alerts, no position button)."""
    for s in setups:
        info = vol_map.get(s.get("symbol"))
        vol = info.get("quote_volume_24h") if info else None
        ok = volume_state(vol, floor)
        s["volume_24h"] = vol if (vol and vol > 0) else None
        s["volume_ok"] = ok
        # PH33B: fail-closed; resolved lifecycles + already-WATCHLIST rows untouched
        if s.get("status") in VOLUME_PRESERVE_STATUSES or s.get("status") == "WATCHLIST":
            continue
        if ok is False:
            s["status"] = "WATCHLIST"
            s["status_reason"] = "LOW_VOLUME"
        elif ok is None:
            s["status"] = "WATCHLIST"
            s["status_reason"] = "NO_VOLUME_DATA"
    return setups


def fetch_candles(symbol, interval, limit=300):
    path = "/api/v3/klines?symbol=%s&interval=%s&limit=%d" % (symbol, interval, limit)
    try:
        from fast_fetch import get_json_fast
        data = get_json_fast(path, timeout=15, cache_ttl=0)
        return [
            {"time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
            for k in data
        ]
    except Exception as e:
        print("  fetch error %s %s: %s" % (symbol, interval, e))
        return None


def red_gate(candles):  # T3D: rule-2 -- True only when the LAST TWO CLOSED candles ([-2],[-3]) are red
    """T3D rule 2: candles[-1] is the forming kline (fetch_candles convention). Fail-close:
    no candles / <3 items / non-numeric open-close -> False (SELL not allowed)."""
    if not candles or len(candles) < 3:
        return False
    try:
        return all(float(c["close"]) < float(c["open"]) for c in (candles[-2], candles[-3]))
    except (TypeError, ValueError, KeyError):
        return False


def classify_setup(line, current_price, atr, candles=None):  # T3D: rule-2 gate feed (SELL only)
    if not line:
        return None
    touches = line["touches"]
    bo = line.get("breakout", {})
    d = line.get("dist_pct", 0)

    if bo.get("broken"):
        side_ok = (d > 0) if line["type"] == "DOWNTREND" else (d < 0)
        if bo.get("recent") and touches >= 3 and side_ok and (atr <= 0 or abs(current_price - line["line_price"]) <= 1.5 * atr and abs(d) < 5.0):
            signal = "BUY" if line["type"] == "DOWNTREND" else "SELL"
            if signal == "SELL" and not red_gate(candles):  # T3D: rule-2 SELL gate (fail-close)
                return None
            return {"status": "TRIGGERED", "signal": signal, "priority": 1, "line": line}
        return None

    if atr > 0 and abs(current_price - line["line_price"]) > 2 * atr:
        return None
    if touches >= 4:
        return {"status": "STRONG", "priority": 2, "line": line}
    if touches == 3:
        return {"status": "CONFIRMED", "priority": 3, "line": line}
    if touches == 2 and atr > 0:
        if abs(current_price - line["line_price"]) <= 0.5 * atr:
            return {"status": "HUNTING", "priority": 4, "line": line}
    return None


def setup_levels(s):
    """D1: SL/TP via sl_tp.py — identical to backtest_lines.py on the same input.
    SL = last opposite pivot +/- sl_atr_factor*ATR (no pivot -> 2*ATR fallback; no ATR -> legacy line / 1% band);
    TP = tp_targets[0] * risk from risk_config.json (second target stamped as tp2 on the setup)."""
    entry = float(s.get("current_price") or 0)
    side = s.get("signal") or ("SELL" if s.get("direction") == "UPTREND" else "BUY")
    atr = float(s.get("atr_at_signal") or 0)
    piv = s.get("pivot_price")
    try:
        piv = float(piv) if piv is not None and float(piv) > 0 else None
    except (TypeError, ValueError):
        piv = None
    if atr > 0:
        if piv is not None:
            sl = sl_tp.calc_sl(side, piv, atr)
        else:
            sl = sl_tp.fallback_sl(side, entry, atr)
    else:
        lp = float((s.get("line") or {}).get("line_price") or 0)
        is_buy = side != "SELL"
        sl = lp if lp > 0 else (entry * 0.99 if is_buy else entry * 1.01)  # legacy last resort (old carried files)
    if not (sl > 0):
        sl = sl_tp.fallback_sl(side, entry, atr) if atr > 0 else 0.0
    tps = sl_tp.calc_tp(entry, sl, side)
    tp = tps[0] if tps else 0.0
    if len(tps) > 1:
        s["tp2"] = round(tps[1], 8)  # D1: second target (tp_targets[1])
    return round(entry, 8), round(sl, 8), round(tp, 8)


def key_of(s):
    return (s.get("symbol"), s.get("tf"), s.get("direction"))


def evaluate_triggered(s, price, now_iso):
    """Live SL/TP check for a TRIGGERED setup vs fresh price."""
    s2 = dict(s)
    try:
        entry = float(s2.get("entry") or 0)
        sl = float(s2.get("sl") or 0)
        tp = float(s2.get("tp") or 0)
    except (TypeError, ValueError):
        entry = sl = tp = 0
    if not (sl > 0 and tp > 0):
        entry, sl, tp = setup_levels(s)
    elif entry <= 0:
        entry = float(s2.get("current_price") or 0)
    s2["entry"], s2["sl"], s2["tp"] = entry, sl, tp
    s2["current_price"] = price
    is_buy = s2.get("signal") == "BUY"
    hit_sl = (price <= sl) if is_buy else (price >= sl)
    hit_tp = (price >= tp) if is_buy else (price <= tp)
    if hit_sl:
        s2["status"] = "STOPPED"
    elif hit_tp:
        s2["status"] = "TARGET_HIT"
    else:
        s2["status"] = "TRIGGERED"
    if s2["status"] in RESOLVED_STATUSES:
        s2["resolved_at"] = now_iso
    return s2


def process_previous(prev_setups, price_map, now_iso, cap=HISTORY_MAX):
    """Split previous setups: still-live TRIGGERED vs resolved history (STOPPED/TARGET_HIT)."""
    carried_live, resolved = [], []
    for s in prev_setups or []:
        st = s.get("status")
        if st == "TRIGGERED":
            price = price_map.get(key_of(s))
            if price is None:
                s2 = dict(s)
                if not (float(s2.get("sl") or 0) > 0):
                    e, sl, tp = setup_levels(s2)
                    s2["entry"], s2["sl"], s2["tp"] = e, sl, tp
                carried_live.append(s2)
                continue
            s2 = evaluate_triggered(s, price, now_iso)
            if s2["status"] == "TRIGGERED":
                carried_live.append(s2)
            else:
                resolved.append(s2)
        elif st in RESOLVED_STATUSES:
            resolved.append(dict(s))
    dedup = {}
    for s in resolved:
        k = key_of(s)
        cur = dedup.get(k)
        if cur is None or str(s.get("resolved_at") or "") >= str(cur.get("resolved_at") or ""):
            dedup[k] = s
    resolved = sorted(dedup.values(), key=lambda x: str(x.get("resolved_at") or ""), reverse=True)[:cap]
    return carried_live, resolved


def _sort_key(s):
    st = s.get("status")
    rank = HUNTER_STATUSES.index(st) if st in HUNTER_STATUSES else len(HUNTER_STATUSES)
    return (rank, s.get("priority", 9), -((s.get("line") or {}).get("touches") or 0))


def merge_tracked(fresh, carried_live, resolved):
    """Merge fresh scan + carried live + resolved history (dedupe by symbol/tf/direction)."""
    final = list(fresh)
    keys = {key_of(s) for s in final}
    for s in carried_live:
        if key_of(s) not in keys:
            final.append(s)
            keys.add(key_of(s))
    for s in resolved:
        if key_of(s) not in keys:
            final.append(s)
            keys.add(key_of(s))
    for s in final:
        if s.get("status") == "TRIGGERED" and not (float(s.get("sl") or 0) > 0):
            e, sl, tp = setup_levels(s)
            s["entry"], s["sl"], s["tp"] = e, sl, tp
    final.sort(key=_sort_key)
    return final


def status_counts(setups):
    return {st: sum(1 for s in setups if s.get("status") == st) for st in HUNTER_STATUSES}


def load_previous():
    """Return (path, data) of the latest hunter file, or (None, None).
    D18: corrupt newest -> skip and fall back to the previous valid file."""
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    files = sorted(glob.glob(os.path.join(results_dir, "hunter_*.json")))
    _err = lambda p, e: print("  prev read error (%s): %s" % (os.path.basename(str(p)), e))
    return io_atomic.load_newest_valid(files, on_error=_err)


def analyze_symbol_tf(symbol, interval, tf_name):
    candles = fetch_candles(symbol, interval)
    if not candles or len(candles) < 51:
        return [], None
    result = analyze_trend_lines(candles, min_touches=2)
    if not result:
        return [], None
    closed_price = candles[-2]["close"]  # last CLOSED candle (classification)
    live_price = candles[-1]["close"]    # live price (SL/TP check)
    atr = result.get("atr", 0)
    setups = []
    for key, direction in (("uptrend_line", "UPTREND"), ("downtrend_line", "DOWNTREND")):
        s = classify_setup(result.get(key), closed_price, atr, candles)  # T3D: rule-2 wiring
        if s:
            s["status"] = gate_status(s["status"])
            if s.get("signal") in ("BUY", "SELL"):  # D1: carry opposite pivot + ATR (sl_tp.py)
                s["pivot_price"] = sl_tp.last_opposite_pivot(s["signal"], closed_price, result)
                s["atr_at_signal"] = atr
            setups.append({"symbol": symbol, "tf": tf_name, "interval": interval,
                           "direction": direction, "current_price": closed_price, **s})
    return setups, live_price


def scan_all(symbols, timeframes, price_map=None):
    all_setups = []
    total = len(symbols) * len(timeframes)
    count = 0
    for symbol in symbols:
        for tf_name, interval in timeframes:
            count += 1
            print("  [%d/%d] %s %s..." % (count, total, symbol, tf_name), end="")
            setups, live = analyze_symbol_tf(symbol, interval, tf_name)
            if live is not None and price_map is not None:
                price_map[(symbol, tf_name)] = live
            all_setups.extend(setups)
            print(" %d setups" % len(setups))
            time.sleep(0.1)
    all_setups.sort(key=lambda x: (x["priority"], -x["line"]["touches"]))
    return all_setups


if __name__ == "__main__":
    import symbols_pool
    symbols = symbols_pool.get_pool_symbols()
    vol_map = symbols_pool.snapshot_meta()  # PH33: volumes for gate stamping
    timeframes = [("15M", "15m"), ("30M", "30m"), ("1H", "1h"), ("4H", "4h"), ("1D", "1d")]

    print("TREND HUNTER v5 - %d symbols (dynamic pool) x %d TFs (+SL/TP lifecycle)" % (len(symbols), len(timeframes)))
    price_map = {}
    setups = scan_all(symbols, timeframes, price_map)

    now_iso = datetime.now().isoformat()
    prev_path, prev = load_previous()
    carried_live, resolved = [], []
    if prev:
        for s in prev.get("setups", []):
            if s.get("status") == "TRIGGERED":
                k = key_of(s)
                if k not in price_map and s.get("symbol"):
                    candles = fetch_candles(s["symbol"], s.get("interval") or "1h")
                    if candles:
                        price_map[k] = candles[-1]["close"]
        carried_live, resolved = process_previous(prev.get("setups", []), price_map, now_iso)
        print("\nLIFECYCLE: prev=%s | live=%d | resolved=%d" % (
            os.path.basename(prev_path), len(carried_live), len(resolved)))
        for s in carried_live[:10]:
            print("  LIVE     %-10s %-4s %s" % (s["symbol"], s["tf"], s.get("signal", "")))
        for s in resolved[:15]:
            print("  %-9s %-10s %-4s %s resolved_at=%s" % (
                s.get("status"), s["symbol"], s["tf"], s.get("signal", ""), s.get("resolved_at")))

    final = merge_tracked(setups, carried_live, resolved)
    # PH33: volume gate -- stamp + downgrade low-vol (non-resolved statuses -> WATCHLIST)
    from symbols_pool import load_config
    floor = load_config()["min_volume_24h"]
    apply_volume_gate(final, vol_map, floor)
    by_status = status_counts(final)

    print("\nRESULTS: %d setups" % len(final))
    lowvol = sorted({s["symbol"] for s in final if s.get("volume_ok") is False})  # PH33
    if lowvol:
        print("VOLUME GATE (PH33): low-vol setups downgraded -> WATCHLIST: %s" % ", ".join(lowvol))
    novol = sorted({s["symbol"] for s in final if s.get("volume_ok") is None})  # PH33B
    if novol:
        print("VOLUME GATE (PH33B): NO_VOLUME_DATA (fail-closed) -> WATCHLIST: %s" % ", ".join(novol))
    for status in HUNTER_STATUSES:
        items = [s for s in final if s.get("status") == status]
        if not items:
            continue
        print("\n%s (%d):" % (status, len(items)))
        for s in items[:15]:
            ln = s.get("line") or {}
            extra = ""
            if status == "TRIGGERED":
                extra = " entry=%.2f sl=%.2f tp=%.2f" % (
                    float(s.get("entry") or 0), float(s.get("sl") or 0), float(s.get("tp") or 0))
            print("  %-10s %-4s %-9s touches=%s score=%s dist=%+.2f%% %s%s" % (
                s["symbol"], s["tf"], s["direction"], ln.get("touches", "-"),
                ln.get("score", 0), ln.get("dist_pct", 0), s.get("signal", ""), extra))

    output = {
        "generated": now_iso,
        "total": len(final),
        "by_status": by_status,
        "lifecycle": {
            "prev_file": os.path.basename(prev_path) if prev_path else None,
            "live_carried": len(carried_live),
            "resolved_carried": len(resolved),
        },
        "setups": final,
    }
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(results_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(results_dir, "hunter_%s.json" % ts)
    io_atomic.atomic_write_json(out_file, output)  # D18 atomic write + lock
    print("\nSaved: hunter_%s.json" % ts)
