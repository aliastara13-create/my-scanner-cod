# -*- coding: utf-8 -*-
# indicators.py — Ichimoku, POC, VWAP, EMA for multi-condition analysis
import os, json, urllib.request
from fast_fetch import get_json_fast
from datetime import datetime, timezone

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

def fetch_klines(symbol, interval, limit=300):
    data = get_json_fast(f"/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}")
    if not data:
        return None
    return [{
        "t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
        "l": float(k[3]), "c": float(k[4]), "v": float(k[5])
    } for k in data]

# ============ Ichimoku Cloud ============
def ichimoku(klines, tenkan=9, kijun=26, senkou=52):
    """محاسبه Ichimoku"""
    if len(klines) < senkou + 26:
        return None
    
    highs = [k["h"] for k in klines]
    lows = [k["l"] for k in klines]
    closes = [k["c"] for k in klines]
    
    # Tenkan-sen
    tenkan_val = (max(highs[-tenkan:]) + min(lows[-tenkan:])) / 2
    # Kijun-sen
    kijun_val = (max(highs[-kijun:]) + min(lows[-kijun:])) / 2
    # Senkou Span A
    span_a = (tenkan_val + kijun_val) / 2
    # Senkou Span B
    span_b = (max(highs[-senkou:]) + min(lows[-senkou:])) / 2
    
    cloud_top = max(span_a, span_b)
    cloud_bottom = min(span_a, span_b)
    price = closes[-1]
    
    # موقعیت قیمت
    if price > cloud_top:
        position = "ABOVE"  # بالای ابر
        signal = "BUY"
    elif price < cloud_bottom:
        position = "BELOW"  # زیر ابر
        signal = "SELL"
    else:
        position = "INSIDE"  # داخل ابر
        signal = "NEUTRAL"
    
    return {
        "tenkan": round(tenkan_val, 8),
        "kijun": round(kijun_val, 8),
        "cloud_top": round(cloud_top, 8),
        "cloud_bottom": round(cloud_bottom, 8),
        "position": position,
        "signal": signal,
        "price": round(price, 8),
    }

# ============ POC (Point of Control) ============
def calc_poc(klines, bins=50):
    """محاسبه POC از Volume Profile"""
    if not klines or len(klines) < 20:
        return None
    
    # بازه قیمت
    highs = [k["h"] for k in klines]
    lows = [k["l"] for k in klines]
    price_min = min(lows)
    price_max = max(highs)
    if price_max == price_min:
        return None
    
    # تعریف bins
    bin_size = (price_max - price_min) / bins
    volume_profile = [0.0] * bins
    
    # پر کردن bins
    for k in klines:
        # هر کندل در کدام bin است؟
        mid_price = (k["h"] + k["l"] + k["c"]) / 3
        bin_idx = min(int((mid_price - price_min) / bin_size), bins - 1)
        volume_profile[bin_idx] += k["v"]
    
    # POC = bin با بیشترین حجم
    poc_idx = volume_profile.index(max(volume_profile))
    poc_price = price_min + (poc_idx + 0.5) * bin_size
    
    # VAL و VAH (Value Area Low/High) — 70% حجم
    total_vol = sum(volume_profile)
    target_vol = total_vol * 0.70
    sorted_bins = sorted(range(bins), key=lambda i: -volume_profile[i])
    va_bins = []
    acc_vol = 0
    for i in sorted_bins:
        va_bins.append(i)
        acc_vol += volume_profile[i]
        if acc_vol >= target_vol:
            break
    vah_idx = max(va_bins)
    val_idx = min(va_bins)
    vah = price_min + (vah_idx + 0.5) * bin_size
    val = price_min + (val_idx + 0.5) * bin_size
    
    price = klines[-1]["c"]
    
    if price > poc_price:
        position = "ABOVE"
        signal = "BUY"
    elif price < poc_price:
        position = "BELOW"
        signal = "SELL"
    else:
        position = "AT"
        signal = "NEUTRAL"
    
    return {
        "poc": round(poc_price, 8),
        "vah": round(vah, 8),
        "val": round(val, 8),
        "position": position,
        "signal": signal,
        "price": round(price, 8),
        "dist_pct": round((price - poc_price) / poc_price * 100, 3),
    }

# ============ EMA ============
def calc_ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema

# ============ VWAP ============
SESSIONS = [
    {"name": "Tokyo",   "start": 0,  "end": 8},
    {"name": "London",  "start": 7,  "end": 16},
    {"name": "New York","start": 12, "end": 21},
]

def calc_vwap(klines, start_h, end_h):
    if not klines:
        return None
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    session_klines = []
    for k in klines:
        dt = datetime.fromtimestamp(k["t"]/1000, tz=timezone.utc)
        if dt < today_start:
            continue
        if not (start_h <= dt.hour < end_h):
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
    return pv / v

# ============ تحلیل کامل ============
def analyze_symbol_multi(symbol):
    """
    تحلیل کامل با ۵ شرط:
    ۱. Ichimoku (4H)
    ۲. POC (4H)
    ۳. VWAP (1m per session)
    ۴. EMA50 (4H)
    ۵. Fibo (باید از scanner_v4 بیاید)
    """
    result = {
        "symbol": symbol,
        "price": None,
        "ichimoku": None,
        "poc": None,
        "vwap": None,
        "ema50": None,
    }
    
    # 4H data
    k4h = fetch_klines(symbol, "4h", 300)
    if not k4h:
        return None
    result["price"] = k4h[-1]["c"]
    
    # ۱. Ichimoku
    result["ichimoku"] = ichimoku(k4h)
    
    # ۲. POC
    result["poc"] = calc_poc(k4h, bins=50)
    
    # ۳. EMA50
    closes_4h = [k["c"] for k in k4h]
    ema50_val = calc_ema(closes_4h, 50)
    if ema50_val:
        price = k4h[-1]["c"]
        position = "ABOVE" if price > ema50_val else "BELOW" if price < ema50_val else "AT"
        signal = "BUY" if position == "ABOVE" else "SELL" if position == "BELOW" else "NEUTRAL"
        result["ema50"] = {
            "value": round(ema50_val, 8),
            "position": position,
            "signal": signal,
            "dist_pct": round((price - ema50_val) / ema50_val * 100, 3),
        }
    
    # ۴. VWAP (1m)
    k1m = fetch_klines(symbol, "1m", 500)
    if k1m:
        vwap_result = {}
        for s in SESSIONS:
            v = calc_vwap(k1m, s["start"], s["end"])
            if v:
                price = k1m[-1]["c"]
                position = "ABOVE" if price > v else "BELOW" if price < v else "AT"
                signal = "BUY" if position == "ABOVE" else "SELL" if position == "BELOW" else "NEUTRAL"
                vwap_result[s["name"]] = {
                    "vwap": round(v, 8),
                    "position": position,
                    "signal": signal,
                    "dist_pct": round((price - v) / v * 100, 3),
                }
        result["vwap"] = vwap_result
    
    # ۵. همسویی کل
    signals = []
    if result["ichimoku"]:
        signals.append(result["ichimoku"]["signal"])
    if result["poc"]:
        signals.append(result["poc"]["signal"])
    if result["ema50"]:
        signals.append(result["ema50"]["signal"])
    if result["vwap"]:
        for v in result["vwap"].values():
            signals.append(v["signal"])
    
    signals = [s for s in signals if s != "NEUTRAL"]
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
            result["strength"] = 0
    else:
        result["alignment"] = "NONE"
        result["signal"] = "NEUTRAL"
        result["strength"] = 0
    
    return result

if __name__ == "__main__":
    print("=" * 100)
    print("  ASTRA MULTI-CONDITION ANALYSIS")
    print("  Ichimoku + POC + VWAP + EMA50")
    print("=" * 100)
    
    for sym in ["SOLUSDT", "DOGEUSDT", "UNIUSDT", "BTCUSDT"]:
        r = analyze_symbol_multi(sym)
        if not r:
            print(f"\n{sym}: خطا")
            continue
        
        print(f"\n📊 {r['symbol']} | قیمت: {r['price']}")
        print(f"{'─' * 100}")
        
        # Ichimoku
        if r["ichimoku"]:
            ic = r["ichimoku"]
            icon = "🟢" if ic["signal"] == "BUY" else "🔴" if ic["signal"] == "SELL" else "⚪"
            print(f"  {icon} Ichimoku: {ic['position']} (ابر: {ic['cloud_bottom']:.4f} - {ic['cloud_top']:.4f})")
        
        # POC
        if r["poc"]:
            pc = r["poc"]
            icon = "🟢" if pc["signal"] == "BUY" else "🔴" if pc["signal"] == "SELL" else "⚪"
            print(f"  {icon} POC: {pc['position']} ({pc['poc']:.4f}, dist: {pc['dist_pct']:+.3f}%)")
            print(f"     VAL: {pc['val']:.4f} | VAH: {pc['vah']:.4f}")
        
        # EMA50
        if r["ema50"]:
            e = r["ema50"]
            icon = "🟢" if e["signal"] == "BUY" else "🔴" if e["signal"] == "SELL" else "⚪"
            print(f"  {icon} EMA50 4H: {e['position']} ({e['value']:.4f}, dist: {e['dist_pct']:+.3f}%)")
        
        # VWAP
        if r["vwap"]:
            print(f"  📊 VWAP:")
            for name, v in r["vwap"].items():
                icon = "🟢" if v["signal"] == "BUY" else "🔴" if v["signal"] == "SELL" else "⚪"
                print(f"     {icon} {name}: {v['position']} ({v['dist_pct']:+.3f}%)")
        
        # نتیجه
        sig = r.get("signal", "NEUTRAL")
        align = r.get("alignment", "NONE")
        strength = r.get("strength", 0)
        if sig != "NEUTRAL":
            icon = "🟢" if sig == "BUY" else "🔴"
            print(f"\n  {icon} نتیجه: {align} | سیگنال: {sig} | قدرت: {strength}")
        else:
            print(f"\n  ⚠️ نتیجه: {align} (ناهماهنگ)")
    
    print("\n" + "=" * 100)


