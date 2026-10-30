# -*- coding: utf-8 -*-
# agent_decision.py — لایه تصمیم ایجنت (فاز ۲۰)
# وزن‌دهی + ترکیب + تصمیم نهایی + Position Sizing
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class AgentDecision:
    """
    لایه تصمیم ایجنت
    وزن‌دهی + ترکیب + تصمیم نهایی + Position Sizing
    """
    
    def __init__(self, weights=None, threshold=70):
        self.weights = weights or {
            "fibo":       0.30,   # استراتژی اصلی
            "mtf":        0.20,   # Multi-Timeframe
            "ichimoku":   0.15,   # ابر کومو
            "vwap":       0.15,   # میانگین وزنی
            "poc":        0.10,   # Volume Profile
            "dominance":  0.10,   # BTC.D + USDT.D
        }
        self.threshold = threshold
    
    def _norm(self, sig):
        if not sig:
            return "NEUTRAL"
        if isinstance(sig, dict):
            s = sig.get("signal", "NEUTRAL")
        else:
            s = sig
        if s in ("BUY", "SELL", "NEUTRAL"):
            return s
        if s == "ALL_BUY":
            return "BUY"
        if s == "ALL_SELL":
            return "SELL"
        return "NEUTRAL"
    
    def _get_signal(self, data, key):
        if not data:
            return "NEUTRAL"
        
        if key == "fibo":
            signals = data.get("signals", [])
            for s in signals:
                if s.get("zone_status") in ("IN_ZONE", "NEAR"):
                    return s.get("side", "NEUTRAL")
            return "NEUTRAL"
        
        if key == "mtf":
            mtf = data.get("mtf", [])
            if not mtf:
                return "NEUTRAL"
            buys = sum(1 for m in mtf if m.get("side") == "BUY")
            sells = sum(1 for m in mtf if m.get("side") == "SELL")
            if buys > sells:
                return "BUY"
            elif sells > buys:
                return "SELL"
            return "NEUTRAL"
        
        if key == "ema":
            ema = data.get("ema_mtf") or {}
            return self._norm(ema.get("alignment", "NEUTRAL"))
        
        if key == "vwap":
            vwap = data.get("vwap") or {}
            return self._norm(vwap.get("alignment", "NEUTRAL"))
        
        if key == "ichimoku":
            multi = data.get("multi") or {}
            ic = multi.get("ichimoku") or {}
            return self._norm(ic.get("signal", "NEUTRAL"))
        
        if key == "poc":
            multi = data.get("multi") or {}
            pc = multi.get("poc") or {}
            return self._norm(pc.get("signal", "NEUTRAL"))
        
        if key == "dominance":
            dom = data.get("dominance") or {}
            overall = dom.get("overall", "NEUTRAL")
            if overall in ("STRONG_BUY", "BUY"):
                return "BUY"
            elif overall in ("STRONG_SELL", "SELL"):
                return "SELL"
            return "NEUTRAL"
        
        return "NEUTRAL"
    
    def decide(self, data):
        """تصمیم نهایی ایجنت"""
        details = []
        buy_score = 0.0
        sell_score = 0.0
        
        for name, w in self.weights.items():
            sig = self._get_signal(data, name)
            w_pct = w * 100
            
            if sig == "BUY":
                buy_score += w_pct
                details.append({"filter": name, "signal": "BUY", "weight": w_pct})
            elif sig == "SELL":
                sell_score += w_pct
                details.append({"filter": name, "signal": "SELL", "weight": w_pct})
            else:
                details.append({"filter": name, "signal": "NEUTRAL", "weight": 0})
        
        if buy_score >= self.threshold and buy_score > sell_score + 10:
            return {
                "decision": "BUY",
                "confidence": round(buy_score, 1),
                "buy_score": round(buy_score, 1),
                "sell_score": round(sell_score, 1),
                "risk_pct": self._calc_position(buy_score),
                "details": details,
            }
        elif sell_score >= self.threshold and sell_score > buy_score + 10:
            return {
                "decision": "SELL",
                "confidence": round(sell_score, 1),
                "buy_score": round(buy_score, 1),
                "sell_score": round(sell_score, 1),
                "risk_pct": self._calc_position(sell_score),
                "details": details,
            }
        else:
            return {
                "decision": "WAIT",
                "confidence": round(max(buy_score, sell_score), 1),
                "buy_score": round(buy_score, 1),
                "sell_score": round(sell_score, 1),
                "risk_pct": 0,
                "reason": f"امتیاز کافی نیست (BUY={buy_score:.0f}، SELL={sell_score:.0f})",
                "details": details,
            }
    
    def _calc_position(self, confidence):
        """PH33B: tier by confidence, capped by min(tier, max_risk_pct) from risk_config.json."""
        confidence = float(confidence)
        if confidence >= 90:
            tier = 1.5
        elif confidence >= 80:
            tier = 1.0
        elif confidence >= 70:
            tier = 0.5
        else:
            tier = 0.0
        if tier <= 0:
            return 0.0
        return min(tier, self._max_risk_pct())

    def _max_risk_pct(self):
        """PH33B: single numeric source risk_config.json (fallback 1.5 = pre-PH33B max tier)."""
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "risk_config.json")
            with open(path, encoding="utf-8") as f:
                return float(json.load(f).get("max_risk_pct", 1.5))
        except Exception:
            return 1.5


if __name__ == "__main__":
    print("=" * 80)
    print("  PHASE 20: AGENT DECISION")
    print("=" * 80)
    
    agent = AgentDecision(threshold=70)
    
    # Test 1: Strong BUY
    t1 = {
        "signals": [{"side": "BUY", "zone_status": "IN_ZONE", "rr": 1.8}],
        "ema_mtf": {"alignment": "ALL_BUY"},
        "vwap": {"alignment": "ALL_BUY"},
        "multi": {"ichimoku": {"signal": "BUY"}, "poc": {"signal": "BUY"}},
        "dominance": {"overall": "BUY"},
    }
    r = agent.decide(t1)
    print("\n▶ Test 1: Strong BUY")
    print(f"  Decision:    {r['decision']}")
    print(f"  Confidence:  {r['confidence']}%")
    print(f"  BUY score:   {r['buy_score']}%")
    print(f"  SELL score:  {r['sell_score']}%")
    print(f"  Risk:        {r['risk_pct']}%")
    
    # Test 2: MIXED
    t2 = {
        "signals": [{"side": "BUY", "zone_status": "IN_ZONE", "rr": 1.5}],
        "ema_mtf": {"alignment": "ALL_SELL"},
        "vwap": {"alignment": "MIXED"},
        "multi": {"ichimoku": {"signal": "SELL"}, "poc": {"signal": "BUY"}},
        "dominance": {"overall": "SELL"},
    }
    r = agent.decide(t2)
    print("\n▶ Test 2: MIXED")
    print(f"  Decision:    {r['decision']}")
    print(f"  BUY score:   {r['buy_score']}%")
    print(f"  SELL score:  {r['sell_score']}%")
    print(f"  Reason:      {r.get('reason', '')}")
    
    print("\n" + "=" * 80)
    print("  ✅ PHASE 20 COMPLETE")
    print("=" * 80)
