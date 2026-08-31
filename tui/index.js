#!/usr/bin/env node
// opentrader-tui — read-only terminal client over the harness state files.
// Zero-build: plain JS + React.createElement (no JSX, no transpiler).
// Reads: ab_equity.csv, ui_feed.jsonl, paper_state.json, health_status.log,
//        health_state.json, agent_state.json (main + shadow_scaled dirs),
//        wayfinder/deployability_status.json (ADR-0002 scoreboard),
//        live_router_state.json (router weights + fwd_n accrual),
//        fills_ledger.jsonl (authoritative fills, continuity-3).
import React, { useEffect, useState } from "react";
import { render, Box, Text, useInput, useApp } from "ink";
import { readFileSync } from "node:fs";

const BASE = "/home/mrc/opentrader/data";
const SHADOW = `${BASE}/shadow_scaled`;
const WAYFINDER = `${BASE}/wayfinder`;

const read = (p) => {
  try {
    return readFileSync(p, "utf8");
  } catch {
    return null;
  }
};
const readJson = (p) => {
  const s = read(p);
  if (!s) return null;
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
};

function loadState() {
  // equity history (last 140 rows)
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
  // ui feed tails
  const feedMain = (read(`${BASE}/ui_feed.jsonl`) || "").trim().split("\n").slice(-4);
  const feedShadow = (read(`${SHADOW}/ui_feed.jsonl`) || "").trim().split("\n").slice(-4);
  // paper states
  const paperMain = readJson(`${BASE}/paper_state.json`);
  const paperShadow = readJson(`${SHADOW}/paper_state.json`);
  // health
  const healthLog = (read(`${SHADOW}/health_status.log`) || "").trim().split("\n").slice(-3);
  const healthState = readJson(`${SHADOW}/health_state.json`);
  const agent = readJson(`${SHADOW}/agent_state.json`);
  // ADR-0002 scoreboard (V11 recompute)
  const deploy = readJson(`${WAYFINDER}/deployability_status.json`);
  // router state (weights + forward accrual)
  const router = readJson(`${BASE}/live_router_state.json`);
  // fills ledger (authoritative, continuity-3)
  const ledgerLines = (read(`${BASE}/fills_ledger.jsonl`) || "")
    .split("\n").filter((l) => l.trim()).length;
  return { last, mainSeries, shadowSeries, feedMain, feedShadow, paperMain, paperShadow, healthLog, healthState, agent, deploy, router, ledgerLines };
}

function sparkline(series, width = 60) {
  if (!series.length) return "(no data)";
  const vals = series.slice(-width);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const chars = "▁▂▃▄▅▆▇█";
  return vals
    .map((v) => chars[Math.min(7, Math.max(0, Math.floor(((v - min) / span) * 7)))])
    .join("");
}

function pnlCell(pos) {
  const cur = pos.current_price || 0;
  const ent = pos.entry_price || 0;
  if (!cur || !ent) return "—";
  const pct = ((cur - ent) / ent) * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

function PositionsTable({ title, paper, color }) {
  const positions = (paper && paper.positions) || [];
  const value = paper && paper.portfolio_value;
  return React.createElement(
    Box, { flexDirection: "column", marginRight: 2, width: 56 },
    React.createElement(Text, { bold: true, color },
      `${title}  value: ${value != null ? "$" + value.toFixed(2) : "—"}`),
    positions.length === 0
      ? React.createElement(Text, { dimColor: true }, "  (no positions)")
      : positions.map((p, i) =>
          React.createElement(
            Text, { key: i },
            `  ${p.symbol.padEnd(12)} qty ${String(p.quantity).slice(0, 10).padEnd(10)} ` +
              `ent $${(p.entry_price || 0).toFixed(2).padStart(9)}  now ${p.current_price ? "$" + p.current_price.toFixed(2) : "0 (feed?)".padStart(9)}  ` +
              `pnl ${pnlCell(p).padStart(8)}  SL ${p.stop_loss ? "$" + p.stop_loss.toFixed(2) : "—"}  TP ${p.take_profit ? "$" + p.take_profit.toFixed(2) : "—"}`
          )
        )
  );
}

function clauseCell(pass) {
  if (pass === true) return React.createElement(Text, { color: "green" }, "PASS");
  if (pass === false) return React.createElement(Text, { color: "red" }, "FAIL");
  return React.createElement(Text, { color: "yellow" }, "PENDING");
}

function ScoreboardPanel({ deploy }) {
  if (!deploy) {
    return React.createElement(
      Box, { flexDirection: "column", marginTop: 1, marginRight: 2 },
      React.createElement(Text, { bold: true }, "DEPLOYABILITY (ADR-0002)"),
      React.createElement(Text, { dimColor: true }, "  no recompute yet — run job-v11 (opentask)")
    );
  }
  const c1 = deploy.clause1_plumbing || {};
  const c2 = deploy.clause2_edge || {};
  const c3 = deploy.clause3_calendar || {};
  const fd = c1.fatal_defects || {};
  const fatal = (fd.silent_hold || 0) + (fd.state_corruption || 0) + (fd.order_rejection || 0);
  return React.createElement(
    Box, { flexDirection: "column", marginTop: 1, marginRight: 2 },
    React.createElement(Text, { bold: true }, `DEPLOYABILITY (ADR-0002)  computed ${String(deploy.generated || "").slice(0, 10)}`),
    React.createElement(Text, null,
      `  C1 plumbing    closed=${c1.closed_trades != null ? c1.closed_trades : "?"} exits=${(c1.exit_paths_seen || []).length} fatal=${fatal}  `,
      clauseCell(c1.pass)),
    React.createElement(Text, null,
      `  C2 edge        fwd_mean=${c2.rule_floor_impact_mean != null ? c2.rule_floor_impact_mean : "?"} n=${c2.n != null ? c2.n : "?"}  `,
      clauseCell(c2.pass)),
    React.createElement(Text, null,
      `  C3 calendar    days=${c3.continuous_days != null ? c3.continuous_days : "?"}/70  `,
      clauseCell(c3.pass)),
  );
}

function RouterPanel({ router, ledgerLines }) {
  if (!router) {
    return React.createElement(
      Box, { flexDirection: "column", marginTop: 1, marginRight: 2 },
      React.createElement(Text, { bold: true }, "ROUTER (MoT)"),
      React.createElement(Text, { dimColor: true }, "  no live_router_state.json")
    );
  }
  const line = (regime) => {
    const w = (router.weights || {})[regime] || {};
    const track = (router.track || {})[regime] || {};
    const parts = Object.entries(w)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
      .map(([e, wt]) => {
        const t = track[e] || {};
        const fwd = t.fwd_n != null ? t.fwd_n : 0;
        return `${e} ${wt.toFixed(2)}${e !== "rule" ? ` (fwd ${fwd}/5)` : ""}`;
      });
    return `${regime}: ` + (parts.join(" · ") || "(none)");
  };
  return React.createElement(
    Box, { flexDirection: "column", marginTop: 1, marginRight: 2 },
    React.createElement(Text, { bold: true }, `ROUTER (MoT)  ${router.schema || ""} fills-ledger: ${ledgerLines}`),
    React.createElement(Text, null, "  " + line("up")),
    React.createElement(Text, null, "  " + line("down")),
    React.createElement(Text, { dimColor: true }, "  fwd n/5 = forward windows toward step() eligibility")
  );
}

function FxPanel() {
  return React.createElement(
    Box, { flexDirection: "column", marginTop: 1, marginRight: 2 },
    React.createElement(Text, { bold: true, color: "cyan" }, "TRACK B — FX (OANDA practice)"),
    React.createElement(Text, null, "  adapter: LIVE (a371d1b) · round-trip proven 08-31 (net 0, spread $0.02)"),
    React.createElement(Text, null, "  majors: EUR_USD GBP_USD USD_JPY USD_CHF GBP_JPY AUD_USD USD_CAD"),
    React.createElement(Text, { dimColor: true }, "  daily cycle + expert mapping: this week · evidence: fills-ledger (fwd)"),
  );
}

function TimelinePanel() {
  return React.createElement(
    Box, { flexDirection: "column", marginTop: 1 },
    React.createElement(Text, { bold: true }, "TIMELINE"),
    React.createElement(Text, { dimColor: true }, "  Mon 17:30 shadow-driver accrual (fwd_n+1)  ·  Fri 17:00 V11 recompute"),
    React.createElement(Text, { dimColor: true }, "  Sep 7-14 FX gate review → first-deposit decision (D4)  ·  ~Nov 8 crypto 10-week mark"),
  );
}

function App() {
  const { exit } = useApp();
  const [state, setState] = useState(loadState);
  const [feedOffset, setFeedOffset] = useState(0);
  useInput((input) => {
    if (input === "q") exit();
    if (input === "r") setState(loadState());
    if (input === "j") setFeedOffset((o) => o + 1);
    if (input === "k") setFeedOffset((o) => Math.max(0, o - 1));
  });
  useEffect(() => {
    const t = setInterval(() => setState(loadState()), 2000);
    return () => clearInterval(t);
  }, []);

  const { last, mainSeries, shadowSeries, feedMain, feedShadow, paperMain, paperShadow, healthLog, agent, deploy, router, ledgerLines } = state;
  const mainVal = last ? parseFloat(last[2]) : null;
  const shadowVal = last ? parseFloat(last[6]) : null;
  const mainCycle = last ? last[1] : "—";
  const shadowCycle = last ? last[5] : "—";
  const health = healthLog.length ? healthLog[healthLog.length - 1] : "no health log";
  const ok = health.includes("HEALTHY");

  const feedLines = [...feedMain.slice(-2), ...feedShadow.slice(-2)].reverse();

  return React.createElement(
    Box, { flexDirection: "column", paddingX: 1, width: "100%" },
    React.createElement(Text, { bold: true, backgroundColor: ok ? "green" : "red", color: "black" },
      ` OPENTRADER ${ok ? "HEALTHY" : "PROBLEM"} `,
      React.createElement(Text, { color: "black" }, ` cycle main=${mainCycle} shadow=${shadowCycle} `)),
    React.createElement(
      Box, { marginTop: 1 },
      React.createElement(Text, null,
        `main   $${mainVal != null ? mainVal.toFixed(2) : "—"}  `,
        React.createElement(Text, { color: "green" }, sparkline(mainSeries, 56))),
    ),
    React.createElement(
      Box, { marginTop: 0 },
      React.createElement(Text, null,
        `shadow $${shadowVal != null ? shadowVal.toFixed(2) : "—"}  `,
        React.createElement(Text, { color: "yellow" }, sparkline(shadowSeries, 56))),
    ),
    React.createElement(
      Box, { marginTop: 1 },
      React.createElement(PositionsTable, { title: "MAIN", paper: paperMain, color: "green" }),
      React.createElement(PositionsTable, { title: "SHADOW", paper: paperShadow, color: "yellow" })
    ),
    React.createElement(
      Box, { marginTop: 1 },
      React.createElement(ScoreboardPanel, { deploy }),
      React.createElement(FxPanel)
    ),
    React.createElement(RouterPanel, { router, ledgerLines }),
    React.createElement(Text, { dimColor: true, marginTop: 1 }, "health: " + health),
    React.createElement(Text, { bold: true, marginTop: 1 }, "feed (latest)"),
    ...feedLines.map((l, i) =>
      React.createElement(Text, { key: i, dimColor: true }, "  " + l.slice(0, 150))
    ),
    agent
      ? React.createElement(Text, { dimColor: true, marginTop: 1 },
          `agent: cycles=${agent.cycle_count} peak=${
            agent._peak_value != null ? "$" + Number(agent._peak_value).toFixed(2) : "—"
          }`)
      : null,
    React.createElement(TimelinePanel),
    React.createElement(Text, { dimColor: true, marginTop: 1 },
      "  [q] quit  [r] refresh  [j/k] scroll feed  — polls every 2s")
  );
}

render(React.createElement(App));
