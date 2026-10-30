# -*- coding: utf-8 -*-
# test_a3a4.py - A3 (dedupe) + A4 (stats exclude DUPLICATE). Run from the project folder: python test_a3a4.py
# Uses a TEMP database only. The real data/astra_history.db is never touched.
import os, re, sys, sqlite3, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import telegram  # noqa: F401
except Exception:  # sandbox without the project's telegram.py
    m = types.ModuleType("telegram")
    m.check_and_alert_hunter = lambda: {}
    sys.modules["telegram"] = m

import automation as A

FAILS = []
TOTAL = [0]


def check(name, cond, detail=""):
    TOTAL[0] += 1
    if cond:
        print("PASS  %s" % name)
    else:
        FAILS.append(name)
        print("FAIL  %s %s" % (name, detail))


def fresh_db(old_schema=False):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    A.DB = path
    if old_schema:  # legacy table: no reasons / dup_of / orig_result columns
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE signals (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT, side TEXT,
            score REAL, stars INTEGER, regime TEXT, adx REAL, price REAL, entry_lo REAL, entry_hi REAL,
            sl REAL, tp REAL, rr REAL, zone_status TEXT, result TEXT DEFAULT 'OPEN',
            closed_ts TEXT, closed_price REAL, UNIQUE(ts, symbol, side))""")
        conn.commit()
        conn.close()
    return path


def live(ts, symbol="BNBUSDT", side="BUY", lo=733.14, hi=736.17, status="IN_ZONE"):
    return {"generated": ts, "results": [{"symbol": symbol, "score": 51, "stars": 4, "regime": "STRONG", "adx": 30,
            "price": 737.0, "signals": [{"side": side, "entry_zone_lo": lo, "entry_zone_hi": hi, "sl": 718.65,
            "tp": 758.44, "rr": 2.0, "zone_status": status}]}]}


def rows(path, where="1=1"):
    conn = sqlite3.connect(path)
    r = conn.execute("SELECT id, ts, symbol, side, result, dup_of, orig_result FROM signals WHERE %s ORDER BY id" % where).fetchall()
    conn.close()
    return r


def raw_insert(path, ts, symbol="BNBUSDT", side="BUY", lo=733.14, hi=736.17, result="OPEN", closed_ts=None):
    A.init_db().close()
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO signals (ts,symbol,side,score,stars,regime,adx,price,entry_lo,entry_hi,sl,tp,rr,zone_status,result,closed_ts)"
                 " VALUES (?,?,?,50,4,'STRONG',30,737,?,?,718.65,758.44,2.0,'IN_ZONE',?,?)",
                 (ts, symbol, side, lo, hi, result, closed_ts))
    conn.commit()
    conn.close()


# ---- T1 static: INSERT column count == placeholder count (was 14 vs 15 -> every insert raised) ----
src = open(os.path.join(HERE, "automation.py"), encoding="utf-8").read()
m = re.search(r"INSERT OR IGNORE INTO signals\s*\((.*?)\)\s*VALUES\s*\((.*?)\)", src, re.S)
ncols = len([c for c in m.group(1).split(",") if c.strip()])
nph = m.group(2).count("?")
check("T1 INSERT columns == placeholders", ncols == nph, "(columns=%d placeholders=%d)" % (ncols, nph))

# ---- T2 save_signals works on a legacy-schema DB (no reasons column) ----
p = fresh_db(old_schema=True)
n = A.save_signals(live("20261014_161252"))
check("T2 save_signals inserts on legacy-schema DB", n == 1 and len(rows(p)) == 1, "(saved=%s rows=%d)" % (n, len(rows(p)) if os.path.exists(p) else -1))

# ---- T3 same setup re-scanned at a new timestamp -> no new OPEN row ----
p = fresh_db()
A.save_signals(live("20261014_161252"))
A.save_signals(live("20261014_161853"))
A.save_signals(live("20261014_162423"))
check("T3 repeated scan of same zone keeps ONE open row", len(rows(p, "result='OPEN'")) == 1, "(open rows=%d)" % len(rows(p, "result='OPEN'")))

# ---- T4 different zone / side are NOT blocked ----
A.save_signals(live("20261014_163000", lo=700.0, hi=705.0))
A.save_signals(live("20261014_163001", side="SELL"))
A.save_signals(live("20261014_163002", symbol="ETHUSDT"))
check("T4 other zone/side/symbol still saved", len(rows(p, "result='OPEN'")) == 4, "(open rows=%d)" % len(rows(p, "result='OPEN'")))

# ---- T5 re-entry after the first trade CLOSED is allowed ----
p = fresh_db()
A.save_signals(live("20261014_161252"))
conn = sqlite3.connect(p); conn.execute("UPDATE signals SET result='SL', closed_ts='20261014_170000'"); conn.commit(); conn.close()
A.save_signals(live("20261015_090000"))
check("T5 new OPEN allowed after previous one closed", len(rows(p)) == 2 and len(rows(p, "result='OPEN'")) == 1)

# ---- T6 dedupe dry-run reports but changes nothing; the real BNB case (8 closed SL rows) ----
p = fresh_db()
stamps = ["20261014_161252", "20261014_161853", "20261014_162423", "20261014_163428",
          "20261014_163709", "20261014_164436", "20261014_165117", "20261014_165843"]
for t in stamps:
    raw_insert(p, t, result="SL", closed_ts="20261018_233000")
before = rows(p)
fn = getattr(A, "mark_duplicate_signals", None)
dry = fn() if fn else None
check("T6a dry-run lists 7 duplicates", dry is not None and len(dry) == 7, "(got %s)" % (None if dry is None else len(dry)))
check("T6b dry-run changes nothing", rows(p) == before)

# ---- T7 apply: keep earliest, flag the rest, remember original result ----
done = fn(apply=True) if fn else None
rr = rows(p)
check("T7a earliest row kept as SL", bool(rr) and rr[0][4] == "SL")
check("T7b other 7 rows are DUPLICATE with dup_of=first id", bool(rr) and all(r[4] == "DUPLICATE" and r[5] == rr[0][0] for r in rr[1:]) and len(rr) == 8)
check("T7c original result remembered (undo possible)", bool(rr) and all(r[6] == "SL" for r in rr[1:]))
again = fn(apply=True) if fn else None
check("T7d second apply is a no-op (idempotent)", again == [] , "(got %s)" % (again,))

# ---- T8 legit re-entry (created AFTER the first trade closed) is NOT flagged ----
p = fresh_db()
raw_insert(p, "20261014_161252", result="SL", closed_ts="20261014_170000")
raw_insert(p, "20261015_090000", result="OPEN")
d = fn() if fn else None
check("T8 later re-entry not flagged", d == [], "(got %s)" % (d,))

# ---- T9 different zone/side/symbol never flagged ----
p = fresh_db()
raw_insert(p, "20261014_161252")
raw_insert(p, "20261014_161853", lo=700.0, hi=705.0)
raw_insert(p, "20261014_162423", side="SELL")
raw_insert(p, "20261014_163428", symbol="ETHUSDT")
d = fn() if fn else None
check("T9 distinct setups untouched", d == [], "(got %s)" % (d,))

# ---- T10 tracker never touches DUPLICATE rows ----
p = fresh_db()
raw_insert(p, "20261014_161252")
raw_insert(p, "20261014_161853")
if fn:
    fn(apply=True)
calls = []
A.get_current_price = lambda s: (calls.append(s), 700.0)[1]  # BUY, price below SL 718.65
closed = A.track_open_signals()
check("T10a tracker closes only the kept row", closed == 1 and len(calls) == 1, "(closed=%s calls=%d)" % (closed, len(calls)))
check("T10b DUPLICATE row stays DUPLICATE", [r[4] for r in rows(p)] == ["SL", "DUPLICATE"] if fn else False, "(%s)" % ([r[4] for r in rows(p)],))

# ---- T11 daily report counts exclude DUPLICATE ----
check("T11 daily report closed-count excludes DUPLICATE", "NOT IN ('OPEN','DUPLICATE')" in src.replace('"', "'") or "NOT IN ('OPEN', 'DUPLICATE')" in src)

# ---- A4: dashboard stats queries exclude DUPLICATE ----
dsrc = open(os.path.join(HERE, "dashboard.py"), encoding="utf-8").read()
q = re.findall(r'c\.execute\("""(.*?)""",\s*\(symbol,\)\)', dsrc, re.S)
sig_q = [x for x in q if "FROM signals" in x]
check("A4-1 both dashboard signal queries found", len(sig_q) == 2, "(found %d)" % len(sig_q))
check("A4-2 both exclude DUPLICATE", len(sig_q) == 2 and all("DUPLICATE" in x for x in sig_q))
p = fresh_db()
for t in stamps:
    raw_insert(p, t, result="SL", closed_ts="20261018_233000")
if fn:
    fn(apply=True)
conn = sqlite3.connect(p)
cnts = []
for x in sig_q:
    cnts.append(len(conn.execute(x, ("BNBUSDT",)).fetchall()))
conn.close()
check("A4-3 BNB history: 8 signals -> 1 (was 8 rows / -8R)", cnts == [1, 1], "(rows per query=%s)" % cnts)

print("\n%d/%d PASS" % (TOTAL[0] - len(FAILS), TOTAL[0]))
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
