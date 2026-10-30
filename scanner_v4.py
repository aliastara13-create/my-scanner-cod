# -*- coding: utf-8 -*-
# scanner_v4.py — Live scan + S/R + Zone detection + Alerts
# STANDALONE
import os, json, time, urllib.request
from datetime import datetime, timezone
import io_atomic  # D18
import sl_tp  # D1C:
import numpy as np
try:
    from agent_decision import AgentDecision
    _agent = AgentDecision(threshold=70)
except ImportError:
    AgentDecision = None
    _agent = None
try:
    from fast_fetch import get_json_fast
except ImportError:
    get_json_fast = None
try:
    from dominance import analyze_dominance
except ImportError:
    analyze_dominance = None

try:
    from trend_lines import analyze_trend_lines
except ImportError:
    analyze_trend_lines = None

# Cache برای dominance
_DOM_CACHE = {"data": None, "ts": 0}

_EMA_CACHE = {}
_VWAP_CACHE = {}
_MULTI_CACHE = {}

def get_ema_cached(symbol):
    if symbol in _EMA_CACHE:
        return _EMA_CACHE[symbol]
    if analyze_ema_multi_tf:
        try:
            _EMA_CACHE[symbol] = analyze_ema_multi_tf(symbol)
        except Exception:
            _EMA_CACHE[symbol] = None
    return _EMA_CACHE.get(symbol)

def get_vwap_cached(symbol):
    if symbol in _VWAP_CACHE:
        return _VWAP_CACHE[symbol]
    if analyze_vwap_sessions:
        try:
            _VWAP_CACHE[symbol] = analyze_vwap_sessions(symbol)
        except Exception:
            _VWAP_CACHE[symbol] = None
    return _VWAP_CACHE.get(symbol)

def get_multi_cached(symbol):
    if symbol in _MULTI_CACHE:
        return _MULTI_CACHE[symbol]
    if analyze_symbol_multi:
        try:
            _MULTI_CACHE[symbol] = analyze_symbol_multi(symbol)
        except Exception:
            _MULTI_CACHE[symbol] = None
    return _MULTI_CACHE.get(symbol)

def get_dominance_cached():
    import time
    if _DOM_CACHE["data"] and (time.time() - _DOM_CACHE["ts"] < 300):
        return _DOM_CACHE["data"]
    if analyze_dominance:
        _DOM_CACHE["data"] = analyze_dominance()
        _DOM_CACHE["ts"] = time.time()
    return _DOM_CACHE["data"]
try:
    from ema_multi_tf import analyze_ema_multi_tf
    from vwap_session import analyze_vwap_sessions
except ImportError:
    analyze_ema_multi_tf = None
    analyze_vwap_sessions = None
try:
    from news import get_news_for_symbol
except ImportError:
    get_news_for_symbol = None

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results")
ALERTS = os.path.join(BASE, "data", "alerts.json")

ENDPOINTS = [
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://data-api.binance.vision",
    "https://api1.binance.com",
    "https://api2.binance.com",
]

STABLES = {"USDCUSDT","USD1USDT","RLUSDUSDT","FDUSDUSDT","TUSDUSDT",
           "BUSDUSDT","DAIUSDT","USDPUSDT","USDDUSDT","PYUSDUSDT",
           "EURUSDT","GBPUSDT","AEURUSDT","EURIUSDT","UUSDT","BFUSDUSDT",
           "USD4USDT","XUSDUSDT","USDXUSDT","USDEUSDT","SUSDUSDT"}

PIVOT_N=3; MAX_AGE=2016
ENTRY_LO=0.618; ENTRY_HI=0.702
# D1C: legacy zone consts (SL_ATR/TP_PCT/MIN/MAX_RISK) removed — SL/TP now via sl_tp.py (risk_config.json)
NEAR_ZONE_PCT = 0.5  # هشدار اگر فاصله < 0.5%
VOL_MA=20; VOL_MULT=1.2; TREND_EMA=50

TF_SECONDS = {"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400}
SESSIONS = [
    {"name":"Asia","start":0,"end":8,"color":"#a371f7"},
    {"name":"London","start":7,"end":16,"color":"#58a6ff"},
    {"name":"New York","start":12,"end":21,"color":"#3fb950"},
    {"name":"Close","start":21,"end":24,"color":"#8b949e"},
]

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

def klines_to_arrays(klines):
    if not klines or len(klines) < 20: return None
    return {"h":[float(k[2]) for k in klines],
            "l":[float(k[3]) for k in klines],
            "c":[float(k[4]) for k in klines],
            "v":[float(k[5]) for k in klines],
            "t":[int(k[0]) for k in klines],
            "ct":[int(k[6]) for k in klines]}

def ema(arr, p):
    out = []; k = 2/(p+1)
    for i, v in enumerate(arr):
        out.append(v if i==0 else v*k + out[-1]*(1-k))
    return out

def atr_arr(h, l, c, p=14):
    trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(c))]
    if len(trs) < p: return []
    out = [sum(trs[:p])/p]
    for i in range(p, len(trs)):
        out.append((out[-1]*(p-1)+trs[i])/p)
    return out

def adx_arr(h, l, c, p=14):
    n = len(c)
    if n < p*2: return []
    pdm, mdm = [], []
    for i in range(1, n):
        up = h[i]-h[i-1]; dn = l[i-1]-l[i]
        pdm.append(up if (up>dn and up>0) else 0)
        mdm.append(dn if (dn>up and dn>0) else 0)
    trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(c))]
    def wilder(a):
        if len(a)<p: return []
        s = sum(a[:p]); out = [s]
        for i in range(p, len(a)):
            s = s - s/p + a[i]; out.append(s)
        return out
    aw = wilder(trs); pw = wilder(pdm); mw = wilder(mdm)
    if not aw: return []
    pdi = [100*pp/a if a>0 else 0 for pp,a in zip(pw, aw)]
    mdi = [100*mm/a if a>0 else 0 for mm,a in zip(mw, aw)]
    dx = [100*abs(pp-mm)/(pp+mm) if (pp+mm)>0 else 0 for pp,mm in zip(pdi, mdi)]
    if len(dx)<p: return []
    adx = [sum(dx[:p])/p]
    for i in range(p, len(dx)):
        adx.append((adx[-1]*(p-1)+dx[i])/p)
    return adx

def pivots(arr, n, kind):
    out = []
    for i in range(n, len(arr)-n):
        w = arr[i-n:i+n+1]
        # support both numpy array and python list
        if hasattr(w, 'max'):
            wmax = w.max()
            wmin = w.min()
        else:
            wmax = max(w)
            wmin = min(w)
        if (kind=="high" and arr[i]==wmax) or (kind=="low" and arr[i]==wmin):
            out.append(i)
    return out

def detect_leg(h, l, ts, a, side):
    last = len(h)-1
    p_hi = pivots(h, PIVOT_N, "high")
    p_lo = pivots(l, PIVOT_N, "low")
    if not p_hi or not p_lo: return None
    if side == "BUY":
        for ph in reversed(p_hi):
            if (last-ph)>MAX_AGE: continue
            la = [i for i in p_lo if i>ph]
            if not la: continue
            pl = la[0]
            hi, lo = h[ph], l[pl]
            if hi<=lo: continue
            conf_i = pl + PIVOT_N
            if conf_i>last: continue
            atr_val = a[ph] if ph<len(a) and not np.isnan(a[ph]) else (a[-1] if a else 0)
            return dict(side="BUY", hi=hi, lo=lo, hi_idx=ph, lo_idx=pl,
                        hi_ts=ts[ph], lo_ts=ts[pl], leg=hi-lo,
                        atr=atr_val, conf_ts=ts[conf_i])
    else:
        for pl in reversed(p_lo):
            if (last-pl)>MAX_AGE: continue
            ha = [i for i in p_hi if i>pl]
            if not ha: continue
            ph = ha[0]
            hi, lo = h[ph], l[pl]
            if hi<=lo: continue
            conf_i = ph + PIVOT_N
            if conf_i>last: continue
            atr_val = a[pl] if pl<len(a) and not np.isnan(a[pl]) else (a[-1] if a else 0)
            return dict(side="SELL", hi=hi, lo=lo, hi_idx=ph, lo_idx=pl,
                        hi_ts=ts[ph], lo_ts=ts[pl], leg=hi-lo,
                        atr=atr_val, conf_ts=ts[conf_i])
    return None

def gp_zone(hi, lo, side):
    leg = hi-lo
    if side=="BUY":
        z_hi = hi - leg*ENTRY_LO
        z_lo = hi - leg*ENTRY_HI
    else:
        z_lo = lo + leg*ENTRY_LO
        z_hi = lo + leg*ENTRY_HI
    return min(z_lo, z_hi), max(z_lo, z_hi)

def detect_sr(h, l, c, price, pivot_n=5, lookback=100, num_levels=3):
    if len(h) < lookback: lookback = len(h)
    hh = h[-lookback:]; ll = l[-lookback:]
    ph = pivots(hh, pivot_n, "high")
    pl = pivots(ll, pivot_n, "low")
    res = sorted([hh[i] for i in ph if hh[i] > price])[:num_levels]
    sup = sorted([ll[i] for i in pl if ll[i] < price], reverse=True)[:num_levels]
    return {
        "resistances": [{"price":round(r,8),"dist_pct":round((r-price)/price*100,2)} for r in res],
        "supports": [{"price":round(s,8),"dist_pct":round((price-s)/price*100,2)} for s in sup]
    }

def zone_status(price, z_lo, z_hi, side):
    """وضعیت قیمت نسبت به زون"""
    if z_lo <= price <= z_hi:
        return "IN_ZONE"
    if side == "BUY":
        # ورود از بالا (قیمت بالای زون است، منتظر برگشت)
        if price > z_hi:
            dist_pct = (price - z_hi) / price * 100
            if dist_pct < NEAR_ZONE_PCT:
                return "NEAR"
            return "WAITING"
        # قیمت زیر زون (از دست رفته)
        return "MISSED"
    else:  # SELL
        if price < z_lo:
            dist_pct = (z_lo - price) / price * 100
            if dist_pct < NEAR_ZONE_PCT:
                return "NEAR"
            return "WAITING"
        return "MISSED"

def compute_stars(score, signals, adx):
    """محاسبه ستاره ۱ تا ۵"""
    in_zone = any(s.get("zone_status") == "IN_ZONE" for s in signals)
    near = any(s.get("zone_status") == "NEAR" for s in signals)
    rr_list = [s.get("rr", 0) for s in signals if s.get("zone_status") in ("IN_ZONE", "NEAR")]
    best_rr = max(rr_list) if rr_list else 0
    
    # ۵ ستاره: عالی
    if in_zone and score >= 70 and best_rr >= 1.5:
        return 5, "عالی برای شکار"
    # ۴ ستاره: آماده
    if in_zone and score >= 50:
        return 4, "آماده برای شکار"
    # ۳ ستاره: انتظار
    if near and score >= 40:
        return 3, "در لیست انتظار"
    # ۲ ستاره: رصد
    if score >= 30:
        return 2, "رصد"
    # ۱ ستاره
    return 1, "فقط تماشا"


def compute_score(adx, regime, signals, sr_all, volume_24h, vwap=None, ema_mtf=None, multi=None):
    """
    محاسبه Score — نسخه بهبودیافته
    حتی بدون سیگنال، امتیاز بر اساس ADX + Regime + Alignment محاسبه می‌شود.
    """
    score = 0

    # ۱. ADX — حداکثر ۲۵
    score += min(25, adx * 25 / 50)

    # ۲. Regime — حداکثر ۱۵
    score += {"STRONG":15,"TRENDING":10,"NEUTRAL":3,"RANGING":0}.get(regime, 0)

    # ۳. سیگنال و Zone — حداکثر ۳۰
    best_side = None
    for s in signals:
        if s.get("zone_status") in ("IN_ZONE", "NEAR"):
            best_side = s["side"]
            break

    in_zone = any(s.get("zone_status") == "IN_ZONE" for s in signals)
    near = any(s.get("zone_status") == "NEAR" for s in signals)

    if in_zone:
        score += 30
    elif near:
        score += 20
    elif signals:
        score += 10

    # ۴. Volume 24h — حداکثر ۱۵
    if volume_24h > 500e6: score += 15
    elif volume_24h > 200e6: score += 12
    elif volume_24h > 100e6: score += 8
    elif volume_24h > 50e6: score += 5

    # ۵. S/R نزدیک — حداکثر ۱۵
    if in_zone and best_side:
        for s in signals:
            if s.get("zone_status") == "IN_ZONE" and s["side"] == "BUY":
                for sup in sr_all.get("1h", {}).get("supports", []):
                    if sup.get("dist_pct", 999) < 1.0: score += 15; break
            elif s.get("zone_status") == "IN_ZONE" and s["side"] == "SELL":
                for res in sr_all.get("1h", {}).get("resistances", []):
                    if res.get("dist_pct", 999) < 1.0: score += 15; break

    # ۶. EMA50 alignment — حداکثر ۲۰
    if ema_mtf:
        ema_align = ema_mtf.get("alignment", "NONE")
        ema_strength = ema_mtf.get("strength", 0)
        if best_side:
            if ema_align == ("ALL_" + best_side):
                score += 20
            elif ema_align == "MIXED":
                score -= 10
        else:
            if ema_align in ("ALL_BUY", "ALL_SELL"):
                score += min(15, ema_strength * 4)

    # ۷. VWAP alignment — حداکثر ۱۵
    if vwap:
        vwap_align = vwap.get("alignment", "NONE")
        vwap_strength = vwap.get("strength", 0)
        if best_side:
            if vwap_align == ("ALL_" + best_side):
                score += 15
        else:
            if vwap_align in ("ALL_BUY", "ALL_SELL"):
                score += min(10, vwap_strength * 5)

    # ۸. Ichimoku + POC — حداکثر ۱۰
    if multi:
        ichi = multi.get("ichimoku", {})
        poc = multi.get("poc", {})
        multi_signal = multi.get("signal", "NEUTRAL")
        multi_strength = multi.get("strength", 0)
        if best_side:
            if ichi.get("signal") == best_side: score += 5
            if poc.get("signal") == best_side: score += 5
        else:
            if multi_signal in ("BUY", "SELL"):
                score += min(8, multi_strength * 1.5)

    score = max(0, min(100, round(score, 1)))
    return score
def analyze_symbol(symbol):
    df4h = (get_json_fast or get_json)(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=300")
    df5m = (get_json_fast or get_json)(f"/api/v3/klines?symbol={symbol}&interval=5m&limit=500")
    df1h = (get_json_fast or get_json)(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=300")
    df1d = (get_json_fast or get_json)(f"/api/v3/klines?symbol={symbol}&interval=1d&limit=200")
    if not df4h or not df5m: return None
    a4 = klines_to_arrays(df4h); a5 = klines_to_arrays(df5m)
    a1h = klines_to_arrays(df1h) if df1h else None
    a1d = klines_to_arrays(df1d) if df1d else None
    price = a5["c"][-1]
    adx_vals = adx_arr(a4["h"], a4["l"], a4["c"])
    adx = adx_vals[-1] if adx_vals else 0
    regime = "STRONG" if adx>25 else "TRENDING" if adx>20 else "NEUTRAL" if adx>15 else "RANGING"
    atr4 = atr_arr(a4["h"], a4["l"], a4["c"])
    signals = []
    # ═══════════ فیلتر MTF: تعیین جهت مجاز ═══════════
    # ۱. روند 4H
    ema50_4h = None
    try:
        closes_4h = df4h["close"].values
        if len(closes_4h) >= 50:
            k = 2 / 51
            ema_4h = closes_4h[0]
            for v in closes_4h[1:]:
                ema_4h = v * k + ema_4h * (1 - k)
            ema50_4h = ema_4h
    except Exception:
        pass

    # ۲. روند 1H
    ema50_1h = None
    try:
        if df1h and len(df1h) >= 50:
            closes_1h = [float(k[4]) for k in df1h[:200]]
            k = 2 / 51
            ema_1h = closes_1h[0]
            for v in closes_1h[1:]:
                ema_1h = v * k + ema_1h * (1 - k)
            ema50_1h = ema_1h
    except Exception:
        pass

    # ۳. تعیین جهت مجاز
    trend_4h = "NEUTRAL"
    trend_1h = "NEUTRAL"
    price_now = a4["c"][-1]

    if ema50_4h:
        dist_4h = (price_now - ema50_4h) / ema50_4h * 100
        if dist_4h > 0.5:
            trend_4h = "UP"
        elif dist_4h < -0.5:
            trend_4h = "DOWN"

    if ema50_1h:
        dist_1h = (price_now - ema50_1h) / ema50_1h * 100
        if dist_1h > 0.5:
            trend_1h = "UP"
        elif dist_1h < -0.5:
            trend_1h = "DOWN"

    # ۴. جهت مجاز
    allowed_sides = []
    if trend_4h == "UP" and trend_1h == "UP":
        allowed_sides = ["BUY"]
    elif trend_4h == "DOWN" and trend_1h == "DOWN":
        allowed_sides = ["SELL"]
    # ناهماهنگ → بدون سیگنال
    
    # ۵. فیلتر Dominance (BTC.D + USDT.D + Market Cap)
    if allowed_sides:
        try:
            dom = get_dominance_cached()
            if dom:
                overall = dom.get("overall", "NEUTRAL")
                if overall in ("STRONG_SELL", "SELL"):
                    # فقط SELL مجاز
                    allowed_sides = [s for s in allowed_sides if s == "SELL"]
                elif overall in ("STRONG_BUY", "BUY"):
                    # فقط BUY مجاز
                    allowed_sides = [s for s in allowed_sides if s == "BUY"]
                else:
                    # NEUTRAL → بدون سیگنال
                    allowed_sides = []
        except Exception as e:
            print(f"  ⚠️ dominance error: {e}")

    # ═══════════ تولید سیگنال فقط در جهت مجاز ═══════════
    for side in allowed_sides:
        leg = detect_leg(a4["h"], a4["l"], a4["t"], atr4, side)
        if leg is None: continue
        z1, z2 = gp_zone(leg["hi"], leg["lo"], side)
        zs = zone_status(price, z1, z2, side)
        # D1C: SL/TP via sl_tp.py — identical to backtest_mtf (zone-edge pivot anchor, price-based R)
        if side == "BUY":
            sl = sl_tp.calc_sl("BUY", z1, leg["atr"])
        else:
            sl = sl_tp.calc_sl("SELL", z2, leg["atr"])
        risk = (price - sl) if side == "BUY" else (sl - price)
        tps = sl_tp.calc_tp(price, sl, side)
        # Fee gate: stop distance <= round-trip fee -> economically unviable
        if risk <= 0 or not tps or (risk / price) <= sl_tp.fee("round_trip"):
            continue
        tp = tps[0]
        tp2 = tps[1] if len(tps) > 1 else None
        rr = abs(tp - price) / abs(risk)
        # فاصله تا زون
        if zs == "WAITING":
            if side == "BUY":
                dist_pct = (price - z2) / price * 100
            else:
                dist_pct = (z1 - price) / price * 100
        elif zs == "NEAR":
            if side == "BUY":
                dist_pct = (price - z2) / price * 100
            else:
                dist_pct = (z1 - price) / price * 100
        else:
            dist_pct = 0.0
        signals.append({
            "side": side,
            "entry_zone_lo": round(z1, 8), "entry_zone_hi": round(z2, 8),
            "sl": round(sl, 8), "tp": round(tp, 8),
            "tp2": (round(tp2, 8) if tp2 is not None else None),  # D1C: second target (tp_targets[1])
            "rr": round(rr, 2),
            "leg_hi": round(leg["hi"], 8), "leg_lo": round(leg["lo"], 8),
            "zone_status": zs,
            "dist_pct": round(dist_pct, 3),
            "in_zone": bool(zs == "IN_ZONE"),
        })
    sr = {}
    if a1h: sr["1h"] = detect_sr(a1h["h"], a1h["l"], a1h["c"], price)
    if a4:  sr["4h"] = detect_sr(a4["h"], a4["l"], a4["c"], price)
    if a1d: sr["1d"] = detect_sr(a1d["h"], a1d["l"], a1d["c"], price, pivot_n=3)
    # Events
    events = []
    if get_news_for_symbol:
        try:
            ev = get_news_for_symbol(symbol)
            events = ev.get("events", [])
        except Exception:
            pass
    
    # EMA50 Multi-TF
    ema_mtf = None
    if analyze_ema_multi_tf:
        try:
            ema_mtf = get_ema_cached(symbol)
        except Exception:
            pass
    
    # VWAP Session
    vwap = None
    if analyze_vwap_sessions:
        try:
            vwap = get_vwap_cached(symbol)
        except Exception:
            pass
    
    # ─── Multi-Condition (Ichimoku + POC) ───
    multi = None
    try:
        from indicators import analyze_symbol_multi
        multi = analyze_symbol_multi(symbol)
    except Exception as e:
        pass
    
    # --- Trend Lines ---
    trend_data = None
    if analyze_trend_lines and df4h:
        try:
            candles_4h = [
                {"time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
                 "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
                for k in df4h
            ]
            trend_data = analyze_trend_lines(candles_4h, current_price=price)
        except Exception as e:
            print(f"  WARN trend_lines error for {symbol}: {e}")

    # ─── Agent Decision (لایه ۴) ───
    agent_result = None
    if _agent:
        try:
            agent_result = _agent.decide({
                "signals": signals,
                "ema_mtf": ema_mtf,
                "vwap": vwap,
                "multi": multi,
                "dominance": get_dominance_cached(),
                "trend_lines": trend_data,
            })
        except Exception as e:
            print(f"  ⚠️ agent error for {symbol}: {e}")
    
    return {"symbol": symbol, "price": round(price, 8), "adx": round(adx, 2),
            "regime": regime, "signals": signals, "sr": sr, "events": events,
            "ema_mtf": ema_mtf, "vwap": vwap, "multi": multi,
            "dominance": get_dominance_cached(),
            "trend_lines": trend_data,
            "agent": agent_result}

def get_tf_timers():
    now = int(time.time())
    out = {}
    for tf, sec in TF_SECONDS.items():
        nxt = (now // sec + 1) * sec
        out[tf] = {
            "seconds_left": nxt - now,
            "next_close_utc": datetime.fromtimestamp(nxt, tz=timezone.utc).strftime("%H:%M"),
        }
    return out

def get_sessions():
    now_utc = datetime.now(timezone.utc)
    h = now_utc.hour + now_utc.minute/60
    out = []
    for s in SESSIONS:
        active = s["start"] <= h < s["end"]
        if active:
            remain = int((s["end"] - h) * 60)
        else:
            until = (s["start"] - h) if h < s["start"] else (24 - h + s["start"])
            remain = int(until * 60)
        out.append({**s, "active": active, "remaining_min": remain})
    return out

if __name__ == "__main__":
    print("=" * 100)
    print("  ASTRA SCANNER v4 — Zone Detection + Alerts")
    print("=" * 100)
    timers = get_tf_timers()
    print()
    print("⏰ TF Timers:")
    for tf, t in timers.items():
        m, s = divmod(t["seconds_left"], 60)
        h, m = divmod(m, 60)
        print(f"  {tf:<5} : {h:02d}:{m:02d}:{s:02d}  (بعدی: {t['next_close_utc']} UTC)")
    sessions = get_sessions()
    print()
    print("🌍 Sessions:")
    for s in sessions:
        st = "🟢 ACTIVE" if s["active"] else "⚪"
        print(f"  {s['name']:<10} : {st}  ({s['remaining_min']} min)")
    
    scan_files = sorted([f for f in os.listdir(OUT) if f.startswith("scan_")])
    if not scan_files:
        print("[X] No scan"); exit(1)
    with open(os.path.join(OUT, scan_files[-1]), encoding="utf-8") as f:
        scan = json.load(f)
    qualified = [d for d in scan["top"] if d.get("adx", 0) >= 20]
    print(f"\n[*] Qualified: {len(qualified)}")
    t0 = time.time()
    results = []
    for d in qualified:
        print(f"[*] {d['symbol']}...")
        r = analyze_symbol(d["symbol"])
        if r:
            r.update({"adx":d["adx"],"regime":d["regime"],
                     "volume_24h":d["quote_volume_24h"],"change_pct":d["change_pct"],
                     "rank":d["rank"],"base":d["base"]})
            r["score"] = compute_score(r["adx"], r["regime"], r["signals"], r["sr"], d["quote_volume_24h"], r.get("vwap"), r.get("ema_mtf"), r.get("multi"))
            r["stars"], r["stars_label"] = compute_stars(r["score"], r["signals"], r["adx"])
            results.append(r)
        time.sleep(0.1)
    def sort_key(x):
        # اولویت: IN_ZONE > NEAR > بقیه
        has_zone = any(s.get("zone_status") == "IN_ZONE" for s in x.get("signals", []))
        has_near = any(s.get("zone_status") == "NEAR" for s in x.get("signals", []))
        zone_rank = 2 if has_zone else (1 if has_near else 0)
        return (zone_rank, x.get("stars", 0), x["score"])
    results.sort(key=sort_key, reverse=True)
    for i, r in enumerate(results, 1):
        r["priority"] = i
    
    # آلارم‌ها
    alerts = {"in_zone": [], "near": []}
    for r in results:
        for s in r["signals"]:
            if s["zone_status"] == "IN_ZONE":
                alerts["in_zone"].append({"symbol": r["symbol"], "side": s["side"],
                                          "zone": [s["entry_zone_lo"], s["entry_zone_hi"]],
                                          "price": r["price"], "score": r["score"]})
            elif s["zone_status"] == "NEAR":
                alerts["near"].append({"symbol": r["symbol"], "side": s["side"],
                                       "zone": [s["entry_zone_lo"], s["entry_zone_hi"]],
                                       "price": r["price"], "dist_pct": s["dist_pct"]})
    
    os.makedirs(os.path.dirname(ALERTS), exist_ok=True)
    with open(ALERTS, "w", encoding="utf-8") as f:
        json.dump({"ts": datetime.now().isoformat(), "alerts": alerts}, f, ensure_ascii=False, indent=2)
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fp = os.path.join(OUT, f"live_{ts}.json")
    io_atomic.atomic_write_json(fp, {"generated": ts, "count": len(results),
                                     "timers": timers, "sessions": sessions,
                                     "alerts": alerts, "results": results})  # D18 atomic write + lock
    
    print()
    print(f"{'stars':<8}{'#':<4}{'symbol':<10}{'score':>7}  {'status':<10}{'side':<6}{'zone':<28}{'price':>12}")
    print("-" * 118)
    for r in results:
        for s in r["signals"]:
            if s["zone_status"] in ("IN_ZONE", "NEAR"):
                zone = f"{s['entry_zone_lo']:.4f}-{s['entry_zone_hi']:.4f}"
                stars_str = "⭐" * r.get("stars", 1)
                print(f"{stars_str:<8}{r['priority']:<4}{r['symbol']:<10}{r['score']:>7.1f}  {s['zone_status']:<10}{s['side']:<6}{zone:<28}{r['price']:>12.4f}")
    print()
    print(f"🎯 IN ZONE: {len(alerts['in_zone'])}")
    print(f"⚡ NEAR   : {len(alerts['near'])}")
    print(f"[OK] Saved: {fp}")
    print(f"[T] Time: {time.time()-t0:.1f}s")






















