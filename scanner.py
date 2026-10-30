# -*- coding: utf-8 -*-
# scanner.py — Binance Top 20 USDT pairs by 24h volume
# STANDALONE — does NOT touch any original file
import os, json, time, urllib.request, urllib.error
from datetime import datetime
import io_atomic  # D18R:

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results")

ENDPOINTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api-gcp.binance.com",
    "https://api2.binance.com",
]

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

def scan_top_volume(limit=20, min_volume_usdt=1_000_000):
    print("[*] Fetching all tickers...")
    data = get_json("/api/v3/ticker/24hr")
    if not data:
        print("[X] No data from any endpoint")
        return None
    usdt = [d for d in data if d["symbol"].endswith("USDT")]
    print(f"    Total USDT pairs: {len(usdt)}")
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
            "volume_24h": float(d["volume"]),
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
    io_atomic.atomic_write_json(fp, {"generated": ts, "count": len(top), "top": top})  # D18R:
    return fp

if __name__ == "__main__":
    print("=" * 80)
    print("  ASTRA SCANNER - Top 20 USDT pairs by 24h volume")
    print("  STANDALONE - no original file touched")
    print("=" * 80)
    t0 = time.time()
    top = scan_top_volume(limit=20)
    if top:
        fp = save_result(top)
        print()
        print(f"{'#':<4}{'symbol':<12}{'price':>14}{'change%':>10}{'vol24h($M)':>14}")
        print("-" * 80)
        for d in top:
            print(f"{d['rank']:<4}{d['symbol']:<12}{d['price']:>14.4f}{d['change_pct']:>+10.2f}{d['quote_volume_24h']/1e6:>14,.1f}")
        print()
        print(f"[OK] Saved: {fp}")
        print(f"[T] Time: {time.time()-t0:.1f}s")
    else:
        print("[X] Scan failed")
