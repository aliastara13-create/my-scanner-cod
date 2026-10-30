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
pivot_highs = find_pivots(candles, "high", 7)
pivot_lows = find_pivots(candles, "low", 7)
typed_highs = classify_pivots(pivot_highs, "high")
typed_lows = classify_pivots(pivot_lows, "low")
lh_pivots = [p for p in typed_highs if p["type"] == "LH"]
hl_pivots = [p for p in typed_lows if p["type"] == "HL"]

current_price = candles[-1]["close"]
last_idx = len(candles) - 1

# Downtrend
best_down = find_best_line(lh_pivots, atr, current_price, min_touches=2)
if best_down:
    slope = best_down["slope"]
    intercept = best_down["intercept"]
    i0 = best_down["start_idx"]
    i1 = last_idx
    tol = atr * 0.5
    
    print("=== Downtrend LH pivots check ===")
    print(f"slope={slope}, intercept={intercept:.2f}, i0={i0}, i1={i1}, tol={tol:.2f}")
    print()
    print(f"{'idx':>4} {'pivot_high':>12} {'line':>12} {'diff':>10} {'violate?':>10}")
    violations = 0
    for p in pivot_highs:
        if p["idx"] < i0 or p["idx"] > i1:
            continue
        y = slope * p["idx"] + intercept
        diff = p["price"] - y
        violate = diff > tol
        if violate:
            violations += 1
        print(f"{p['idx']:>4} {p['price']:>12.2f} {y:>12.2f} {diff:>10.2f} {'❌' if violate else '✅':>10}")
    print(f"\nTotal violations: {violations}")
    
    # چک کنیم pivot_highs vs lh_pivots
    print()
    print("=== LH pivots used in line ===")
    for p in lh_pivots:
        print(f"  idx={p['idx']:>4} price={p['price']:>10.2f}")
