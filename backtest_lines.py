# -*- coding: utf-8 -*-
# backtest_lines.py - walk-forward backtest of TRIGGERED trend-line breakouts
# no look-ahead: at step t only candles[:t+1] are closed and visible
# entry = close[t]; SL = last opposite pivot +/- sl_atr_factor*ATR via sl_tp.py (D1); TP = tp_targets from risk_config.json; time-stop; fee from sl_tp (risk_config.json)
import os
import sys
import json
import time
import argparse
import urllib.request
from datetime import datetime
from trend_lines import analyze_trend_lines
import sl_tp  # D1
import io_atomic  # D18R:

TF_MAP = {"5M": "5m", "15M": "15m", "30M": "30m", "1H": "1h", "4H": "4h", "1D": "1d"}


def fetch(symbol, interval, total):
    out = []
    end = None
    while len(out) < total:
        url = "https://api.binance.com/api/v3/klines?symbol=%s&interval=%s&limit=1000" % (symbol, interval)
        if end:
            url += "&endTime=%d" % end
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode())
        except Exception as e:
            print("  fetch error %s %s: %s" % (symbol, interval, e))
            break
        if not data:
            break
        out = data + out
        end = data[0][0] - 1
        if len(data) < 1000:
            break
        time.sleep(0.15)
    seen = set()
    candles = []
    for k in out:
        if k[0] in seen:
            continue
        seen.add(k[0])
        candles.append({"time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
                        "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])})
    candles.sort(key=lambda c: c["time"])
    return candles[:-1] if candles else candles  # drop open candle


def simulate(candles, t, side, entry, sl, rr, horizon, fee):
    risk = abs(entry - sl)
    d = 1 if side == "BUY" else -1
    tp = entry + d * rr * risk
    last = min(len(candles) - 1, t + horizon)
    r = None
    for j in range(t + 1, last + 1):
        hi, lo = candles[j]["high"], candles[j]["low"]
        if side == "BUY":
            if lo <= sl:
                r = -1.0
                break
            if hi >= tp:
                r = float(rr)
                break
        else:
            if hi >= sl:
                r = -1.0
                break
            if lo <= tp:
                r = float(rr)
                break
    if r is None:
        r = d * (candles[last]["close"] - entry) / risk
    return r - fee * entry / risk


def run(symbol, tf, candles, window, step, horizon, fee, max_dist_atr=1.5):
    trades = []
    skipped = 0
    seen = set()
    busy_until = -1
    n = len(candles)
    for t in range(window, n - 1, step):
        if t <= busy_until:
            continue
        off = t + 1 - window
        w = candles[off:t + 2]  # last element is dropped inside (treated as open)
        res = analyze_trend_lines(w, min_touches=3)
        if not res:
            continue
        atr = res["atr"]
        price = candles[t]["close"]
        for key, ltype in (("downtrend_line", "DOWNTREND"), ("uptrend_line", "UPTREND")):
            ln = res.get(key)
            if not ln or not ln["breakout"]["broken"]:
                continue
            bo = ln["breakout"]
            if bo["bars_ago"] is None or bo["bars_ago"] > step - 1:
                continue
            line_now = ln["line_price"]
            d = (price - line_now) / line_now * 100
            side = "BUY" if ltype == "DOWNTREND" else "SELL"
            if (side == "BUY" and d <= 0) or (side == "SELL" and d >= 0):
                continue
            if abs(price - line_now) > max_dist_atr * atr or abs(d) >= 5.0:
                continue
            uid = (ltype, off + ln["start_idx"], off + bo["break_idx"])
            if uid in seen:
                continue
            seen.add(uid)
            # D1: SL via sl_tp.py — same formula as live hunter (identical on the same input)
            piv = sl_tp.last_opposite_pivot(side, price, res)
            sl = sl_tp.calc_sl(side, piv, atr) if piv is not None else sl_tp.fallback_sl(side, price, atr)
            risk = abs(price - sl)
            # Fee gate: stop distance <= round-trip fee -> economically unviable
            if risk < 0.3 * atr or risk > 4 * atr or (risk / price) <= sl_tp.fee("round_trip"):
                skipped += 1
                continue
            tr = {"symbol": symbol, "tf": tf, "side": side, "t": t, "time": candles[t]["time"],
                  "entry": price, "sl": sl, "touches": ln["touches"], "score": ln["score"]}
            for rr in sl_tp.tp_targets():  # D1: targets from risk_config.json
                tr["R%d" % rr] = round(simulate(candles, t, side, price, sl, rr, horizon, fee), 3)
            trades.append(tr)
            busy_until = t + horizon
            break
    return trades, skipped


def stats(trades, label):
    if not trades:
        return "%-18s n=0" % label
    parts = ["%-18s n=%-4d" % (label, len(trades))]
    for rr in sl_tp.tp_targets():  # D1: targets from risk_config.json
        rs = [x["R%d" % rr] for x in trades]
        wins = [r for r in rs if r > 0]
        loss = [-r for r in rs if r <= 0]
        pf = (sum(wins) / sum(loss)) if loss and sum(loss) > 0 else float("inf")
        parts.append("TP%dR: win=%5.1f%% avgR=%+.2f sumR=%+.1f PF=%.2f" % (
            rr, len(wins) / len(rs) * 100, sum(rs) / len(rs), sum(rs), pf))
    return " | ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT")
    ap.add_argument("--tfs", default="15M,1H,4H")
    ap.add_argument("--candles", type=int, default=2000)
    ap.add_argument("--window", type=int, default=300)
    ap.add_argument("--step", type=int, default=3)
    ap.add_argument("--horizon", type=int, default=48)
    ap.add_argument("--fee", type=float, default=sl_tp.fee("low"))  # D1: from risk_config.json
    a = ap.parse_args()

    all_trades = []
    t0 = time.time()
    for sym in a.symbols.split(","):
        for tf in a.tfs.split(","):
            candles = fetch(sym, TF_MAP[tf], a.candles)
            if len(candles) < a.window + 50:
                print("%s %s: not enough candles (%d)" % (sym, tf, len(candles)))
                continue
            tr, sk = run(sym, tf, candles, a.window, a.step, a.horizon, a.fee)
            all_trades.extend(tr)
            print("%s %s: candles=%d trades=%d skipped_risk=%d (%.0fs)" % (
                sym, tf, len(candles), len(tr), sk, time.time() - t0))

    print("\n=== RESULTS (fee=%.2f%% round trip, horizon=%d bars) ===" % (a.fee * 100, a.horizon))
    print(stats(all_trades, "ALL"))
    for tf in a.tfs.split(","):
        print(stats([x for x in all_trades if x["tf"] == tf], "TF " + tf))
    for side in ("BUY", "SELL"):
        print(stats([x for x in all_trades if x["side"] == side], "SIDE " + side))
    for tc in (3, 4):
        sub = [x for x in all_trades if (x["touches"] == 3 if tc == 3 else x["touches"] >= 4)]
        print(stats(sub, "touches %s" % ("=3" if tc == 3 else ">=4")))

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(out_dir, exist_ok=True)
    fp = os.path.join(out_dir, "backtest_%s.json" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    io_atomic.atomic_write_json(fp, {"params": vars(a), "trades": all_trades})  # D18R:
    print("\nSaved: %s" % os.path.basename(fp))


if __name__ == "__main__":
    main()
