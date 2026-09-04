#!/usr/bin/env python3
"""OpenTrader Terminal Dashboard -- AdGuardian-style TUI.

Rich-powered, all panels, clean exit, scales to any terminal.
Keys: 1/2/3=tabs  q=quit  p=pause  r=refresh

Requires: pip install rich
"""

import argparse, atexit, json, os, re, signal, sys, time
from collections import deque
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.align import Align
from rich.columns import Columns
from rich.box import ROUNDED, MINIMAL, SIMPLE

# ── Config ──
PROJECT = Path(__file__).resolve().parent
STATE = PROJECT / "data"
EQUITY = deque(maxlen=60)
TAB = 0
TABS = [None, None, None]  # cached Layouts

SCALE = None  # (w, h) snapshot for layout calc


# ── Helpers ──

def _g(v): return f"[green]{v}[/]"
def _r(v): return f"[red]{v}[/]"
def _y(v): return f"[yellow]{v}[/]"
def _d(v): return f"[dim]{v}[/]"
def _c(v): return f"[cyan]{v}[/]"
def _b(v): return f"[bold]{v}[/]"

def pct(v):
    if v > 0: return _g(f"+{v:.2f}%")
    if v < 0: return _r(f"{v:.2f}%")
    return _d(f"{v:.2f}%")

def dpnl(v):
    if v > 0: return _g(f"+${v:,.2f}")
    if v < 0: return _r(f"-${abs(v):,.2f}")
    return _d("$0.00")

BLOCKS = " ▁▂▃▄▅▆▇█"
def spark(vals, w=60):
    if len(vals) < 2: return _d("collecting data...")
    mn, mx = min(vals), max(vals)
    if mx == mn: mx = mn + 0.01
    n, step = len(vals), max(1, len(vals) // w)
    s = [vals[i] for i in range(0, n, step)][-w:]
    return "".join(BLOCKS[max(0, min(8, int((v - mn) / (mx - mn) * 8)))] for v in s)


def load_state():
    try: return json.loads((STATE / "paper_state.json").read_text())
    except: return {}

def load_registry():
    try: return json.loads((STATE / "adapter_registry.json").read_text())
    except: return {}


# ── Panels ──

def kpi_header(s):
    """Single row of KPI tiles, AdGuardian style."""
    pv = s.get("portfolio_value", 0)
    init = s.get("initial_cash", 0) or 1
    ret = (pv - init) / init * 100
    cy = s.get("cycle", 0)
    m = s.get("metrics", {})
    tr = m.get("total_fills", 0)
    wr = m.get("signal_accuracy", {}).get("overall_accuracy_pct", 0)
    dd = m.get("drawdown_pct", 0)
    pk = m.get("peak_value", 0) or pv

    kpis = [
        (f"${pv:,.2f}", "Portfolio"),
        (pct(ret), "Return"),
        (f"{tr}", "Trades"),
        (f"{wr:.1f}%" if wr > 0 else "--", "Win Rate"),
        (f"{dd:.2f}%", "Drawdown"),
        (f"${pk:,.2f}", "Peak"),
        (f"{cy:,}", "Cycle"),
    ]

    tiles = []
    for v, l in kpis:
        t = Text()
        t.append(f"{v}\n", style="bold")
        t.append(l, style="dim")
        tiles.append(Panel(Align(t, "center"), box=ROUNDED, padding=(0, 1)))
    return Panel(Columns(tiles, equal=True, padding=0),
                 title="[bold]OpenTrader[/]",
                 subtitle=_d(f"{s.get('timestamp','')[:19]}  1=ov 2=pos 3=trn 4=deb 5=pipeline q=quit"),
                 box=ROUNDED)


def equity_panel():
    vals = list(EQUITY)
    if len(vals) < 2:
        # Show progress bar toward first chart point + elapsed time
        n = len(vals)
        bar_w = 40
        filled = min(bar_w, max(1, int(n / 2 * bar_w)))  # 2 points → full bar
        bar = "█" * filled + "░" * (bar_w - filled)
        age = "just started" if n == 0 else f"{n} sample{'s' if n != 1 else ''}"
        t = Text()
        t.append(f"[dim]Building equity curve... {age}\n[/]")
        t.append(bar + f"\n")
        t.append(_d(f"Need 2+ data points -- collecting every 2s"))
        return Panel(Align(t, "center"), title="Equity Curve", box=ROUNDED)
    chg = (vals[-1] - vals[0]) / vals[0] * 100 if vals[0] else 0
    color = "green" if chg >= 0 else "red"
    t = Text()
    t.append(f"{spark(vals, 70)}\n", style=color)
    t.append(f"${min(vals):,.2f}  ─  ${max(vals):,.2f}  │  {_g(f'{chg:+.2f}%') if chg >= 0 else _r(f'{chg:.2f}%')}  │  {len(vals)} pts")
    return Panel(Align(t, "center"), title="Equity Curve", box=ROUNDED)


def positions_panel(s):
    pos = s.get("positions", [])
    if not pos:
        return Panel(_d("No open positions"), title="Positions", box=ROUNDED)

    cy = s.get("cycle", 0)

    def exit_prob(p, current_cycle):
        """Estimate probability position closes next cycle (%).

        Based on distance to SL vs TP relative to current price.
        Closer to SL → higher exit probability (biased toward stop-out).
        Older positions → slightly higher probability of resolution.
        """
        sl = float(p.get("stop_loss", 0))
        tp = float(p.get("take_profit", 0))
        cur = float(p.get("current_price", 0))
        if not sl or not tp or not cur:
            return 0.0, "--"

        sl_dist = (cur - sl) / cur       # 0 = at SL, 1 = far away
        tp_dist = (tp - cur) / cur       # 0 = at TP, 1 = far away
        if sl_dist + tp_dist < 0.001:
            sl_dist = tp_dist = 1.0

        # Raw probability: higher when closer to SL vs TP
        raw = tp_dist / (sl_dist + tp_dist)  # 0=near SL (will stop), 1=near TP (will profit)
        # Invert: we want "probability of EXIT" (SL hit = exit)
        exit_raw = 1.0 - raw  # high when near SL

        # Age factor: older positions marginally more likely to resolve
        opened = int(p.get("cycle_opened", current_cycle))
        age_cycles = max(0, current_cycle - opened)
        age_bonus = min(0.15, age_cycles * 0.01)  # caps at 15% after 15 cycles

        prob = min(0.99, exit_raw + age_bonus)
        # Guard: if very close to SL, probability is high
        if sl_dist < 0.01:  # within 1% of SL
            prob = max(prob, 0.85)
        direction = "sl" if exit_raw > 0.5 else "tp"
        return prob, direction

    t = Table(box=MINIMAL, expand=True, header_style="bold")
    t.add_column("Symbol", style="cyan")
    t.add_column("Qty", justify="right")
    t.add_column("Entry", justify="right")
    t.add_column("Current", justify="right")
    t.add_column("P&L", justify="right")
    t.add_column("Ret", justify="right")
    t.add_column("Exit ↗", justify="right")

    for p in pos:
        sym = p.get("symbol", "?")
        q = float(p.get("quantity", 0))
        e = float(p.get("entry_price", 0))
        c = float(p.get("current_price", 0))
        pnl_v = (c - e) * q
        r_v = ((c - e) / e * 100) if e > 0 else 0

        prob, bias = exit_prob(p, cy)
        if prob > 0:
            pc = "red" if bias == "sl" else "green"
            ep = f"[{pc}]{prob:.0%}→{bias}[/]"
        else:
            ep = _d("--")

        t.add_row(sym, f"{q:.4f}", f"${e:,.2f}", f"${c:,.2f}",
                  dpnl(pnl_v), pct(r_v), ep)
    return Panel(t, title="Positions", box=ROUNDED)


def signals_panel(s):
    sigs = s.get("signals", [])[-6:][::-1]
    if not sigs:
        return Panel(_d("No recent signals"), title="Recent Signals", box=ROUNDED)
    t = Table(box=MINIMAL, expand=True, header_style="bold")
    t.add_column("Sym", style="cyan")
    t.add_column("Act")
    t.add_column("Conf", justify="right")
    t.add_column("Reason", max_width=40)
    for sig in sigs:
        act = sig.get("action", "HOLD").upper()
        c = "[green]" if act == "BUY" else "[red]" if act == "SELL" else "[dim]"
        t.add_row(sig.get("symbol", "?"),
                  f"{c}{act}[/]",
                  f"{sig.get('confidence', 0):.2f}",
                  (sig.get("reasoning", "") or sig.get("reason", ""))[:40])
    return Panel(t, title="Recent Signals", box=ROUNDED)

def thinking_panel(s):
    """Display Kimi K3-style thinking from recent signals."""
    # Get thinking history from signals
    thinking_entries = []
    for sig in s.get("signals", [])[-10:]:
        think = sig.get("reasoning") or sig.get("reason", "")
        if think:
            thinking_entries.append({
                "cycle": sig.get("cycle", "?"),
                "symbol": sig.get("symbol", "?"),
                "action": sig.get("action", "N/A"),
                "confidence": sig.get("confidence", 0),
                "reasoning": think,
            })
    
    if not thinking_entries:
        return Panel(
            _d("[Kimi K3] No thinking steps yet -- waiting for agent reasoning...\n\n"
               "Once the agent completes a full analysis cycle, it will output:\n"
               "<|thinking_start|>  (structured reasoning steps)\n"
               "  Thought: [step 1]\n"
               "  Thought: [step 2]\n"
               "  Thought: [step 3]\n"
               "  Thought: [step 4]\n"
               "  Thought: [step 5]\n"
               "<|thinking_end|>\n"
               "\nThen the final SIGNAL:"),
            title="Thinking (Kimi K3)",
            box=ROUNDED,
        )
    
    t = Text()
    t.append("[bold]Thinking History (last 5 cycles with reasoning):[/]\n\n")
    for entry in thinking_entries[-5:]:
        action = entry.get("action", "HOLD")
        color = "green" if action == "BUY" else "red" if action == "SELL" else "dim"
        t.append(f"[bold]{entry['symbol']}[/] ({action}) -- confidence: {entry.get('confidence', 0):.2f}\n")
        reasoning = entry.get("reasoning", "")
        if len(reasoning) > 120:
            reasoning = reasoning[:120] + "..."
        t.append(f"  Reasoning: {reasoning}\n")
        t.append(f"  Cycle: {entry['cycle']}\n\n")
    
    return Panel(Align(t, "left"), title="Thinking (Kimi K3)", box=ROUNDED, padding=(0, 1))
def status_panel():
    t = Text()
    # Harness
    hpid = None
    try:
        for p in Path("/proc").iterdir():
            if p.name.isdigit():
                c = (p / "cmdline").read_text(errors="ignore")
                if "harness.py" in c:
                    hpid = p.name
                    break
    except OSError: pass
    t.append(f"Harness:   {'● running' if hpid else '○ stopped'}\n")

    # Model
    spid = None
    try:
        for p in Path("/proc").iterdir():
            if p.name.isdigit():
                c = (p / "cmdline").read_text(errors="ignore").replace("\x00", " ")
                if "llama-server" in c and "5806" in c:
                    spid = p.name
                    break
    except OSError: pass
    t.append(f"Model:     {'● running' if spid else '○ stopped'}\n")

    train = (STATE / "training.lock").exists()
    t.append(f"Training:  {'■ active' if train else '□ idle'}\n")
    t.append(f"Mode:      Universe + ADIR debate\n")
    t.append(f"Cron:      train 02:00 | eval /30min | deploy chained\n")
    return Panel(t, title="System Status", box=ROUNDED)


def training_panel():
    reg = load_registry()
    active, active_ev = "", 0.0
    for v, e in reg.items():
        if e.get("status") == "active":
            active = v
            active_ev = e.get("eval_score", 0) or 0
    t = Text()
    t.append(f"Active: [cyan bold]{active}[/] (eval {active_ev:.4f})\n\n")
    t.append("[bold]Eval Scores:[/]\n")
    seen = set()
    rdir = STATE / "eval" / "reports"
    if rdir.exists():
        for r in sorted(rdir.glob("*_deep_*.json"), reverse=True):
            vn = r.stem.split("_deep_")[0]
            if vn in seen: continue
            seen.add(vn)
            try:
                d = json.loads(r.read_text())
                sc = d.get("weighted_score", 0)
                c = "green" if sc >= 0.75 else "yellow" if sc >= 0.5 else "red"
                t.append(f"  {vn}: [{c}]{sc:.4f}[/]\n")
            except: pass

    # Advisor (Fork 2d fix: uses eval_score cross-referenced with harness metrics)
    s = load_state()
    m = s.get("metrics", {})
    wr = m.get("signal_accuracy", {}).get("overall_accuracy_pct", 0)
    br = s.get("hodl_benchmark", {}).get("outperform_pct", 0)
    t.append("\n[bold]Advisor:[/]\n")
    if active_ev >= 0.75 and (br > 0 or wr > 55):
        t.append(_g("  Strong -- eval >=0.75, beating market. Stay the course.\n"))
    elif active_ev >= 0.50:
        t.append(_y("  Developing -- eval healthy, building track record.\n"))
    elif active_ev > 0:
        t.append(_r("  Weak -- eval below 0.50, needs more training.\n"))
    else:
        t.append(_r("  Unevaluated -- pending deep_eval.\n"))

    return Panel(t, title="Training & Eval", box=ROUNDED)


# ── Fork 2a: Per-dimension breakdown with mini-bars ──────────

DIM_LABELS = {
    "signal_accuracy": "SigAcc", "reasoning_coherence": "ReasCoh",
    "confidence_calibration": "ConfCal", "adversarial_robustness": "AdvRob",
    "debate_quality": "DebQual", "edge_detection": "EdgeDet",
    "temporal_consistency": "TempCon",
}
DIM_WEIGHTS = {
    "signal_accuracy": 0.25, "reasoning_coherence": 0.20,
    "confidence_calibration": 0.20, "adversarial_robustness": 0.12,
    "debate_quality": 0.10, "edge_detection": 0.08,
    "temporal_consistency": 0.05,
}


def eval_breakdown_panel():
    rdir = STATE / "eval" / "reports"
    if not rdir.exists():
        return Panel(_d("No eval reports yet"), title="Eval Breakdown", box=ROUNDED)

    # Collect latest report per model + compute stddev across runs
    models = {}
    for r in sorted(rdir.glob("*_deep_*.json")):
        vn = r.stem.split("_deep_")[0]
        d = json.loads(r.read_text())
        models.setdefault(vn, []).append(d)

    if not models:
        return Panel(_d("No eval reports found"), title="Eval Breakdown", box=ROUNDED)

    t = Table(box=MINIMAL, expand=True, header_style="bold")
    t.add_column("Model", style="cyan", width=11)
    t.add_column("Wgt", justify="right", width=6)
    for dk in DIM_LABELS:
        t.add_column(DIM_LABELS[dk], justify="center", width=8)
    t.add_column("RUNS", justify="right", width=5)

    sorted_models = sorted(models.items(), key=lambda x: x[1][-1]["weighted_score"], reverse=True)

    for vn, runs in sorted_models:
        latest = runs[-1]
        ws = latest["weighted_score"]
        dims = latest.get("per_dim_scores", {})
        n = len(runs)

        # Highlight top model
        style = "cyan" if vn == sorted_models[0][0] else ""

        row = [_b(_c(vn)) if style else vn]
        c = "green" if ws >= 0.75 else "yellow" if ws >= 0.5 else "red"
        row.append(f"[{c}]{ws:.3f}[/]")

        for dk in DIM_LABELS:
            ds = dims.get(dk, 0)
            # Mini-bar: 4 chars wide
            bar = spark([ds], 4) if ds > 0 else "    "
            c2 = "green" if ds >= 0.75 else "yellow" if ds >= 0.5 else "red"
            row.append(f"[{c2}]{ds:.3f}[/]")

        row.append(str(n))
        t.add_row(*row)

    return Panel(t, title="Eval Breakdown (per dim)", box=ROUNDED)


# ── Fork 2b: Pending candidates awaiting eval ─────────────────

def pending_candidates_panel():
    reg = load_registry()
    pending = []
    for v, e in reg.items():
        if e.get("status") in ("pending", "rolled_back") and not e.get("eval_score"):
            pending.append((v, e))

    train = (STATE / "training.lock").exists()
    now = __import__("datetime").datetime.now()
    eta = (30 - now.minute % 30) % 30

    if not pending:
        return Panel(_d("No pending candidates -- all evaluated"), title="Pending Candidates",
                     box=ROUNDED)

    t = Table(box=MINIMAL, expand=True, header_style="bold")
    t.add_column("Candidate", style="cyan")
    t.add_column("Examples", justify="right")
    t.add_column("Status")
    t.add_column("Eval Status")
    t.add_column(f"Next eval ~{eta}m")

    for v, e in pending:
        ex = e.get("training_examples", e.get("examples", 0))
        st = e.get("status", "?")
        ev_st = "✗ blocked by training" if train else "✗ awaiting eval"
        next_ev = _d("deferred") if train else _y(f"~{eta}min")
        t.add_row(v, str(ex), st, ev_st, next_ev)

    return Panel(t, title="Pending Candidates", box=ROUNDED)


# ── Fork 2c: Deploy gate comparison ──────────────────────────

def deploy_gate_panel():
    reg = load_registry()
    active_v, active_s = "", 0.0
    for v, e in reg.items():
        if e.get("status") == "active":
            active_v = v
            active_s = e.get("eval_score", 0) or 0
            break

    candidates = []
    for v, e in reg.items():
        if v != active_v and (e.get("eval_score") or 0) > 0:
            candidates.append((v, e.get("eval_score", 0) or 0))

    if not candidates:
        return Panel(_d("No evaluated candidates to compare"), title="Deploy Gate", box=ROUNDED)

    t = Table(box=MINIMAL, expand=True, header_style="bold")
    t.add_column("Candidate", style="cyan")
    t.add_column("Score", justify="right")
    t.add_column(f"Active ({active_v})", justify="right")
    t.add_column("Delta", justify="right")
    t.add_column("Gate (>=+3.0)", justify="right")
    t.add_column("Verdict")

    candidates.sort(key=lambda x: x[1], reverse=True)
    for v, s in candidates:
        delta = s - active_s
        verd = "ready" if delta >= 3.0 else ("no edge" if delta >= 0 else "no promo")
        c = "green" if delta >= 3.0 else ("yellow" if delta >= 0 else "red")
        t.add_row(v, f"{s:.4f}", f"{active_s:.4f}", f"{delta:+.4f}",
                  f"[dim]>=+3.0[/]", f"[{c}]{verd}[/]")

    return Panel(t, title="Deploy Gate", box=ROUNDED)


# ── Tabs ──

def build_overview(s):
    l = Layout()
    l.split_column(
        Layout(kpi_header(s), name="kpi", size=4),
        Layout(name="main"),
    )
    l["main"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )
    l["left"].split_column(
        Layout(positions_panel(s), name="positions", ratio=1),
        Layout(signals_panel(s), name="signals", ratio=1),
        Layout(thinking_panel(s), name="thinking", ratio=0.5),
    )

    l["right"].split_column(
        Layout(status_panel(), name="status"),
        Layout(training_panel(), name="training"),
        Layout(equity_panel(), name="equity"),
    )
    return l

def build_positions_detail(s):
    l = Layout()
    l.split_column(
        Layout(kpi_header(s), name="kpi", size=4),
        Layout(name="body"),
    )
    l["body"].split_column(
        Layout(positions_panel(s), name="positions", ratio=2),
        Layout(signals_panel(s), name="signals", ratio=1),
    )
    return l

def build_training_detail(s):
    l = Layout()
    l.split_column(
        Layout(kpi_header(s), name="kpi", size=4),
        Layout(name="body"),
    )
    l["body"].split_column(
        Layout(training_panel(), name="training", ratio=1),
        Layout(status_panel(), name="status"),
    )
    return l


# ── Fork 3a: Research heartbeat ──────────────────────────────

def research_heartbeat_panel():
    t = Text()

    sch_path = STATE / "scheduler_state.json"
    if sch_path.exists():
        try:
            sch = json.loads(sch_path.read_text())
        except Exception:
            sch = {}
    else:
        sch = {}

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    def age(ts):
        if not ts: return "never"
        try:
            dt = __import__("datetime").datetime.fromisoformat(ts)
            h = (now - dt).total_seconds() / 3600
            if h < 1: return f"{int(h*60)}m ago"
            if h < 24: return f"{int(h)}h ago"
            return f"{int(h/24)}d {int(h%24)}h ago"
        except: return ts[:19]

    t.append("[bold]Scheduler:[/]\n")
    sts = sch.get("last_scout_sweep")
    t.append(f"  Scout:     {age(sts)}")
    if sts:
        try:
            h = (now - __import__("datetime").datetime.fromisoformat(sts)).total_seconds() / 3600
            t.append(f"[red] ⚠ stale {h:.0f}h[/]" if h > 6 else _d(" fresh"))
        except: pass
    t.append("\n")

    t.append(f"  Distill:   {age(sch.get('last_distill'))}\n")
    t.append(f"  ATDL:      {age(sch.get('last_atdl_trigger'))}\n")
    t.append(f"  Research:  {age(sch.get('last_research_model_check'))}\n")

    ap = STATE / "atdl_state.json"
    if ap.exists():
        try:
            a = json.loads(ap.read_text())
            t.append("\n[bold]ATDL:[/]\n")
            ph = a.get("phase", "?")
            c = "green" if ph == "MONITOR" else "yellow" if ph == "PLAN" else "red"
            t.append(f"  Phase:      [{c}]{ph}[/]\n")
            t.append(f"  Variants:   {a.get('variant_counter', 0)}\n")
            h = a.get("history", [])
            if h:
                lh = h[-1]
                t.append(f"  Last:       {lh.get('from_phase','?')} → {lh.get('to_phase','?')} (c{lh.get('cycle','?')})\n")
        except: pass

    return Panel(t, title="Research Heartbeat", box=ROUNDED)


def build_pipeline_detail(s):
    l = Layout()
    l.split_column(
        Layout(kpi_header(s), name="kpi", size=4),
        Layout(name="body"),
    )
    l["body"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )
    l["left"].split_column(
        Layout(eval_breakdown_panel(), name="breakdown", ratio=2),
        Layout(pending_candidates_panel(), name="pending"),
    )
    l["right"].split_column(
        Layout(deploy_gate_panel(), name="deploy"),
        Layout(research_heartbeat_panel(), name="research"),
    )
    return l


def build_debate_placeholder(s):
    """Fork 1 -- live ADIR debate + universe scout from ui_feed.jsonl."""
    return build_debate_detail(s)


# ── Fork 1e: Universe picks panel ─────────────────────────────

def universe_panel():
    feed_path = STATE / "ui_feed.jsonl"
    if not feed_path.exists():
        return Panel(_d("No ui_feed.jsonl yet -- harness must write it (Fork 1)"),
                     title="Universe Scout", box=ROUNDED)

    try:
        lines = feed_path.read_text().splitlines()
        last = json.loads(lines[-1]) if lines else {}
    except Exception:
        return Panel(_d("Error reading ui_feed.jsonl"), title="Universe Scout", box=ROUNDED)

    picks = last.get("universe", [])
    if not picks:
        return Panel(_d("No universe picks in latest cycle"), title="Universe Scout", box=ROUNDED)

    t = Table(box=MINIMAL, expand=True, header_style="bold")
    t.add_column("Symbol", style="cyan")
    t.add_column("Score", justify="right")
    t.add_column("Reason", max_width=40)

    for p in picks[:6]:
        sym = p.get("symbol", "?")
        sc = p.get("score", 0)
        c = "green" if sc >= 7 else "yellow" if sc >= 5 else "red"
        t.add_row(sym, f"[{c}]{sc:.1f}[/]", p.get("reason", "")[:40])

    n = len(picks)
    return Panel(t, title=f"Universe Top {n} (agent scouts 52)", box=ROUNDED)


# ── Fork 1e: Debate votes panel ───────────────────────────────

def debate_panel():
    feed_path = STATE / "ui_feed.jsonl"
    if not feed_path.exists():
        return Panel(_d("No ui_feed.jsonl yet"), title="ADIR Debate", box=ROUNDED)

    try:
        lines = feed_path.read_text().splitlines()
        last = json.loads(lines[-1]) if lines else {}
    except Exception:
        return Panel(_d("Error reading ui_feed.jsonl"), title="ADIR Debate", box=ROUNDED)

    debates = last.get("debates", {})
    if not debates:
        return Panel(_d("No debate data in latest cycle"), title="ADIR Debate", box=ROUNDED)

    t = Table(box=MINIMAL, expand=True, header_style="bold")
    t.add_column("Symbol", style="cyan")
    t.add_column("Role")
    t.add_column("Action")
    t.add_column("Conf", justify="right")
    t.add_column("Bar")

    for sym, roles in debates.items():
        for role_name in ("bull", "bear", "risk"):
            r = roles.get(role_name, {})
            act = r.get("action", "HOLD")
            conf = r.get("conf", 0)
            evq = r.get("evq")
            bar_w = int(conf * 10)
            bar = "█" * bar_w + "░" * (10 - bar_w)
            c = "[green]" if act == "BUY" else "[red]" if act == "SELL" else "[dim]"
            role_color = "[green]" if role_name == "bull" else "[red]" if role_name == "bear" else "[yellow]"
            evq_str = f" evq={evq:.2f}" if evq is not None else ""
            t.add_row(
                sym if role_name == "bull" else "",
                f"{role_color}{role_name.upper()}[/]",
                f"{c}{act}[/]",
                f"{conf:.0%}{evq_str}",
                f"{bar}",
            )
        t.add_row("", "", "", "", "")  # blank separator

    return Panel(t, title="ADIR Debate Votes", box=ROUNDED)


# ── Fork 1e: Debate tab builder ──────────────────────────────

def build_debate_detail(s):
    l = Layout()
    l.split_column(
        Layout(kpi_header(s), name="kpi", size=4),
        Layout(name="body"),
    )
    l["body"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )
    l["left"].split_column(
        Layout(universe_panel(), name="universe", ratio=1),
        Layout(positions_panel(s), name="positions", ratio=1),
    )
    l["right"].update(debate_panel())
    return l


# ── Main ──

def main():
    global TAB
    console = Console()
    paused = False
    running = True

    def build():
        s = load_state()
        pv = s.get("portfolio_value", 0)
        if pv > 0 and (not EQUITY or pv != EQUITY[-1]):
            EQUITY.append(pv)
        builders = [build_overview, build_positions_detail, build_training_detail,
                    build_debate_detail, build_pipeline_detail]
        return builders[TAB](s)

    # Keyboard: try /dev/tty first, fall back to sys.stdin
    tty_fd = None
    try:
        tty_fd = os.open("/dev/tty", os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        pass

    kbd = tty_fd if tty_fd is not None else sys.stdin.fileno()
    import termios as _tm, tty as _tt
    _old_tm = _tm.tcgetattr(kbd) if os.isatty(kbd) else None
    if _old_tm is not None:
        _tt.setcbreak(kbd)

    # Ensure terminal restored on any exit
    def cleanup():
        if _old_tm is not None:
            try: _tm.tcsetattr(kbd, _tm.TCSADRAIN, _old_tm)
            except: pass
        if tty_fd is not None:
            try: os.close(tty_fd)
            except: pass
        os.system("stty sane 2>/dev/null")
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()
    atexit.register(cleanup)

    def sig_handler(s, f):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    # SIGWINCH handler -- flush Rich's cached terminal size on resize
    def on_resize(s, f):
        console._size = None
        os.get_terminal_size()
    signal.signal(signal.SIGWINCH, on_resize)

    # Manual screen management -- enter alt screen, render, poll keys
    sys.stdout.write("\033[?1049h\033[?25l\033[2J")
    sys.stdout.flush()

    last = 0
    while running:
        # Non-blocking key read
        try:
            import select as sel
            r, _, _ = sel.select([kbd], [], [], 0)
            if r:
                data = os.read(kbd, 16).decode(errors="ignore")
                for ch in data:
                    if ch == "q":
                        running = False
                    elif ch == "p":
                        paused = not paused
                    elif ch == "1": TAB = 0
                    elif ch == "2": TAB = 1
                    elif ch == "3": TAB = 2
                    elif ch == "4": TAB = 3
                    elif ch == "5": TAB = 4
                    elif ch == "r" or ch == "\x12":  # r or Ctrl+R
                        last = 0  # force immediate refresh
        except (OSError, ValueError):
            pass

        now = time.time()
        if not paused and now - last >= 2.0:
            console._size = None  # force re-measure on each render
            layout = build()
            sys.stdout.write("\033[H\033[2J")
            console.print(layout)
            sys.stdout.flush()
            last = now
        time.sleep(0.05)


if __name__ == "__main__":
    main()
