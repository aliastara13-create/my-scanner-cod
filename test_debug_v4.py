import urllib.request, json
from trend_lines import (
    calculate_atr_wilder, find_pivots, classify_pivots, find_best_line
)

url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=300"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=15) as r:
    klines = json.loads(r.read().decode())

candles = [{"time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in klines]
candles = candles[:-1]

atr = calculate_atr_wilder(candles)
pivot_lows = find_pivots(candles, "low", 7)
typed_lows = classify_pivots(pivot_lows, "low")
hl_pivots = [p for p in typed_lows if p["type"] == "HL"]

current_price = candles[-1]["close"]
last_idx = len(candles) - 1
tol = atr * 0.5

best_up = find_best_line(hl_pivots, atr, current_price, min_touches=2)

if best_up:
    print("=== Uptrend HL pivots check ===")
    print(f"slope={best_up['slope']:.4f}, i0(end_idx)={best_up['end_idx']}, i1={last_idx}, tol={tol:.2f}")
    print()
    print(f"{'idx':>4} {'pivot_low':>12} {'line':>12} {'diff':>10} {'violate?':>10}")
    violations = 0
    for p in pivot_lows:
        if p["idx"] < best_up["end_idx"] or p["idx"] > last_idx:
            continue
        y = best_up["slope"] * p["idx"] + best_up["intercept"]
        diff = p["price"] - y
        violate = diff < -tol
        if violate:
            violations += 1
        print(f"{p['idx']:>4} {p['price']:>12.2f} {y:>12.2f} {diff:>10.2f} {'❌' if violate else '✅':>10}")
    print(f"\nTotal violations: {violations}")
