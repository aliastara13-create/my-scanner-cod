# -*- coding: utf-8 -*-
# scanner_mtf.py — Multi-Timeframe Scanner (5 TF)
# هدف: کشف همه فرصت‌های شکار در همه TFها
# TF: 15M, 30M, 1H, 4H, 1D
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import io_atomic  # D18
import sl_tp  # D1C:
import scanner_v4 as sv4
from agent_decision import AgentDecision

_agent = AgentDecision()

TIMEFRAMES = [
    {
        "name": "15M",
        "interval": "15m",
        "entry_tf": "1m",
        "limit": 200,
        "max_bars": 60,
        "pivot_n": 3,
        "max_age_bars": 96,
        "position_size": 0.25,
        "priority": 1,
    },
    {
        "name": "30M",
        "interval": "30m",
        "entry_tf": "1m",
        "limit": 200,
        "max_bars": 90,
        "pivot_n": 3,
        "max_age_bars": 96,
        "position_size": 0.5,
        "priority": 2,
    },
    {
        "name": "1H",
        "interval": "1h",
        "entry_tf": "5m",
        "limit": 200,
        "max_bars": 200,
        "pivot_n": 3,
        "max_age_bars": 168,
        "position_size": 1.0,
        "priority": 3,
    },
    {
        "name": "4H",
        "interval": "4h",
        "entry_tf": "15m",
        "limit": 200,
        "max_bars": 400,
        "pivot_n": 3,
        "max_age_bars": 168,
        "position_size": 1.5,
        "priority": 4,
    },
    {
        "name": "1D",
        "interval": "1d",
        "entry_tf": "1h",
        "limit": 200,
        "max_bars": 500,
        "pivot_n": 3,
        "max_age_bars": 168,
        "position_size": 2.0,
        "priority": 5,
    },
]


def analyze_symbol_tf(symbol, scan_data, tf_config):
    """تحلیل یک نماد در یک TF"""
    try:
        # ۱. دریافت کندل‌ها
        struct_klines = sv4.get_json_fast(
            f"/api/v3/klines?symbol={symbol}&interval={tf_config['interval']}&limit={tf_config['limit']}"
        )
        entry_klines = sv4.get_json_fast(
            f"/api/v3/klines?symbol={symbol}&interval={tf_config['entry_tf']}&limit={tf_config['limit']}"
        )
        
        if not struct_klines or not entry_klines:
            return None
        
        # ۲. تبدیل
        a_struct = sv4.klines_to_arrays(struct_klines)
        a_entry = sv4.klines_to_arrays(entry_klines)
        
        if not a_struct or not a_entry:
            return None
        
        price = a_entry["c"][-1]
        
        # ۳. ADX + Regime
        adx_vals = sv4.adx_arr(a_struct["h"], a_struct["l"], a_struct["c"])
        adx = adx_vals[-1] if adx_vals else 0
        regime = "STRONG" if adx>25 else "TRENDING" if adx>20 else "NEUTRAL" if adx>15 else "RANGING"
        
        # ۴. ATR
        atr_struct = sv4.atr_arr(a_struct["h"], a_struct["l"], a_struct["c"])
        
        # ۵. لگ + سیگنال
        signals = []
        for side in ("BUY", "SELL"):
            leg = sv4.detect_leg(a_struct["h"], a_struct["l"], a_struct["t"], atr_struct, side)
            if leg is None:
                continue
            
            z1, z2 = sv4.gp_zone(leg["hi"], leg["lo"], side)
            zs = sv4.zone_status(price, z1, z2, side)
            
            # D1C: SL/TP via sl_tp.py — identical to backtest_mtf (zone-edge pivot anchor, price-based R)
            if side == "BUY":
                sl = sl_tp.calc_sl("BUY", z1, leg["atr"])
            else:
                sl = sl_tp.calc_sl("SELL", z2, leg["atr"])
            risk = (price - sl) if side == "BUY" else (sl - price)
            tps = sl_tp.calc_tp(price, sl, side)
            # Fee gate: stop distance <= round-trip fee -> economically unviable
            if risk <= 0 or not tps or (risk / price) <= sl_tp.fee("round_trip"):
                continue
            tp = tps[0]
            tp2 = tps[1] if len(tps) > 1 else None
            rr = abs(tp - price) / abs(risk)
            
            if zs == "WAITING":
                dist_pct = (price - z2) / price * 100 if side == "BUY" else (z1 - price) / price * 100
            elif zs == "NEAR":
                dist_pct = (price - z2) / price * 100 if side == "BUY" else (z1 - price) / price * 100
            else:
                dist_pct = 0.0
            
            signals.append({
                "side": side,
                "entry_zone_lo": round(z1, 8),
                "entry_zone_hi": round(z2, 8),
                "sl": round(sl, 8),
                "tp": round(tp, 8),
                "tp2": (round(tp2, 8) if tp2 is not None else None),  # D1C: second target (tp_targets[1])
                "rr": round(rr, 2),
                "leg_hi": round(leg["hi"], 8),
                "leg_lo": round(leg["lo"], 8),
                "zone_status": zs,
                "dist_pct": round(dist_pct, 3),
                "in_zone": bool(zs == "IN_ZONE"),
            })
        
        if not signals:
            return None
        
        # ─── محاسبه Score ───
        score = 0
        score += min(25, adx * 25 / 50)
        score += {"STRONG": 15, "TRENDING": 10, "NEUTRAL": 3, "RANGING": 0}.get(regime, 0)
        
        in_zone = any(s.get("zone_status") == "IN_ZONE" for s in signals)
        near = any(s.get("zone_status") == "NEAR" for s in signals)
        if in_zone: score += 30
        elif near: score += 20
        elif signals: score += 10
        
        volume_24h = scan_data["quote_volume_24h"]
        if volume_24h > 500e6: score += 15
        elif volume_24h > 200e6: score += 12
        elif volume_24h > 100e6: score += 8
        elif volume_24h > 50e6: score += 5
        
        score = min(100, max(0, round(score, 1)))
        
        # ─── محاسبه Stars ───
        best_rr = 0
        for s in signals:
            if s.get("zone_status") in ("IN_ZONE", "NEAR"):
                if s.get("rr", 0) > best_rr:
                    best_rr = s["rr"]
        
        if in_zone and score >= 70 and best_rr >= 1.5:
            stars = 5
            stars_label = "عالی برای شکار"
        elif in_zone and score >= 50:
            stars = 4
            stars_label = "آماده برای شکار"
        elif near and score >= 40:
            stars = 3
            stars_label = "در لیست انتظار"
        elif score >= 30:
            stars = 2
            stars_label = "رصد"
        else:
            stars = 1
            stars_label = "فقط تماشا"
        
        # PH33: result container (volume gate applied below)
        result = {
            "symbol": symbol,
            "tf": tf_config["name"],
            "interval": tf_config["interval"],
            "entry_tf": tf_config["entry_tf"],
            "price": float(price),  # RF1: keep raw precision (sub-1e-8 symbols e.g. PEPE; no destructive zero)
            "adx": round(adx, 2),
            "regime": regime,
            "signals": signals,
            "score": score,
            "stars": stars,
            "stars_label": stars_label,
            "risk_pct": _agent._calc_position(score),
            "position_size": tf_config["position_size"],
            "priority": tf_config["priority"],
            "adx_scan": scan_data["adx"],
            "regime_scan": scan_data["regime"],
            "volume_24h": scan_data["quote_volume_24h"],
            "change_pct": scan_data["change_pct"],
            "rank": scan_data["rank"],
            "base": scan_data["base"],
        }
        result["volume_ok"] = scan_data.get("volume_ok")  # PH33
        # PH33B: fail-closed -- only explicit True passes; False/None/missing -> watchlist tier
        if result["volume_ok"] is not True:
            result["stars"] = 1
            result["stars_label"] = ("فقط تماشا (حجم کم)" if result["volume_ok"] is False
                                     else "فقط تماشا (حجم نامشخص)")
            result["risk_pct"] = 0.0
        return result
    
    except Exception as e:
        print(f"  ⚠️ {symbol} {tf_config['name']}: {e}")
        return None


def qualify_symbols(pool, scan):
    """PH33: pool -> qualified symbols. No ADX filter (per Phase 33 spec).
    Volume fields are refreshed from pool tickers (fresher than the scan file)."""
    scan_by_symbol = {}
    for d in scan.get("top", []):
        scan_by_symbol[d["symbol"]] = d
    qualified = []
    for p in pool:
        d = scan_by_symbol.get(p["symbol"])
        if d is not None:
            d2 = dict(d)
            d2["quote_volume_24h"] = p.get("quote_volume_24h", d.get("quote_volume_24h"))
            d2["volume_ok"] = p.get("volume_ok")
            qualified.append(d2)
        else:
            qualified.append({
                "symbol": p["symbol"],
                "adx": None, "regime": None,
                "quote_volume_24h": p.get("quote_volume_24h", 0.0),
                "volume_ok": p.get("volume_ok"),
                "change_pct": p.get("change_pct", 0.0),
                "rank": None, "base": p["symbol"][:-4],
            })
    return qualified


if __name__ == "__main__":
    import glob
    import symbols_pool
    
    print("=" * 100)
    print("  ASTRA MTF SCANNER — 5 Timeframes (15M, 30M, 1H, 4H, 1D)")
    print("=" * 100)
    
    # آخرین scan
    scan_files = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "scan_*.json")))
    if not scan_files:
        print("[X] No scan file — run scanner_v2.py first")
        sys.exit(1)
    
    with open(scan_files[-1], encoding="utf-8") as f:
        scan = json.load(f)
    
    pool, live_fetch = symbols_pool.pool_with_meta()
    qualified = qualify_symbols(pool, scan)  # PH33: no ADX filter + volume enrichment
    print(f"[*] Pool: {len(pool)} (live_fetch={live_fetch}) | Qualified: {len(qualified)} (no ADX filter, PH33)")
    print()
    
    t0 = time.time()
    all_results = []
    
    for d in qualified:
        print(f"[*] {d['symbol']}...")
        for tf_config in TIMEFRAMES:
            r = analyze_symbol_tf(d["symbol"], d, tf_config)
            if r:
                all_results.append(r)
    
    # ذخیره
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", f"mtf_{ts}.json")
    io_atomic.atomic_write_json(out, {  # D18 atomic write + lock
        "generated": ts,
        "count": len(all_results),
        "results": all_results,
    })
    
    # نمایش
    print()
    print(f"{'TF':<6}{'symbol':<10}{'status':<10}{'side':<6}{'zone':<30}{'price':>12}{'R:R':>6}")
    print("-" * 110)
    
    for r in sorted(all_results, key=lambda x: (x["priority"], x["symbol"])):
        for s in r["signals"]:
            if s["zone_status"] in ("IN_ZONE", "NEAR"):
                zone = f"{s['entry_zone_lo']:.4f}-{s['entry_zone_hi']:.4f}"
                print(f"{r['tf']:<6}{r['symbol']:<10}{s['zone_status']:<10}{s['side']:<6}{zone:<30}{r['price']:>12.4f}{s['rr']:>6.2f}")
    
    # آمار
    print()
    print("=" * 100)
    in_zone = sum(1 for r in all_results for s in r["signals"] if s["zone_status"] == "IN_ZONE")
    near = sum(1 for r in all_results for s in r["signals"] if s["zone_status"] == "NEAR")
    print(f"  🎯 IN ZONE: {in_zone}")
    print(f"  ⚡ NEAR:    {near}")
    print(f"  📊 Total:   {len(all_results)} symbols × TF")
    print("=" * 100)
    
    print()
    print(f"[OK] Saved: {out}")
    print(f"[T] Time: {time.time()-t0:.1f}s")

