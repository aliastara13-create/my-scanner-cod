import time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fast_fetch import get_json_fast, get_multi_klines_fast

print("=" * 60)
print("  FAST FETCH TEST v2")
print("=" * 60)

# ۳ بار تست
for i in range(3):
    print(f"\n▶ Run {i+1}: Single klines (4h)...")
    t0 = time.time()
    d = get_json_fast("/api/v3/klines?symbol=BTCUSDT&interval=4h&limit=200")
    print(f"  ✅ {time.time()-t0:.2f}s — {len(d) if d else 0} candles")

print("\n▶ Multi klines (5 TF parallel)...")
t0 = time.time()
d = get_multi_klines_fast("BTCUSDT")
print(f"  ✅ {time.time()-t0:.2f}s")
for tf, data in d.items():
    print(f"     {tf}: {len(data) if data else 0}")
