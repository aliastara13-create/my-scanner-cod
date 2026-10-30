import urllib.request, json
from trend_lines import analyze_trend_lines

symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
tfs = [("15M", "15m"), ("1H", "1h"), ("4H", "4h")]

for sym in symbols:
    for tf_name, interval in tfs:
        url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit=300"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            klines = json.loads(r.read().decode())
        
        candles = [{"time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in klines]
        
        result = analyze_trend_lines(candles)
        if not result:
            continue
        
        for line_type in ["uptrend_line", "downtrend_line"]:
            line = result.get(line_type)
            if line:
                b = line.get("breakout", {})
                print(f"  {sym:10} {tf_name:4} {line_type:15} "
                      f"touches={line['touches']} "
                      f"broken={b.get('broken')} "
                      f"recent={b.get('recent')} "
                      f"type={b.get('type')}")
