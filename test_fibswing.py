# -*- coding: utf-8 -*-
"""test_fibswing.py — FIBSWING port verification (HLOOP v1).

Pure-stdlib logic tests (T1-T7) run on ANY Python; Flask route tests (T8)
auto-skip when flask is not importable (WSL python3 has no flask — run full
suite with Windows Python 3.12 like test_dsl_np).

Run:  python3 test_fibswing.py          (logic only, WSL-safe)
      "<win-python>" test_fibswing.py   (logic + route, full)
"""

import glob
import json
import math
import os
import sys
import tempfile
import time
import types
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import scanner_fibswing as FF

N = 300  # bars: >=240 for trend gate, break within last 168 (max_age 7d @1h)


def _c_at(i):
    """Synthetic 1h closes: rise -> swing high 172 -> decline -> trough 250
    -> micro-bounce 253 -> breakdown 256 -> drift down to 88 (SELL trend)."""
    if i <= 129:
        return 90.0 + 0.02 * i
    if i <= 171:
        return 92.58 + 0.18 * (i - 130)
    if i == 172:
        return 100.0
    if i <= 245:
        return 99.0 - 5.85 * (i - 173) / 72.0
    if i == 246:
        return 93.10
    if i == 247:
        return 93.08
    if i == 248:
        return 93.06
    if i == 249:
        return 93.04
    if i == 250:
        return 93.00   # swing low (l = 91.00, pivot)
    if i == 251:
        return 94.00
    if i == 252:
        return 95.20
    if i == 253:
        return 96.00   # bounce peak (h = 98.00, pivot = ph)
    if i == 254:
        return 95.80
    if i == 255:
        return 95.40
    if i == 256:
        return 90.50   # breakdown close < l[250]=91.00 -> ib
    return 90.50 - 2.50 * (i - 256) / 43.0


def build_sell_series(n=N):
    c = [_c_at(i) for i in range(n)]
    h = [x + 2.0 for x in c]
    l = [x - 2.0 for x in c]
    h[172] = 105.0
    ts = [float(1700000000000 + i * 3600000) for i in range(n)]
    return h, l, c, ts


def mirror_sell(s, p=200.0):
    """h_x = P - l_s, l_x = P - h_s, c_x = P - c_s -> analyze()'s BUY path
    is detect on (h_s - P, l_s - P, c_s - P) = translation of the SELL detect."""
    h, l, c, ts = s
    return [p - x for x in l], [p - x for x in h], [p - x for x in c], list(ts)


def build_klines(n=N, now_ms=None):
    """Realistic klines rows with all bars CLOSED ~30min before now."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    last_close = now_ms - int(0.5 * 3600000)
    base_open = last_close - n * 3600000 + 1
    h, l, c, _ = build_sell_series(n)
    rows = []
    for i in range(n):
        open_t = base_open + i * 3600000
        close_t = open_t + 3600000 - 1
        rows.append([int(open_t), c[i], h[i], l[i], c[i], 12345.6, int(close_t),
                     1.0e9, 1000, 1.0, 1.0, 0])
    return rows, now_ms


class TestNetRR(unittest.TestCase):
    def test_fs_core_sanity(self):
        # fs_core self-check: fee 1.5bps*2 sides on entry 100, risk 2, TP 2.01R
        self.assertAlmostEqual(FF.net_rr(100, 2, 2.01, 15), 1.8, delta=0.01)

    def test_min_rr_gate_value(self):
        # net_rr grows with risk/entry; synthetic SELL setup must clear 1.5
        self.assertGreaterEqual(FF.net_rr(90.5, 7.5, FF.FIB_TP1, 15), 1.5)


class TestDetectSell(unittest.TestCase):
    def test_end_to_end_sell_signal(self):
        h, l, c, ts = build_sell_series()
        sigs = FF.analyze(h, l, c, ts, "BTCUSDT", FF.CFG, c4=list(c))  # P4: agreeing 4h
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s["side"], "SELL")
        self.assertEqual(s["symbol"], "BTCUSDT")
        self.assertEqual(s["timeframe"], "1h")
        self.assertAlmostEqual(s["entry"], 90.5, places=6)
        self.assertAlmostEqual(s["stop"], 98.0, places=6)
        self.assertGreater(s["stop"], s["entry"])          # stop above entry
        self.assertGreater(s["entry"], s["tp1"])           # TP1 below entry (short)
        self.assertGreater(s["entry"], s["tp3"])
        self.assertGreaterEqual(s["net_rr_tp1"], 1.5)
        self.assertTrue(s["swing_id"].startswith("SELL|BTCUSDT|1h|"))
        self.assertEqual(s["mode"], "shadow")
        self.assertIn("T", s["swing_low_ts"])              # ISO timestamps
        self.assertIn("T", s["swing_high_ts"])
        self.assertIn("T", s["issued_at"])


class TestDetectBuy(unittest.TestCase):
    def test_end_to_end_buy_signal(self):
        mx = mirror_sell(build_sell_series())
        sigs = FF.analyze(mx[0], mx[1], mx[2], mx[3], "ETHUSDT", FF.CFG, c4=list(mx[2]))  # P4: agreeing 4h
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s["side"], "BUY")
        self.assertEqual(s["symbol"], "ETHUSDT")
        self.assertAlmostEqual(s["entry"], 200.0 - 90.5, places=6)   # 109.5
        self.assertAlmostEqual(s["stop"], 200.0 - 98.0, places=6)    # 102.0
        self.assertLess(s["stop"], s["entry"])           # stop below entry (long)
        self.assertGreater(s["tp1"], s["entry"])         # TP1 above entry (long)
        self.assertGreaterEqual(s["net_rr_tp1"], 1.5)
        self.assertTrue(s["swing_id"].startswith("BUY|ETHUSDT|1h|"))


class TestTrendGate(unittest.TestCase):
    def test_directions(self):
        self.assertEqual(FF.trend_direction(build_sell_series()[2]), "SELL")
        self.assertEqual(FF.trend_direction(mirror_sell(build_sell_series())[2]), "BUY")
        self.assertIsNone(FF.trend_direction([100.0] * N))   # flat -> no signal
        self.assertIsNone(FF.trend_direction([100.0] * 200))  # short history

    def test_gate_kills_setup_when_none(self):
        h, l, c, ts = build_sell_series()
        orig = FF.trend_direction
        FF.trend_direction = lambda x, buffer=0.005: None
        try:
            self.assertEqual(FF.analyze(h, l, c, ts, "BTCUSDT", FF.CFG), [])
        finally:
            FF.trend_direction = orig

    def test_gate_filters_wrong_side(self):
        # SELL setup present but trend says BUY -> SELL must be filtered out
        h, l, c, ts = build_sell_series()
        orig = FF.trend_direction
        FF.trend_direction = lambda x, buffer=0.005: "BUY"
        try:
            self.assertEqual(FF.analyze(h, l, c, ts, "BTCUSDT", FF.CFG), [])
        finally:
            FF.trend_direction = orig


class TestHostRotation(unittest.TestCase):
    def test_vision_first_api_last(self):
        self.assertIn("data-api.binance.vision", FF.BINANCE_HOSTS[0])
        self.assertTrue(FF.BINANCE_HOSTS[-1].endswith("api.binance.com"))
        self.assertEqual(len(FF.BINANCE_HOSTS), 5)


class TestFetchClosed(unittest.TestCase):
    def setUp(self):
        self._orig = FF._binance_json
        self.rows, self.now_ms = build_klines()

    def tearDown(self):
        FF._binance_json = self._orig

    def _patch(self, payload):
        FF._binance_json = lambda path, timeout=15: payload

    def test_good_returns_300_closed(self):
        self._patch(self.rows)
        df = FF.fetch_closed("BTCUSDT", "1h", 500, self.now_ms)
        self.assertIsNotNone(df)
        self.assertEqual(len(df["c"]), 300)
        self.assertAlmostEqual(df["c"][256], 90.50, places=6)

    def test_short_raw_returns_none(self):
        self._patch(self.rows[:50])
        self.assertIsNone(FF.fetch_closed("BTCUSDT", "1h", 500, self.now_ms))

    def test_nan_returns_none(self):
        bad = [list(r) for r in self.rows]
        bad[100][4] = float("nan")
        self._patch(bad)
        self.assertIsNone(FF.fetch_closed("BTCUSDT", "1h", 500, self.now_ms))

    def test_stale_returns_none(self):
        # server 3.5h ahead of last close -> 3.5h > 2*TF staleness budget
        self._patch(self.rows)
        self.assertIsNone(FF.fetch_closed("BTCUSDT", "1h", 500,
                                          self.now_ms + int(3 * 3600000)))

    def test_all_forming_returns_none(self):
        # srv far in the past -> no row has close_ts < srv
        self._patch(self.rows)
        self.assertIsNone(FF.fetch_closed("BTCUSDT", "1h", 500, 1))


class TestRunEndToEnd(unittest.TestCase):
    """run() with faked network + redirected RESULTS/DATA (no real files touched)."""

    def setUp(self):
        self._orig_binance = FF._binance_json
        self._orig_results, self._orig_data = FF.RESULTS, FF.DATA

    def tearDown(self):
        FF._binance_json = self._orig_binance
        FF.RESULTS, FF.DATA = self._orig_results, self._orig_data

    def test_snapshot_and_journal_dedupe(self):
        rows, now_ms = build_klines()
        calls = []

        def fake(path, timeout=15):
            calls.append(path)
            if path.startswith("/api/v3/time"):
                return {"serverTime": int(now_ms)}
            if path.startswith("/api/v3/klines"):
                return rows
            raise AssertionError("unexpected path: %r" % path)

        FF._binance_json = fake
        with tempfile.TemporaryDirectory() as td:
            FF.RESULTS = os.path.join(td, "results")
            FF.DATA = os.path.join(td, "data")
            rc1 = FF.run()
            self.assertEqual(rc1, 0)
            snaps = glob.glob(os.path.join(FF.RESULTS, "fibswing_*.json"))
            self.assertEqual(len(snaps), 1)
            with open(snaps[0], encoding="utf-8") as f:
                snap = json.load(f)
            # snapshot shape (pipeline contract)
            self.assertEqual(snap["count"], 6)          # 6 symbols x 1 setup each
            self.assertEqual(snap["strategy"], "FIBSWING")
            self.assertEqual(snap["timeframe"], "1h")
            self.assertEqual(len(snap["results"]), 6)
            self.assertEqual(len(snap["symbols"]), 6)
            import re
            self.assertRegex(snap["generated"], r"^\d{8}_\d{6}$")  # _age_from_generated
            for key in ("swing_id", "symbol", "side", "entry", "stop",
                        "tp1", "tp2", "tp3", "net_rr_tp1", "mode",
                        "age_bars", "age_hours", "freshness", "trend_4h"):
                self.assertIn(key, snap["results"][0])
            # journal: 6 new lines; seen persisted
            jp = os.path.join(FF.DATA, "fibswing_journal.jsonl")
            with open(jp, encoding="utf-8") as f:
                lines1 = [x for x in f.read().splitlines() if x.strip()]
            self.assertEqual(len(lines1), 6)
            seen_path = os.path.join(FF.DATA, "fibswing_seen.json")
            with open(seen_path, encoding="utf-8") as f:
                self.assertEqual(len(json.load(f)), 6)
            # second run: same swings -> journal NOT duplicated, snapshot refreshed
            time.sleep(1.1)
            rc2 = FF.run()
            self.assertEqual(rc2, 0)
            with open(jp, encoding="utf-8") as f:
                lines2 = [x for x in f.read().splitlines() if x.strip()]
            self.assertEqual(len(lines2), 6)
            snaps2 = glob.glob(os.path.join(FF.RESULTS, "fibswing_*.json"))
            self.assertEqual(len(snaps2), 2)  # new snapshot per run (freshness)
            # one server-time call per run + (1h + 4h) klines x6 symbols per run = 26 calls
            self.assertEqual(len(calls), 26)
            # klines paths use the rotation entry point (12 per run: 6x1h + 6x4h)
            self.assertEqual(
                len([c for c in calls if c.startswith("/api/v3/klines?")]), 24)

    def test_skew_abort_writes_nothing(self):
        rows, now_ms = build_klines()

        def fake(path, timeout=15):
            if path.startswith("/api/v3/time"):
                return {"serverTime": int(now_ms + 10 * 60 * 1000)}  # 10min skew > 90s
            return rows

        FF._binance_json = fake
        with tempfile.TemporaryDirectory() as td:
            FF.RESULTS = os.path.join(td, "results")
            FF.DATA = os.path.join(td, "data")
            rc = FF.run()
            self.assertEqual(rc, 1)
            self.assertEqual(glob.glob(os.path.join(FF.RESULTS, "fibswing_*.json")), [])


class TestConfluenceDecay(unittest.TestCase):
    """Phase 4 (backlog #3): 4H trend confluence gate + entry-age decay fields."""

    def test4h_agreement_keeps_signal(self):
        h, l, c, ts = build_sell_series()
        sigs = FF.analyze(h, l, c, ts, "BTCUSDT", FF.CFG, c4=list(c))
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s["trend_4h"], "SELL")
        self.assertIsInstance(s["age_bars"], int)
        self.assertGreaterEqual(s["age_bars"], 0)
        self.assertEqual(s["age_hours"], float(s["age_bars"]))  # 1h bars == hours
        self.assertGreater(s["freshness"], 0.0)
        self.assertLessEqual(s["freshness"], 1.0)

    def test4h_conflict_drops_signal(self):
        h, l, c, ts = build_sell_series()
        c4 = mirror_sell((h, l, c, ts))[2]  # 1h SELL setup but 4h trend BUY
        self.assertEqual(FF.analyze(h, l, c, ts, "BTCUSDT", FF.CFG, c4=c4), [])

    def test_missing_or_short_4h_fail_closed(self):
        h, l, c, ts = build_sell_series()
        self.assertEqual(FF.analyze(h, l, c, ts, "BTCUSDT", FF.CFG, c4=None), [])
        self.assertEqual(FF.analyze(h, l, c, ts, "BTCUSDT", FF.CFG,
                                    c4=[100.0] * 100), [])  # < 240 bars

    def test_confluence_off_ignores_missing_4h(self):
        h, l, c, ts = build_sell_series()
        cfg = dict(FF.CFG, confluence_tf=None)
        sigs = FF.analyze(h, l, c, ts, "BTCUSDT", cfg, c4=None)
        self.assertEqual(len(sigs), 1)
        self.assertIsNone(sigs[0]["trend_4h"])
        a = sigs[0]["age_bars"]  # age gate still active from CFG even with confluence off
        self.assertAlmostEqual(sigs[0]["freshness"],
                               1 - a / float(FF.CFG["max_entry_age_bars"]), places=3)

    def test_entry_age_gate_and_freshness(self):
        h, l, c, ts = build_sell_series()
        base = FF.analyze(h, l, c, ts, "BTCUSDT", FF.CFG, c4=list(c))
        age = base[0]["age_bars"]
        self.assertGreater(age, 0)  # fixture: break well before final bar
        cfg_old = dict(FF.CFG, max_entry_age_bars=age - 1)
        self.assertEqual(FF.analyze(h, l, c, ts, "BTCUSDT", cfg_old, c4=list(c)), [])
        cfg_ok = dict(FF.CFG, max_entry_age_bars=age + 100)
        s = FF.analyze(h, l, c, ts, "BTCUSDT", cfg_ok, c4=list(c))[0]
        self.assertAlmostEqual(s["freshness"], 1 - age / float(age + 100), places=3)
        self.assertAlmostEqual(s["age_hours"], float(age), places=2)


try:
    import dashboard as D
    _HAVE_FLASK = True
except Exception:  # WSL python3: no flask -> route tests skipped
    D = None
    _HAVE_FLASK = False


@unittest.skipUnless(_HAVE_FLASK, "flask not importable (WSL) — run with Windows Python")
class TestDashboardRoute(unittest.TestCase):
    def test_host_list_parity_with_dashboard(self):
        self.assertEqual(FF.BINANCE_HOSTS, D.BINANCE_HOSTS)

    def test_fibswing_job_registered(self):
        D._fill_d20_jobs()
        self.assertIn("fibswing", D.D20_JOBS)
        self.assertIs(D.D20_JOBS["fibswing"], D._run_fibswing)
        self.assertEqual(D.FIB_DELAY, 60)

    def test_api_fibswing_missing_file(self):
        client = D.app.test_client()
        orig = D.RESULTS
        try:
            with tempfile.TemporaryDirectory() as td:
                D.RESULTS = td
                r = client.get("/api/fibswing")
                self.assertEqual(r.status_code, 200)
                j = r.get_json()
                self.assertFalse(j.get("ok"))
                self.assertIn("error", j)
        finally:
            D.RESULTS = orig

    def test_api_fibswing_serves_snapshot_with_age(self):
        client = D.app.test_client()
        orig = D.RESULTS
        try:
            with tempfile.TemporaryDirectory() as td:
                import io_atomic as io18
                io18.atomic_write_json(os.path.join(td, "fibswing_20261020_120000.json"), {
                    "generated": "20261020_120000",
                    "count": 1,
                    "strategy": "FIBSWING",
                    "timeframe": "1h",
                    "results": [{"symbol": "BTCUSDT", "side": "SELL",
                                 "entry": 90.5, "stop": 98.0, "tp1": 78.365,
                                 "net_rr_tp1": 1.571}],
                })
                D.RESULTS = td
                r = client.get("/api/fibswing")
                j = r.get_json()
                self.assertTrue(j.get("ok"))
                self.assertEqual(j["count"], 1)
                self.assertEqual(j["results"][0]["symbol"], "BTCUSDT")
                self.assertIsInstance(j["age_seconds"], (int, float))
                self.assertGreaterEqual(j["age_seconds"], 0)
        finally:
            D.RESULTS = orig

    def test_market_freshness_has_fibswing_key(self):
        d = D.get_market_data()
        self.assertIn("fibswing", d.get("freshness", {}))


@unittest.skipUnless(_HAVE_FLASK, "flask not importable (WSL) — run with Windows Python")
class TestFibSched(unittest.TestCase):
    """Phase 1: 1h-close-aligned fib scheduling — loop verified with fake clock;
    _sched_run is recorded (no jobs/network executed in tests)."""

    def setUp(self):
        self._orig = {k: getattr(D, k) for k in
                      ("_sched_run", "_sched_due", "SCHED_TICK", "DOM_INTERVAL", "time", "RESULTS")}
        self.calls = []
        self.clock = [0.0]
        outer = self

        class _FakeTime:
            @staticmethod
            def time():
                return outer.clock[0]

            @staticmethod
            def sleep(sec):
                outer.clock[0] += sec

        D.time = _FakeTime
        D.SCHED_TICK = 600          # sleep advances fake clock 600s/tick (settlement math readable)
        D.DOM_INTERVAL = 10 ** 15   # silence dominance except first tick (not under test)
        D._sched_run = lambda name: self.calls.append((name, self.clock[0]))
        D._sched_due = lambda now, lv, lm: []

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(D, k, v)

    @staticmethod
    def _write_fib(results_dir, mtime):
        p = os.path.join(results_dir, "fibswing_19700101_000000.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"generated": "19700101_000000", "count": 0, "results": []}, f)
        os.utime(p, (mtime, mtime))
        return p

    def test_last_1h_boundary_math(self):
        h = 3600 * 10000
        self.assertEqual(D._sched_last_1h(h + 1200), h)         # 20min after close -> settled
        self.assertEqual(D._sched_last_1h(h + 30), h - 3600)    # 30s after close -> NOT settled (delay 60)
        self.assertEqual(D._sched_last_1h(h + 61), h)           # 61s after close -> settled
        self.assertEqual(D._sched_last_1h(h + 3660), h + 3600)  # next close settled

    def test_loop_startup_then_exactly_next_close(self):
        with tempfile.TemporaryDirectory() as td:
            D.RESULTS = td                                      # no fib file -> seed 0 -> run at tick1
            h = 3600 * 10000
            self.clock[0] = h + 660
            D._sched_loop(max_ticks=6)                          # ticks at +0..+3000 (sleep advances)
            fibs = [t for n, t in self.calls if n == "fibswing"]
            self.assertEqual(fibs, [h + 660, h + 3660])         # startup + exactly the next settled close
            # ticks at h+1260..h+3060 all had boundary h <= last_fib -> no runs (count proves it)
            others = {n for n, _ in self.calls} - {"fibswing", "dominance"}
            self.assertEqual(others, set())                     # v4/mtf never dispatched

    def test_restart_fresh_file_no_duplicate_run(self):
        with tempfile.TemporaryDirectory() as td:
            h = 3600 * 10000
            self._write_fib(td, h + 660)                        # last run 11min ago (before next close)
            D.RESULTS = td
            self.clock[0] = h + 690                             # restart 30s after last run
            D._sched_loop(max_ticks=1)
            self.assertFalse([n for n, _ in self.calls if n == "fibswing"])

    def test_restart_stale_file_runs_immediately(self):
        with tempfile.TemporaryDirectory() as td:
            h = 3600 * 10000
            self._write_fib(td, h - 10000)                      # last run ~3h ago (missed closes)
            D.RESULTS = td
            self.clock[0] = h + 690
            D._sched_loop(max_ticks=1)
            self.assertEqual([n for n, _ in self.calls if n == "fibswing"], ["fibswing"])


class _FakeResp:
    def __init__(self, payload=b'{"ok": 1}'):
        self._p = payload

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestSourceLock(unittest.TestCase):
    """Phase 3 (backlog #2): source-lock + per-host cooldown on _binance_json."""

    def setUp(self):
        self._orig_urlopen = urllib.request.urlopen
        self._orig_time = FF.time
        self._saved_lock = FF._LOCK["host"]
        self._saved_next = dict(FF._HOST_NEXT)
        FF._LOCK["host"] = None
        FF._HOST_NEXT.clear()
        self.attempts = []

    def tearDown(self):
        urllib.request.urlopen = self._orig_urlopen
        FF.time = self._orig_time
        FF._LOCK["host"] = self._saved_lock
        FF._HOST_NEXT.clear()
        FF._HOST_NEXT.update(self._saved_next)

    def _install(self, fail_hosts=(), clock=None):
        attempts = self.attempts

        def fake_urlopen(req, timeout=15):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            host = "https://" + url.split("/")[2]
            attempts.append(host)
            if host in fail_hosts:
                raise OSError("simulated outage: %s" % host)
            return _FakeResp()

        urllib.request.urlopen = fake_urlopen
        if clock is not None:
            FF.time = types.SimpleNamespace(time=lambda: clock[0])

    def test_lock_moves_to_working_host(self):
        self._install(fail_hosts=("https://data-api.binance.vision",))
        self.assertEqual(FF._binance_json("/api/v3/time"), {"ok": 1})
        self.assertEqual(self.attempts[:2], ["https://data-api.binance.vision",
                                             "https://api1.binance.com"])
        self.assertEqual(FF._LOCK["host"], "https://api1.binance.com")
        FF._binance_json("/api/v3/time")  # locked host only — no re-probe of dead vision
        self.assertEqual(self.attempts[2:], ["https://api1.binance.com"])

    def test_locked_host_failure_unlocks_and_cooldowns(self):
        self._install()
        FF._binance_json("/api/v3/time")
        self.assertEqual(FF._LOCK["host"], "https://data-api.binance.vision")
        self.attempts.clear()
        self._install(fail_hosts=("https://data-api.binance.vision",))
        FF._binance_json("/api/v3/time")
        self.assertEqual(self.attempts[0], "https://data-api.binance.vision")  # locked probe fails
        self.assertEqual(FF._LOCK["host"], "https://api1.binance.com")         # moved on
        self.assertIn("https://data-api.binance.vision", FF._HOST_NEXT)        # quarantined
        self.attempts.clear()
        FF._binance_json("/api/v3/time")  # vision in cooldown -> untouched
        self.assertEqual(self.attempts, ["https://api1.binance.com"])

    def test_total_failure_raises_cools_all_then_fail_open(self):
        self._install(fail_hosts=tuple(FF.BINANCE_HOSTS))
        with self.assertRaises(RuntimeError):
            FF._binance_json("/api/v3/time")
        self.assertIsNone(FF._LOCK["host"])
        self.assertEqual(len(FF._HOST_NEXT), len(FF.BINANCE_HOSTS))
        self.attempts.clear()
        self._install()  # network healthy again but all still cooling -> fail-open
        self.assertEqual(FF._binance_json("/api/v3/time"), {"ok": 1})
        self.assertEqual(self.attempts, ["https://data-api.binance.vision"])

    def test_cooldown_expiry_retries_host(self):
        clock = [1000.0]
        self._install(fail_hosts=("https://data-api.binance.vision",), clock=clock)
        FF._binance_json("/api/v3/time")  # vision fails -> quarantined until 1300
        self.attempts.clear()
        self._install(clock=clock)  # healthy again, still inside quarantine window
        FF._binance_json("/api/v3/time")
        self.assertEqual(self.attempts, ["https://api1.binance.com"])
        clock[0] = 1000.0 + FF.COOLDOWN_S + 1  # quarantine expired -> vision eligible again
        self.attempts.clear()
        FF._binance_json("/api/v3/time")
        # stickiness: healthy lock (api1) does NOT get preempted by the revived host
        self.assertEqual(self.attempts, ["https://api1.binance.com"])
        # when the lock degrades, revived vision is retried in rotation order
        self.attempts.clear()
        self._install(fail_hosts=("https://api1.binance.com",), clock=clock)
        FF._binance_json("/api/v3/time")
        self.assertEqual(self.attempts[:2], ["https://api1.binance.com",
                                             "https://data-api.binance.vision"])
        self.assertEqual(FF._LOCK["host"], "https://data-api.binance.vision")


if __name__ == "__main__":
    unittest.main(verbosity=2)
