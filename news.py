# -*- coding: utf-8 -*-
# news.py — News & Events for symbols
import os, json, time, urllib.request, urllib.parse
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
NEWS_FILE = os.path.join(DATA, "news_cache.json")

os.makedirs(DATA, exist_ok=True)

def get_json(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"News fetch error: {e}")
        return None

def fetch_news(symbol="SOL"):
    """CoinGecko News API"""
    base = symbol.replace("USDT", "").lower()
    url = f"https://api.coingecko.com/api/v3/coins/{base}"
    d = get_json(url)
    if not d:
        return []
    news = []
    # CoinGecko doesn't have news directly, use status_updates
    for u in d.get("status_updates", [])[:5]:
        news.append({
            "title": u.get("description", "")[:200],
            "category": u.get("category", ""),
            "created_at": u.get("created_at", ""),
        })
    return news

def fetch_events(symbol):
    """Event calendar (placeholder)"""
    events = {
        "SOLUSDT": [
            {"date": "2026-10-21", "event": "Alpenglow Upgrade", "impact": "high"},
        ],
        "BTCUSDT": [
            {"date": "2026-11-01", "event": "FOMC Meeting", "impact": "high"},
        ],
    }
    return events.get(symbol, [])

def load_news_cache():
    if os.path.exists(NEWS_FILE):
        try:
            with open(NEWS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

def save_news_cache(data):
    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_news_for_symbol(symbol):
    cache = load_news_cache()
    cached = cache.get(symbol, {})
    ts = cached.get("ts", 0)
    # cache for 1 hour
    if time.time() - ts < 3600:
        return cached
    events = fetch_events(symbol)
    result = {
        "ts": time.time(),
        "symbol": symbol,
        "events": events,
    }
    cache[symbol] = result
    save_news_cache(cache)
    return result

if __name__ == "__main__":
    print("=" * 70)
    print("  ASTRA NEWS & EVENTS")
    print("=" * 70)
    
    # نمایش رویدادهای SOL
    print("\n📅 SOLUSDT Events:")
    events = get_news_for_symbol("SOLUSDT")
    for e in events.get("events", []):
        print(f"  {e['date']} | {e['event']} | impact: {e['impact']}")
    
    print("\n📅 BTCUSDT Events:")
    events = get_news_for_symbol("BTCUSDT")
    for e in events.get("events", []):
        print(f"  {e['date']} | {e['event']} | impact: {e['impact']}")
