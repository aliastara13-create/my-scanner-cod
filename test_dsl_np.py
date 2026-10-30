# -*- coding: utf-8 -*-
# test_dsl_np.py - DSL backtest must not crash with "name 'np' is not defined". Synthetic candles, no network.
# Run: python test_dsl_np.py [module_name]   (default: dashboard)
import os, sys, types, importlib, math
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import telegram  # noqa
except Exception:
    m = types.ModuleType("telegram"); m.check_and_alert_hunter = lambda: {}
    for n in ("send_telegram", "format_signal", "mask_token"):
        setattr(m, n, lambda *a, **k: None)
    sys.modules["telegram"] = m
for _m in ("io_atomic", "position_sizing", "zones", "dominance"):
    try:
        __import__(_m)
    except Exception:
        sys.modules[_m] = mock.MagicMock()
D = importlib.import_module(sys.argv[1] if len(sys.argv) > 1 else "dashboard")

def fake_candles(n=400):
    out = []
    for i in range(n):
        c = 100 + 10 * math.sin(i / 12.0) + i * 0.02
        out.append({"time": i * 3600000, "open": c - 0.3, "high": c + 1.0, "low": c - 1.0, "close": c, "volume": 1000 + 300 * math.sin(i / 5.0) + i})
    return out
D._load_historical_candles = lambda symbol, tf, limit=2000: fake_candles()

F = 0
def check(n, c, d=""):
    global F
    print(("PASS  " if c else "FAIL  ") + n + ("" if c else " " + str(d)))
    if not c: F += 1

try:
    r = D._run_dsl_backtest("BTCUSDT", "1H", "CLOSE > EMA_21 AND ADX > 15")
    check("T1 backtest runs without np error", isinstance(r, dict) and "error" not in r, r)
    check("T2 metrics present (trades, hit_rate, total_r, max_dd, avg_hold, equity_curve)",
          all(k in r for k in ("trades", "hit_rate", "total_r", "max_dd", "avg_hold", "equity_curve")), r)
    check("T3 at least one trade on synthetic trend data", r.get("trades", 0) >= 1, r)
    check("T4 avg_hold is a plain number (JSON-safe)", isinstance(r.get("avg_hold"), (int, float)) and not isinstance(r.get("avg_hold"), bool), type(r.get("avg_hold")))
except NameError as e:
    check("T1 backtest runs without np error", False, "NameError: %s" % e)

# route level (Flask test client): must return ok:true JSON, with the symbol-pool check stubbed
import json
sp = types.ModuleType("symbols_pool"); sp.get_pool_symbols = lambda: ["BTCUSDT"]
sys.modules["symbols_pool"] = sp
resp = D.app.test_client().post("/api/alert/dsl/backtest", json={"symbol": "btc", "tf": "1H", "dsl": "CLOSE > EMA_21 AND ADX > 15", "fee": 0.0015})
body = resp.get_json()
check("T5 route returns ok:true", body and body.get("ok") is True, body)
try:
    json.dumps(body); check("T6 response is JSON-serialisable", True)
except Exception as e:
    check("T6 response is JSON-serialisable", False, e)
print("RESULT: %s" % ("ALL PASS" if not F else "FAILED %d" % F))
sys.exit(1 if F else 0)
