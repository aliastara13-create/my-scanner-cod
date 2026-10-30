# -*- coding: utf-8 -*-
# test_network.py — تست سرعت endpoint های Binance
import time, urllib.request, json

ENDPOINTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api-gcp.binance.com",
    "https://api2.binance.com",
]

print("=" * 70)
print("  NETWORK SPEED TEST — Binance Endpoints")
print("=" * 70)

for ep in ENDPOINTS:
    try:
        t0 = time.time()
        req = urllib.request.Request(ep + "/api/v3/time", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            elapsed = time.time() - t0
            status = "🟢" if elapsed < 1 else ("🟡" if elapsed < 3 else "🔴")
            print(f"  {status} {ep:<40} {elapsed:.2f}s")
    except Exception as e:
        print(f"  ❌ {ep:<40} ERROR: {str(e)[:40]}")

# تست CoinGecko
print()
print("=" * 70)
print("  CoinGecko")
print("=" * 70)
try:
    t0 = time.time()
    req = urllib.request.Request("https://api.coingecko.com/api/v3/ping", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        elapsed = time.time() - t0
        status = "🟢" if elapsed < 1 else ("🟡" if elapsed < 3 else "🔴")
        print(f"  {status} CoinGecko /ping{'':<22} {elapsed:.2f}s")
except Exception as e:
    print(f"  ❌ CoinGecko: {e}")

print()
print("=" * 70)
