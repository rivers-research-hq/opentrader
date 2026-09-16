"""ReAct paper trader — tool-using LLM, never places live orders."""
import json, urllib.request, os
from .features import daily_context

URL = os.environ.get("TRADER_AGENT_URL", "http://127.0.0.1:5808/v1/chat/completions")
SYSTEM = """You are a cautious FX paper-trading analyst. You receive causal market
features only up to the as-of date. Reason briefly, then output ONLY valid JSON:
{"action":"BUY|SELL|HOLD","conviction":0.0,"thesis":"one sentence","risk_flags":["..."]}
Rules: never invent data; HOLD when evidence conflicts; conviction is 0 to 1;
this is a paper vote, never an order. Oil shock means crude above its 60d risk
threshold: consider commodity/EM FX exposure carefully, but do not force a trade.
"""


def decide(symbol: str, context: dict | None = None, timeout: int = 180) -> dict:
    """Ask the local OpenAI-compatible model for a structured paper vote."""
    context = context or daily_context(symbol)
    prompt = ("Produce one paper vote for this pair. Use only this JSON context. "
              "Do not call tools or add markdown.\n" + json.dumps(context, default=str))
    body = json.dumps({"model": "local-worker", "temperature": 0,
                       "max_tokens": 256,
                       "messages": [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = json.loads(r.read().decode())
        text = raw["choices"][0]["message"]["content"]
        # tolerate a reasoning wrapper but parse only the first JSON object
        start, end = text.find("{"), text.rfind("}")
        vote = json.loads(text[start:end + 1])
        action = str(vote.get("action", "HOLD")).upper()
        if action not in {"BUY", "SELL", "HOLD"}:
            action = "HOLD"
        conviction = max(0.0, min(1.0, float(vote.get("conviction", 0))))
        return {"symbol": symbol, "action": action, "conviction": conviction,
                "thesis": str(vote.get("thesis", ""))[:500],
                "risk_flags": vote.get("risk_flags", []),
                "context_asof": context.get("asof"), "model_raw": text[:1000]}
    except Exception as exc:
        return {"symbol": symbol, "action": "HOLD", "conviction": 0.0,
                "thesis": "agent_error: " + str(exc)[:200], "risk_flags": ["agent_error"]}
