# -*- coding: utf-8 -*-
# automation.py — Cron + SQLite + Tracking + Alert
import os, sys, json, time, sqlite3, subprocess, glob, io_atomic
from datetime import datetime, timezone
import urllib.request, urllib.parse
from telegram import check_and_alert_hunter

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
RESULTS = os.path.join(BASE, "results")
DB = os.path.join(DATA, "astra_history.db")
SETTINGS = os.path.join(DATA, "settings.json")
SENT_FILE = os.path.join(DATA, "sent_signals.json")

os.makedirs(DATA, exist_ok=True)

# ==================== HTTP ====================
def get_json(path, timeout=15):
    eps = [
        "https://data-api.binance.vision",
        "https://api.binance.com",
        "https://api1.binance.com",
    ]
    for ep in eps:
        try:
            req = urllib.request.Request(ep + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except: continue
    return None

def get_current_price(symbol):
    d = get_json(f"/api/v3/ticker/price?symbol={symbol}")
    return float(d["price"]) if d and "price" in d else None

# ==================== DB ====================
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, symbol TEXT, side TEXT,
            score REAL, stars INTEGER, regime TEXT, adx REAL,
            price REAL, entry_lo REAL, entry_hi REAL,
            sl REAL, tp REAL, rr REAL, zone_status TEXT,
            reasons TEXT,
            result TEXT DEFAULT 'OPEN',
            closed_ts TEXT, closed_price REAL,
            UNIQUE(ts, symbol, side)
        )
    """)
    # migration: older DBs may lack these columns (A3)
    have = {r[1] for r in c.execute("PRAGMA table_info(signals)").fetchall()}
    for col, typ in (("reasons", "TEXT"), ("dup_of", "INTEGER"), ("orig_result", "TEXT")):
        if col not in have:
            c.execute("ALTER TABLE signals ADD COLUMN %s %s" % (col, typ))
    c.execute("CREATE INDEX IF NOT EXISTS idx_symbol ON signals(symbol)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_result ON signals(result)")
    conn.commit()
    return conn

def save_signals(live_data):
    conn = init_db()
    c = conn.cursor()
    ts = live_data.get("generated", "")
    count = 0
    for r in live_data.get("results", []):
        for s in r.get("signals", []):
            if s.get("zone_status") not in ("IN_ZONE", "NEAR"):
                continue
            try:
                # A3: same symbol+side+zone still OPEN -> do not create another row
                c.execute("SELECT 1 FROM signals WHERE result='OPEN' AND symbol=? AND side=? "
                          "AND entry_lo=? AND entry_hi=? LIMIT 1",
                          (r["symbol"], s["side"], s.get("entry_zone_lo", 0), s.get("entry_zone_hi", 0)))
                if c.fetchone():
                    continue
                c.execute("""
                    INSERT OR IGNORE INTO signals
                    (ts, symbol, side, score, stars, regime, adx, price,
                     entry_lo, entry_hi, sl, tp, rr, zone_status, reasons)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (ts, r["symbol"], s["side"], r.get("score", 0),
                      r.get("stars", 0), r.get("regime", ""), r.get("adx", 0),
                      r.get("price", 0), s.get("entry_zone_lo", 0),
                      s.get("entry_zone_hi", 0), s.get("sl", 0),
                      s.get("tp", 0), s.get("rr", 0), s.get("zone_status", ""), json.dumps(s.get("reasons", []), ensure_ascii=False)))
                if c.rowcount > 0:
                    count += 1
            except Exception as e:
                print(f"  DB error: {e}")
    conn.commit()
    conn.close()
    return count

def mark_duplicate_signals(apply=False):
    """A3: flag repeated rows of the same setup (symbol+side+zone) created while the
    earlier one was still open. Never deletes. Default is dry-run.
    Returns list of (id, symbol, side, ts, kept_id)."""
    conn = init_db()
    c = conn.cursor()
    c.execute("SELECT id, ts, symbol, side, entry_lo, entry_hi, result, closed_ts FROM signals "
              "WHERE result != 'DUPLICATE' ORDER BY id")
    kept = {}   # key -> (id, closed_ts)
    found = []
    for (sid, ts, symbol, side, lo, hi, result, closed_ts) in c.fetchall():
        key = (symbol, side, lo, hi)
        k = kept.get(key)
        if k is not None and (k[1] is None or (ts or "") <= k[1]):
            found.append((sid, symbol, side, ts, k[0], result))
        else:
            kept[key] = (sid, closed_ts)
    if apply:
        for (sid, symbol, side, ts, kid, old) in found:
            c.execute("UPDATE signals SET orig_result=?, dup_of=?, result='DUPLICATE' WHERE id=?",
                      (old, kid, sid))
        conn.commit()
    conn.close()
    return [(f[0], f[1], f[2], f[3], f[4]) for f in found]

def track_open_signals():
    """رصد سیگنال‌های باز — چک TP/SL"""
    conn = init_db()
    c = conn.cursor()
    c.execute("SELECT id, symbol, side, entry_lo, entry_hi, sl, tp, price FROM signals WHERE result='OPEN'")
    open_signals = c.fetchall()
    
    closed = 0
    for (sid, symbol, side, entry_lo, entry_hi, sl, tp, entry_price) in open_signals:
        current = get_current_price(symbol)
        if current is None: continue
        
        result = None
        if side == "BUY":
            if current <= sl: result = "SL"
            elif current >= tp: result = "TP"
        else:  # SELL
            if current >= sl: result = "SL"
            elif current <= tp: result = "TP"
        
        if result:
            c.execute("""
                UPDATE signals SET result=?, closed_ts=?, closed_price=?
                WHERE id=?
            """, (result, datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"), current, sid))
            closed += 1
            print(f"  📊 {symbol} {side}: {result} at {current}")
            
            # Alert
            settings = load_settings()
            if settings.get("telegram_on"):
                emoji = "✅" if result == "TP" else "🛑"
                msg = f"{emoji} <b>{symbol} {side}</b>\nنتیجه: <b>{result}</b>\nقیمت خروج: <code>{current}</code>\nورود: <code>{entry_price}</code>\n\n⚡ ASTRA SCANNER"
                send_tg(settings.get("telegram_token",""), settings.get("telegram_chat",""), msg)
    
    conn.commit()
    conn.close()
    return closed

# ==================== Alert ====================
def load_settings():
    if os.path.exists(SETTINGS):
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    return {}

def send_tg(token, chat_id, msg):
    if not token or not chat_id: return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except: return False

def send_5star_alerts(live_data):
    settings = load_settings()
    token = settings.get("telegram_token", "")
    chat_id = settings.get("telegram_chat", "")
    if not token or not chat_id: return 0
    
    sent = set()
    if os.path.exists(SENT_FILE):
        try:
            with open(SENT_FILE) as f: sent = set(json.load(f))
        except: pass
    
    count = 0
    for r in live_data.get("results", []):
        if r.get("stars", 0) < 5: continue
        for s in r.get("signals", []):
            if s.get("zone_status") != "IN_ZONE": continue
            key = f"{live_data.get('generated','')}_{r['symbol']}_{s['side']}"
            if key in sent: continue
            
            side_icon = "🟢" if s["side"] == "BUY" else "🔴"
            msg = f"""<b>{side_icon} {s['side']} {r['symbol']}</b>
<b>🎯 IN ZONE ⭐⭐⭐⭐⭐</b>

💰 قیمت: <code>{r['price']}</code>
📍 ورود: <code>{s['entry_zone_lo']} - {s['entry_zone_hi']}</code>
🛑 SL: <code>{s['sl']}</code>
🎯 TP: <code>{s['tp']}</code>
📊 R:R: <b>{s['rr']}</b>

📈 ADX: {r['adx']} [{r['regime']}]
🏆 امتیاز: <b>{r['score']}</b>

⚡ ASTRA SCANNER · DeepSeek Ali.Astara13"""
            if send_tg(token, chat_id, msg):
                sent.add(key)
                count += 1
                print(f"  ✅ Alert: {r['symbol']} {s['side']}")
    
    with open(SENT_FILE, "w") as f:
        json.dump(list(sent)[-500:], f)
    return count

# ==================== Report ====================
def send_daily_report():
    settings = load_settings()
    token = settings.get("telegram_token", "")
    chat_id = settings.get("telegram_chat", "")
    if not token or not chat_id: return False
    
    conn = init_db()
    c = conn.cursor()
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    c.execute("SELECT COUNT(*) FROM signals WHERE ts LIKE ?", (f"{today}%",))
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*), SUM(CASE WHEN result='TP' THEN 1 ELSE 0 END), SUM(CASE WHEN result='SL' THEN 1 ELSE 0 END) FROM signals WHERE result NOT IN ('OPEN','DUPLICATE')")
    row = c.fetchone()
    closed, tp_count, sl_count = row[0] or 0, row[1] or 0, row[2] or 0
    wr = (tp_count / closed * 100) if closed > 0 else 0
    conn.close()
    
    msg = f"""<b>📊 گزارش روزانه ASTRA</b>

📅 تاریخ: {datetime.now().strftime('%Y-%m-%d')}

📈 سیگنال‌های امروز: <b>{total}</b>
📊 کل بسته‌شده: <b>{closed}</b>
✅ TP: <b>{tp_count}</b>
🛑 SL: <b>{sl_count}</b>
🎯 نرخ برد: <b>{wr:.1f}%</b>

⚡ ASTRA SCANNER · DeepSeek Ali.Astara13"""
    return send_tg(token, chat_id, msg)

# ==================== Cycle ====================
def run_cycle():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Cycle started...")
    
    # ۱. رصد سیگنال‌های باز (اول از همه)
    closed = track_open_signals()
    if closed:
        print(f"  📊 Closed {closed} signals")
    
    # ۲. اسکن
    subprocess.run([sys.executable, os.path.join(BASE, "scanner_v2.py")], cwd=BASE)
    subprocess.run([sys.executable, os.path.join(BASE, "scanner_v4.py")], cwd=BASE)
    try:
        print("  📊 Running scanner_mtf...")
        subprocess.run([sys.executable, os.path.join(BASE, "scanner_mtf.py")], cwd=BASE)
    except Exception as e:
        print(f"  ❌ scanner_mtf error: {e}")
    try:
        print("  🏹 Running trend_hunter...")
        subprocess.run([sys.executable, os.path.join(BASE, "trend_hunter.py")], cwd=BASE)
    except Exception as e:
        print(f"  ❌ trend_hunter error: {e}")
    
    # ۳. ذخیره
    files = sorted(glob.glob(os.path.join(RESULTS, "live_*.json")))
    path, live = io_atomic.load_newest_valid(files)  # DQ-1: never trust corrupt newest
    if live is not None:
        if path:
            print(f"  💾 Using: {os.path.basename(path)}")
        count = save_signals(live)
        print(f"  💾 Saved {count} new signals")
        
        # ۴. Alert
        alerts = send_5star_alerts(live)
        if alerts:
            print(f"  📱 Sent {alerts} alerts")
    
    # ۵. Hunter alerts (فقط ستاپ‌های TRIGGERED جدید)
    try:
        hr = check_and_alert_hunter()
        if hr.get("sent"):
            print(f"  🏹 Hunter alerts sent: {hr['sent']}")
        elif hr.get("skipped"):
            print(f"  🏹 Hunter: {hr['skipped']} already alerted")
    except Exception as e:
        print(f"  ❌ Hunter alert error: {e}")
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Cycle done.")

def cron_loop(interval=5):
    print("=" * 70)
    print("  ASTRA SCANNER — AUTO CRON + TRACKING")
    print("=" * 70)
    print(f"  Interval : {interval} min")
    print(f"  DB       : {DB}")
    print("=" * 70)
    init_db()
    while True:
        try: run_cycle()
        except Exception as e: print(f"  ❌ {e}")
        print(f"  💤 Waiting {interval} min...")
        time.sleep(interval * 60)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=int, default=5)
    p.add_argument("--once", action="store_true")
    p.add_argument("--db-stats", action="store_true")
    p.add_argument("--track", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--hunter-alerts", action="store_true")
    p.add_argument("--dedupe", action="store_true", help="list duplicate signals (dry-run)")
    p.add_argument("--apply", action="store_true", help="with --dedupe: really mark them DUPLICATE")
    args = p.parse_args()
    
    if args.once: run_cycle()
    elif args.track:
        n = track_open_signals()
        print(f"Tracked: {n} closed")
    elif args.dedupe:
        d = mark_duplicate_signals(apply=args.apply)
        for x in d:
            print(f"  id={x[0]} {x[1]} {x[2]} {x[3]} -> duplicate of id={x[4]}")
        print(f"{len(d)} duplicate(s) " + ("MARKED" if args.apply else "found (dry-run, nothing changed; add --apply)"))
    elif args.report: send_daily_report()
    elif args.hunter_alerts: print(check_and_alert_hunter())
    elif args.db_stats:
        conn = init_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*), SUM(CASE WHEN result='OPEN' THEN 1 ELSE 0 END), SUM(CASE WHEN result='TP' THEN 1 ELSE 0 END), SUM(CASE WHEN result='SL' THEN 1 ELSE 0 END) FROM signals")
        r = c.fetchone()
        total, open_c, tp_c, sl_c = r
        print(f"Total: {total} | Open: {open_c} | TP: {tp_c} | SL: {sl_c}")
        c.execute("SELECT ts, symbol, side, score, stars, result FROM signals ORDER BY id DESC LIMIT 15")
        for row in c.fetchall():
            print(f"  {row[0]} | {row[1]:<10} | {row[2]:<4} | score={row[3]:.1f} | ⭐{row[4]} | {row[5]}")
        conn.close()
    else: cron_loop(args.interval)

