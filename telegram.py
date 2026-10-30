# -*- coding: utf-8 -*-
# telegram.py — Send signals to Telegram
import os, json, glob, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
RESULTS = os.path.join(BASE, "results")
SETTINGS = os.path.join(DATA, "settings.json")
HUNTER_ALERTS_FILE = os.path.join(DATA, "hunter_alerts.json")

def mask_token(token):
    """ماسک توکن برای نمایش/لاگ — هرگز توکن کامل نمایش داده نمی‌شود"""
    if not token:
        return ""
    t = str(token)
    if len(t) <= 8:
        return "****"
    return t[:4] + "****" + t[-4:]

def send_telegram(token, chat_id, message):
    if not token or not chat_id:
        return {"ok": False, "error": "no token or chat_id"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read().decode("utf-8"))
            return {"ok": resp.get("ok", False), "result": resp.get("result", {})}
    except Exception as e:
        err = str(e)
        if token and str(token) in err:
            err = err.replace(str(token), mask_token(token))
        return {"ok": False, "error": err}

def format_signal(r, s):
    side_icon = "🟢" if s["side"] == "BUY" else "🔴"
    status = "🎯 IN ZONE" if s["zone_status"] == "IN_ZONE" else "⚡ NEAR"
    stars = "⭐" * r.get("stars", 1)
    msg = f"""<b>{side_icon} {s['side']} {r['symbol']}</b>
<b>{status}</b> {stars}

💰 قیمت: <code>{r['price']}</code>
📍 ورود: <code>{s['entry_zone_lo']} - {s['entry_zone_hi']}</code>
🛑 SL: <code>{s['sl']}</code>
🎯 TP: <code>{s['tp']}</code>
📊 R:R: <b>{s['rr']}</b>

📈 ADX: {r['adx']} [{r['regime']}]
🏆 امتیاز: <b>{r['score']}</b>

⚡ ASTRA SCANNER · DeepSeek Ali.Astara13"""
    return msg

# ==================== Hunter Alerts ====================
def load_settings():
    if os.path.exists(SETTINGS):
        try:
            with open(SETTINGS, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("[telegram] settings error:", e)
    return {}

def latest_hunter_file():
    files = sorted(glob.glob(os.path.join(RESULTS, "hunter_*.json")))
    return files[-1] if files else None

def format_hunter_alert(setup):
    line = setup.get("line") or {}
    brk = line.get("breakout") or {}
    side_icon = "🟢" if setup.get("signal") == "BUY" else "🔴"
    dir_icon = "📈" if setup.get("direction") == "UPTREND" else "📉"
    brk_txt = "—"
    if brk.get("broken"):
        brk_txt = "<b>%s</b>" % (brk.get("type") or "BREAK")
        if brk.get("bars_ago") is not None:
            brk_txt += " · %s کندل پیش" % brk["bars_ago"]
    score = line.get("score")
    touches = line.get("touches")
    dist = line.get("dist_pct")
    msg = """⚡ <b>HUNTER ALERT — تریگر شد</b>

{side_icon} <b>{signal} {symbol}</b> · {tf}
{dir_icon} روند: <b>{direction}</b>

💰 قیمت فعلی: <code>{price}</code>
🏆 امتیاز خط: <b>{score}</b>
📍 تعداد برخورد: <b>{touches}</b>
🎯 فاصله از خط: <b>{dist}%</b>
⚡ بریک‌اوت: {brk}

⚡ ASTRA SCANNER · DeepSeek Ali.Astara13""".format(
        side_icon=side_icon,
        signal=setup.get("signal"),
        symbol=setup.get("symbol"),
        tf=setup.get("tf"),
        dir_icon=dir_icon,
        direction=setup.get("direction"),
        price=setup.get("current_price"),
        score=score if score is not None else "—",
        touches=touches if touches is not None else "—",
        dist=dist if dist is not None else "—",
        brk=brk_txt,
    )
    return msg

def send_hunter_alert(setup, token=None, chat_id=None):
    """فقط برای ستاپTRIGGERED — با send_telegram موجود ارسال می‌شود"""
    if not setup or setup.get("status") != "TRIGGERED":
        return {"ok": False, "error": "not TRIGGERED"}
    if not token or not chat_id:
        st = load_settings()
        token = token or st.get("telegram_token", "")
        chat_id = chat_id or st.get("telegram_chat", "")
    msg = format_hunter_alert(setup)
    return send_telegram(token, chat_id, msg)

def _hunter_key(setup):
    line = setup.get("line") or {}
    brk = line.get("breakout") or {}
    return "|".join(str(x) for x in (
        setup.get("symbol"), setup.get("tf"),
        setup.get("direction"), setup.get("signal"),
        brk.get("break_idx", ""),
    ))

def load_alerted_hunters():
    try:
        if os.path.exists(HUNTER_ALERTS_FILE):
            with open(HUNTER_ALERTS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as e:
        print("[telegram] hunter_alerts load error:", e)
    return []

def save_alerted_hunters(keys):
    os.makedirs(DATA, exist_ok=True)
    with open(HUNTER_ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(keys[-500:], f, ensure_ascii=False, indent=1)

def check_and_alert_hunter(path=None, token=None, chat_id=None):
    """آخرین hunter_*.json را می‌خواند و فقط برای TRIGGEREDهای جدید آلارم می‌فرستد"""
    path = path or latest_hunter_file()
    if not path or not os.path.exists(path):
        print("[hunter-alert] no hunter file found")
        return {"ok": False, "error": "no hunter file", "sent": 0, "skipped": 0, "total_triggered": 0}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print("[hunter-alert] read error:", e)
        return {"ok": False, "error": str(e), "sent": 0, "skipped": 0, "total_triggered": 0}

    if not token or not chat_id:
        st = load_settings()
        token = token or st.get("telegram_token", "")
        chat_id = chat_id or st.get("telegram_chat", "")
    if not token or not chat_id:
        print("[hunter-alert] no token/chat_id in settings")
        return {"ok": False, "error": "no token or chat_id", "sent": 0, "skipped": 0, "total_triggered": 0}

    triggered = [s for s in data.get("setups", []) if s.get("status") == "TRIGGERED"]
    known = set(load_alerted_hunters())
    sent, skipped = 0, 0
    for s in triggered:
        key = _hunter_key(s)
        if key in known:
            skipped += 1
            continue
        res = send_hunter_alert(s, token, chat_id)
        if res.get("ok"):
            known.add(key)
            sent += 1
            print("  ✅ Hunter alert: %s %s %s" % (s.get("symbol"), s.get("signal"), s.get("tf")))
        else:
            print("  ❌ Hunter alert failed: %s — %s" % (s.get("symbol"), res.get("error", res)))
    if sent:
        save_alerted_hunters(sorted(known))
    return {
        "ok": True,
        "file": os.path.basename(path),
        "total_triggered": len(triggered),
        "sent": sent,
        "skipped": skipped,
    }

if __name__ == "__main__":
    print("Telegram module ready")
