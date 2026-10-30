# -*- coding: utf-8 -*-
# astra_tv_push.py - reads OPEN signals from ASTRA's DB and draws them on TradingView Desktop (real chart).
# Put in the ASTRA project folder. Run:  python astra_tv_push.py          (once)
#                                         python astra_tv_push.py --loop 60 (repeat every 60s)
#                                         python astra_tv_push.py --dry / --probe / --clear
# Needs: TradingView Desktop started with --remote-debugging-port=9222 (your launcher bot does this).
import json, os, shutil, sqlite3, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "astra_history.db")
LEVELS = os.path.join(HERE, "data", "astra_levels.json")
MCP_DIR = os.environ.get("TV_MCP_DIR", r"C:\Users\Raman\tradingview-mcp")
SCRIPT = os.path.join(MCP_DIR, "astra_tv_draw.mjs")


def read_open_signals(db=DB):
    """OPEN rows only (DUPLICATE/closed are excluded). Newest first."""
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT id, symbol, side, entry_lo, entry_hi, sl, tp, rr, zone_status FROM signals "
            "WHERE result='OPEN' ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    keys = ("id", "symbol", "side", "entry_lo", "entry_hi", "sl", "tp", "rr", "zone_status")
    return [dict(zip(keys, r)) for r in rows]


def write_levels(signals, path=LEVELS):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "signals": signals}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def node_exe():
    return shutil.which("node") or r"C:\Program Files\nodejs\node.exe"


def run_once(extra):
    sigs = read_open_signals()
    write_levels(sigs)
    cmd = [node_exe(), SCRIPT, LEVELS] + extra
    p = subprocess.run(cmd, cwd=MCP_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    out = (p.stdout or "").strip() or (p.stderr or "").strip()
    print("[%s] open=%d  %s" % (time.strftime("%H:%M:%S"), len(sigs), out))
    return p.returncode


def main(argv):
    extra = [a for a in argv if a in ("--dry", "--probe", "--clear") or a.startswith("--symbol=")]
    loop = None
    if "--loop" in argv:
        i = argv.index("--loop")
        loop = int(argv[i + 1]) if i + 1 < len(argv) else 60
    if loop is None:
        return run_once(extra)
    while True:
        try:
            run_once(extra)
        except Exception as e:  # keep looping; TradingView may be closed for a while
            print("[%s] error: %s" % (time.strftime("%H:%M:%S"), e))
        time.sleep(loop)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
