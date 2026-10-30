# -*- coding: utf-8 -*-
# test_engine.py — Sanity tests (from z.ai TVRemix)
import sys
sys.path.insert(0, r"E:\RAMAN.RAMIYA.ARAN\Robot.03-----Z.ai\ASTRA_SCANNER_V1")

from scanner_v4 import pivots, gp_zone

def test_pivots_high():
    """تشخیص پیوت سقف"""
    arr = [1, 3, 5, 3, 1]
    result = pivots(arr, 1, "high")
    assert result == [2], f"Expected [2], got {result}"
    print("✅ test_pivots_high PASSED")

def test_pivots_low():
    """تشخیص پیوت کف"""
    arr = [5, 3, 1, 3, 5]
    result = pivots(arr, 1, "low")
    assert result == [2], f"Expected [2], got {result}"
    print("✅ test_pivots_low PASSED")

def test_gp_zone_buy():
    """Golden Pocket BUY"""
    z1, z2 = gp_zone(807.49, 674.60, "BUY")
    # z1 باید 721.11 باشد، z2 باید 725.36
    assert abs(z1 - 721.11) < 0.5, f"z1={z1}"
    assert abs(z2 - 725.36) < 0.5, f"z2={z2}"
    print(f"✅ test_gp_zone_buy PASSED (z1={z1:.2f}, z2={z2:.2f})")

def test_gp_zone_sell():
    """Golden Pocket SELL"""
    z1, z2 = gp_zone(807.49, 674.60, "SELL")
    assert abs(z1 - 756.73) < 0.5, f"z1={z1}"
    print(f"✅ test_gp_zone_sell PASSED (z1={z1:.2f}, z2={z2:.2f})")

if __name__ == "__main__":
    print("=" * 70)
    print("  ASTRA SCANNER — Sanity Tests")
    print("=" * 70)
    test_pivots_high()
    test_pivots_low()
    test_gp_zone_buy()
    test_gp_zone_sell()
    print("=" * 70)
    print("✅ ALL TESTS PASSED")
