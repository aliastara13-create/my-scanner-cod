import urllib.request, json
from trend_lines import (
    calculate_atr_wilder, find_pivots, classify_pivots,
    find_best_line, line_valid_pivots
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

print("=== Downtrend ===")
best_down = find_best_line(lh_pivots, atr, current_price, min_touches=2)
if best_down:
    print(f"  slope: {best_down['slope']}")
    print(f"  touches: {best_down['touches']}")
    print(f"  score: {best_down['score']}")
    print(f"  start_idx: {best_down['start_idx']}")
    print(f"  end_idx: {best_down['end_idx']}")
    
    # از end_idx (لنگر دوم)
    is_valid = line_valid_pivots(pivot_highs, best_down["slope"], best_down["intercept"],
                                  best_down["end_idx"], last_idx, "res", atr * 0.5)
    print(f"  line_valid_pivots (from end_idx): {is_valid}")
    
    # نمایش violations
    print()
    print(f"  {'idx':>4} {'pivot_high':>12} {'line':>12} {'diff':>10} {'violate?':>10}")
    violations = 0
    for p in pivot_highs:
        if p["idx"] < best_down["end_idx"] or p["idx"] > last_idx:
            continue
        y = best_down["slope"] * p["idx"] + best_down["intercept"]
        diff = p["price"] - y
        violate = diff > atr * 0.5
        if violate:
            violations += 1
        print(f"  {p['idx']:>4} {p['price']:>12.2f} {y:>12.2f} {diff:>10.2f} {'❌' if violate else '✅':>10}")
    print(f"  Total violations: {violations}")
else:
    print("  ❌ No line found")

print()
print("=== Uptrend ===")
best_up = find_best_line(hl_pivots, atr, current_price, min_touches=2)
if best_up:
    print(f"  slope: {best_up['slope']}")
    print(f"  touches: {best_up['touches']}")
    print(f"  score: {best_up['score']}")
    print(f"  end_idx: {best_up['end_idx']}")
    
    is_valid = line_valid_pivots(pivot_lows, best_up["slope"], best_up["intercept"],
                                  best_up["end_idx"], last_idx, "sup", atr * 0.5)
    print(f"  line_valid_pivots: {is_valid}")
