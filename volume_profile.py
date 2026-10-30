# -*- coding: utf-8 -*-
# volume_profile.py - ASTRA SCANNER Extension
# Purpose: Calculate Volume Profile (POC, VA) without modifying core files.
# Logic: Standard Volume Profile based on price-binning of klines.

import os
import json
import math
import time
from datetime import datetime
import io_atomic  # D18 atomic writes
from fast_fetch import get_json_fast

BASE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(BASE, "results")
DATA = os.path.join(BASE, "data")

# Configuration
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AAVEUSDT"]
BIN_SIZE_PCT = 0.001  # 0.1% price bins for volume aggregation
VA_PERCENT = 0.70     # 70% Value Area

def calculate_volume_profile(symbol, interval="1h", limit=500):
    """
    Calculates POC, Value Area, and HVNs for a given symbol.
    """
    path = f"/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    klines = get_json_fast(path)
    
    if not klines:
        return None

    # 1. Price Binning
    prices = [float(k[4]) for k in klines] # Close prices
    volumes = [float(k[5]) for k in klines] # Volumes
    
    min_p, max_p = min(prices), max(prices)
    bin_width = (max_p - min_p) * BIN_SIZE_PCT
    if bin_width == 0: return None
    
    bins = {}
    for p, v in zip(prices, volumes):
        bin_idx = math.floor((p - min_p) / bin_width)
        bin_price = min_p + (bin_idx * bin_width)
        bins[bin_price] = bins.get(bin_price, 0) + v

    if not bins: return None

    # 2. Find POC (Point of Control)
    poc_price = max(bins, key=bins.get)
    total_volume = sum(bins.values())

    # 3. Calculate Value Area (VA)
    sorted_bins = sorted(bins.items(), key=lambda x: x[0])
    va_vol = 0
    va_low = poc_price
    va_high = poc_price
    
    # Expand from POC until VA_PERCENT of volume is reached
    current_va_vol = bins[poc_price]
    while current_va_vol < total_volume * VA_PERCENT:
        # Check bin above and below
        # This is a simplified version of the VA algorithm
        below = None
        above = None
        
        # Find bin below VA_LOW
        for p, v in sorted_bins:
            if p < va_low: below = (p, v)
        # Find bin above VA_HIGH
        for p, v in reversed(sorted_bins):
            if p > va_high: above = (p, v)
            
        if not below and not above: break
        
        if below and (not above or below[1] >= above[1]):
            va_low = below[0]
            current_va_vol += below[1]
        elif above:
            va_high = above[0]
            current_va_vol += above[1]
        else:
            break

    # 4. High Volume Nodes (HVN) - Top 3 bins excluding POC
    hvn = sorted(bins.items(), key=lambda x: x[1], reverse=True)[1:4]
    
    return {
        "symbol": symbol,
        "timestamp": datetime.utcnow().isoformat(),
        "poc": round(poc_price, 8),
        "va_low": round(va_low, 8),
        "va_high": round(va_high, 8),
        "total_vol": total_volume,
        "hvn": [{"price": round(p, 8), "vol": v} for p, v in hvn]
    }

def run_profile_scan(symbols=None):
    symbols = symbols or DEFAULT_SYMBOLS
    results = {}
    
    for sym in symbols:
        print(f"Analyzing Volume Profile for {sym}...")
        res = calculate_volume_profile(sym)
        if res:
            results[sym] = res
            # Save individual atomic file for each symbol
            save_path = os.path.join(RESULTS, f"vol_profile_{sym}.json")
            io_atomic.atomic_write_json(save_path, res)
            
    return results

if __name__ == "__main__":
    # To test: python volume_profile.py
    start = time.time()
    final_res = run_profile_scan()
    print(f"Done in {time.time()-start:.2f}s. Results saved to {RESULTS}")
