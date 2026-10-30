# -*- coding: utf-8 -*-
# dominance.py — BTC.D + USDT.D از CoinGecko
# منبع: https://api.coingecko.com/api/v3/global
import os, json, urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))

def get_json(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  dominance error: {e}")
        return None

def analyze_dominance():
    """تحلیل BTC.D + USDT.D از CoinGecko"""
    data = get_json("https://api.coingecko.com/api/v3/global")
    if not data or "data" not in data:
        return None
    
    d = data["data"]
    btc_d = round(d["market_cap_percentage"].get("btc", 0), 2)
    usdt_d = round(d["market_cap_percentage"].get("usdt", 0), 2)
    eth_d = round(d["market_cap_percentage"].get("eth", 0), 2)
    total_mcap = d["total_market_cap"].get("usd", 0)
    mcap_change_24h = round(d["market_cap_change_percentage_24h_usd"], 2)
    
    # تحلیل BTC.D
    if btc_d > 60:
        btc_state = "HIGH"
        btc_signal = "SELL_ALT"  # آلت‌کوین ضعیف
    elif btc_d < 50:
        btc_state = "LOW"
        btc_signal = "BUY_ALT"  # آلت‌کوین قوی
    else:
        btc_state = "MID"
        btc_signal = "NEUTRAL"
    
    # تحلیل USDT.D
    if usdt_d > 8:
        usdt_state = "HIGH"
        usdt_signal = "BEARISH"  # پول خارج می‌شود
    elif usdt_d < 5:
        usdt_state = "LOW"
        usdt_signal = "BULLISH"  # پول وارد می‌شود
    else:
        usdt_state = "MID"
        usdt_signal = "NEUTRAL"
    
    # تحلیل Market Cap Change 24h
    if mcap_change_24h < -5:
        mcap_signal = "STRONG_BEARISH"
    elif mcap_change_24h < -2:
        mcap_signal = "BEARISH"
    elif mcap_change_24h > 5:
        mcap_signal = "STRONG_BULLISH"
    elif mcap_change_24h > 2:
        mcap_signal = "BULLISH"
    else:
        mcap_signal = "NEUTRAL"
    
    # ترکیب نهایی
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
    
    return {
        "btc_d": btc_d,
        "usdt_d": usdt_d,
        "eth_d": eth_d,
        "total_mcap": total_mcap,
        "mcap_change_24h": mcap_change_24h,
        "btc_state": btc_state,
        "usdt_state": usdt_state,
        "btc_signal": btc_signal,
        "usdt_signal": usdt_signal,
        "mcap_signal": mcap_signal,
        "overall": overall,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

if __name__ == "__main__":
    print("=" * 80)
    print("  ASTRA DOMINANCE — CoinGecko")
    print("=" * 80)
    
    r = analyze_dominance()
    if not r:
        print("❌ خطا در دریافت داده")
        exit(1)
    
    print(f"\n📊 BTC.D:  {r['btc_d']}% ({r['btc_state']}) → {r['btc_signal']}")
    print(f"📊 USDT.D: {r['usdt_d']}% ({r['usdt_state']}) → {r['usdt_signal']}")
    print(f"📊 ETH.D:  {r['eth_d']}%")
    print(f"\n💰 Total Market Cap: ${r['total_mcap']/1e12:.2f}T")
    print(f"📈 24h Change: {r['mcap_change_24h']:+.2f}%")
    print(f"\n🎯 نتیجه: {r['overall']}")
    
    if r["overall"] == "STRONG_BUY":
        print("\n🟢🟢 STRONG BUY — پول وارد آلت‌کوین‌ها می‌شود")
    elif r["overall"] == "BUY":
        print("\n🟢 BUY — بازار صعودی")
    elif r["overall"] == "STRONG_SELL":
        print("\n🔴🔴 STRONG SELL — پول از کریپتو خارج می‌شود")
    elif r["overall"] == "SELL":
        print("\n🔴 SELL — بازار نزولی")
    else:
        print("\n⚪ NEUTRAL — بازار خنثی")

