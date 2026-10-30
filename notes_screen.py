# -*- coding: utf-8 -*-
"""D1: notes screen - persistent annotations for connector imports.

# D1NOTE: record_prod_result(row) appends the scanner_v4.py prod-run result row
# to NOTES_FILE (JSONL, one record per line). Screen output mirrors the note.
Notes failures are contained by the connector (import never breaks).
"""
import json
import os
import time

NOTES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes_d1.jsonl")


def record_prod_result(row):
    """D1NOTE: stamp one scanner_v4 prod-run result row; returns the record."""
    rec = {
        "ts": round(time.time(), 6),
        "run": "scanner_v4_prod",
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "entry": row.get("entry"),
        "sl": row.get("sl"),
        "tp": row.get("tp"),
        "note": "scanner_v4.py prod-run result row, stamped by D1 connector",
    }
    with open(NOTES_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    print("[notes-screen] %s %s entry=%s sl=%s tp=%s" % (
        rec["symbol"], rec["side"], rec["entry"], rec["sl"], rec["tp"]))
    return rec
