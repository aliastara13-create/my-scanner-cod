# -*- coding: utf-8 -*-
# ema_multi_tf.py — EMA50 در چند تایم‌فریم
import os, json, urllib.request
from fast_fetch import get_json_fast

BASE = os.path.dirname(os.path.abspath(__file__))

ENDPOINTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
]

def get_json(path, timeout=15):
    for ep in ENDPOINTS:
        try:
            req = urllib.request.Request(ep + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception:
            continue
    return None

def ema(values, period):
    if len(values) < period:
        return []
    out = []
    k = 2 / (period + 1)
    for i, v in enumerate(values):
        out.append(v if i == 0 else v * k + out[-1] * (1 - k))
    return out

def fetch_closes(symbol, interval, limit=200):
    data = get_json_fast(f"/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}")
    if not data:
        return None
    return [float(k[4]) for k in data]

def analyze_ema_multi_tf(symbol):
    result = {"symbol": symbol, "price": None, "timeframes": {},
              "alignment": "NONE", "signal": "NEUTRAL", "strength": 0}
    
    for tf in ["5m", "15m", "1h", "4h"]:
        closes = fetch_closes(symbol, tf, 200)
        if not closes or len(closes) < 50:
            continue
        ema50 = ema(closes, 50)
        if not ema50:
            continue
        price = closes[-1]
        ema50_now = ema50[-1]
        ema50_prev = ema50[-2] if len(ema50) >= 2 else ema50_now
        position = "ABOVE" if price > ema50_now else "BELOW" if price < ema50_now else "AT"
        slope = "UP" if ema50_now > ema50_prev else "DOWN" if ema50_now < ema50_prev else "FLAT"
        dist_pct = (price - ema50_now) / ema50_now * 100
        
        result["price"] = price
        result["timeframes"][tf] = {
            "ema50": round(ema50_now, 8),
            "price": round(price, 8),
            "position": position,
            "slope": slope,
            "dist_pct": round(dist_pct, 3),
            "signal": "BUY" if position == "ABOVE" else "SELL" if position == "BELOW" else "NEUTRAL",
        }
    
    signals = [s["signal"] for s in result["timeframes"].values() if s["signal"] != "NEUTRAL"]
    if signals:
        if all(s == "BUY" for s in signals):
            result["alignment"] = "ALL_BUY"
            result["signal"] = "BUY"
            result["strength"] = len(signals)
        elif all(s == "SELL" for s in signals):
            result["alignment"] = "ALL_SELL"
            result["signal"] = "SELL"
            result["strength"] = len(signals)
        else:
            result["alignment"] = "MIXED"
            result["signal"] = "NEUTRAL"
    
    return result

if __name__ == "__main__":
    print("=" * 80)
    print("  ASTRA EMA50 MULTI-TF")
    print("=" * 80)
    for sym in ["SOLUSDT", "DOGEUSDT", "XRPUSDT", "BTCUSDT"]:
        r = analyze_ema_multi_tf(sym)
        if not r["timeframes"]:
            print(f"\n{sym}: خطا"); continue
        print(f"\n📊 {r['symbol']} | قیمت: {r['price']}")
        print(f"{'─' * 80}")
        print(f"{'TF':<6}{'EMA50':>16}{'Price':>16}{'Position':>10}{'Slope':>8}{'Dist%':>10}")
        for tf in ["5m", "15m", "1h", "4h"]:
            if tf in r["timeframes"]:
                s = r["timeframes"][tf]
                print(f"{tf:<6}{s['ema50']:>16.6f}{s['price']:>16.6f}{s['position']:>10}{s['slope']:>8}{s['dist_pct']:>+10.3f}")
        sig = r.get("signal", "NEUTRAL")
        align = r.get("alignment", "NONE")
        strength = r.get("strength", 0)
        if sig != "NEUTRAL":
            icon = "🟢" if sig == "BUY" else "🔴"
            print(f"\n  {icon} EMA50: {align} | سیگنال: {sig} | قدرت: {strength}/4")
        else:
            print(f"\n  ⚠️ EMA50: {align}")
    print("\n" + "=" * 80)

