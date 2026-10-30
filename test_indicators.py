# -*- coding: utf-8 -*-
# test_indicators.py — راستی‌آزمایی عمیق indicators
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from indicators import ichimoku, calc_poc, calc_ema, calc_vwap, fetch_klines, analyze_symbol_multi

def test_ichimoku():
    """تست Ichimoku با داده واقعی"""
    print("\n" + "=" * 80)
    print("  TEST 1: Ichimoku Cloud")
    print("=" * 80)
    
    k = fetch_klines("BTCUSDT", "4h", 300)
    if not k:
        print("❌ خطا در fetch")
        return False
    
    ic = ichimoku(k)
    if not ic:
        print("❌ ichimoku None")
        return False
    
    # بررسی‌ها
    checks = []
    
    # ۱. cloud_top > cloud_bottom
    checks.append(("cloud_top > cloud_bottom", ic["cloud_top"] > ic["cloud_bottom"], 
                   f"{ic['cloud_top']} vs {ic['cloud_bottom']}"))
    
    # ۲. قیمت در محدوده منطقی
    price = k[-1]["c"]
    checks.append(("قیمت در محدوده ابر", ic["cloud_bottom"] * 0.7 < price < ic["cloud_top"] * 1.3,
                   f"{price} vs {ic['cloud_bottom']}-{ic['cloud_top']}"))
    
    # ۳. tenkan و kijun منطقی
    checks.append(("tenkan > 0", ic["tenkan"] > 0, f"{ic['tenkan']}"))
    checks.append(("kijun > 0", ic["kijun"] > 0, f"{ic['kijun']}"))
    
    # ۴. position درست
    if price > ic["cloud_top"]:
        expected_pos = "ABOVE"
    elif price < ic["cloud_bottom"]:
        expected_pos = "BELOW"
    else:
        expected_pos = "INSIDE"
    checks.append(("position درست", ic["position"] == expected_pos, 
                   f"{ic['position']} vs {expected_pos}"))
    
    # نمایش
    all_ok = True
    for name, ok, detail in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}: {detail}")
        if not ok:
            all_ok = False
    
    return all_ok


def test_poc():
    """تست POC با داده واقعی"""
    print("\n" + "=" * 80)
    print("  TEST 2: POC (Volume Profile)")
    print("=" * 80)
    
    k = fetch_klines("BTCUSDT", "4h", 300)
    if not k:
        print("❌ خطا در fetch")
        return False
    
    pc = calc_poc(k, bins=50)
    if not pc:
        print("❌ POC None")
        return False
    
    checks = []
    
    # ۱. POC در محدوده قیمت
    highs = [x["h"] for x in k]
    lows = [x["l"] for x in k]
    pmin, pmax = min(lows), max(highs)
    checks.append(("POC در محدوده", pmin <= pc["poc"] <= pmax,
                   f"{pc['poc']} بین {pmin}-{pmax}"))
    
    # ۲. VAL <= POC <= VAH
    checks.append(("VAL <= POC", pc["val"] <= pc["poc"],
                   f"{pc['val']} <= {pc['poc']}"))
    checks.append(("POC <= VAH", pc["poc"] <= pc["vah"],
                   f"{pc['poc']} <= {pc['vah']}"))
    
    # ۳. dist_pct درست
    price = k[-1]["c"]
    expected_dist = (price - pc["poc"]) / pc["poc"] * 100
    checks.append(("dist_pct درست", abs(pc["dist_pct"] - expected_dist) < 0.01,
                   f"{pc['dist_pct']} vs {expected_dist:.3f}"))
    
    all_ok = True
    for name, ok, detail in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}: {detail}")
        if not ok:
            all_ok = False
    
    print(f"\n  📊 POC: {pc['poc']:.2f}")
    print(f"     VAL: {pc['val']:.2f}")
    print(f"     VAH: {pc['vah']:.2f}")
    print(f"     قیمت: {price:.2f} ({pc['dist_pct']:+.3f}%)")
    
    return all_ok


def test_ema():
    """تست EMA با داده مصنوعی"""
    print("\n" + "=" * 80)
    print("  TEST 3: EMA")
    print("=" * 80)
    
    checks = []
    
    # ۱. EMA با داده ثابت
    vals = [100] * 100
    ema = calc_ema(vals, 50)
    checks.append(("EMA ثابت = 100", abs(ema - 100) < 0.01, f"{ema}"))
    
    # ۲. EMA با داده صعودی
    vals = list(range(1, 101))
    ema = calc_ema(vals, 50)
    checks.append(("EMA صعودی > 50", ema > 50, f"{ema:.2f}"))
    
    # ۳. EMA با داده کوتاه
    vals = [100] * 10
    ema = calc_ema(vals, 50)
    checks.append(("EMA کوتاه = None", ema is None, f"{ema}"))
    
    all_ok = True
    for name, ok, detail in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}: {detail}")
        if not ok:
            all_ok = False
    
    return all_ok


def test_vwap():
    """تست VWAP"""
    print("\n" + "=" * 80)
    print("  TEST 4: VWAP")
    print("=" * 80)
    
    k = fetch_klines("BTCUSDT", "1m", 1500)
    if not k:
        print("❌ خطا در fetch")
        return False
    
    checks = []
    
    # VWAP London
    v = calc_vwap(k, 7, 16)
    if v:
        # VWAP باید نزدیک قیمت باشد
        price = k[-1]["c"]
        dist = abs(v - price) / price * 100
        checks.append(("VWAP نزدیک قیمت (<5%)", dist < 5, f"{v:.2f} vs {price:.2f} ({dist:.2f}%)"))
    else:
        checks.append(("VWAP محاسبه شد", False, "None"))
    
    all_ok = True
    for name, ok, detail in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}: {detail}")
        if not ok:
            all_ok = False
    
    return all_ok


def test_alignment():
    """تست همسویی"""
    print("\n" + "=" * 80)
    print("  TEST 5: Alignment Logic")
    print("=" * 80)
    
    checks = []
    
    for sym in ["BTCUSDT", "DOGEUSDT", "UNIUSDT"]:
        r = analyze_symbol_multi(sym)
        if not r:
            checks.append((f"{sym} analysis", False, "None"))
            continue
        
        align = r.get("alignment", "NONE")
        signal = r.get("signal", "NEUTRAL")
        strength = r.get("strength", 0)
        
        # چک: اگر ALL_BUY → signal=BUY
        if align == "ALL_BUY":
            ok = signal == "BUY"
        elif align == "ALL_SELL":
            ok = signal == "SELL"
        elif align in ("MIXED", "NONE"):
            ok = signal == "NEUTRAL"
        else:
            ok = False
        
        checks.append((f"{sym} منطق درست", ok, f"{align} → {signal} (قدرت {strength})"))
    
    all_ok = True
    for name, ok, detail in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}: {detail}")
        if not ok:
            all_ok = False
    
    return all_ok


def test_consistency():
    """تست پایداری — ۳ بار پشت سر هم"""
    print("\n" + "=" * 80)
    print("  TEST 6: Consistency (3 runs)")
    print("=" * 80)
    
    results = []
    for i in range(3):
        r = analyze_symbol_multi("BTCUSDT")
        if r:
            results.append((r["signal"], r.get("strength", 0)))
    
    checks = []
    if len(results) == 3:
        # بررسی پایداری
        signals = [x[0] for x in results]
        stable = len(set(signals)) == 1
        checks.append(("پایداری سیگنال در 3 اجرا", stable, f"{signals}"))
    else:
        checks.append(("3 اجرا", False, f"فقط {len(results)} اجرا"))
    
    all_ok = True
    for name, ok, detail in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}: {detail}")
        if not ok:
            all_ok = False
    
    return all_ok


def test_edge_cases():
    """تست حالات مرزی"""
    print("\n" + "=" * 80)
    print("  TEST 7: Edge Cases")
    print("=" * 80)
    
    checks = []
    
    # ۱. داده خالی
    try:
        ic = ichimoku([])
        checks.append(("Ichimoku داده خالی = None", ic is None, f"{ic}"))
    except Exception as e:
        checks.append(("Ichimoku داده خالی (بدون crash)", False, f"crash: {e}"))
    
    # ۲. داده کوتاه
    try:
        short = [{"t": i, "o": 100, "h": 101, "l": 99, "c": 100, "v": 10} for i in range(5)]
        ic = ichimoku(short)
        checks.append(("Ichimoku داده کوتاه = None", ic is None, f"{ic}"))
    except Exception as e:
        checks.append(("Ichimoku داده کوتاه (بدون crash)", False, f"crash: {e}"))
    
    # ۳. داده ثابت (بدون نوسان)
    try:
        flat = [{"t": i*60000, "o": 100, "h": 100, "l": 100, "c": 100, "v": 10} for i in range(100)]
        pc = calc_poc(flat, bins=50)
        # باید None بدهد یا کار کند
        checks.append(("POC داده ثابت (بدون crash)", True, "OK"))
    except Exception as e:
        checks.append(("POC داده ثابت (بدون crash)", False, f"crash: {e}"))
    
    all_ok = True
    for name, ok, detail in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}: {detail}")
        if not ok:
            all_ok = False
    
    return all_ok


if __name__ == "__main__":
    print("=" * 80)
    print("  ASTRA INDICATORS — DEEP TEST")
    print("=" * 80)
    
    results = {}
    results["Ichimoku"] = test_ichimoku()
    results["POC"] = test_poc()
    results["EMA"] = test_ema()
    results["VWAP"] = test_vwap()
    results["Alignment"] = test_alignment()
    results["Consistency"] = test_consistency()
    results["Edge Cases"] = test_edge_cases()
    
    print("\n" + "=" * 80)
    print("  📊 نتایج نهایی")
    print("=" * 80)
    
    all_pass = True
    for name, ok in results.items():
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}: {'PASS' if ok else 'FAIL'}")
        if not ok:
            all_pass = False
    
    print()
    if all_pass:
        print("  🎉 همه تست‌ها PASSED — آماده ادغام")
    else:
        print("  ⚠️ برخی تست‌ها FAILED — قبل از ادغام رفع شود")
    
    print("=" * 80)
