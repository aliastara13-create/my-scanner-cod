"""Realized-R performance stats from journal rows (pure functions, no I/O)."""

def realized_r(row, entry_mode="zone_mid"):
    side = (row.get("side") or "").upper()
    sign = 1 if side in ("BUY", "LONG") else -1 if side in ("SELL", "SHORT") else None
    sl, closed = row.get("sl"), row.get("closed_price")
    if entry_mode == "zone_mid":
        lo, hi = row.get("entry_lo"), row.get("entry_hi")
        entry = (lo + hi) / 2.0 if lo is not None and hi is not None else None
    else:
        entry = row.get("price")
    if sign is None or sl is None or closed is None or entry is None:
        return None
    risk = abs(entry - sl)
    if risk == 0:
        return None
    return sign * (closed - entry) / risk

def compute_performance(rows, entry_mode="zone_mid"):
    trades, skipped = [], 0
    for r in rows:
        if r.get("result") not in ("TP", "SL", "TIME"):
            continue
        rv = realized_r(r, entry_mode)
        if rv is None:
            skipped += 1
            continue
        trades.append((r.get("closed_ts") or "", rv))
    trades.sort(key=lambda t: t[0])
    equity = peak = max_dd = 0.0
    for _, rv in trades:
        equity += rv
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    n = len(trades)
    wins = sum(1 for _, rv in trades if rv > 0)
    return {"trades": n, "skipped_no_data": skipped,
            "win_rate": (wins / n * 100) if n else None,
            "total_r": equity, "avg_r": (equity / n) if n else None,
            "max_drawdown_r": max_dd}
