# -*- coding: utf-8 -*-
# analyzer.py — Fibo v3 Golden Pocket analyzer
# Uses ab_final.py logic (imported, not modified)
# STANDALONE
import os, sys, json, time, urllib.request
from datetime import datetime
import numpy as np
import io_atomic  # D18R:
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results")
FIBO_DIR = r"E:\RAMAN.RAMIYA.ARAN\Robot.03-----Z.ai\FIBO_V2_DEV"

ENDPOINTS = [
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://data-api.binance.vision",
    "https://api1.binance.com",
    "https://api2.binance.com",
]

# Fibo v3 config (from ab_final.py)
PIVOT_N=3; MAX_AGE=2016
ENTRY_LO=0.618; ENTRY_HI=0.702
SL_ATR=0.5; MAX_RISK=0.05; MIN_RISK=0.005
TP_PCT=1.00; PARTIAL=0.5
VOL_MA=20; VOL_MULT=1.2; TREND_EMA=50
FEE_BPS=15; SLIP_BPS=5; MAX_BARS=200

def get_json(path, timeout=15):
    for ep in ENDPOINTS:
        try:
            url = ep + path
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
    return None

def fetch_klines(symbol, interval, limit):
    data = get_json(f"/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}")
    if not data or len(data) < 50:
        return None
    df = pd.DataFrame(data)
    df.columns = ["t","open","high","low","close","volume","close_ts","qvol","trades","tbb","tbq","ignore"][:df.shape[1]]
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["t","open","high","low","close"]).reset_index(drop=True)
    # ts units (Binance may be ms or us)
    v = df["t"].iloc[0]
    if v > 1e14:  # microseconds
        df["t"] = df["t"] / 1000
        df["close_ts"] = df["close_ts"] / 1000
    return df[["t","open","high","low","close","volume","close_ts"]]

def ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def atr(df, p=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/p, adjust=False).mean()

def pivots(arr, n, kind):
    out = []
    for i in range(n, len(arr)-n):
        w = arr[i-n:i+n+1]
        if (kind=="high" and arr[i]==w.max()) or (kind=="low" and arr[i]==w.min()):
            out.append(i)
    return out

def gp_zone(hi, lo, side):
    leg = hi - lo
    if side == "BUY":
        z_hi = hi - leg*ENTRY_LO
        z_lo = hi - leg*ENTRY_HI
    else:
        z_lo = lo + leg*ENTRY_LO
        z_hi = lo + leg*ENTRY_HI
    return min(z_lo, z_hi), max(z_lo, z_hi)

def detect_leg(h, l, ts, a, side):
    last = len(h) - 1
    p_hi = pivots(h, PIVOT_N, "high")
    p_lo = pivots(l, PIVOT_N, "low")
    if not p_hi or not p_lo:
        return None
    if side == "BUY":
        for ph in reversed(p_hi):
            if (last-ph) > MAX_AGE:
                continue
            la = [i for i in p_lo if i > ph]
            if not la: continue
            pl = la[0]
            hi, lo = h[ph], l[pl]
            if hi <= lo: continue
            conf_i = pl + PIVOT_N
            if conf_i > last: continue
            return dict(side="BUY", hi=hi, lo=lo, hi_idx=ph, lo_idx=pl,
                        hi_ts=ts[ph], lo_ts=ts[pl], leg=hi-lo,
                        atr=a[ph] if not np.isnan(a[ph]) else a[last],
                        conf_ts=ts[conf_i])
    else:
        for pl in reversed(p_lo):
            if (last-pl) > MAX_AGE: continue
            ha = [i for i in p_hi if i > pl]
            if not ha: continue
            ph = ha[0]
            hi, lo = h[ph], l[pl]
            if hi <= lo: continue
            conf_i = ph + PIVOT_N
            if conf_i > last: continue
            return dict(side="SELL", hi=hi, lo=lo, hi_idx=ph, lo_idx=pl,
                        hi_ts=ts[ph], lo_ts=ts[pl], leg=hi-lo,
                        atr=a[pl] if not np.isnan(a[pl]) else a[last],
                        conf_ts=ts[conf_i])
    return None

def analyze_symbol(symbol):
    """تحلیل یک نماد با Fibo v3"""
    df4h = fetch_klines(symbol, "4h", 300)
    df5m = fetch_klines(symbol, "5m", 500)
    if df4h is None or df5m is None:
        return None

    # افزودن اندیکاتورها به df5
    df5 = df5m.copy()
    df5["ema50"] = ema(df5["close"], TREND_EMA)
    df5["atr"] = atr(df5)

    h = df4h["high"].values
    l = df4h["low"].values
    ts = df4h["t"].values
    a = atr(df4h).values

    # آخرین لگ
    signals = []
    for side in ("BUY", "SELL"):
        leg = detect_leg(h, l, ts, a, side)
        if leg is None: continue
        
        # محاسبه zone
        z1, z2 = gp_zone(leg["hi"], leg["lo"], side)
        price = float(df5["close"].iloc[-1])
        
        # آیا قیمت در ناحیه است؟
        in_zone = bool(z1 <= price <= z2)
        
        signals.append({
            "side": side,
            "entry_zone_lo": round(z1, 8),
            "entry_zone_hi": round(z2, 8),
            "leg_hi": round(leg["hi"], 8),
            "leg_lo": round(leg["lo"], 8),
            "leg_size_atr": round(leg["leg"] / leg["atr"], 2) if leg["atr"] else 0,
            "current_price": round(price, 8),
            "in_zone": in_zone,
            "conf_ts": int(leg["conf_ts"]),
        })
    
    return {
        "symbol": symbol,
        "price": round(float(df5["close"].iloc[-1]), 8),
        "signals": signals,
    }

if __name__ == "__main__":
    print("=" * 100)
    print("  ASTRA ANALYZER — Fibo v3 Golden Pocket")
    print("=" * 100)
    
    # خواندن آخرین اسکن
    scan_files = sorted([f for f in os.listdir(OUT) if f.startswith("scan_")])
    if not scan_files:
        print("[X] No scan file — run scanner_v2.py first")
        exit(1)
    latest = os.path.join(OUT, scan_files[-1])
    print(f"[*] Using scan: {latest}")
    
    with open(latest, encoding="utf-8") as f:
        scan = json.load(f)
    
    # فیلتر نمادهای با ADX >= 20
    qualified = [d for d in scan["top"] if d.get("adx", 0) >= 20]
    print(f"[*] Qualified symbols (ADX >= 20): {len(qualified)}")
    print()
    
    t0 = time.time()
    results = []
    for d in qualified:
        print(f"[*] Analyzing {d['symbol']}...")
        r = analyze_symbol(d["symbol"])
        if r:
            r["adx"] = d["adx"]
            r["regime"] = d["regime"]
            r["volume_24h"] = d["quote_volume_24h"]
            results.append(r)
        time.sleep(0.1)
    
    # ذخیره
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fp = os.path.join(OUT, f"analyze_{ts}.json")
    io_atomic.atomic_write_json(fp, {"generated": ts, "count": len(results), "results": results})  # D18R:
    
    # نمایش
    print()
    print(f"{'symbol':<12}{'price':>12}{'ADX':>7}{'regime':>10}  {'signal':<30}")
    print("-" * 100)
    for r in results:
        for s in r["signals"]:
            sig_str = f"{s['side']} @ {s['entry_zone_lo']:.4f}-{s['entry_zone_hi']:.4f}"
            if s["in_zone"]:
                sig_str += "  <<< IN ZONE!"
            print(f"{r['symbol']:<12}{r['price']:>12.4f}{r['adx']:>7.1f}{r['regime']:>10}  {sig_str}")
    
    print()
    print(f"[OK] Saved: {fp}")
    print(f"[T] Time: {time.time()-t0:.1f}s")


