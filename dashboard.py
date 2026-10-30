# -*- coding: utf-8 -*-
# dashboard.py — ASTRA SCANNER Dashboard v2.1
import os, sys, json, glob, subprocess, threading, time
import io_atomic  # D18
from datetime import datetime
from flask import Flask, jsonify, send_from_directory, request
from telegram import send_telegram, format_signal, mask_token
from position_sizing import calculate_position_size, calculate_rr, suggest_risk_pct
import zones  # ZN1: Visual Zone Recognition + Liquidity

BASE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(BASE, "results")
FRONTEND = os.path.join(BASE, "frontend")
DATA = os.path.join(BASE, "data")
SETTINGS = os.path.join(DATA, "settings.json")

os.makedirs(DATA, exist_ok=True)
app = Flask(__name__, static_folder=None)

def latest_file(pattern):
    files = sorted(glob.glob(os.path.join(RESULTS, pattern)))
    if not files:
        print("[DEBUG] No file for pattern:", pattern)
        return None
    f = files[-1]
    print("[DEBUG] latest_file:", os.path.basename(f))
    return f

def load_json(path):
    if not path or not os.path.exists(path): return None
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except Exception as e:
        print("[ERR]", e)
        return None

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io_atomic.atomic_write_json(path, data)  # D18R: atomic also for settings state

def load_results(pattern):
    """D18: newest valid results file; skip unreadable/corrupt, fall back to previous valid."""
    files = sorted(glob.glob(os.path.join(RESULTS, pattern)))
    return io_atomic.load_newest_valid(files)[1]


def load_settings():
    if os.path.exists(SETTINGS): return load_json(SETTINGS)
    return {"telegram_token":"","telegram_chat":"","telegram_on":False,
            "sound_on":True,"desktop_notify":True,"min_score_alert":70}

def _age_from_generated(pattern):
    """D26 (hard-data rule 2): age from the newest file's own "generated" ts (not page load); mtime fallback.
    Handles scanner ts format (YYYYmmdd_HHMMSS) and ISO formats; unreadable/missing -> mtime result."""
    files = sorted(glob.glob(os.path.join(RESULTS, pattern)))
    if not files:
        return None
    gen = None
    try:
        with open(files[-1], encoding="utf-8") as f:
            gen = (json.load(f) or {}).get("generated")
    except Exception:
        gen = None
    parsed = None
    if gen:
        try:
            parsed = datetime.strptime(str(gen), "%Y%m%d_%H%M%S")
        except Exception:
            parsed = None
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(str(gen).replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(tz=None).replace(tzinfo=None)
            except Exception:
                parsed = None
    if parsed is None:
        return _age_of(pattern)
    return max(0, int(time.time() - parsed.timestamp()))


PRICES_CACHE = {"ts": 0.0, "data": None}   # D26: 5s server cache
_URLOPEN = None                              # D26: injectable urlopen (tests monkeypatch dsh._URLOPEN)


def _prices_impl(symbols_raw):
    """D26 (rule 3): ONE /api/v3/ticker/price upstream GET per <=5s window; cache full upstream map; filter to requested symbols."""
    global _URLOPEN
    if _URLOPEN is None:
        import urllib.request as _u
        _URLOPEN = _u.urlopen
    now = time.time()
    want = [s.strip().upper() for s in (symbols_raw or "").split(",") if s.strip()]
    all_prices = PRICES_CACHE.get("all")
    if all_prices is not None and (now - PRICES_CACHE.get("ts", 0.0) <= 5.0):
        prices = {sym: price for sym, price in all_prices.items() if (not want or sym in want)}
        data = {"ok": True, "fetched_at": PRICES_CACHE.get("ts", now), "count": len(prices),
                "requested": want, "prices": prices, "upstream_calls": 1, "cached": True}
        PRICES_CACHE["data"] = data
        return dict(data)
    try:
        import urllib.request as _u
        allp = None
        last_err = None
        for _host in BINANCE_HOSTS:
            try:
                req = _u.Request(_host + "/api/v3/ticker/price",
                                  headers={"User-Agent": "Mozilla/5.0"})
                with _URLOPEN(req, timeout=10) as resp:
                    allp = json.loads(resp.read().decode())
                break
            except Exception as e:
                last_err = e
        if allp is None:
            raise last_err if last_err else RuntimeError("no upstream")
        fetched_at = time.time()
    except Exception as e:
        return {"ok": False, "error": str(e)[:160], "fetched_at": now}
    all_prices = {}
    for row in allp:
        sym = (row.get("symbol") or "").upper()
        try:
            all_prices[sym] = float(row["price"])
        except Exception:
            continue
    prices = {sym: price for sym, price in all_prices.items() if (not want or sym in want)}
    data = {"ok": True, "fetched_at": fetched_at, "count": len(prices),
            "requested": want, "prices": prices, "upstream_calls": 1}
    # "cached" stays absent on genuine upstream responses.
    PRICES_CACHE["ts"] = fetched_at
    PRICES_CACHE["all"] = all_prices
    PRICES_CACHE["data"] = data
    return dict(data)


def get_market_data():
    live = load_results("live_*.json")  # D18
    scan = load_results("scan_*.json")  # D18
    mtf = load_results("mtf_*.json")  # D18
    
    print("[DEBUG] live:", len(live.get("results", [])))
    print("[DEBUG] mtf: ", len(mtf.get("results", [])))
    
    # ─── ادغام: live (4H) + MTF (همه TFها) ───
    results = []
    
    # ۱. از live (4H) — هر نماد یک کارت
    for r in live.get("results", []):
        r["tf"] = "4H"
        r["source"] = "live"
        results.append(r)
    
    # ۲. از MTF — فقط TFهایی که در live نیستند (15M, 30M, 1H, 1D)
    for r in mtf.get("results", []):
        if r.get("tf") == "4H":
            continue  # 4H از live آمده
        r["source"] = "mtf"
        
        # اضافه کردن info از live اگر موجود بود
        live_r = next((x for x in live.get("results", []) if x["symbol"] == r["symbol"]), None)
        if live_r:
            if "ema_mtf" not in r:
                r["ema_mtf"] = live_r.get("ema_mtf")
            if "vwap" not in r:
                r["vwap"] = live_r.get("vwap")
            if "multi" not in r:
                r["multi"] = live_r.get("multi")
            if "agent" not in r:
                r["agent"] = live_r.get("agent")
            if "events" not in r:
                r["events"] = live_r.get("events", [])
        
        results.append(r)
    
    print("[DEBUG] merged:", len(results))
    
    return {
        "scan_time": scan.get("generated"),
        "live_time": live.get("generated"),
        "mtf_time": mtf.get("generated"),
        "timers": live.get("timers", {}),
        "sessions": live.get("sessions", []),
        "alerts": live.get("alerts", {"in_zone": [], "near": []}),
        "results": results,
        "dominance": load_results("dominance_*.json"),  # D20: 5-min dominance file (frontend prefers this)
        "freshness": {  # D20 -> D26: ages from each file's own "generated" ts (hard-data rule 2), mtime fallback
            "dominance": _age_from_generated("dominance_*.json"),
            "live": _age_from_generated("live_*.json"),
            "mtf": _age_from_generated("mtf_*.json"),
            "hunter": _age_from_generated("hunter_*.json"),
            "fibswing": _age_from_generated("fibswing_*.json"),
        },
    }

# ============================================================
#  D20 Scheduler: dominance 5m / v2->v4 at 4H close / mtf at TF close
# ============================================================
SCHED_LOCK = threading.Lock()   # D20: single lock for ALL scan-family runs (no overlap)
SCAN_TIMEOUT = 1800             # D20: per-script budget (matches hunter timeout)
DOM_INTERVAL = 300              # D20: dominance refresh (seconds)
FIB_DELAY = 60                  # D20: settle seconds after 1h close before FIBSWING (mirror MTF_DELAY)
V4_DELAY = 120                  # D20: settle seconds after 4H close before pipeline
MTF_DELAY = 60                  # D20: settle seconds after any TF close before mtf
SCHED_TICK = 20                 # D20: worker poll interval


def _age_of(pattern):
    """D20: seconds since newest results file write (None = no file yet)."""
    files = sorted(glob.glob(os.path.join(RESULTS, pattern)))
    if not files:
        return None
    return int(time.time() - os.path.getmtime(files[-1]))


def _seed_mtime(pattern):
    """D20: newest file mtime (epoch) for restart-safe boundary seeding."""
    files = sorted(glob.glob(os.path.join(RESULTS, pattern)))
    return os.path.getmtime(files[-1]) if files else 0.0


def _sched_last_4h(now_epoch, delay=V4_DELAY):
    """D20: most recent SETTLED 4H boundary (UTC-aligned, epoch multiplicities of 14400)."""
    b = now_epoch - delay
    return b - (b % (4 * 3600))


def _sched_last_tf(now_epoch, delay=MTF_DELAY):
    """D20: most recent SETTLED TF boundary on the union grid (15/30/60.. min are 15m multiples)."""
    b = now_epoch - delay
    return b - (b % 900)


def _sched_last_1h(now_epoch, delay=FIB_DELAY):
    """D20: most recent SETTLED 1h boundary (UTC-aligned, epoch multiples of 3600)."""
    b = now_epoch - delay
    return b - (b % 3600)


def _sched_due(now_epoch, last_v4, last_mtf):
    """D20: due jobs ordered v4-chain first (fresh v2 base for mtf), then mtf."""
    due = []
    if _sched_last_4h(now_epoch) > last_v4:
        due.append("v4")
    if _sched_last_tf(now_epoch) > last_mtf:
        due.append("mtf")
    return due


def _dominance_body():
    """D20: CoinGecko dominance via dominance.py (single source) -> atomic results file with ts."""
    import dominance as _dom20
    res = _dom20.analyze_dominance()
    if res:
        res["generated"] = datetime.now().isoformat()
        fp = os.path.join(RESULTS, "dominance_%s.json" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        io_atomic.atomic_write_json(fp, res)
        print("[sched-job] dominance OK overall=%s" % res.get("overall"), flush=True)


def _run_pipeline_v2_v4(reason):
    """D20: manual/scheduled pipeline scanner_v2 (base refresh) -> scanner_v4 (live). Lock via caller."""
    print("[sched-job] pipeline v2->v4 (%s)..." % reason, flush=True)
    for script in ("scanner_v2.py", "scanner_v4.py"):
        subprocess.run([sys.executable, os.path.join(BASE, script)], cwd=BASE, timeout=SCAN_TIMEOUT)


def _run_mtf(reason="sched-TF"):
    """D20: mtf scanner run (per TF close). Lock via caller."""
    r = subprocess.run([sys.executable, os.path.join(BASE, "scanner_mtf.py")], cwd=BASE, timeout=SCAN_TIMEOUT)
    print("[sched-job] mtf rc=%s (%s)" % (r.returncode, reason), flush=True)


def _run_fibswing(reason="sched-interval"):
    """D20: FIBSWING shadow scanner (scanner_fibswing.py) -> results/fibswing_*.json. Lock via caller."""
    r = subprocess.run([sys.executable, os.path.join(BASE, "scanner_fibswing.py")], cwd=BASE, timeout=300)
    print("[sched-job] fibswing rc=%s (%s)" % (r.returncode, reason), flush=True)


D20_JOBS = {}

def _fill_d20_jobs():
    """D20: job name -> zero-arg callable (lock-free bodies; _sched_run holds SCHED_LOCK)."""
    D20_JOBS["v4"] = lambda: _run_pipeline_v2_v4("sched-4H")
    D20_JOBS["manual"] = lambda: _run_pipeline_v2_v4("manual")
    D20_JOBS["mtf"] = _run_mtf
    D20_JOBS["dominance"] = _dominance_body
    D20_JOBS["fibswing"] = _run_fibswing


def _sched_run(name):
    """D20: every job body executes under the single scheduler lock (serial, no overlap)."""
    fn = D20_JOBS.get(name)
    if fn is None:
        print("[sched-job] unknown job %r" % name, flush=True)
        return
    with SCHED_LOCK:
        try:
            fn()
        except Exception as e:
            print("[sched-job] %s error: %s" % (name, e), flush=True)


def _sched_loop(max_ticks=None):
    """D20: worker - dominance every DOM_INTERVAL (once at startup), v4/mtf per settled boundaries,
    fibswing at settled 1h closes. Boundary keys seed from file mtimes so a restart does not redo fresh work."""
    last_v4 = _seed_mtime("live_*.json")
    last_mtf = _seed_mtime("mtf_*.json")
    last_fib = _seed_mtime("fibswing_*.json")   # D20: restart-safe 1h-close alignment
    next_dom = 0.0
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        now = time.time()
        try:
            if now >= next_dom:
                _sched_run("dominance")
                next_dom = now + DOM_INTERVAL
            if _sched_last_1h(now) > last_fib:
                _sched_run("fibswing")
                last_fib = now                  # boundary consumed (no retry storms)
            for name in _sched_due(now, last_v4, last_mtf):
                _sched_run(name)
                if name == "v4":
                    last_v4 = now   # boundary consumed; avoids retry storms after failures
                elif name == "mtf":
                    last_mtf = now
        except Exception as e:
            print("[sched-job] error:", e, flush=True)
        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            break
        time.sleep(SCHED_TICK)


def start_sched_jobs():
    """D20: background scheduler thread."""
    t = threading.Thread(target=_sched_loop, name="sched-jobs", daemon=True)
    t.start()
    return t


@app.route("/")
def index(): return send_from_directory(FRONTEND, "index.html")

@app.route("/api/market")
def api_market(): return jsonify(get_market_data())


@app.route("/api/status")
def api_status():
    # Compatibility alias: no /api/status existed; expose concise service health + market freshness
    data = get_market_data()
    return jsonify({
        "ok": True,
        "generated": data.get("generated"),
        "freshness": data.get("freshness", {}),
        "results_count": (data.get("live") or {}).get("count", 0),
        "hunter_age_seconds": (load_results("hunter_*.json") or {}).get("age_seconds"),
    })


@app.route("/api/live")
def api_live():
    # Compatibility alias for live scan payload
    return jsonify(load_results("live_*.json"))


@app.route("/api/dominance")
def api_dominance():
    # Compatibility alias; dominance is nested in /api/market too
    live = load_results("dominance_*.json")
    return jsonify(live if live is not None else {})

@app.route("/api/debug")
def api_debug():
    lf = latest_file("live_*.json")  # D18: keep names consistent
    return jsonify({"cwd": os.getcwd(), "results": RESULTS,
                    "live_file": os.path.basename(lf) if lf else None,
                    "live_count": load_results("live_*.json").get("count", 0)})

@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        body = request.get_json() or {}
        current = load_settings()
        tok = body.get("telegram_token", "")
        if (not tok) or ("****" in str(tok)):
            body["telegram_token"] = current.get("telegram_token", "")
        save_json(SETTINGS, body)
        return jsonify({"ok": True})
    s = load_settings()
    s["telegram_token"] = mask_token(s.get("telegram_token", ""))
    return jsonify(s)

@app.route("/api/scan", methods=["POST"])
def api_scan():
    threading.Thread(target=_sched_run, args=("manual",), daemon=True).start()  # D20: serialized pipeline
    return jsonify({"ok": True})

@app.route("/api/prices")  # D26: rule 3 proxy (single upstream GET, 5s cache, fetched_at in response)
def api_prices():
    return jsonify(_prices_impl(request.args.get("symbols") or ""))


@app.route("/decision")  # D26: decision screen
def decision_page():
    return send_from_directory(FRONTEND, "decision.html")


@app.route("/d26.js")  # D26F1: decision logic route (relative src 404d under /decision -> blank page)
def d26_js():
    # UTF-8 pinned: decision matrix glyphs (arrows) must not mojibake under charset-less transports
    return send_from_directory(FRONTEND, "d26.js", mimetype="application/javascript; charset=utf-8")


@app.route("/api/health")
def health(): return jsonify({"ok": True})


@app.route("/api/send-telegram", methods=["POST"])
def api_send_telegram():
    data = request.get_json() or {}
    symbol = data.get("symbol")
    settings = load_settings()
    token = settings.get("telegram_token", "")
    chat_id = settings.get("telegram_chat", "")
    if not token or not chat_id:
        return jsonify({"ok": False, "error": "token or chat_id not set"})
    live = load_results("live_*.json")  # D18
    results = live.get("results", [])
    r = next((x for x in results if x["symbol"] == symbol), None)
    if not r:
        return jsonify({"ok": False, "error": "symbol not found"})
    best_sig = None
    for s in r.get("signals", []):
        if s["zone_status"] == "IN_ZONE":
            best_sig = s
            break
    if best_sig is None:
        for s in r.get("signals", []):
            if s["zone_status"] == "NEAR":
                best_sig = s
                break
    if not best_sig:
        return jsonify({"ok": False, "error": "no active signal"})
    msg = format_signal(r, best_sig)
    result = send_telegram(token, chat_id, msg)
    return jsonify(result)

@app.route("/api/test-telegram", methods=["POST"])
def api_test_telegram():
    settings = load_settings()
    token = settings.get("telegram_token", "")
    chat_id = settings.get("telegram_chat", "")
    if not token or not chat_id:
        return jsonify({"ok": False, "error": "token or chat_id not set"})
    result = send_telegram(token, chat_id, "ASTRA SCANNER test")
    return jsonify(result)


@app.route("/api/verify")
def api_verify():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from verify import verify_all_5star, format_verification_report
    live = load_results("live_*.json")  # D18
    verifications = verify_all_5star(live)
    return jsonify({
        "ok": True,
        "count": len(verifications),
        "verifications": verifications,
    })

@app.route("/api/verify-report")
def api_verify_report():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from verify import verify_all_5star, format_verification_report
    live = load_results("live_*.json")  # D18
    verifications = verify_all_5star(live)
    report = format_verification_report(verifications)
    return jsonify({"ok": True, "report": report})


@app.route("/api/events/<symbol>")
def api_events(symbol):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from news import get_news_for_symbol
    return jsonify(get_news_for_symbol(symbol.upper()))

@app.route("/api/events-all")
def api_events_all():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from news import get_news_for_symbol
    live = load_results("live_*.json")  # D18
    result = {}
    for r in live.get("results", []):
        sym = r["symbol"]
        ev = get_news_for_symbol(sym)
        if ev.get("events"):
            result[sym] = ev["events"]
    return jsonify({"ok": True, "events": result})


@app.route("/api/symbol/<symbol>")
def api_symbol_detail(symbol):
    """جزئیات کامل یک نماد از DB"""
    import sqlite3
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = symbol + "USDT"
    
    db = os.path.join(DATA, "astra_history.db")
    if not os.path.exists(db):
        return jsonify({"ok": False, "error": "DB not found"})
    
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # همه سیگنال‌های این نماد (مرتب‌شده بر اساس زمان نزولی)
    c.execute("""
        SELECT * FROM signals WHERE symbol = ? AND result != 'DUPLICATE'
        ORDER BY ts DESC LIMIT 100
    """, (symbol,))
    rows = [dict(r) for r in c.fetchall()]
    
    # آمار
    total = len(rows)
    open_count = sum(1 for r in rows if r["result"] == "OPEN")
    tp_count = sum(1 for r in rows if r["result"] == "TP")
    sl_count = sum(1 for r in rows if r["result"] == "SL")
    time_count = sum(1 for r in rows if r["result"] == "TIME")
    closed = total - open_count
    wr = (tp_count / closed * 100) if closed > 0 else 0
    
    # PnL تقریبی
    pnl_r = 0
    for r in rows:
        if r["result"] == "TP":
            pnl_r += r.get("rr", 1.5) or 1.5
        elif r["result"] == "SL":
            pnl_r -= 1.0
    
    # آخرین سیگنال
    last = rows[0] if rows else None
    
    # آخرین live file (برای داده‌های زنده)
    live = load_results("live_*.json")  # D18
    live_row = None
    for x in live.get("results", []):
        if x["symbol"] == symbol:
            live_row = x
            break
    
    conn.close()
    
    from performance import compute_performance ; perf = compute_performance(rows)
    
    return jsonify({
        "ok": True,
        "symbol": symbol,
        "stats": {
            "total": total,
            "open": open_count,
            "tp": tp_count,
            "sl": sl_count,
            "time": time_count,
            "closed": closed,
            "win_rate": round(wr, 1),
            "pnl_r": round(perf["total_r"], 2) if perf["trades"] > 0 else round(pnl_r, 2),
            "pnl_r_source": "realized" if perf["trades"] > 0 else "estimated",
            "perf": perf,
        },
        "signals": rows,
        "last": last,
        "live": live_row,
    })

@app.route("/api/symbol/<symbol>/history")
def api_symbol_history(symbol):
    """تاریخچه PnL نماد"""
    import sqlite3
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = symbol + "USDT"
    
    db = os.path.join(DATA, "astra_history.db")
    if not os.path.exists(db):
        return jsonify({"ok": False, "error": "DB not found"})
    
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("""
        SELECT ts, side, result, rr, score, stars, price, sl, tp, 
               entry_lo, entry_hi, closed_ts, closed_price
        FROM signals WHERE symbol = ? AND result != 'DUPLICATE'
        ORDER BY ts ASC LIMIT 500
    """, (symbol,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    
    return jsonify({"ok": True, "symbol": symbol, "history": rows})


@app.route("/api/mtf")
def api_mtf():
    import glob
    data = load_results("mtf_*.json")  # D18: corrupt newest -> previous valid file
    if data is None:
        return jsonify({"ok": False, "error": "no mtf data"})
    return jsonify({
        "ok": True,
        "generated": data.get("generated"),
        "count": data.get("count", 0),
        "results": data.get("results", []),
    })

@app.route("/api/mtf-in-zone")
def api_mtf_in_zone():
    import glob
    data = load_results("mtf_*.json")  # D18: corrupt newest -> previous valid file
    if data is None:
        return jsonify({"ok": False, "error": "no mtf data"})
    # فیلتر IN_ZONE
    in_zone = []
    for r in data.get("results", []):
        for s in r.get("signals", []):
            if s.get("zone_status") == "IN_ZONE":
                in_zone.append({
                    "symbol": r["symbol"],
                    "tf": r["tf"],
                    "side": s["side"],
                    "entry_lo": s.get("entry_zone_lo"),   # D22-HARD rule 1: fail-safe, None -> frontend gap
                    "entry_hi": s.get("entry_zone_hi"),
                    "sl": s.get("sl"),
                    "tp": s.get("tp"),
                    "rr": s.get("rr"),
                    "price": r.get("price"),
                    "adx": r.get("adx"),
                    "regime": r.get("regime"),
                    "score": r.get("score"),
                    "risk_pct": r.get("risk_pct"),
                    "volume_ok": r.get("volume_ok"),  # PH33C fail-closed passthrough (missing/null => frontend hides button)
                })
    # D22-HARD (rule 2): source/age from the file's own generated ts
    return jsonify({
        "ok": True,
        "generated": data.get("generated"),
        "age_seconds": _age_from_generated("mtf_*.json"),
        "count": len(in_zone),
        "in_zone": in_zone,
    })


@app.route("/api/hunter")
def api_hunter():
    data = load_results("hunter_*.json")  # D18: corrupt newest -> previous valid file
    if data is None:
        return jsonify({"ok": False, "error": "no hunter data"})
    # D22-HARD (rule 2): add age in seconds from this file's own generated ts (payload intact)
    out = dict(data)
    out["age_seconds"] = _age_from_generated("hunter_*.json")
    return jsonify(out)


@app.route("/api/fibswing")
def api_fibswing():
    """FIBSWING shadow signals (weekly-swing fib module, fs_core port) — snapshot payload + age."""
    data = load_results("fibswing_*.json")  # D18: corrupt newest -> previous valid file
    if data is None:
        return jsonify({"ok": False, "error": "no fibswing data"})
    out = dict(data)
    out["ok"] = True
    out["age_seconds"] = _age_from_generated("fibswing_*.json")
    return jsonify(out)


@app.route("/api/position", methods=["POST"])
def api_position():
    data = request.get_json() or {}
    symbol = data.get("symbol", "")
    try:
        balance = float(data.get("balance"))
        entry = float(data.get("entry"))
        sl = float(data.get("sl"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "balance, entry, sl required (numbers)"}), 400
    try:
        tp = float(data.get("tp"))
    except (TypeError, ValueError):
        tp = None
    try:
        confidence = float(data.get("confidence", 60))
    except (TypeError, ValueError):
        confidence = 60.0
    side = str(data.get("side", "")).strip().upper()
    if balance <= 0 or entry <= 0 or sl <= 0:
        return jsonify({"ok": False, "error": "values must be positive"}), 400
    if entry == sl:
        return jsonify({"ok": False, "error": "entry equals sl"}), 400

    warning = None
    if side == "BUY":
        if sl >= entry:
            warning = "SL برای BUY باید پایین‌تر از ورود باشد"
        elif tp is not None and tp <= entry:
            warning = "TP برای BUY باید بالاتر از ورود باشد"
    elif side == "SELL":
        if sl <= entry:
            warning = "SL برای SELL باید بالاتر از ورود باشد"
        elif tp is not None and tp >= entry:
            warning = "TP برای SELL باید پایین‌تر از ورود باشد"

    risk_pct = suggest_risk_pct(confidence)
    sizing = calculate_position_size(balance, risk_pct, entry, sl)
    rr = calculate_rr(entry, sl, tp) if (tp is not None and tp > 0) else None
    return jsonify({
        "ok": True,
        "symbol": symbol,
        "side": side or None,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "confidence": confidence,
        "balance": balance,
        "risk_pct": risk_pct,
        "risk_usdt": round(sizing["risk_usdt"], 2),
        "size_usdt": round(sizing["size_usdt"], 2),
        "size_units": round(sizing["size_units"], 8),
        "rr": round(rr, 2) if rr is not None else None,
        "warning": warning,
    })


# ═══════════════════════════════════════════════════════════════
#  /api/chart/<symbol>/<interval>
#  دریافت کندل‌های واقعی از Binance + خطوط روند
# ═══════════════════════════════════════════════════════════════
BINANCE_HOSTS = [
    "https://data-api.binance.vision",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api-gcp.binance.com",
    "https://api.binance.com",
]

def _binance_json(path, timeout=15):
    """GET with host rotation — api.binance.com may return HTTP 451 (geo)."""
    import urllib.request
    last = None
    for host in BINANCE_HOSTS:
        try:
            req = urllib.request.Request(host + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            continue
    raise RuntimeError(f"all binance hosts failed: {last}")


@app.route("/api/chart/<symbol>/<interval>")
def api_chart(symbol, interval):
    """
    interval: 15m, 30m, 1h, 4h, 1d
    """
    try:
        # ۱. دریافت کندل‌ها از Binance (واقعی، آنلاین)
        klines = _binance_json(
            f"/api/v3/klines?symbol={symbol}&interval={interval}&limit=300"
        )
        
        if not klines or len(klines) < 30:
            return jsonify({"error": "not enough data", "symbol": symbol, "interval": interval}), 400
        
        # ۲. تبدیل به فرمت کندل
        candles = [
            {
                "time": int(k[0]) // 1000,   # timestamp به ثانیه
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            }
            for k in klines
        ]
        
        # ۳. محاسبه trend lines
        trend_data = None
        try:
            from trend_lines import analyze_trend_lines
            trend_data = analyze_trend_lines(candles)
        except Exception as e:
            print(f"[chart] trend_lines error: {e}")
        
        # ۴. خروجی
        return jsonify({
            "symbol": symbol,
            "interval": interval,
            "count": len(candles),
            "candles": candles,
            "trend_lines": trend_data,
            "ts": datetime.now().isoformat(),
        })
    
    except Exception as e:
        print(f"[chart] error: {e}")
        return jsonify({"error": str(e), "symbol": symbol, "interval": interval}), 500

# A3: Alert DSL Backtest API
DSL_TEMPLATES = {
    "rsi_oversold": 'RSI(14) < 30 AND VOLUME_RATIO > 2 AND REGIME != "RANGING"',
    "breakout": 'CLOSE > HIGH_20 AND VOLUME_RATIO > 1.5 AND ADX > 25',
    "mean_reversion": 'RSI(14) > 70 AND CLOSE < VWAP AND VOLUME_RATIO < 0.8',
    "trend_follow": 'EMA_9 > EMA_21 AND CLOSE > EMA_9 AND ADX > 20',
    "custom": ''
}

def _load_historical_candles(symbol, tf, limit=2000):
    """Load historical candles from Binance REST API (public, host rotation — 451-safe)."""
    interval_map = {"5M": "5m", "15M": "15m", "30M": "30m", "1H": "1h", "4H": "4h", "1D": "1d"}
    interval = interval_map.get(tf, "1h")
    try:
        data = _binance_json(f"/api/v3/klines?symbol={symbol}&interval={interval}&limit={min(int(limit), 1000)}")
        candles = []
        for k in data:
            candles.append({
                "time": k[0], "open": float(k[1]), "high": float(k[2]),
                "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])
            })
        return candles
    except Exception as e:
        print(f"[_load_historical_candles] {symbol} {tf}: {e}")
        return []

def _compute_indicators(candles):
    """Compute basic indicators for DSL evaluation."""
    import numpy as np
    n = len(candles)
    if n < 50:
        return {}
    closes = np.array([c["close"] for c in candles])
    highs = np.array([c["high"] for c in candles])
    lows = np.array([c["low"] for c in candles])
    volumes = np.array([c["volume"] for c in candles])
    
    def sma(arr, period):
        return np.convolve(arr, np.ones(period)/period, mode='valid')
    
    def rsi(arr, period=14):
        deltas = np.diff(arr)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.convolve(gains, np.ones(14)/14, mode='valid')
        avg_loss = np.convolve(losses, np.ones(14)/14, mode='valid')
        rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss!=0)
        rsi_vals = 100 - (100 / (1 + rs))
        return np.pad(rsi_vals, (len(arr)-len(rsi_vals), 0), 'edge')
    
    def ema(arr, period):
        alpha = 2 / (period + 1)
        ema_vals = np.zeros_like(arr)
        ema_vals[0] = arr[0]
        for i in range(1, len(arr)):
            ema_vals[i] = alpha * arr[i] + (1 - alpha) * ema_vals[i-1]
        return ema_vals
    
    def vwap(candles_arr):
        typical = (highs + lows + closes) / 3
        cum_vol = np.cumsum(volumes)
        cum_pv = np.cumsum(typical * volumes)
        return np.divide(cum_pv, cum_vol, out=np.zeros_like(cum_pv), where=cum_vol!=0)
    
    def adx(high_arr, low_arr, close_arr, period=14):
        plus_dm = np.diff(high_arr)
        minus_dm = np.diff(low_arr)
        plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0)
        minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0)
        tr1 = np.abs(high_arr[1:] - low_arr[1:])
        tr2 = np.abs(high_arr[1:] - close_arr[:-1])
        tr3 = np.abs(low_arr[1:] - close_arr[:-1])
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        atr = np.convolve(tr, np.ones(14)/14, mode='valid')
        plus_di = 100 * np.convolve(plus_dm, np.ones(14)/14, mode='valid') / atr
        minus_di = 100 * np.convolve(minus_dm, np.ones(14)/14, mode='valid') / atr
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        return np.pad(np.convolve(dx, np.ones(14)/14, mode='valid'), (len(close_arr)-len(dx), 0), 'edge')
    
    volume_sma_20 = np.pad(sma(volumes, 20), (len(volumes)-len(sma(volumes, 20)), 0), 'edge')
    volume_ratio = np.divide(volumes, volume_sma_20, out=np.ones_like(volumes), where=volume_sma_20!=0)
    
    high_20 = np.zeros_like(highs)
    for i in range(len(highs)):
        start = max(0, i-19)
        high_20[i] = np.max(highs[start:i+1])
    
    return {
        "close": closes, "high": highs, "low": lows, "volume": volumes,
        "rsi_14": rsi(closes),
        "ema_9": ema(closes, 9),
        "ema_21": ema(closes, 21),
        "sma_20": np.pad(sma(closes, 20), (len(closes)-len(sma(closes, 20)), 0), 'edge'),
        "high_20": high_20,
        "vwap": vwap(candles),
        "adx": adx(highs, lows, closes),
        "volume": volumes,
        "volume_ratio": volume_ratio,
    }

def _eval_dsl_condition(cond_str, indicators, idx):
    """Evaluate a simple DSL condition at index idx."""
    if idx < 0 or idx >= len(indicators.get("close", [])):
        return False
    try:
        # Replace indicator names with values at idx
        expr = cond_str
        replacements = {
            "RSI(14)": f"{indicators['rsi_14'][idx]:.2f}",
            "CLOSE": f"{indicators['close'][idx]:.8f}",
            "HIGH_20": f"{indicators['high_20'][idx]:.8f}",
            "VOLUME_RATIO": f"{indicators['volume_ratio'][idx]:.4f}",
            "ADX": f"{indicators['adx'][idx]:.2f}",
            "VWAP": f"{indicators['vwap'][idx]:.8f}",
            "EMA_9": f"{indicators['ema_9'][idx]:.8f}",
            "EMA_21": f"{indicators['ema_21'][idx]:.8f}",
            "REGIME": '"TRENDING"',  # simplified
        }
        for k, v in replacements.items():
            expr = expr.replace(k, v)
        expr = expr.replace("AND", "and").replace("OR", "or").replace("NOT", "not")
        expr = expr.replace(">", ">").replace("<", "<").replace(">=", ">=").replace("<=", "<=")
        expr = expr.replace("==", "==").replace("!=", "!=")
        return eval(expr, {"__builtins__": {}}, {})
    except Exception as e:
        print(f"[_eval_dsl_condition] error: {e}")
        return False

def _run_dsl_backtest(symbol, tf, dsl_expr, fee=0.0015, window=2000, step=1):
    """Run backtest for a DSL expression on symbol/tf."""
    import numpy as np  # fix: 'name np is not defined' (np was only imported inside _compute_indicators)
    candles = _load_historical_candles(symbol, tf)
    if len(candles) < 100:
        return {"error": f"Insufficient candles: {len(candles)}"}
    
    indicators = _compute_indicators(candles)
    n = len(indicators["close"])
    if n < 50:
        return {"error": "Insufficient indicator data"}
    
    trades = []
    in_position = False
    entry_price = 0
    entry_idx = 0
    
    for i in range(50, n-1):  # leave room for indicators
        signal = _eval_dsl_condition(dsl_expr, indicators, i)
        price = indicators["close"][i]
        
        if signal and not in_position:
            # Enter long
            in_position = True
            entry_price = price
            entry_idx = i
        elif not signal and in_position:
            # Exit
            exit_price = indicators["close"][i+1] if i+1 < len(indicators["close"]) else price
            pnl_pct = (exit_price - entry_price) / entry_price - fee  # fee
            trades.append({
                "entry_idx": entry_idx, "exit_idx": i,
                "entry_price": entry_price, "exit_price": exit_price,
                "pnl_pct": pnl_pct, "pnl_r": pnl_pct / 0.02  # rough R
            })
            in_position = False
    
    # Close any open position at end
    if in_position:
        exit_price = indicators["close"][-1]
        pnl_pct = (exit_price - entry_price) / entry_price - fee
        trades.append({
            "entry_idx": entry_idx, "exit_idx": n-1,
            "entry_price": entry_price, "exit_price": exit_price,
            "pnl_pct": pnl_pct, "pnl_r": pnl_pct / 0.02
        })
    
    # Compute metrics
    if not trades:
        return {"trades": 0, "hit_rate": 0, "total_r": 0, "max_dd": 0, "equity_curve": [1.0]}
    
    equity = 1.0
    equity_curve = [1.0]
    wins = 0
    peak = 1.0
    max_dd = 0
    
    for t in trades:
        equity *= (1 + t["pnl_pct"])
        equity_curve.append(equity)
        if t["pnl_pct"] > 0:
            wins += 1
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)
    
    return {
        "trades": len(trades),
        "hit_rate": round(wins / len(trades) * 100, 1),
        "total_r": round(sum(t["pnl_r"] for t in trades), 2),
        "max_dd": round(max_dd * 100, 1),
        "equity_curve": [round(e, 4) for e in equity_curve],
        "avg_hold": round(np.mean([t["exit_idx"] - t["entry_idx"] for t in trades]), 1) if trades else 0,
    }

@app.route("/api/alert/dsl/backtest", methods=["POST"])
def api_alert_dsl_backtest():
    """Run DSL backtest on symbol/timeframe."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"ok": False, "error": "No JSON payload"})
        
        symbol = data.get("symbol", "").upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        
        tf = data.get("tf", "1H")
        dsl_expr = data.get("dsl", "").strip()
        try:
            fee = float(data.get("fee", 0.0015))
        except (TypeError, ValueError):
            fee = 0.0015
        if not (0.0 <= fee <= 0.01):
            fee = 0.0015
        
        if not dsl_expr:
            return jsonify({"ok": False, "error": "DSL expression required"})
        
        # Validate symbol exists in our pool
        import symbols_pool
        pool = symbols_pool.get_pool_symbols()
        if symbol not in pool:
            return jsonify({"ok": False, "error": f"Symbol {symbol} not in pool"})
        
        result = _run_dsl_backtest(symbol, tf, dsl_expr, fee=fee)
        
        if "error" in result:
            return jsonify({"ok": False, "error": result["error"]})
        
        return jsonify({"ok": True, "symbol": symbol, "tf": tf, "dsl": dsl_expr, **result})
        
    except Exception as e:
        import traceback
        print(f"[api_alert_dsl_backtest] error: {traceback.format_exc()}")
        return jsonify({"ok": False, "error": str(e)[:200]})

@app.route("/api/alert/dsl/templates")
def api_alert_dsl_templates():
    """Get DSL templates."""
    return jsonify({"ok": True, "templates": DSL_TEMPLATES})

# ZN1: Visual Zone Recognition + Liquidity (on-demand fetch, 60s cache, NO background jobs)
ZONES_CACHE = {}

@app.route("/api/zones/<symbol>")
def api_zones(symbol):
    now = time.time()
    cached = ZONES_CACHE.get(symbol)
    if cached and (now - cached[0]) < 60:
        return jsonify(cached[1])
    payload = {"symbol": symbol, "zones": [], "liquidity": None, "ts": datetime.now().isoformat()}
    try:
        h1 = zones.klines_to_candles(zones.fetch_klines(symbol, "1h", 400) or [])
        d1 = zones.klines_to_candles(zones.fetch_klines(symbol, "1d", 12) or [])
        w1 = zones.klines_to_candles(zones.fetch_klines(symbol, "1w", 8) or [])
        h4 = zones.klines_to_candles(zones.fetch_klines(symbol, "4h", 90) or [])
        payload["zones"] = zones.detect_1h_zones(h1) if h1 else []
        payload["liquidity"] = zones.detect_liquidity_levels({"1D": d1, "1W": w1, "4H": h4})
        payload["last_close"] = (h1[-1]["close"] if h1 else None)
        print("[zones] %s: %d zones" % (symbol, len(payload["zones"])), flush=True)
    except Exception as e:
        print(f"[zones] error: {e}")
        payload["error"] = str(e)
        payload["ts"] = datetime.now().isoformat()
    ZONES_CACHE[symbol] = (now, payload)
    return jsonify(payload)

# ==================== Background Hunter Job ====================
HUNTER_JOB_INTERVAL = 300  # seconds (5 min)

def _hunter_job_loop():
    script = os.path.join(BASE, "trend_hunter.py")
    while True:
        t0 = time.time()
        try:
            print("[hunter-job] running trend_hunter.py ...", flush=True)
            with SCHED_LOCK:  # D20: hunter serialized with scan family
                r = subprocess.run([sys.executable, script], cwd=BASE, timeout=1800)
            print("[hunter-job] done rc=%s in %.1fs" % (r.returncode, time.time() - t0), flush=True)
        except Exception as e:
            print("[hunter-job] error:", e, flush=True)
        time.sleep(HUNTER_JOB_INTERVAL)

def start_hunter_job():
    t = threading.Thread(target=_hunter_job_loop, name="hunter-job", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    print("=" * 70)
    print("  ASTRA SCANNER DASHBOARD v2.1")
    print("=" * 70)
    print("  CWD    :", os.getcwd())
    print("  URL    : http://127.0.0.1:8080")
    print("=" * 70)
    print("[STARTUP TEST]")
    d = get_market_data()
    print("[DEBUG] results:", len(d["results"]))
    start_hunter_job()
    print("[hunter-job] started (every %ds)" % HUNTER_JOB_INTERVAL)
    _fill_d20_jobs()  # D20
    start_sched_jobs()  # D20
    print("[sched-jobs] started (dominance 5m / v2->v4 at 4H close / mtf at TF close, one lock)")
    app.run(host="127.0.0.1", port=8080, debug=False)








