# -*- coding: utf-8 -*-
# fast_fetch.py — موازی‌سازی + cache دیسک
import concurrent.futures
import urllib.request, json, time, os, hashlib

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

ENDPOINTS = [
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://data-api.binance.vision",
    "https://api1.binance.com",
    "https://api2.binance.com",
]

_PREFERRED = {"ep": None, "ts": 0}

def _cache_key(path):
    return hashlib.md5(path.encode()).hexdigest()[:16]

def _cache_get(path, max_age=60):
    key = _cache_key(path)
    fp = os.path.join(CACHE_DIR, key + ".json")
    if not os.path.exists(fp):
        return None
    if time.time() - os.path.getmtime(fp) > max_age:
        return None
    try:
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _cache_set(path, data):
    key = _cache_key(path)
    fp = os.path.join(CACHE_DIR, key + ".json")
    try:
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass

def _fetch_one(ep, path, timeout):
    try:
        req = urllib.request.Request(ep + path, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ep": ep, "data": json.loads(r.read().decode())}
    except Exception:
        return None

def get_json_fast(path, timeout=8, cache_ttl=300):
    # ۱. Cache دیسک
    cached = _cache_get(path, cache_ttl)
    if cached is not None:
        return cached
    
    # ۲. Endpoint ترجیحی
    if _PREFERRED["ep"] and (time.time() - _PREFERRED["ts"] < 300):
        result = _fetch_one(_PREFERRED["ep"], path, timeout)
        if result:
            _PREFERRED["ts"] = time.time()
            _cache_set(path, result["data"])
            return result["data"]
    
    # ۳. موازی
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(ENDPOINTS)) as ex:
        tasks = [(ep, ex.submit(_fetch_one, ep, path, timeout)) for ep in ENDPOINTS]
        for ep, fut in tasks:
            try:
                result = fut.result(timeout=timeout+2)
                if result:
                    _PREFERRED["ep"] = result["ep"]
                    _PREFERRED["ts"] = time.time()
                    _cache_set(path, result["data"])
                    return result["data"]
            except Exception:
                continue
    return None

def get_multi_klines_fast(symbol):
    paths = {
        "5m": f"/api/v3/klines?symbol={symbol}&interval=5m&limit=200",
        "15m": f"/api/v3/klines?symbol={symbol}&interval=15m&limit=200",
        "1h": f"/api/v3/klines?symbol={symbol}&interval=1h&limit=200",
        "4h": f"/api/v3/klines?symbol={symbol}&interval=4h&limit=200",
        "1m": f"/api/v3/klines?symbol={symbol}&interval=1m&limit=500",
    }
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futures = {tf: ex.submit(get_json_fast, p) for tf, p in paths.items()}
        for tf, f in futures.items():
            results[tf] = f.result()
    return results

