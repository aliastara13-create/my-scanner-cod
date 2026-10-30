# -*- coding: utf-8 -*-
# scanner_v2.py — Binance Top 20 USDT (NO stablecoins) + Regime filter (ADX)
# STANDALONE
import os, json, time, urllib.request
from datetime import datetime
import io_atomic  # D18

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results")

ENDPOINTS = [
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://data-api.binance.vision",
    "https://api1.binance.com",
    "https://api2.binance.com",
]

# Stablecoins / pegged assets to exclude
STABLES = {
    # Major stablecoins
    "USDCUSDT", "USD1USDT", "RLUSDUSDT", "FDUSDUSDT", "TUSDUSDT",
    "BUSDUSDT", "DAIUSDT", "USDPUSDT", "USDDUSDT", "PYUSDUSDT",
    # Fiat
    "EURUSDT", "GBPUSDT", "AEURUSDT", "EURIUSDT", "TRYUSDT",
    # Newer / less common stables
    "UUSDT", "BFUSDUSDT", "USD4USDT", "XUSDUSDT", "USDXUSDT",
    "USDEUSDT", "SUSDUSDT", "USDFUSDT", "USDYUSDT", "USRUSDT",
    "USD0USDT", "USDJUSDT", "USDLUSDT", "USDMUSDT", "USDOUSDT",
    "USDQUSDT", "USDRUSDT", "USDSUSDT", "USDTBUSDT", "USDVUSDT",
    "USNUSDT", "USTCUSDT", "USTUSDT", "VAIUSDT", "FRAXUSDT",
    "MIMUSDT", "LUSDUSDT", "GUSDUSDT", "SUSDUSDT", "CUSDUSDT",
    "DOLAUSDT", "ALUSDUSDT", "USKUSDT", "ZUSDUSDT", "XDAIUSDT",
}

def get_json(path, timeout=10):
    for ep in ENDPOINTS:
        try:
            url = ep + path
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
    return None

def ema(series, period):
    k = 2 / (period + 1)
    out = []
    for i, v in enumerate(series):
        if i == 0:
            out.append(v)
        else:
            out.append(v * k + out[-1] * (1 - k))
    return out

def atr_series(highs, lows, closes, period=14):
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    # Wilder smoothing
    out = []
    if len(trs) < period:
        return out
    first_atr = sum(trs[:period]) / period
    out.append(first_atr)
    for i in range(period, len(trs)):
        out.append((out[-1] * (period - 1) + trs[i]) / period)
    return out

def adx_series(highs, lows, closes, period=14):
    n = len(closes)
    if n < period * 2:
        return []
    plus_dm = []
    minus_dm = []
    for i in range(1, n):
        up = highs[i] - highs[i-1]
        dn = lows[i-1] - lows[i]
        plus_dm.append(up if (up > dn and up > 0) else 0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0)
    trs = []
    for i in range(1, n):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
    # Wilder smoothing
    def wilder(arr):
        out = []
        if len(arr) < period: return out
        s = sum(arr[:period])
        out.append(s)
        for i in range(period, len(arr)):
            s = s - (s / period) + arr[i]
            out.append(s)
        return out
    atr_w = wilder(trs)
    pdm_w = wilder(plus_dm)
    mdm_w = wilder(minus_dm)
    if not atr_w:
        return []
    pdi = [100 * p / a if a > 0 else 0 for p, a in zip(pdm_w, atr_w)]
    mdi = [100 * m / a if a > 0 else 0 for m, a in zip(mdm_w, atr_w)]
    dx = [100 * abs(p - m) / (p + m) if (p + m) > 0 else 0 for p, m in zip(pdi, mdi)]
    # ADX = Wilder smoothing of DX
    adx_out = []
    if len(dx) < period: return []
    first = sum(dx[:period]) / period
    adx_out.append(first)
    for i in range(period, len(dx)):
        adx_out.append((adx_out[-1] * (period - 1) + dx[i]) / period)
    return adx_out

def get_klines(symbol, interval="4h", limit=100):
    """دریافت کندل‌های بسته 4H"""
    data = get_json(f"/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}")
    if not data:
        return None
    return data

def analyze_regime(symbol):
    """تشخیص رژیم با ADX روی 4H"""
    klines = get_klines(symbol, "4h", 100)
    if not klines or len(klines) < 50:
        return None
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    adx_vals = adx_series(highs, lows, closes)
    if not adx_vals:
        return None
    adx_now = adx_vals[-1]
    if adx_now > 25:
        regime = "STRONG"
    elif adx_now > 20:
        regime = "TRENDING"
    elif adx_now > 15:
        regime = "NEUTRAL"
    else:
        regime = "RANGING"
    return {
        "adx": round(adx_now, 2),
        "regime": regime,
    }

def scan_top_volume(limit=20, min_volume_usdt=1_000_000):
    print("[*] Fetching all tickers...")
    data = get_json("/api/v3/ticker/24hr")
    if not data:
        print("[X] No data")
        return None
    usdt = [d for d in data if d["symbol"].endswith("USDT")]
    print(f"    Total USDT pairs: {len(usdt)}")
    
    # Filter stablecoins
    usdt = [d for d in usdt if d["symbol"] not in STABLES]
    print(f"    After stablecoin filter: {len(usdt)}")
    
    # Filter volume
    usdt = [d for d in usdt if float(d["quoteVolume"]) >= min_volume_usdt]
    print(f"    After volume filter (>${min_volume_usdt/1e6:.0f}M): {len(usdt)}")
    
    usdt.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
    top = usdt[:limit]
    
    result = []
    for i, d in enumerate(top, 1):
        result.append({
            "rank": i,
            "symbol": d["symbol"],
            "base": d["symbol"].replace("USDT", ""),
            "price": float(d["lastPrice"]),
            "change_pct": float(d["priceChangePercent"]),
            "quote_volume_24h": float(d["quoteVolume"]),
            "high_24h": float(d["highPrice"]),
            "low_24h": float(d["lowPrice"]),
            "trades": int(d["count"]),
        })
    return result

def save_result(top, label="scan"):
    os.makedirs(OUT, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fp = os.path.join(OUT, f"{label}_{ts}.json")
    io_atomic.atomic_write_json(fp, {"generated": ts, "count": len(top), "top": top})  # D18 atomic write + lock
    return fp

if __name__ == "__main__":
    print("=" * 100)
    print("  ASTRA SCANNER v2 - Top 20 USDT (no stables) + Regime (ADX 4H)")
    print("=" * 100)
    t0 = time.time()
    
    # ۱. اسکن
    top = scan_top_volume(limit=20)
    if not top:
        print("[X] Scan failed")
        exit(1)
    
    # ۲. رژیم
    print()
    print("[*] Analyzing regime (ADX on 4H)...")
    for d in top:
        r = analyze_regime(d["symbol"])
        if r:
            d["regime"] = r["regime"]
            d["adx"] = r["adx"]
        else:
            d["regime"] = "?"
            d["adx"] = 0
        time.sleep(0.05)  # rate limit
    
    fp = save_result(top)
    
    # ۳. نمایش
    print()
    print(f"{'#':<4}{'symbol':<12}{'price':>12}{'chg%':>8}{'vol($M)':>10}{'ADX':>7}{'regime':>10}")
    print("-" * 100)
    for d in top:
        print(f"{d['rank']:<4}{d['symbol']:<12}{d['price']:>12.4f}{d['change_pct']:>+8.2f}{d['quote_volume_24h']/1e6:>10,.1f}{d['adx']:>7.1f}{d['regime']:>10}")
    print()
    print(f"[OK] Saved: {fp}")
    print(f"[T] Time: {time.time()-t0:.1f}s")


