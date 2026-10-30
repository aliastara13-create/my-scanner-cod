# -*- coding: utf-8 -*-
# test_speed_detailed.py — تست سرعت دقیق
import time, urllib.request, json

def test_endpoint(url, label, n=5):
    times = []
    for i in range(n):
        try:
            t0 = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
            elapsed = time.time() - t0
            times.append(elapsed)
            time.sleep(0.5)
        except Exception as e:
            times.append(None)
    
    valid = [t for t in times if t is not None]
    if valid:
        avg = sum(valid) / len(valid)
        mn = min(valid)
        mx = max(valid)
        print(f"  {label:<50} avg={avg:.2f}s min={mn:.2f}s max={mx:.2f}s")
    else:
        print(f"  {label:<50} ❌ all failed")

print("=" * 80)
print("  DETAILED SPEED TEST (5 runs each)")
print("=" * 80)

# تست ۱: endpoint ها
for ep in ["https://api.binance.com", "https://api-gcp.binance.com", "https://data-api.binance.vision"]:
    test_endpoint(f"{ep}/api/v3/time", ep)

print()
# تست ۲: DNS
print("DNS Test:")
import socket
for host in ["api.binance.com", "api-gcp.binance.com"]:
    t0 = time.time()
    try:
        ip = socket.gethostbyname(host)
        elapsed = time.time() - t0
        print(f"  {host:<40} → {ip:<15} {elapsed:.2f}s")
    except Exception as e:
        print(f"  {host:<40} ❌ {e}")

print()
print("=" * 80)
