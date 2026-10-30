import time
import urllib.request, json
from trend_lines import analyze_trend_lines

start = time.time()
url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=4h&limit=300"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=15) as r:
    data = json.loads(r.read().decode())
print(f"Fetch: {time.time()-start:.2f}s")

candles = [{"time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in data]
print(f"Candles: {len(candles)}")

start = time.time()
result = analyze_trend_lines(candles)
elapsed = time.time() - start
print(f"analyze_trend_lines: {elapsed:.2f}s")

if result:
    up = result.get("uptrend_line")
    down = result.get("downtrend_line")
    print(f"Uptrend: {up['strength'] if up else 'None'}")
    print(f"Downtrend: {down['strength'] if down else 'None'}")
    print(f"Pivot highs: {result.get('pivot_highs_count', 0)}")
    print(f"Pivot lows: {result.get('pivot_lows_count', 0)}")
else:
    print("No result")
