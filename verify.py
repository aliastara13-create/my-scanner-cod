# -*- coding: utf-8 -*-
# verify.py — Auto verification for signals (5-star priority)
# STANDALONE
import json, os
from datetime import datetime

def verify_signal(r, s):
    """
    راستی‌آزمایی یک سیگنال با معیارهای مشخص
    Returns: dict with checks, passed, score
    """
    checks = []
    
    # ۱. قیمت داخل ناحیه؟ (با tolerance 0.1%)
    in_zone = s.get("zone_status") == "IN_ZONE"
    # بررسی دستی با tolerance
    price = r["price"]
    z_lo = s.get("entry_zone_lo", 0)
    z_hi = s.get("entry_zone_hi", 0)
    tol = 0.001  # 0.1%
    near_zone = (z_lo * (1 - tol) <= price <= z_hi * (1 + tol))
    passed = in_zone or near_zone
    checks.append({
        "name": "قیمت داخل ناحیه",
        "passed": passed,
        "detail": f"قیمت {price} vs ناحیه {z_lo}-{z_hi}" + (" (با tolerance)" if near_zone and not in_zone else "")
    })
    
    # ۲. SL منطقی (زیر حمایت نزدیک)
    supports_1h = r.get("sr", {}).get("1h", {}).get("supports", [])
    if supports_1h:
        nearest_support = supports_1h[0]["price"]
        sl_ok = (s["side"] == "BUY" and s["sl"] < nearest_support) or \
                (s["side"] == "SELL" and s["sl"] > nearest_support)
    else:
        sl_ok = False  # DQ-2 fail-closed: missing S/R = not verified (was fail-open True)
        nearest_support = None
    checks.append({
        "name": "SL منطقی",
        "passed": sl_ok,
        "detail": f"SL={s['sl']} vs حمایت={nearest_support}"
    })
    
    # ۳. TP منطقی — عبور از مقاومت‌های کوچک OK، عبور از همه مقاومت‌ها غیرمنطقی
    resistances_1h = r.get("sr", {}).get("1h", {}).get("resistances", [])
    resistances_4h = r.get("sr", {}).get("4h", {}).get("resistances", [])
    resistances_1d = r.get("sr", {}).get("1d", {}).get("resistances", [])
    
    all_resistances = [x["price"] for x in resistances_1h] + \
                      [x["price"] for x in resistances_4h] + \
                      [x["price"] for x in resistances_1d]
    
    if s["side"] == "BUY" and all_resistances:
        # TP باید حداقل از یک مقاومت عبور نکند (به بزرگ‌ترین مقاومت برسد)
        max_resistance = max(all_resistances)
        if s["tp"] >= max_resistance * 1.05:
            # TP از بزرگ‌ترین مقاومت هم عبور می‌کند → غیرمنطقی
            tp_ok = False
            tp_detail = f"TP={s['tp']} > بزرگ‌ترین مقاومت={max_resistance} (خطر برگشت)"
        else:
            tp_ok = True
            nearest = min([x["price"] for x in resistances_1h]) if resistances_1h else max_resistance
            tp_detail = f"TP={s['tp']} (نزدیک‌ترین مقاومت={nearest}, OK برای عبور)"
    elif s["side"] == "SELL" and all_resistances:
        min_resistance = min(all_resistances)
        if s["tp"] <= min_resistance * 0.95:
            tp_ok = False
            tp_detail = f"TP={s['tp']} < کوچک‌ترین مقاومت={min_resistance} (خطر برگشت)"
        else:
            tp_ok = True
            nearest = min([x["price"] for x in resistances_1h]) if resistances_1h else min_resistance
            tp_detail = f"TP={s['tp']} (نزدیک‌ترین مقاومت={nearest}, OK)"
    else:
        tp_ok = True
        tp_detail = "S/R ندارد"
    
    checks.append({
        "name": "TP منطقی",
        "passed": tp_ok,
        "detail": tp_detail
    })
    
    # ۴. R:R منطقی (1.0 - 5.0)
    rr = s.get("rr", 0)
    rr_ok = 1.0 <= rr <= 5.0
    checks.append({
        "name": "R:R منطقی",
        "passed": rr_ok,
        "detail": f"R:R={rr} (محدوده 1.0-5.0)"
    })
    
    # ۵. ADX (روند قوی)
    adx = r.get("adx", 0)
    adx_ok = adx >= 25
    checks.append({
        "name": "ADX قوی",
        "passed": adx_ok,
        "detail": f"ADX={adx} (حداقل 25)"
    })
    
    # ۶. حجم (بالای $10M)
    vol = r.get("volume_24h", 0)
    vol_ok = vol >= 10e6
    checks.append({
        "name": "حجم کافی",
        "passed": vol_ok,
        "detail": f"حجم ${vol/1e6:.1f}M (حداقل $10M)"
    })
    
    # ۷. Regime (STRONG یا TRENDING)
    regime = r.get("regime", "")
    regime_ok = regime in ("STRONG", "TRENDING")
    checks.append({
        "name": "Regime مناسب",
        "passed": regime_ok,
        "detail": f"Regime={regime}"
    })
    
    # محاسبه امتیاز نهایی
    passed_count = sum(1 for c in checks if c["passed"])
    total = len(checks)
    confidence = round(passed_count / total * 100, 1)
    
    return {
        "symbol": r["symbol"],
        "side": s["side"],
        "stars": r.get("stars", 0),
        "checks": checks,
        "passed": passed_count,
        "total": total,
        "confidence": confidence,
        "verified": passed_count >= 5,  # حداقل 5 از 7
        "ts": datetime.now().isoformat(),
    }

def verify_all_5star(live_data):
    """راستی‌آزمایی همه سیگنال‌های ۵ ستاره"""
    results = []
    for r in live_data.get("results", []):
        if r.get("stars", 0) < 5:
            continue  # فقط ۵ ستاره
        for s in r.get("signals", []):
            if s.get("zone_status") in ("IN_ZONE", "NEAR"):
                v = verify_signal(r, s)
                results.append(v)
    return results

def format_verification_report(verifications):
    """فرمت گزارش راستی‌آزمایی"""
    if not verifications:
        return "هیچ سیگنال ۵ ستاره‌ای برای راستی‌آزمایی نیست."
    
    lines = []
    lines.append("=" * 70)
    lines.append("  🔍 گزارش راستی‌آزمایی سیگنال‌های ۵ ستاره")
    lines.append("=" * 70)
    lines.append("")
    
    for v in verifications:
        status = "✅ تأیید شد" if v["verified"] else "⚠️ نیاز به بررسی"
        lines.append(f"  📊 {v['symbol']} | {v['side']} | ⭐⭐⭐⭐⭐ {status}")
        lines.append(f"     اطمینان: {v['confidence']}% ({v['passed']}/{v['total']})")
        for c in v["checks"]:
            icon = "✅" if c["passed"] else "❌"
            lines.append(f"     {icon} {c['name']}: {c['detail']}")
        lines.append("")
    
    lines.append("=" * 70)
    return "\n".join(lines)

if __name__ == "__main__":
    # تست
    BASE = os.path.dirname(os.path.abspath(__file__))
    RESULTS = os.path.join(BASE, "results")
    
    # آخرین live
    import glob
    files = sorted(glob.glob(os.path.join(RESULTS, "live_*.json")))
    if not files:
        print("No live file found")
        exit(1)
    
    with open(files[-1], encoding="utf-8") as f:
        live = json.load(f)
    
    verifications = verify_all_5star(live)
    report = format_verification_report(verifications)
    print(report)
    
    # ذخیره
    out = os.path.join(RESULTS, "verify_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generated": datetime.now().isoformat(), "verifications": verifications}, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Saved: {out}")


