# -*- coding: utf-8 -*-
# backtest_mtf.py — Phase 32: walk-forward backtest of scanner_mtf zone-leg signals
# no look-ahead: at step t only candles[:t+1] closed bars visible (window = last 200 closed, live struct limit)
# signal = exact live engine: sv4.detect_leg + gp_zone + zone_status -> IN_ZONE or NEAR
# entry=close[t]; SL=zone boundary +/- sl_atr_factor*ATR via sl_tp.py (D1); TP=tp_targets (risk_config.json); horizon=48 bars; fee from sl_tp (risk_config.json)
# one trade per leg (uid=(side,hi_idx,lo_idx)) + busy_until horizon (same methodology as backtest_lines.py)
import os
import sys
import json
import time
import argparse
import io_atomic  # D18R:
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scanner_v4 as sv4
from backtest_lines import fetch, simulate, TF_MAP
import sl_tp  # D1

WINDOW = 200  # live struct limit: scanner_mtf TIMEFRAMES "limit": 200
SIG_TYPES = ("IN_ZONE", "NEAR")


def eval_step(w, side, max_age=sv4.MAX_AGE):
    """Replicate live scanner_mtf per-side signal at the last closed bar of window w."""
    h, l, c, ts = w["h"], w["l"], w["c"], w["t"]
    atr = sv4.atr_arr(h, l, c)
    if len(atr) < 15:
        return None
    leg = sv4.detect_leg(h, l, ts, atr, side)
    if leg is None:
        return None
    if side == "BUY" and (len(h) - 1 - leg["hi_idx"]) > max_age:
        return None
    if side == "SELL" and (len(h) - 1 - leg["lo_idx"]) > max_age:
        return None
    price = c[-1]
    z1, z2 = sv4.gp_zone(leg["hi"], leg["lo"], side)  # z1 < z2
    zs = sv4.zone_status(price, z1, z2, side)
    if zs not in SIG_TYPES:
        return None
    if side == "BUY":
        sl = sl_tp.calc_sl("BUY", z1, leg["atr"])  # D1: zone edge as pivot anchor (sl_atr_factor)
        risk = price - sl
    else:
        sl = sl_tp.calc_sl("SELL", z2, leg["atr"])  # D1: zone edge as pivot anchor (sl_atr_factor)
        risk = sl - price
    # Fee gate: stop distance <= round-trip fee -> economically unviable
    if risk <= 0 or leg["atr"] <= 0 or (risk / price) <= sl_tp.fee("round_trip"):
        return None
    return {"leg": leg, "z1": z1, "z2": z2, "status": zs, "price": price,
            "sl": sl, "risk": risk}


def run(symbol, tf, candles, step, horizon, fee, max_dist_pct=sv4.NEAR_ZONE_PCT):
    trades = []
    n = len(candles)
    seen = set()
    busy_until = -1
    signals_seen = 0
    risk_bad = 0
    for t in range(WINDOW, n - 1, step):
        if t <= busy_until:
            continue
        off = t + 1 - WINDOW
        w = {"h": [c["high"] for c in candles[off:t + 1]],
             "l": [c["low"] for c in candles[off:t + 1]],
             "c": [c["close"] for c in candles[off:t + 1]],
             "t": [c["time"] for c in candles[off:t + 1]]}
        for side in ("BUY", "SELL"):
            r = eval_step(w, side)
            if r is None:
                continue
            signals_seen += 1
            leg = r["leg"]
            uid = (side, off + leg["hi_idx"], off + leg["lo_idx"])
            if uid in seen:
                continue
            dist_pct = 0.0
            if r["status"] != "IN_ZONE":
                dist_pct = ((r["price"] - r["z2"]) / r["price"] * 100 if side == "BUY"
                            else (r["z1"] - r["price"]) / r["price"] * 100)
                if dist_pct >= max_dist_pct:
                    continue
            seen.add(uid)
            tr = {"symbol": symbol, "tf": tf, "side": side, "t": t,
                  "time": candles[t]["time"], "status": r["status"],
                  "entry": round(r["price"], 8), "sl": round(r["sl"], 8),
                  "dist_pct": round(dist_pct, 3),
                  "risk_atr": round(r["risk"] / leg["atr"], 3)}
            for rr in sl_tp.tp_targets():  # D1: targets from risk_config.json
                tr["R%d" % rr] = round(simulate(candles, t, side, r["price"], r["sl"], rr, horizon, fee), 3)
            trades.append(tr)
            busy_until = t + horizon
    return trades, signals_seen, risk_bad


def stats(trades, label):
    if not trades:
        return "%-16s n=0" % label
    parts = ["%-16s n=%-4d" % (label, len(trades))]
    for rr in sl_tp.tp_targets():  # D1: targets from risk_config.json
        rs = [x["R%d" % rr] for x in trades]
        wins = [r for r in rs if r > 0]
        loss = [-r for r in rs if r <= 0]
        pf = (sum(wins) / sum(loss)) if loss and sum(loss) > 0 else float("inf")
        sd = (sum((x - sum(rs) / len(rs)) ** 2 for x in rs) / (len(rs) - 1)) ** 0.5 if len(rs) > 1 else 0
        tstat = (sum(rs) / len(rs)) / (sd / len(rs) ** 0.5) if sd > 0 else float("inf")
        parts.append("TP%dR: win=%5.1f%% avgR=%+.2f PF=%.2f t=%+.2f" % (
            rr, len(wins) / len(rs) * 100, sum(rs) / len(rs), pf, tstat))
    return " | ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT")
    ap.add_argument("--tfs", default="15M,30M,1H,4H")
    ap.add_argument("--candles", type=int, default=3000)
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--horizon", type=int, default=48)
    ap.add_argument("--fee", type=float, default=sl_tp.fee("round_trip"))  # D1: from risk_config.json
    a = ap.parse_args()

    all_trades = []
    t0 = time.time()
    for sym in a.symbols.split(","):
        for tf in a.tfs.split(","):
            candles = fetch(sym, TF_MAP[tf], a.candles)
            if len(candles) < WINDOW + 50:
                print("%s %s: not enough candles (%d)" % (sym, tf, len(candles)))
                continue
            tr, seen, _rb = run(sym, tf, candles, a.step, a.horizon, a.fee)
            all_trades.extend(tr)
            print("%s %s: candles=%d trades=%d signals=%d (%.0fs)" % (
                sym, tf, len(candles), len(tr), seen, time.time() - t0))

    print("\n=== MTF ZONE BACKTEST (fee=%.2f%% round trip, horizon=%d bars, window=%d) ===" % (
        a.fee * 100, a.horizon, WINDOW))
    print("t = mean/(sd/sqrt(n)); n per row shown; SAME fee sim as backtest_lines.py")
    print(stats(all_trades, "ALL"))
    for tf in a.tfs.split(","):
        print(stats([x for x in all_trades if x["tf"] == tf], "TF " + tf))
    for side in ("BUY", "SELL"):
        print(stats([x for x in all_trades if x["side"] == side], "SIDE " + side))
    for st in SIG_TYPES:
        print(stats([x for x in all_trades if x["status"] == st], "signal " + st))

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(out_dir, exist_ok=True)
    fp = os.path.join(out_dir, "backtest_mtf_%s.json" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    io_atomic.atomic_write_json(fp, {"params": vars(a), "window": WINDOW, "trades": all_trades})  # D18R:
    print("\nSaved: %s" % os.path.basename(fp))


if __name__ == "__main__":
    main()
