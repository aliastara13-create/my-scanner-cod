# -*- coding: utf-8 -*-
# profile_test.py — پیدا کردن کدام فیلتر کند است
import time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# import ماژول‌ها
import indicators
import ema_multi_tf
import vwap_session
import dominance
import news

SYMBOL = "BTCUSDT"

print("=" * 80)
print("  PROFILE TEST — " + SYMBOL)
print("=" * 80)

# ۱. Dominance
print("\n▶ Dominance...")
t0 = time.time()
r = dominance.analyze_dominance()
print(f"  ✅ {time.time() - t0:.2f}s — overall={r.get('overall') if r else 'None'}")

# ۲. EMA Multi-TF
print("\n▶ EMA Multi-TF...")
t0 = time.time()
r = ema_multi_tf.analyze_ema_multi_tf(SYMBOL)
print(f"  ✅ {time.time() - t0:.2f}s — {r.get('alignment') if r else 'None'}")

# ۳. VWAP Session
print("\n▶ VWAP Session...")
t0 = time.time()
r = vwap_session.analyze_vwap_sessions(SYMBOL)
print(f"  ✅ {time.time() - t0:.2f}s — {r.get('alignment') if r else 'None'}")

# ۴. Multi (Ichimoku + POC)
print("\n▶ Multi (Ichimoku + POC)...")
t0 = time.time()
r = indicators.analyze_symbol_multi(SYMBOL)
print(f"  ✅ {time.time() - t0:.2f}s — {r.get('alignment') if r else 'None'}")

# ۵. News
print("\n▶ News...")
t0 = time.time()
r = news.get_news_for_symbol(SYMBOL)
print(f"  ✅ {time.time() - t0:.2f}s")

print()
print("=" * 80)
print("  ✅ Profile complete")
print("=" * 80)
