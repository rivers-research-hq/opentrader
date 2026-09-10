#!/usr/bin/env python3
"""fx_warden — the local-model lane monitor (human directive 2026-09-08).

A bounded local-LLM lane (Qwen3.8-4B on the RTX 3070, :5802) that watches
every active FX lane, takes structured notes, and sets each lane's
EXPECTED performance for the period — conditioned on the news feeds — so
that scoring is expectation-adjusted: a lane that was expected to do badly
and did, eats a soft penalty; a lane that was expected to do well and
failed, eats a harsh one (the QB/RB rule). Reward accrues in real time;
weekly periods drive a SHADOW CUT LIST (probation before any cut lands on
the human's Friday list).

HARD BOUNDS (per AGENTS.md + 2026-08-31 postmortem):
  - venue access is READ-ONLY; the Warden never places orders
  - lane-tuning authority is PROPOSALS ONLY (data/warden/proposals.jsonl) —
    applying one is a human-gated edit
  - one bounded model call per run (~1-2k in / <=800 out); paid compute
    relinquished for monitoring entirely

MID-TRAINING PATH: every run appends a structured record to
data/warden/records.jsonl — {ts, mode, news_refs, lane_states, plan,
outcome_context}. That file IS the corpus for the narrow mid-train of the
Warden model (lane-state + news -> expectation-setting); the loop is
self-supervised: today's notes are tomorrow's training data.

Usage:
  python3 -m strategies.fx_warden --auto          # cron entry: observe,
                                                  # upgrades to plan/score
                                                  # by wall clock + state
  python3 -m strategies.fx_warden --mode plan     # force a mode
  python3 -m strategies.fx_warden --dry           # no state writes
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from datetime import time as _dtime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from exchange.oanda import OandaExchange  # noqa: E402

WARDEN_DIR = PROJECT / "data" / "warden"
NOTES = WARDEN_DIR / "notes.jsonl"
RECORDS = WARDEN_DIR / "records.jsonl"
PROPOSALS = WARDEN_DIR / "proposals.jsonl"
PLAN = WARDEN_DIR / "game_plan.json"
SCORECARD = WARDEN_DIR / "scorecard.json"
STATE = WARDEN_DIR / "warden_state.json"
FEEDS = Path("/home/mrc/opentrader-data/feeds")
CARRY = Path("/home/mrc/opentrader/data/warden/carry.json")
NEWSFEED_DB = Path("/home/mrc/opentrader/data/newsfeed/newsfeed.db")
LLM = "http://127.0.0.1:5802/v1/chat/completions"

PERIOD_DAYS = 7  # tournament week: Friday close -> Friday close

# Expectation-conditioned reward: score = miss - harshness*|expected| if miss<0
HARSHNESS = 1.0  # extra downside multiplier scaled by |expected| (QB/RB rule)
PROBATE_AFTER = 1  # expectation-adjusted bad periods before probation
ESCALATE_AFTER = 2  # consecutive bad periods before the human's cut list


def _now():
    return datetime.now(timezone.utc).isoformat()


def _week_anchor(now=None):
    """Tournament-week anchor: the most recent Friday 21:00 UTC (Friday
    close). The scoring period runs Friday close -> Friday close, so the
    plan's period_start/nav/realized snapshot AND the MFE peak must persist
    across the whole week. plan() previously rewrote period_start with
    today's date every day, which reset the MFE peak daily — the dashboard
    scoreboard showed peaks that had nothing to do with the week (fixed
    2026-09-10)."""
    now = now or datetime.now(timezone.utc)
    d = now.date()
    delta = (d.weekday() - 4) % 7  # days since Friday (Friday=4)
    base = d - timedelta(days=delta)
    if delta == 0 and now.time() < _dtime(21, 0):
        base = base - timedelta(days=7)  # Friday before close: week started last Friday
    return base.isoformat()


_model_cache = {}


LLM_ENDPOINTS = ["http://127.0.0.1:5802/v1",   # primary: Granite 4.2 on GRE
                 "http://127.0.0.1:5804/v1"]   # fallback: Qwen3.8-4B on 3070
_model_cache = {}


def _model_id():
    """Which model produced this record — the receipt for a future swap.
    Endpoint-aware: during a failover the fallback model stamps the record,
    so lineage survives the swap."""
    if "id" in _model_cache:
        return _model_cache["id"]
    for base in LLM_ENDPOINTS:
        try:
            with urllib.request.urlopen(base + "/models", timeout=8) as r:
                d = json.loads(r.read())
            mid = (d.get("data") or [{}])[0].get("id", "unknown")
            if mid and mid != "unknown":
                _model_cache["id"] = mid
                return mid
        except Exception:
            continue
    return "unknown"


def _append(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")
        f.flush()


def _read_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"last_observe": None, "last_plan_day": None, "last_score_day": None,
            "probation": {}, "history": {}}


def _save_state(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s, indent=1))
    tmp.replace(STATE)


# ── lane truth (venue authoritative + ledger tail) ──────────────────────

def lane_states():
    from strategies.fx_expert_lane import quote_usd_rates
    ex = OandaExchange()
    if not ex.connect():
        return None
    s = ex._request("GET", f"/v3/accounts/{ex._account_id}/summary")["account"]
    trades = ex._request("GET", f"/v3/accounts/{ex._account_id}/openTrades").get("trades", [])
    pairs_all = sorted({t["instrument"] for t in trades})
    rates = quote_usd_rates(ex, sorted({p.split("_")[1] for p in pairs_all}), set(pairs_all))
    by_tag = {}
    for t in trades:
        tag = (t.get("clientExtensions") or {}).get("tag") or "untagged"
        b, q = t["instrument"].split("_")
        usd_notional = abs(float(t["currentUnits"])) * float(t["price"]) * rates.get(q, 1.0)
        signed_usd = usd_notional if float(t["currentUnits"]) > 0 else -usd_notional
        d = by_tag.setdefault(tag, {"positions": 0, "net_units": 0.0, "upl": 0.0,
                                    "net_usd": 0.0, "gross_usd": 0.0, "pairs": []})
        d["positions"] += 1
        d["net_units"] += float(t["currentUnits"])
        d["net_usd"] += signed_usd
        d["gross_usd"] += usd_notional
        d["upl"] += float(t["unrealizedPL"])
        d["pairs"].append(t["instrument"])
    # realized today + period-to-date from the venue journal (tag chain)
    txns = ex._request("GET", f"/v3/accounts/{ex._account_id}/transactions/sinceid?id=0").get("transactions", [])
    fills = [t for t in txns if t.get("type") == "ORDER_FILL"]
    order_tag = {}
    for t in txns:
        if t.get("type") == "MARKET_ORDER":
            tg = (t.get("tradeClientExtensions") or {}).get("tag")
            if tg:
                order_tag[t.get("id")] = tg
    realized_day, realized_all = {}, {}
    today = _now()[:10]
    for f in fills:
        tag = (f.get("clientExtensions") or {}).get("tag") or order_tag.get(f.get("orderID")) or "unknown"
        realized_all[tag] = realized_all.get(tag, 0.0) + float(f.get("pl", 0) or 0)
        if str(f.get("time", ""))[:10] == today:
            realized_day[tag] = realized_day.get(tag, 0.0) + float(f.get("pl", 0) or 0)
    return {
        "asof": _now(),
        "balance": float(s["balance"]), "nav": float(s["NAV"]),
        "unrealized": float(s["unrealizedPL"]),
        "financing_today": float(s.get("financing", 0) or 0),
        "lanes": {tag: {**d, "realized_today": round(realized_day.get(tag, 0.0), 2),
                        "realized_all": round(realized_all.get(tag, 0.0), 2)}
                  for tag, d in sorted(by_tag.items())},
    }


def newsfeed_digest(max_chars=1800):
    """Recent canonical headlines from the newsfeed store (deduped, fresh).
    Carries the newest observation timestamp so the plan knows its news age.
    Returns '' if the DB is missing (standalone degradation)."""
    if not NEWSFEED_DB.exists():
        return ""
    try:
        import sqlite3
        con = sqlite3.connect(str(NEWSFEED_DB))
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT i.published_utc, i.title, s.name AS src
            FROM items i JOIN sources s ON s.id = i.source_id
            WHERE i.is_canonical = 1 AND i.published_utc >= datetime('now', '-7 days')
            ORDER BY i.published_utc DESC LIMIT 25
        """).fetchall()
        newest = con.execute(
            "SELECT MAX(published_utc) FROM items WHERE is_canonical = 1").fetchone()[0]
        con.close()
        lines = [f"{(r['published_utc'] or '?')[:16]} [{r['src'][:14]}] {r['title'][:110]}"
                 for r in rows]
        hdr = f"newsfeed ({len(rows)} canonical items, newest {newest or '?'}):"
        text = hdr + "\n" + "\n".join(lines)
        return text[:max_chars]
    except Exception as e:
        return f"(newsfeed unavailable: {e})"


def feed_digest(max_chars=2500):
    """Compact news digest for the prompt (feeds dir; bounded)."""
    out = []
    try:
        up = json.loads((FEEDS / "ff_upcoming.json").read_text())
        evs = up if isinstance(up, list) else up.get("events", [])
        for e in evs[:8]:
            out.append(f"ECON {str(e.get('date', ''))[:16]} {e.get('currency', '')} "
                       f"{e.get('impact', '')} {e.get('title', '')[:60]}")
    except Exception:
        pass
    try:
        mof = json.loads((FEEDS / "mof_interventions.json").read_text())
        rows = mof if isinstance(mof, list) else mof.get("interventions", [])
        for e in rows[:3]:
            out.append(f"MOF {str(e.get('date', ''))[:10]} {str(e.get('note', e))[:80]}")
    except Exception:
        pass
    try:
        fed = json.loads((FEEDS / "fed_speeches.json").read_text())
        rows = fed if isinstance(fed, list) else fed.get("speeches", [])
        for e in rows[:3]:
            out.append(f"FED {str(e.get('date', ''))[:10]} {str(e.get('title', e))[:80]}")
    except Exception:
        pass
    text = "\n".join(out)[:max_chars]
    return text or "(feeds empty)"


# ── local model call (bounded) ───────────────────────────────────────────

def llm_json(system, user, max_tokens=800):
    """One bounded model call with endpoint failover: primary (Granite on
    GRE) then fallback (Qwen on 3070, started on demand by the failover
    supervisor when the primary's GPU is evicted — e.g. gaming)."""
    body = json.dumps({"messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}],
                       "max_tokens": max_tokens, "temperature": 0.25}).encode()
    last_err = None
    for base in LLM_ENDPOINTS:
        try:
            req = urllib.request.Request(base + "/chat/completions", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
            text = d["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                return None
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        except Exception as e:
            last_err = e
            continue
    print(f"[warden] all LLM endpoints unreachable ({last_err}) — run skipped")
    return None


# ── modes ────────────────────────────────────────────────────────────────

SYSTEM_OBS = ("You are the Warden: a bounded monitor for an FX practice account. "
              "You NEVER place orders and never propose code changes. Read the lane "
              "states and news digest, then return STRICT JSON only: "
              '{"notes":[{"lane":"<tag>","text":"<one factual sentence>"}],'
              '"flags":[{"kind":"anomaly|risk|opportunity","text":"<one sentence>"}]} '
              "Notes must be concrete (pairs, position counts). CITE ONLY numbers "
              "that appear verbatim in states or news — never compute, estimate, or "
              "invent a percentage. Max 3 notes, max 2 flags.")

SYSTEM_PLAN = ("You are the Warden: a bounded monitor for an FX practice account. "
               "You set each ACTIVE lane's EXPECTED profit for the coming week in "
               "account percent (e.g. 0.1 = +0.1%), conditioned on the news digest "
               "and each lane's recent history. Be honest: flat/exhausted lanes "
               "get ~0.0. Return STRICT JSON only: "
               '{"regime_read":"<2 sentences>",'
               '"plan":{"<tag>":{"expected_pnl_pct":0.0,"direction":"long_bias|short_bias|flat",'
               '"conviction":0.5,"rationale":"<one sentence>"}},"watch":["<tag>"]} '
               "Include EVERY lane listed in states.lanes. Max_tokens discipline: be terse.")

SYSTEM_SCORE_NOTE = ("You are the Warden. One paragraph (<=80 words) interpreting this "
                     "period's expectation-adjusted scoreboard for the human. No JSON.")


def corpus_records():
    """Mid-train corpus reader with the lifecycle filter applied at read
    time (expert_lifecycle contract): records whose lanes include a
    cut/archived expert are excluded (quarantined records), and the count
    of exclusions is returned alongside the kept records so the mid-train
    can log its corpus composition honestly."""
    from strategies.expert_lifecycle import all_lifecycles
    lc = all_lifecycles()
    out, excluded = [], 0
    if not RECORDS.exists():
        return out, excluded
    for line in RECORDS.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        tags = set((rec.get("lane_states") or {}).keys())
        if any(lc.get(t) in ("cut", "archived") for t in tags):
            excluded += 1
            continue
        out.append(rec)
    return out, excluded



def _verify_note_numbers(text, st):
    """Audit-gate on the Warden itself: any % number in a note must match a
    real value in states (uPL, realized, financing, upl/all/realized per
    lane, balance moves) within rounding — else the note is tagged
    unverified so fabricated figures can't poison the mid-train corpus."""
    claims = re.findall(r"-?\d+\.?\d*\s*%", text)
    if not claims:
        return True
    allowed = set()
    for lane in (st.get("lanes") or {}).values():
        allowed.add(round(lane.get("upl", 0.0), 2))
        allowed.add(round(lane.get("realized_today", 0.0), 2))
        allowed.add(round(lane.get("realized_all", 0.0), 2))
    allowed.update((round(st.get("unrealized", 0.0), 2),
                    round(st.get("financing_today", 0.0), 2)))
    for c in claims:
        v = round(float(c.replace("%", "").strip()), 2)
        if not any(abs(v - a) <= 0.02 for a in allowed):
            return False
    return True


def observe(dry=False):
    from strategies.expert_lifecycle import all_lifecycles
    st = lane_states()
    if st is None:
        print("[warden] venue unreachable — skip")
        return
    # registry filter: only observe lanes matching a registered expert.
    # Tags map through registry_tag_index() — venue tags (fxexp-g151),
    # registry IDs (fx-expert-g151) and legacy aliases (mom-k5) are three
    # spellings of the same expert; comparing directly orphans every lane.
    from strategies.expert_lifecycle import all_lifecycles, registry_tag_index
    lc = all_lifecycles()
    tag2eid = registry_tag_index()
    orphan_tags = [tag for tag in st["lanes"] if tag not in tag2eid]
    if orphan_tags:
        st["anomaly"] = f"unregistered lanes trading: {orphan_tags}"
        st["lanes"] = {k: v for k, v in st["lanes"].items() if k in tag2eid}
    # cut/archived lanes must be flat — positions on a terminal-state expert
    # are a control-plane violation, not an observation
    dead = [tag for tag in st["lanes"]
            if lc.get(tag2eid[tag]) in ("cut", "archived") and st["lanes"][tag]["positions"]]
    if dead:
        st["anomaly"] = (st.get("anomaly", "") + f" | TERMINAL-STATE LANES HOLDING: {dead}").strip(" |")
    news = feed_digest()
    nf = newsfeed_digest()
    recent = []
    if NOTES.exists():
        recent = [json.loads(l) for l in NOTES.read_text().splitlines()[-5:] if l.strip()]
    inst = instability(dry=dry)
    user = (f"instability table:\n{_instability_table(inst)}\n\n"
            f"news:\n{news}\n\nheadlines:\n{nf}\n\n"
            f"states: {json.dumps(st)[:2200]}\n\n"
            f"recent notes: {json.dumps(recent)[:600]}")
    out = llm_json(SYSTEM_OBS, user, max_tokens=600)
    ts = _now()
    # MFE tracker: per-lane peak uPL, persisted across hourly runs, reset on
    # period change. This is the "how good were the picks at their best"
    # metric — the give-back ratio (peak − current) / peak measures exit
    # skill separately from selection skill.
    if st and not dry:
        state = _read_state()
        mfe = state.setdefault("mfe", {})
        plan_doc = json.loads(PLAN.read_text()) if PLAN.exists() else {}
        cur_period = plan_doc.get("period_start", "")
        for tag, d in st["lanes"].items():
            if not tag.startswith("fxexp"):
                continue
            prev = mfe.get(tag, {})
            if prev.get("period") != cur_period:
                mfe[tag] = {"peak_upl": d["upl"], "period": cur_period}
            else:
                mfe[tag]["peak_upl"] = max(prev["peak_upl"], d["upl"])
        state["mfe"] = mfe
        _save_state(state)
    if out and isinstance(out.get("notes"), list):
        verified = unverified = 0
        for n in out["notes"][:4]:
            text = str(n.get("text", ""))[:280]
            ok = _verify_note_numbers(text, st)
            verified += ok
            unverified += not ok
            _append(NOTES, {"ts": ts, "model": _model_id(), "lane": n.get("lane", "?"),
                            "text": text, "verified": ok,
                            "note": None if ok else "numeric claim unverified vs venue"})
        for f in (out.get("flags") or [])[:3]:
            _append(NOTES, {"ts": ts, "model": _model_id(), "lane": "*", "flag": f.get("kind", "?"),
                            "text": str(f.get("text", ""))[:280], "verified": None})
        print(f"[warden] observe: {len(out.get('notes', []))} notes "
              f"({verified} verified, {unverified} UNVERIFIED — fabricated "
              f"figures flagged), {len(out.get('flags') or [])} flags")
    else:
        print("[warden] observe: model output unparseable — skipped (no state written)")
    _append(RECORDS, {"ts": ts, "model": _model_id(), "mode": "observe", "headlines": nf[:600], "news_refs": news[:400],
                      "lane_states": st["lanes"], "model_out": out})


def plan(dry=False):
    WARDEN_DIR.mkdir(parents=True, exist_ok=True)
    # freshen feeds first (existing guarded fetcher, bounded)
    try:
        import subprocess
        subprocess.run([sys.executable, str(PROJECT / "scripts" / "fetch_event_feeds.py")],
                       capture_output=True, timeout=240)
    except Exception as e:
        print(f"[warden] feed refresh skipped: {e}")
    st = lane_states()
    if st is None:
        print("[warden] venue unreachable — skip")
        return
    prev = {}
    if SCORECARD.exists():
        sc = json.loads(SCORECARD.read_text())
        prev = sc.get("last_scores", {})
    news = feed_digest()
    nf = newsfeed_digest()
    inst = instability(dry=dry)
    user = (f"instability table:\n{_instability_table(inst)}\n\n"
            f"news:\n{news}\n\nheadlines:\n{nf}\n\n"
            f"states: {json.dumps(st)[:2000]}\n\n"
            f"previous period scores (actual vs expected, account %): "
            f"{json.dumps(prev)[:800]}\n\nSet the plan for the coming {PERIOD_DAYS}-day period. "
            f"Lanes exposed to HIGH/CRITICAL instability currencies should have "
            f"expectations near 0 and their rationale must say why. "
            f"Carry data (long carry %/yr per pair): {json.dumps(json.loads((CARRY).read_text()).get('carry_per_pair_pct_yr', {}))[:400] if (CARRY).exists() else '{}'}")
    out = llm_json(SYSTEM_PLAN, user, max_tokens=900)
    if not out or not isinstance(out.get("plan"), dict):
        print("[warden] plan: model output unparseable — keeping previous plan")
        return
    # lane-coverage validation: every lane in states gets a plan entry, even
    # if the model omits it (otherwise the scoreboard silently loses lanes)
    for tag in (st.get("lanes") or {}):
        if tag not in out["plan"]:
            out["plan"][tag] = {"expected_pnl_pct": 0.0, "direction": "flat",
                                "conviction": 0.2,
                                "rationale": "model omitted this lane — defaulted flat"}
    # period anchor: keep the week's snapshot (period_start, nav, realized
    # base) stable for the whole Friday-close-to-Friday-close period — the
    # model refreshes expectations daily, the scoring base does not move
    existing = {}
    if PLAN.exists():
        try:
            existing = json.loads(PLAN.read_text())
        except Exception:
            existing = {}
    anchor = _week_anchor()
    if existing.get("period_start") == anchor and existing.get("period_start_nav"):
        period_start = existing["period_start"]
        period_nav = existing["period_start_nav"]
        realized_base = existing.get("realized_at_plan", {})
        print(f"[warden] period anchor kept: {period_start}")
    else:
        period_start = anchor
        period_nav = st["nav"]
        realized_base = {tag: lane.get("realized_all", 0.0)
                         for tag, lane in st["lanes"].items()}
    plan_doc = {"period_start": period_start,
                "period_start_nav": period_nav,
                "realized_at_plan": realized_base,
                "regime_read": str(out.get("regime_read", ""))[:400],
                "plan": {tag: {"expected_pnl_pct": float(v.get("expected_pnl_pct", 0.0)),
                               "direction": str(v.get("direction", "flat"))[:12],
                               "conviction": float(v.get("conviction", 0.5)),
                               "rationale": str(v.get("rationale", ""))[:200]}
                          for tag, v in out["plan"].items()},
                "watch": [str(w)[:32] for w in (out.get("watch") or [])][:6]}
    if not dry:
        PLAN.write_text(json.dumps(plan_doc, indent=1))
        state = _read_state()
        # last_plan_day is the DAILY trigger bookkeeping (auto() compares it
        # to today); period_start above is the weekly scoring anchor
        state["last_plan_day"] = _now()[:10]
        _save_state(state)
    _append(RECORDS, {"ts": _now(), "model": _model_id(), "mode": "plan", "instability": {k: v for k, v in inst["currencies"].items() if v["tier"] != "calm"}, "headlines": nf[:600], "news_refs": news[:400],
                      "plan": plan_doc["plan"], "regime_read": plan_doc["regime_read"]})
    print(f"[warden] plan written for {period_start}: {len(plan_doc['plan'])} lanes")
    for tag, v in plan_doc["plan"].items():
        print(f"   {tag:12s} expected {v['expected_pnl_pct']:+.2f}% "
              f"{v['direction']:11s} conviction {v['conviction']:.2f}")


def score(dry=False):
    if not PLAN.exists():
        print("[warden] score: no game plan yet — run plan first")
        return
    st = lane_states()
    if st is None:
        print("[warden] venue unreachable — skip")
        return
    plan_doc = json.loads(PLAN.read_text())
    start = plan_doc.get("period_start", "")
    started = datetime.fromisoformat(start + "T00:00:00+00:00") if start else None
    days_in = (datetime.now(timezone.utc) - started).days if started else 0
    acct0 = float(plan_doc.get("period_start_nav") or 0) or st["balance"]  # stored at plan time
    scores = {}
    for tag, exp in plan_doc["plan"].items():
        lane = st["lanes"].get(tag, {})
        # period actual = realized since period start (venue journal walk is
        # all-time; approximate period actual via realized_all delta if the
        # period start predates the journal tail — v0.1 uses all-time delta
        # when the plan was written this period; documented heuristic)
        # period actual = realized delta since the plan snapshot + current uPL
        base_realized = float(plan_doc.get("realized_at_plan", {}).get(tag, 0.0))
        actual_usd = (lane.get("realized_all", 0.0) - base_realized) + lane.get("upl", 0.0)
        actual_pct = 100.0 * actual_usd / max(acct0, 1.0)
        expected = float(exp.get("expected_pnl_pct", 0.0))
        miss = actual_pct - expected
        penalty = miss if miss >= 0 else miss - HARSHNESS * abs(expected)
        scores[tag] = {"actual_pct": round(actual_pct, 3),
                       "expected_pct": round(expected, 3),
                       "miss_pct": round(miss, 3),
                       "score_pct": round(penalty, 3),
                       "direction": exp.get("direction"),
                       "days_in_period": days_in}
    state = _read_state()
    prob = state.setdefault("probation", {})
    for tag, s in scores.items():
        bad = s["score_pct"] < -0.05  # expectation-adjusted bad threshold (acct %)
        if bad:
            n = prob.get(tag, {}).get("bad_periods", 0) + 1
            status = ("escalate" if n >= ESCALATE_AFTER else
                      ("probation" if n >= PROBATE_AFTER else "watch"))
            prob[tag] = {"bad_periods": n, "status": status}
            # lifecycle sync: probation shrinks the lane's notional cap; cut
            # stays human-gated (escalate only lands on the Friday list)
            if status == "probation":
                _sync_lifecycle(tag, "probation",
                                f"warden score {s['score_pct']:+.2f}% ({n} bad period(s))",
                                notional_cap=0.5)
        elif prob.get(tag):
            prev_status = prob[tag].get("status")
            prob[tag] = {"bad_periods": 0,
                         "status": "reprieved",
                         "note": f"recovered {s['score_pct']:+.2f} — shadow cut lifted"}
            if prev_status == "probation":
                _sync_lifecycle(tag, "accruing",
                                f"warden reprieve {s['score_pct']:+.2f}%", notional_cap=1.0)
            prob[tag] = {"bad_periods": 0,
                         "status": "reprieved",
                         "note": f"recovered {s['score_pct']:+.2f} — shadow cut lifted"}
    # MFE: per-lane peak uPL tracked by the hourly observe; give-back ratio
    # measures exit-policy cost separately from selection skill
    mfe = state.get("mfe", {})
    for tag in scores:
        p = mfe.get(tag, {}).get("peak_upl", 0.0)
        cur_upl = st["lanes"].get(tag, {}).get("upl", 0.0)
        gb = ((p - cur_upl) / p) if p > 0 else 0.0
        scores[tag]["peak_upl"] = round(p, 2)
        scores[tag]["current_upl"] = round(cur_upl, 2)
        scores[tag]["give_back"] = round(gb, 3)
    sc = {"asof": _now(), "days_in_period": days_in, "last_scores": scores,
          "probation": prob}
    if not dry:
        SCORECARD.write_text(json.dumps(sc, indent=1))
        state["last_score_day"] = _now()[:10]
        state["history"] = state.get("history", {})
        state["history"][start] = scores
        _save_state(state)
    _append(RECORDS, {"ts": _now(), "model": _model_id(), "mode": "score", "scores": scores,
                      "probation": prob})
    print(f"[warden] score (day {days_in} of period):")
    for tag, s in sorted(scores.items(), key=lambda kv: kv[1]["score_pct"]):
        print(f"   {tag:12s} actual {s['actual_pct']:+.2f}% vs expected "
              f"{s['expected_pct']:+.2f}% -> miss {s['miss_pct']:+.2f}, "
              f"score {s['score_pct']:+.2f}")
    escal = [t for t, p in prob.items() if p.get("status") == "escalate"]
    probate = [t for t, p in prob.items() if p.get("status") == "probation"]
    if escal:
        print(f"[warden] SHADOW CUT LIST (escalate -> human Friday list): {escal}")
    if probate:
        print(f"[warden] probation (one week to improve): {probate}")


def _sync_lifecycle(tag, new_state, reason, notional_cap):
    """Best-effort lifecycle sync for warden probation/reprieve. Legacy lanes
    and unknown tags are skipped (they aren't lifecycle-controlled)."""
    try:
        from strategies.expert_lifecycle import transition, lifecycle_of
        e = lifecycle_of(tag) or lifecycle_of(tag.replace("fxexp-", "fx-expert-"))
        if e is None or e.get("lifecycle") not in ("accruing", "probation"):
            return
        transition(e["expert_id"], new_state, reason=reason, actor="warden",
                   notional_cap=notional_cap)
    except Exception as exc:
        print(f"[warden] lifecycle sync failed for {tag}: {exc}")


CCYS = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "MXN",
        "ZAR", "TRY", "NOK", "SEK", "CZK", "HUF", "PLN", "SGD", "CNH", "THB"}
TIERS = ((60, "critical"), (40, "high"), (20, "elevated"), (0, "calm"))


def instability(dry=False):
    """Per-currency instability composite — code-computed heuristic (labeled),
    the Warden's early-warning layer for TRY-class incidents:
      halt (OANDA non-tradeable) 0-30 | vol spike 0-25 | 5d shock 0-25 |
      high-impact event <48h 0-10 | global bond/vix stress 0-10.
    Global block reads the bond panel: VIX, US HY OAS, EM HY OAS, DGS10,
    T10Y2Y — z-scores vs their own trailing history. Written to
    instability.json and injected into plan/observe prompts."""
    import duckdb
    con = duckdb.connect("/home/mrc/opentrader-data/store.duckdb", read_only=True)
    all_pairs = [r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM bars WHERE timeframe='1d'").fetchall()]
    # global stress block: latest value + z vs trailing history per series
    stress = {}
    for sid, label in (("FRED:VIXCLS", "vix"), ("FRED:BAMLH0A0HYM2", "us_hy_oas"),
                       ("FRED:BAMLEMHYHYLCRPIUSOAS", "em_hy_oas"),
                       ("FRED:DGS10", "ust10y"), ("FRED:T10Y2Y", "curve_2s10s")):
        rows = con.execute("SELECT date, value FROM exog WHERE series = ? ORDER BY date",
                           [sid]).fetchall()
        if not rows:
            continue
        vals = [v for _, v in rows if v is not None]
        if len(vals) < 60:
            continue
        cur = vals[-1]
        hist = vals[-252:]
        mu = sum(hist) / len(hist)
        sd = (sum((x - mu) ** 2 for x in hist) / len(hist)) ** 0.5
        z = (cur - mu) / sd if sd > 0 else 0.0
        stress[label] = {"value": round(cur, 3), "z": round(z, 2)}
    global_stress = 0.0
    if stress.get("vix", {}).get("z", 0) > 1 or \
       stress.get("us_hy_oas", {}).get("z", 0) > 1 or \
       stress.get("em_hy_oas", {}).get("z", 0) > 1:
        global_stress = 10.0  # regime-wide bond/vol stress → all currencies
    ccys = sorted({c for p in all_pairs for c in p.split("_")} & CCYS)
    # FX-side shocks per currency from its pairs' D1 closes
    shocks = {}
    for pair in all_pairs:
        rows = con.execute(
            "SELECT ts, close FROM bars WHERE symbol = ? AND timeframe = '1d' "
            "ORDER BY ts DESC LIMIT 61", [pair]).fetchall()
        if len(rows) < 21:
            continue
        closes = [float(c) for _, c in rows][::-1]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        vol60 = (sum(r * r for r in rets[-60:]) / max(len(rets[-60:]), 1)) ** 0.5
        vol5 = (sum(r * r for r in rets[-5:]) / max(len(rets[-5:]), 1)) ** 0.5
        ret5 = closes[-1] / closes[-6] - 1.0
        for c in pair.split("_"):
            shocks.setdefault(c, []).append(
                {"vol_ratio": vol5 / vol60 if vol60 > 0 else 0.0,
                 "shock": abs(ret5) / (vol60 * (5 ** 0.5) * 3) if vol60 > 0 else 0.0})
    con.close()
    # venue tradeable status: a REAL halt (TRY-class) freezes the price
    # timestamp — status != tradeable AND price >30 min stale. Transient
    # non-tradeable snapshots (daily maintenance ~21:00-22:00 UTC, staggered
    # reopen) carry fresh timestamps and are ignored.
    ex = OandaExchange()
    halted = set()
    if ex.connect():
        pairs_csv = ",".join(all_pairs)
        now_s = time.time()
        stale = 0
        now_halted = set()
        for pr in ex._request("GET", f"/v3/accounts/{ex._account_id}/pricing?instruments={pairs_csv}").get("prices", []):
            if pr.get("status") != "tradeable":
                ts = str(pr.get("time", ""))
                try:
                    pt = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                    if now_s - pt > 1800:
                        now_halted.update(pr["instrument"].split("_"))
                        stale += 1
                except ValueError:
                    pass
        if stale > len(all_pairs) * 0.3:
            out["maintenance_window"] = True  # venue-wide: no halt penalty
            now_halted = set()
        # persistence gate v2: a halt penalizes only after THREE consecutive
        # hourly confirmations (the daily maintenance flicker survives at
        # most 1-2 runs; a real TRY-class halt survives all of them)
        prev = _read_state()
        prev_streak = prev.get("halt_streak", {})
        streak = {}
        for c in now_halted:
            streak[c] = prev_streak.get(c, 0) + 1
        for c in list(prev_streak):
            if c not in now_halted:
                streak[c] = 0  # recovered — reset the streak
        halted = {c for c, n in streak.items() if n >= 3}
        state = _read_state()
        state["halt_streak"] = streak
        _save_state(state)                          # entries must not linger
    # event proximity per currency
    events = {}
    try:
        up = json.loads((FEEDS / "ff_upcoming.json").read_text())
        evs = up if isinstance(up, list) else up.get("events", [])
        for e in evs:
            d = str(e.get("date", ""))[:16]
            if e.get("impact") in ("High", "Med") and d >= _now()[:16]:
                events.setdefault(str(e.get("currency", "")).upper(), []).append(d)
    except Exception:
        pass
    out = {"asof": _now(), "global_stress_bonus": global_stress, "stress": stress,
           "currencies": {}}
    for c in ccys:
        sr = shocks.get(c, [])
        vr = max((s["vol_ratio"] for s in sr), default=0.0)
        sh = max((s["shock"] for s in sr), default=0.0)
        halt = c in halted
        score = (30.0 * halt + 25.0 * min(vr / 2.5, 1.0) +
                 25.0 * min(sh, 1.0) + global_stress +
                 (10.0 if events.get(c) else 0.0))
        score = min(score, 100.0)
        tier = next(t for lo, t in TIERS if score >= lo)
        out["currencies"][c] = {"score": round(score, 1), "tier": tier,
                                "halted": halt,
                                "vol_ratio": round(vr, 2),
                                "shock": round(sh, 2),
                                "event_48h": bool(events.get(c))}
    if not dry:
        WARDEN_DIR.mkdir(parents=True, exist_ok=True)
        (WARDEN_DIR / "instability.json").write_text(json.dumps(out, indent=1))
    return out


def _instability_table(inst):
    rows = sorted(inst["currencies"].items(), key=lambda kv: -kv[1]["score"])
    lines = [f"global stress bonus {inst['global_stress_bonus']:.0f} | "
             + " ".join(f"{k}={v['value']}(z{v['z']:+.1f})" for k, v in inst["stress"].items())]
    for c, d in rows[:10]:
        if d["tier"] == "calm":
            continue
        lines.append(f"{c}: {d['score']:.0f} {d['tier'].upper()}"
                     + (" HALTED" if d["halted"] else "")
                     + (f" vol_ratio {d['vol_ratio']}" if d["vol_ratio"] > 1.3 else "")
                     + (f" 5d-shock {d['shock']:.2f}" if d["shock"] > 0.33 else "")
                     + (" event<48h" if d["event_48h"] else ""))
    return "\n".join(lines) or "all currencies calm"


def audit_sizing(dry=False):
    """Sizing-fidelity audit (human directive 2026-09-08): each trained lane's
    per-leg actual USD notional vs intended |weight|×NOTIONAL. Code-computed
    from venue truth; dust-floor legs excluded, $0 non-dust legs flagged
    missing (halted/rejected)."""
    from strategies.fx_expert_lane import NOTIONAL, today_weights, quote_usd_rates, MIN_UNITS
    ex = OandaExchange()
    if not ex.connect():
        print("[warden] audit: venue unreachable — skip")
        return
    trades = ex._request("GET", f"/v3/accounts/{ex._account_id}/openTrades").get("trades", [])
    pairs = sorted({t["instrument"] for t in trades})
    rates = quote_usd_rates(ex, sorted({p.split("_")[1] for p in pairs}), set(pairs))

    def usd_per_base(sym):
        base, quote = sym.split("_")
        px = ex.get_current_price(sym) or 1.0
        return px * rates.get(quote, 1.0)

    audit = {}
    FX_DIR = PROJECT / "data" / "fx_expert"
    claims = {}
    cf = FX_DIR / "claims.json"
    if cf.exists():
        claims = json.loads(cf.read_text()).get("claims", {})
    for expert in ("g151", "g138", "g137"):
        tag = f"fxexp-{expert}"
        weights, _, day = today_weights(expert)
        # the conviction auction assigns each pair to ONE lane — a lane is
        # only accountable for sizing on its CLAIMED pairs. Comparing against
        # all 57 weighted pairs counted other lanes' books as this lane's
        # "missing" legs and collapsed fidelity to ~30% (fixed 2026-09-10).
        claimed = {p for p, v in claims.items() if v.get("lane") == tag}
        weights = {p: w for p, w in weights.items() if p in claimed}
        actual = {}
        for t in trades:
            if (t.get("clientExtensions") or {}).get("tag") != tag:
                continue
            b, q = t["instrument"].split("_")
            actual[t["instrument"]] = actual.get(t["instrument"], 0.0) + \
                abs(float(t["currentUnits"])) * float(t["price"]) * rates.get(q, 1.0)
        within = missing = dust = 0
        outliers = []
        for sym, w in sorted(weights.items(), key=lambda kv: -abs(kv[1])):
            intended = abs(w) * NOTIONAL
            if intended < MIN_UNITS * usd_per_base(sym):
                dust += 1
                continue
            act = actual.get(sym, 0.0)
            ratio = act / intended
            if 0.65 <= ratio <= 1.35:
                within += 1
            else:
                outliers.append({"pair": sym, "actual_usd": round(act),
                                 "intended_usd": round(intended), "ratio": round(ratio, 2),
                                 "missing": act < 1})
                if act < 1:
                    missing += 1
        n_check = within + len(outliers)
        fid = round(100 * within / n_check, 1) if n_check else 100.0
        audit[tag] = {"fidelity_pct": fid, "within": within, "outliers": len(outliers),
                      "missing": missing, "dust_excluded": dust,
                      "outlier_detail": outliers[:6]}
        print(f"[warden] audit {tag}: fidelity {fid}% ({within}/{n_check} conforming, "
              f"{missing} missing, {dust} dust-excluded)")
        for o in outliers[:4]:
            print(f"    {o['pair']:10s} actual ${o['actual_usd']:7.0f} vs intended "
                  f"${o['intended_usd']:7.0f} (ratio {o['ratio']})")
    if not dry:
        sc = json.loads(SCORECARD.read_text()) if SCORECARD.exists() else {}
        sc["sizing_audit"] = {"asof": _now(), "lanes": audit}
        sc["asof"] = _now()
        SCORECARD.write_text(json.dumps(sc, indent=1))
        _append(RECORDS, {"ts": _now(), "model": _model_id(), "mode": "audit", "sizing": audit})
        _append(NOTES, {"ts": _now(), "model": _model_id(), "lane": "*", "flag": "sizing-audit",
                        "text": "; ".join(f"{t}: {a['fidelity_pct']}% conforming, "
                                          f"{a['missing']} missing" for t, a in audit.items()),
                        "verified": True})
    return audit


def auto():
    """Cron entry: hourly observe; first run after 21:15 UTC -> plan;
    first run after 06:00 UTC -> score (state-tracked, once per day)."""
    st = _read_state()
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    if now.hour >= 21 and st.get("last_plan_day") != today:
        plan()
        st = _read_state()
    if now.hour >= 6 and now.hour < 21 and st.get("last_score_day") != today and PLAN.exists():
        score()
        audit_sizing()
        st = _read_state()
    observe()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--mode", choices=["observe", "plan", "score", "audit"])
    ap.add_argument("--dry", action="store_true", help="no state writes")
    a = ap.parse_args()
    if a.mode == "plan":
        plan(dry=a.dry)
    elif a.mode == "score":
        score(dry=a.dry)
    elif a.mode == "audit":
        audit_sizing(dry=a.dry)
    elif a.mode == "observe":
        observe(dry=a.dry)
    else:
        auto()


if __name__ == "__main__":
    main()
