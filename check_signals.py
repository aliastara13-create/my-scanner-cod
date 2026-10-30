# -*- coding: utf-8 -*-
# check_signals.py — بررسی سیگنال‌های فعلی
import json, glob, os

BASE = os.path.dirname(os.path.abspath(__file__))
files = sorted(glob.glob(os.path.join(BASE, "results", "live_*.json")))
if not files:
    print("[X] No live file")
    exit(1)

with open(files[-1], encoding="utf-8") as f:
    live = json.load(f)

print("=" * 90)
print("  SIGNALS ANALYSIS — " + live.get("generated", ""))
print("=" * 90)

count = 0
for r in live.get("results", []):
    if not r.get("signals"):
        continue
    for s in r["signals"]:
        if s.get("zone_status") not in ("IN_ZONE", "NEAR"):
            continue
        
        ema = r.get("ema_mtf") or {}
        vwap = r.get("vwap") or {}
        multi = r.get("multi") or {}
        
        ema_align = ema.get("alignment", "N/A")
        vwap_align = vwap.get("alignment", "N/A")
        multi_align = multi.get("alignment", "N/A")
        
        side = s.get("side", "?")
        zone = s.get("zone_status", "?")
        
        # چک همسویی
        ema_ok = ema_align == ("ALL_" + side)
        vwap_ok = vwap_align == ("ALL_" + side)
        multi_ok = multi_align == ("ALL_" + side)
        
        print()
        print(f"  {r['symbol']:<10} | {side:<5} | {zone:<8} | score={r.get('score')} | stars={r.get('stars')}")
        print(f"    EMA50:  {ema_align:<12} {'✅' if ema_ok else '❌'}")
        print(f"    VWAP:   {vwap_align:<12} {'✅' if vwap_ok else '❌'}")
        print(f"    Multi:  {multi_align:<12} {'✅' if multi_ok else '❌'}")
        
        # جزئیات multi
        if multi:
            ic = multi.get("ichimoku") or {}
            pc = multi.get("poc") or {}
            print(f"    Ichimoku: {ic.get('position', 'N/A'):<8} | POC: {pc.get('position', 'N/A'):<8}")
        
        count += 1

print()
print("=" * 90)
print(f"  Total: {count} signals")
print("=" * 90)
