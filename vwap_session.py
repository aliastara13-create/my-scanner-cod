# -*- coding: utf-8 -*-
# vwap_session.py — VWAP per session with alignment detection
import os, json, urllib.request
from fast_fetch import get_json_fast
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))

ENDPOINTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
]

SESSIONS = [
    {"name": "Tokyo",     "start": 0,  "end": 8},
    {"name": "London",    "start": 7,  "end": 16},
    {"name": "New York",  "start": 12, "end": 21},
    {"name": "Close",     "start": 21, "end": 24},
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

def fetch_1m_klines(symbol, limit=500):
    data = get_json_fast(f"/api/v3/klines?symbol={symbol}&interval=1m&limit={limit}")
    if not data:
        return None
    return [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
             "l": float(k[3]), "c": float(k[4]), "v": float(k[5])} for k in data]

def calc_vwap_session(klines, session_start_h, session_end_h):
    if not klines:
        return None
    now = datetime.now(timezone.utc)
    today_start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    session_klines = []
    for k in klines:
        dt = datetime.fromtimestamp(k["t"]/1000, tz=timezone.utc)
        if dt < today_start_dt:
            continue
        if not (session_start_h <= dt.hour < session_end_h):
            continue
        session_klines.append(k)
    
    if not session_klines:
        return None
    
    pv = 0.0; v = 0.0
    for k in session_klines:
        tp = (k["h"] + k["l"] + k["c"]) / 3
        pv += tp * k["v"]
        v += k["v"]
    if v == 0:
        return None
    return {"vwap": pv/v, "candles": len(session_klines)}

def analyze_vwap_sessions(symbol):
    klines = fetch_1m_klines(symbol, 500)
    if not klines:
        return None
    price = klines[-1]["c"]
    
    result = {"symbol": symbol, "price": price, "sessions": {},
              "alignment": "NONE", "signal": "NEUTRAL", "strength": 0}
    
    for s in SESSIONS:
        v = calc_vwap_session(klines, s["start"], s["end"])
        if v:
            position = "ABOVE" if price > v["vwap"] else "BELOW" if price < v["vwap"] else "AT"
            dist_pct = (price - v["vwap"]) / v["vwap"] * 100
            signal = "BUY" if position == "ABOVE" else "SELL" if position == "BELOW" else "NEUTRAL"
            result["sessions"][s["name"]] = {
                "vwap": round(v["vwap"], 8),
                "position": position,
                "signal": signal,
                "dist_pct": round(dist_pct, 3),
                "candles": v["candles"],
            }
    
    signals = [s["signal"] for s in result["sessions"].values() if s["signal"] != "NEUTRAL"]
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
    
    return result

if __name__ == "__main__":
    print("=" * 80)
    print("  ASTRA VWAP SESSION")
    print("=" * 80)
    for sym in ["SOLUSDT", "DOGEUSDT", "XRPUSDT", "BTCUSDT"]:
        r = analyze_vwap_sessions(sym)
        if not r:
            print(f"\n{sym}: خطا"); continue
        print(f"\n📊 {r['symbol']} | قیمت: {r['price']}")
        print(f"{'─' * 80}")
        print(f"{'Session':<12}{'VWAP':>16}{'Position':>12}{'Signal':>10}{'Dist%':>10}")
        for name, s in r["sessions"].items():
            print(f"{name:<12}{s['vwap']:>16.6f}{s['position']:>12}{s['signal']:>10}{s['dist_pct']:>+10.3f}")
        sig = r.get("signal", "NEUTRAL")
        align = r.get("alignment", "NONE")
        if sig != "NEUTRAL":
            icon = "🟢" if sig == "BUY" else "🔴"
            print(f"\n  {icon} VWAP: {align} | سیگنال: {sig} | قدرت: {r.get('strength',0)}")
        else:
            print(f"\n  ⚠️ VWAP: {align}")
    print("\n" + "=" * 80)




