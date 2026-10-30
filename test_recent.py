import urllib.request, json
from trend_lines import analyze_trend_lines

url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=300"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=15) as r:
    klines = json.loads(r.read().decode())

candles = [{"time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in klines]

result = analyze_trend_lines(candles)

up = result.get("uptrend_line")
down = result.get("downtrend_line")

if up:
    print("=== UPTREND ===")
    print(f"  touches: {up['touches']}")
    print(f"  breakout: {up.get('breakout')}")
    print()

if down:
    print("=== DOWNTREND ===")
    print(f"  touches: {down['touches']}")
    print(f"  breakout: {down.get('breakout')}")
