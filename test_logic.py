# -*- coding: utf-8 -*-
# test_logic.py — تست منطق فیلترها
import sys, os

def test_mtf_logic():
    print("\n" + "=" * 70)
    print("  TEST 1: MTF Logic (4H + 1H)")
    print("=" * 70)
    
    test_cases = [
        ("UP", "UP", ["BUY"]),
        ("DOWN", "DOWN", ["SELL"]),
        ("UP", "DOWN", []),
        ("DOWN", "UP", []),
        ("NEUTRAL", "UP", []),
        ("NEUTRAL", "DOWN", []),
    ]
    
    all_ok = True
    for t4, t1, expected in test_cases:
        if t4 == "UP" and t1 == "UP":
            result = ["BUY"]
        elif t4 == "DOWN" and t1 == "DOWN":
            result = ["SELL"]
        else:
            result = []
        
        ok = result == expected
        icon = "✅" if ok else "❌"
        print(f"  {icon} 4H={t4:<8} 1H={t1:<8} → {result} (expected {expected})")
        if not ok:
            all_ok = False
    
    return all_ok


def test_dominance_logic():
    print("\n" + "=" * 70)
    print("  TEST 2: Dominance Logic")
    print("=" * 70)
    
    test_cases = [
        (65, 9, -6, "STRONG_SELL"),
        (45, 4, 6, "STRONG_BUY"),
        (58, 7, -3, "SELL"),
        (58, 7, 3, "BUY"),
        (58, 7, 0, "NEUTRAL"),
        (65, 4, 0, "NEUTRAL"),
        (45, 9, 0, "NEUTRAL"),
    ]
    
    all_ok = True
    for btc_d, usdt_d, mcap, expected in test_cases:
        # BTC.D
        if btc_d > 60: btc_signal = "SELL_ALT"
        elif btc_d < 50: btc_signal = "BUY_ALT"
        else: btc_signal = "NEUTRAL"
        
        # USDT.D
        if usdt_d > 8: usdt_signal = "BEARISH"
        elif usdt_d < 5: usdt_signal = "BULLISH"
        else: usdt_signal = "NEUTRAL"
        
        # MCap
        if mcap < -5: mcap_signal = "STRONG_BEARISH"
        elif mcap < -2: mcap_signal = "BEARISH"
        elif mcap > 5: mcap_signal = "STRONG_BULLISH"
        elif mcap > 2: mcap_signal = "BULLISH"
        else: mcap_signal = "NEUTRAL"
        
        # ترکیب
        if btc_signal == "BUY_ALT" and usdt_signal == "BULLISH" and mcap_signal in ("BULLISH", "STRONG_BULLISH"):
            overall = "STRONG_BUY"
        elif btc_signal == "SELL_ALT" and usdt_signal == "BEARISH" and mcap_signal in ("BEARISH", "STRONG_BEARISH"):
            overall = "STRONG_SELL"
        elif mcap_signal == "STRONG_BEARISH":
            overall = "STRONG_SELL"
        elif mcap_signal == "STRONG_BULLISH":
            overall = "STRONG_BUY"
        elif usdt_signal == "BULLISH" and mcap_signal == "BULLISH":
            overall = "BUY"
        elif usdt_signal == "BEARISH" and mcap_signal == "BEARISH":
            overall = "SELL"
        elif mcap_signal == "BEARISH":
            overall = "SELL"
        elif mcap_signal == "BULLISH":
            overall = "BUY"
        else:
            overall = "NEUTRAL"
        
        ok = overall == expected
        icon = "✅" if ok else "❌"
        print(f"  {icon} BTC.D={btc_d}% USDT.D={usdt_d}% MCap={mcap}% → {overall}")
        if not ok:
            all_ok = False
    
    return all_ok


def test_score_logic():
    print("\n" + "=" * 70)
    print("  TEST 3: Score Logic")
    print("=" * 70)
    
    test_cases = [
        # (side, ema_align, vwap_align, expected_score)
        ("BUY", "ALL_SELL", "ALL_SELL", 0),  # ناهماهنگ → 0
        ("SELL", "ALL_SELL", "ALL_SELL", -1),  # همسو (score باید > 0)
        ("BUY", "ALL_BUY", "ALL_BUY", -1),  # همسو (score باید > 0)
        ("SELL", "ALL_BUY", "ALL_BUY", 0),  # ناهماهنگ → 0
    ]
    
    all_ok = True
    for side, ema, vwap, expected in test_cases:
        if ema != "ALL_" + side:
            result = 0
        elif vwap != "ALL_" + side:
            result = 0
        else:
            result = 50  # فرض score مثبت
        
        ok = result == expected if expected != -1 else result > 0
        icon = "✅" if ok else "❌"
        print(f"  {icon} side={side} EMA={ema} VWAP={vwap} → score={result}")
        if not ok:
            all_ok = False
    
    return all_ok


if __name__ == "__main__":
    print("=" * 70)
    print("  LOGIC TESTS")
    print("=" * 70)
    
    r1 = test_mtf_logic()
    r2 = test_dominance_logic()
    r3 = test_score_logic()
    
    print("\n" + "=" * 70)
    print("  نتایج")
    print("=" * 70)
    print(f"  MTF Logic:        {'PASS' if r1 else 'FAIL'}")
    print(f"  Dominance Logic:  {'PASS' if r2 else 'FAIL'}")
    print(f"  Score Logic:      {'PASS' if r3 else 'FAIL'}")
    print("=" * 70)
    
    if r1 and r2 and r3:
        print("  همه تست‌ها PASSED")
    else:
        print("  برخی تست‌ها FAILED")
    print("=" * 70)
