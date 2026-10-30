from trend_hunter import analyze_symbol_tf

symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
tfs = [("15M", "15m"), ("1H", "1h"), ("4H", "4h")]

total = 0
for sym in symbols:
    for tf_name, interval in tfs:
        setups = analyze_symbol_tf(sym, interval, tf_name)
        for s in setups:
            line = s["line"]
            score = line.get("score", 0)
            signal = s.get("signal", "-")
            print(f"  {s['symbol']:10} {s['tf']:4} {s['direction']:10} {s['status']:10} touches={line['touches']} score={score} signal={signal}")
            total += 1
print(f"\nTotal: {total} setups")
