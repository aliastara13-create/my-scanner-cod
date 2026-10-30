# -*- coding: utf-8 -*-
"""D1: candidate-table import connector.

# D1CONN: commission is resolved exactly ONCE per candidate row - rows flagged
# fee_applied=True pass through untouched (never double-charge). Single fee
# resolution point for both strategies.
# D1C1A: base SL $ / trigger $ rule.
# D1C1B: 24h delta rule.
# D1NOTE: at the connector end, notes_screen records the scanner_v4.py prod-run
# result row (rows carrying result_row are stamped; notes never break imports).
"""

import json
import os


def load_fee_round_trip():
    # D1CONN: round-trip fee always sourced from risk_config.json (no hardcoded fee literals in repo .py)
    cfg_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "risk_config.json")
    with open(cfg_p, encoding="utf-8") as fh:
        cfg = json.load(fh)
    fee = cfg.get("fee_round_trip")
    if isinstance(fee, (int, float)) and fee > 0:
        return float(fee)
    raise RuntimeError("risk_config.json fee_round_trip missing - refuse to guess the fee (hard-data rule)")


FEE_ROUND_TRIP = load_fee_round_trip()   # loaded from risk_config.json at import

__all__ = [
    "FEE_ROUND_TRIP", "resolve_commission", "base_sl_trigger_rule", "delta_24h",
    "import_candidates_c1a", "import_candidates_c1b", "connect",
]


def resolve_commission(row):
    """D1CONN: apply round-trip fee once; already-flagged rows pass unchanged."""
    if row.get("fee_applied"):
        return dict(row, fee_source="pass-through")
    entry = row.get("entry")
    if entry is None:
        return dict(row, fee_applied=False, fee_source="no-entry")
    fee = abs(entry) * FEE_ROUND_TRIP
    out = dict(row)
    out["fee_abs"] = round(fee, 8)          # 0.5-rounding convention on derived values
    out["fee_applied"] = True
    out["fee_source"] = "round_trip"
    return out


def base_sl_trigger_rule(entry, sl_dollars, trigger_dollars):
    """D1C1A: long orientation - base SL = entry - SL$; trigger arms at entry + Trigger$.
    None-safe: any missing component -> (None, None). Stored values not re-rounded."""
    if entry is None or sl_dollars is None or trigger_dollars is None:
        return None, None
    return round(entry - sl_dollars, 8), round(entry + trigger_dollars, 8)


def delta_24h(row, price_col="entry", past_col="entry_24h"):
    """D1C1B: 24h delta percent from the row own past price; None-safe."""
    now_v = row.get(price_col)
    past = row.get(past_col)
    if not now_v or not past:
        return None
    return round((now_v - past) / past * 100.0, 8)


def _normalize(row, strategy):
    out = dict(row)
    out["strategy"] = strategy
    out.setdefault("result_row", None)
    return out


def import_candidates_c1a(rows):
    """D1C1A: candidate-table import; SL/trigger computed, fee resolved once."""
    out = []
    for r in rows or []:
        row = _normalize(r, "C1A")
        sl, trig = base_sl_trigger_rule(row.get("entry"), row.get("sl_dollars"), row.get("trigger_dollars"))
        row["sl"] = sl
        row["trigger"] = trig
        row = resolve_commission(row)          # D1CONN: single fee resolution point
        out.append(row)
    return out


def import_candidates_c1b(rows):
    """D1C1B: candidate-table import; 24h delta computed, fee resolved once."""
    out = []
    for r in rows or []:
        row = _normalize(r, "C1B")
        row["delta_24h"] = delta_24h(row)
        row = resolve_commission(row)          # D1CONN: single fee resolution point
        out.append(row)
    return out


def connect(rows, strategy):
    """D1CONN: candidate-table import entry point; notes screen fires at the end."""
    if strategy == "C1A":
        imported = import_candidates_c1a(rows)
    elif strategy == "C1B":
        imported = import_candidates_c1b(rows)
    else:
        raise ValueError("unknown strategy %r" % (strategy,))

    for row in imported:                        # D1NOTE: connector end -> notes screen
        if row.get("result_row"):
            try:
                from notes_screen import record_prod_result
                record_prod_result(row["result_row"])
            except Exception as exc:
                print("[d1-connector] notes screen skipped: %s" % (exc,))
    return imported
