#!/usr/bin/env node
// opentrader-tui — read-only terminal client over the harness state files.
// Zero-build: plain JS + React.createElement (no JSX, no transpiler).
// v2 design: single-column sections, fixed-width aligned cells, color hierarchy.
import React, { useEffect, useState } from "react";
import { render, Box, Text, useInput, useApp } from "ink";
import { readFileSync } from "node:fs";

const BASE = "/home/mrc/opentrader/data";
const SHADOW = `${BASE}/shadow_scaled`;
const WAYFINDER = `${BASE}/wayfinder`;

const read = (p) => { try { return readFileSync(p, "utf8"); } catch { return null; } };
const readJson = (p) => {
  const s = read(p);
  if (!s) return null;
  try { return JSON.parse(s); } catch { return null; }
};

const W = 96; // design width — lines are built to this, ink wraps beyond it

function loadState() {
  const csv = read(`${SHADOW}/ab_equity.csv`);
  let rows = [];
  let mainSeries = [];
  let shadowSeries = [];
  if (csv) {
    rows = csv.trim().split("\n").slice(1).map((l) => l.split(","));
    const tail = rows.slice(-140);
    mainSeries = tail.map((r) => parseFloat(r[2])).filter((v) => !isNaN(v));
    shadowSeries = tail.map((r) => parseFloat(r[6])).filter((v) => !isNaN(v));
  }
  const last = rows.length ? rows[rows.length - 1] : null;
  const feedMain = (read(`${BASE}/ui_feed.jsonl`) || "").trim().split("\n").slice(-2);
  const paperMain = readJson(`${BASE}/paper_state.json`);
  const paperShadow = readJson(`${SHADOW}/paper_state.json`);
  const deploy = readJson(`${WAYFINDER}/deployability_status.json`);
  const router = readJson(`${BASE}/live_router_state.json`);
  const ledgerLines = (read(`${BASE}/fills_ledger.jsonl`) || "").split("\n").filter((l) => l.trim()).length;
  return { last, mainSeries, shadowSeries, feedMain, paperMain, paperShadow, deploy, router, ledgerLines };
}

function sparkline(series, width = 46) {
  if (!series.length) return "(no data)";
  const vals = series.slice(-width);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const chars = "▁▂▃▄▅▆▇█";
  return vals.map((v) => chars[Math.min(7, Math.max(0, Math.floor(((v - min) / span) * 7)))]).join("");
}

const money = (v, d = 2) => (v != null && !isNaN(v) ? Number(v).toFixed(d) : "—");
const fmtQty = (q) => {
  const n = Number(q);
  if (isNaN(n)) return "—";
  if (Math.abs(n) >= 100) return n.toFixed(1);
  if (Math.abs(n) >= 1) return n.toFixed(3);
  return n.toFixed(6);
};

// positions → aligned table rows (fixed columns, ~86 chars)
function positionRows(paper) {
  const positions = (paper && paper.positions) || [];
  const head = "  SYMBOL       QTY         ENTRY       LAST        P/L       STOP        TARGET";
  const rows = positions.map((p) => {
    const cur = Number(p.current_price || 0), ent = Number(p.entry_price || 0);
    const pnl = cur && ent ? ((cur - ent) / ent) * 100 : null;
    const pnlS = pnl == null ? "—" : `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}%`;
    const stopDist = p.stop_loss && cur ? (((p.stop_loss - cur) / cur) * 100).toFixed(1) + "%" : "—";
    const tgtDist = p.take_profit && cur ? (((p.take_profit - cur) / cur) * 100).toFixed(1) + "%" : "—";
    return {
      color: pnl == null ? null : pnl >= 0 ? "green" : "red",
      text:
        `  ${String(p.symbol).padEnd(12)} ${fmtQty(p.quantity).padStart(10)} ` +
        `${money(ent).padStart(10)}  ${money(cur).padStart(10)}  ${pnlS.padStart(7)}  ` +
        `${stopDist.padStart(7)}  ${tgtDist.padStart(7)}`,
    };
  });
  return { head, rows };
}

function buildLines(state) {
  const { last, mainSeries, shadowSeries, paperMain, paperShadow, deploy, router, ledgerLines } = state;
  const L = [];
  const sep = () => L.push({ text: "─".repeat(W), dim: true });
  const header = (txt, color) => L.push({ text: txt, bold: true, color: color || "cyan" });

  // header
  const now = new Date().toTimeString().slice(0, 8);
  L.push({
    text: ` OPENTRADER · ${now} · main cycle ${last ? last[1] : "—"} · shadow cycle ${last ? last[5] : "—"}`,
    bold: true, bg: "blue",
  });

  // equity
  L.push({ text: "" });
  const mv = last ? parseFloat(last[2]) : null;
  const sv = last ? parseFloat(last[6]) : null;
  L.push({ text: ` main   $${money(mv)}  ${sparkline(mainSeries, 44)}`, color: "green" });
  L.push({ text: ` shadow $${money(sv)}  ${sparkline(shadowSeries, 44)}`, color: "yellow" });

  // books
  for (const [title, paper, color] of [
    ["CRYPTO BOOK — MAIN", paperMain, "green"],
    ["CRYPTO BOOK — SHADOW", paperShadow, "yellow"],
  ]) {
    const value = paper && paper.portfolio_value;
    const cash = paper && paper.cash;
    L.push({ text: "" });
    header(`${title}   value $${money(value)} · cash $${money(cash)}`, color);
    const { head, rows } = positionRows(paper);
    L.push({ text: head, dim: true });
    if (!rows.length) L.push({ text: "  (no positions)", dim: true });
    for (const r of rows) L.push(r);
  }

  // deployability
  // Display semantics (2026-08-31): FAIL = actively violated. Insufficient
  // elapsed time/data is ACCRUING, not failure. Derivation:
  //   C1 fail iff fatal defects > 0        C2 fail iff measured AND decayed
  //   C3 fail iff a gap exists post-clock-start (continuity fix, Aug 31)
  //   otherwise the clause is ACCRUING toward its bar.
  L.push({ text: "" });
  header("DEPLOYABILITY — ADR-0002" + (deploy ? ` · computed ${String(deploy.generated || "").slice(0, 10)}` : " · no data"));
  if (!deploy) {
    L.push({ text: "  run job-v11 (opentask) to compute", dim: true });
  } else {
    const c1 = deploy.clause1_plumbing || {}, c2 = deploy.clause2_edge || {}, c3 = deploy.clause3_calendar || {};
    const fd = c1.fatal_defects || {};
    const fatal = (fd.silent_hold || 0) + (fd.state_corruption || 0) + (fd.order_rejection || 0);
    const gaps = c3.gaps || [];
    const CLOCK_START = "2026-08-31"; // continuity fix — restarts safe from here
    const postFixGap = gaps.some((g) => String(g).slice(0, 10) >= CLOCK_START);
    const c1State = fatal > 0 ? ["✗ FAIL — fatal defect", "red"] : ["accruing", "yellow"];
    const c2State = c2.pass === true ? ["✓ PASS", "green"] : c2.pass === false ? ["✗ FAIL — decayed", "red"] : ["accruing — measurable at fwd 5/5", "yellow"];
    const c3State = postFixGap ? ["✗ FAIL — continuity broken", "red"] : [`${c3.continuous_days ?? 0}/70 days — accruing`, "yellow"];
    L.push({ text: `  C1 plumbing   closed ${String(c1.closed_trades ?? "?").padStart(3)} · exits ${(c1.exit_paths_seen || []).length} · fatal ${fatal}`.padEnd(62) + c1State[0], color: c1State[1] });
    L.push({ text: `  C2 edge       fwd_mean ${String(c2.rule_floor_impact_mean ?? "?").padStart(6)} (n=${c2.n ?? "?"})`.padEnd(62) + c2State[0], color: c2State[1] });
    L.push({ text: `  C3 calendar   ${String(c3.continuous_days ?? "?").padStart(3)} / 70 days continuous`.padEnd(62) + c3State[0], color: c3State[1] });
  }

  // router
  L.push({ text: "" });
  header(`ROUTER — MoT · fills-ledger ${ledgerLines}`);
  if (!router) {
    L.push({ text: "  no live_router_state.json", dim: true });
  } else {
    for (const regime of ["up", "down"]) {
      const w = (router.weights || {})[regime] || {};
      const track = (router.track || {})[regime] || {};
      const parts = Object.entries(w).sort((a, b) => b[1] - a[1]).slice(0, 4)
        .map(([e, wt]) => {
          const t = track[e] || {};
          const fwd = t.fwd_n != null ? t.fwd_n : 0;
          return `${e} ${Number(wt).toFixed(2)}${e !== "rule" ? ` [fwd ${fwd}/5]` : ""}`;
        });
      L.push({ text: `  ${regime.toUpperCase().padEnd(5)} ${parts.join("  ·  ") || "(none)"}` });
    }
  }

  // FX track
  L.push({ text: "" });
  header("TRACK B — FX · OANDA practice");
  L.push({ text: "  adapter LIVE (a371d1b) · round-trip proven 08-31 (net 0, spread $0.02)" });
  L.push({ text: "  majors: EUR_USD  GBP_USD  USD_JPY  USD_CHF  GBP_JPY  AUD_USD  USD_CAD", dim: true });
  L.push({ text: "  daily cycle + expert mapping: this week", dim: true });

  // timeline
  L.push({ text: "" });
  header("TIMELINE");
  L.push({ text: "  Mon 17:30 shadow accrual   Fri 17:00 V11 recompute", dim: true });
  L.push({ text: "  Sep 7-14 FX gate review → D4 deposit decision   ~Nov 8 crypto 10-week mark", dim: true });
  return L;
}

function App() {
  const { exit } = useApp();
  const [state, setState] = useState(loadState);
  useInput((input) => {
    if (input === "q") exit();
    if (input === "r") setState(loadState());
  });
  useEffect(() => {
    const t = setInterval(() => setState(loadState()), 2000);
    return () => clearInterval(t);
  }, []);

  const lines = buildLines(state);
  return React.createElement(
    Box, { flexDirection: "column", paddingX: 1 },
    lines.map((l, i) =>
      React.createElement(
        Text, { key: i, bold: !!l.bold, color: l.color, backgroundColor: l.bg, dimColor: !!l.dim },
        l.text || " "
      )
    ),
    React.createElement(Text, { dimColor: true, marginTop: 1 }, "  [q] quit  [r] refresh  — polls every 2s")
  );
}

render(React.createElement(App));
