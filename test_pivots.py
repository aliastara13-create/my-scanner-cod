import urllib.request, json
from trend_lines import find_pivots, fit_line, count_touches

# دریافت داده
url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=4h&limit=300"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=15) as r:
    klines = json.loads(r.read().decode())

candles = [{"time": int(k[0])//1000, "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in klines]

highs = [c["high"] for c in candles]
lows = [c["low"] for c in candles]

pivot_highs, pivot_lows = find_pivots(highs, lows, lookback=5)

print(f"Total candles: {len(candles)}")
print(f"Pivot highs: {len(pivot_highs)}")
print(f"Pivot lows:  {len(pivot_lows)}")
print()

print("=== Last 5 pivot highs ===")
for idx, price in pivot_highs[-5:]:
    print(f"  idx={idx:3}  price={price:.2f}")
print()

print("=== Last 5 pivot lows ===")
for idx, price in pivot_lows[-5:]:
    print(f"  idx={idx:3}  price={price:.2f}")
print()

# Test fit_line with last 6 pivot highs
recent_highs = pivot_highs[-6:]
line = fit_line(recent_highs)
if line:
    print("=== Line from last 6 pivot highs ===")
    print(f"  slope: {line['slope']:.6f}")
    print(f"  intercept: {line['intercept']:.2f}")
    print(f"  R2: {line['r_squared']:.4f}")
    print()
    
    print("=== Distance of each pivot from line ===")
    for idx, price in recent_highs:
        line_price = line["slope"] * idx + line["intercept"]
        dist_pct = abs(price - line_price) / line_price * 100
        print(f"  idx={idx:3}  price={price:.2f}  line={line_price:.2f}  dist={dist_pct:.3f}%")
