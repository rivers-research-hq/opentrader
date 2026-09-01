#!/usr/bin/env node
// opentrader-tui — read-only terminal client over the harness state files.
// Zero-build: plain JS + React.createElement (no JSX, no transpiler).
// v3 design: two pages ([1] Home — agent aggregation + portfolio + boards,
// [2] Forex — the practice book), boxed panels (cli-boxes), per-lane color
// identity. Data: state files + the dashboard's /api/fx (venue authoritative).
import React, { useEffect, useState } from "react";
import { render, Box, Text, useInput, useApp } from "ink";
import { readFileSync, readdirSync } from "node:fs";
import { execSync } from "node:child_process";
import cliBoxes from "cli-boxes";

const boxes = cliBoxes.round;

const BASE = "/home/mrc/opentrader/data";
const SHADOW = `${BASE}/shadow_scaled`;
const WAYFINDER = `${BASE}/wayfinder`;

const read = (p) => { try { return readFileSync(p, "utf8"); } catch { return null; } };
const readJson = (p) => {
  const s = read(p);
  if (!s) return null;
  try { return JSON.parse(s); } catch { return null; }
};

const W = Math.min(process.stdout.columns > 40 ? process.stdout.columns - 2 : 96, 120); // adaptive design width
const LANE_COLOR = {
  "mom-k5": "cyan", "c08-fade": "green", "h1-mom": "yellow",
  crash: "red", watchdog: "magenta", reconciled: null,
};

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
  const paperMain = readJson(`${BASE}/paper_state.json`);
  const paperShadow = readJson(`${SHADOW}/paper_state.json`);
  const deploy = readJson(`${WAYFINDER}/deployability_status.json`);
  const router = readJson(`${BASE}/live_router_state.json`);
  const ledgerLines = (read(`${BASE}/fills_ledger.jsonl`) || "").split("\n").filter((l) => l.trim()).length;
  const registry = (readJson(`${BASE}/epoch_registry.json`) || { experts: [] }).experts || [];
  const crash = readJson(`${BASE}/fx_crashtest.json`) || {};
  const watchdog = readJson(`${BASE}/fx_watchdog_state.json`) || {};
  return { last, mainSeries, shadowSeries, paperMain, paperShadow, deploy, router,
           ledgerLines, registry, crash, watchdog };
}

// live FX snapshot — dashboard /api/fx (venue is authoritative)
async function fetchFx(setFx) {
  try {
    const r = await fetch("http://127.0.0.1:8097/api/fx", { signal: AbortSignal.timeout(4000) });
    setFx(await r.json());
  } catch { /* keep last snapshot; page shows offline state */ }
}

// ledger → per-lane realized P&L / round trips / win rate (FIFO, USD-approx)
function laneStats() {
  const raw = read(`${BASE}/fx_ledger.jsonl`);
  if (!raw) return {};
  const rows = raw.trim().split("\n").filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  rows.sort((a, b) => String(a.timestamp) < String(b.timestamp) ? -1 : 1);
  const laneOf = (r) => {
    const reason = r.reason || "";
    if (reason.startsWith("c08") || reason.startsWith("mr-fade")) return "c08-fade";
    if (reason.startsWith("intraday")) return "h1-mom";
    if (reason.startsWith("watchdog")) return "watchdog";
    if (reason.startsWith("crash")) return "crash";
    if (["momentum-entry", "out-of-target", "max-hold"].includes(reason)) return "mom-k5";
    return "reconciled";
  };
  const books = {};
  for (const r of rows) {
    const lane = laneOf(r), sym = r.symbol;
    if (!sym || sym === "-") continue;
    const side = (r.side || "").toUpperCase();
    const qty = Number(r.quantity || 0), price = Number(r.price || 0);
    if (!qty || !price) continue;
    books[lane] = books[lane] || {};
    const book = books[lane][sym] = books[lane][sym] || { qty: 0, cost: 0, realized: 0, rounds: 0, wins: 0 };
    if (side === "BUY") { book.qty += qty; book.cost += qty * price; }
    else if (side === "SELL" && book.qty > 1e-9) {
      const avg = book.cost / book.qty, q = Math.min(qty, book.qty);
      let pnl = (price - avg) * q;
      const quote = sym.split("_")[1];
      if (quote !== "USD") pnl = pnl / (price || 1); // quote-ccy → USD at exit
      book.realized += pnl; book.rounds += 1; book.wins += pnl > 0 ? 1 : 0;
      book.qty -= q; book.cost = avg * book.qty;
    }
  }
  const out = {};
  for (const [lane, syms] of Object.entries(books)) {
    const realized = Object.values(syms).reduce((a, b) => a + b.realized, 0);
    const rounds = Object.values(syms).reduce((a, b) => a + b.rounds, 0);
    const wins = Object.values(syms).reduce((a, b) => a + b.wins, 0);
    out[lane] = { realized, rounds, winrate: rounds ? (100 * wins) / rounds : null };
  }
  return out;
}

// next central-bank decisions (single cached python call — the calendar moves slowly)
function nextEvents() {
  try {
    return execSync(
      `/home/mrc/opentrader/.venv/bin/python3 -c "` +
      `import sys; sys.path.insert(0,'/home/mrc/opentrader'); ` +
      `from data.economic_calendar import bank_dates; ` +
      `now=dt.date.today() if (dt:=__import__('datetime')) else None; ` +
      `ev=[]; [ev.extend([(d,b) for d in sorted(bank_dates(b)) if d>=now]) ` +
      `for b in ['FED','ECB','BOE','BOJ','SNB','BOC','RBA','RBNZ']]; ` +
      `ev.sort(); print(' | '.join(f'{b} {d}' for d,b in ev[:4]))"`,
      { timeout: 8000 }).toString().trim() || "—";
  } catch { return "—"; }
}

function proposals() {
  const out = { batches: 0, survivors: 0, last: null };
  try {
    const dir = `${BASE}/agent_gym/proposals`;
    for (const rep of readdirSync(dir)) {
      const r = read(`${dir}/${rep}/report.md`);
      if (!r) continue;
      out.batches += 1; out.last = rep;
      out.survivors += (r.match(/SURVIVOR/g) || []).length;
    }
  } catch { }
  return out;
}

// boxed panel: rounded border + embedded title, wraps the page's line objects
function box(title, lines, color = "cyan") {
  const b = boxes;
  const titleText = ` ${title} `;
  const fill = Math.max(0, W - titleText.length - 2);
  const out = [];
  out.push({ text: b.topLeft + b.top.repeat(2) + titleText + b.top.repeat(fill) + b.topRight, bold: true, color });
  for (const l of lines) {
    const content = ` ${l.text !== undefined ? l.text : l}`.padEnd(W - 2);
    out.push({ text: b.left + content + b.right, color: l.color || null, dim: !!l.dim, bold: !!l.bold });
  }
  out.push({ text: b.bottomLeft + b.top.repeat(W - 2) + b.bottomRight, color, dim: true });
  return out;
}

const money = (v, d = 2) => (v != null && !isNaN(v) ? Number(v).toFixed(d) : "—");
const laneColor = (tag) => LANE_COLOR[tag] || "grey";

function sparkline(series, width = 46) {
  if (!series.length) return "(no data)";
  const vals = series.slice(-width);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const chars = "▁▂▃▄▅▆▇█";
  return vals.map((v) => chars[Math.min(7, Math.max(0, Math.floor(((v - min) / span) * 7)))]).join("");
}

function laneRow(tag, s, note) {
  const sign = (s.realized || 0) >= 0 ? "+" : "";
  const wr = s.winrate == null ? "—" : s.winrate.toFixed(0) + "%";
  return { text: ` ● ${tag.padEnd(10)} realized ${sign}${(s.realized || 0).toFixed(2)}  ·  ${s.rounds || 0} RT  ·  WR ${wr}   ${note || ""}`, color: laneColor(tag) };
}

function buildHome(state, fx) {
  const { last, mainSeries, shadowSeries, paperMain, paperShadow, deploy, router,
          ledgerLines, registry, crash, watchdog, proposals } = state;
  const lanes = state.lanes || {};
  const L = [];

  const bal = fx && fx.balance, nav = fx && fx.nav;
  const openPl = (fx && fx.book ? fx.book : []).reduce((a, t) => a + Number(t.pl || 0), 0);
  const mom = lanes["mom-k5"] || { realized: 0, rounds: 0, winrate: null };
  L.push({ text: ` FX PRACTICE   balance $${money(bal)}  NAV $${money(nav)}  unrealized ${openPl >= 0 ? "+" : ""}${openPl.toFixed(2)}  ·  mom-k5 realized ${mom.realized >= 0 ? "+" : ""}${mom.realized.toFixed(2)} (${mom.rounds} RT)`,
           bold: true, bg: "blue" });
  L.push({ text: ` crash-test $300-equivalent: equity $${money(300 + (crash.realized || 0))} · max DD $${money(crash.max_dd || 0)}  ·  watchdog flattened ${watchdog.flattened ?? 0}`, dim: true });
  L.push({ text: "" });

  const agentLines = [];
  for (const e of registry) {
    const a = e.accrual || {};
    agentLines.push({ text: ` [${e.kind === "incumbent" ? "★" : " "}] ${e.expert_id.padEnd(22)} ${String(e.kind).padEnd(12)} ${String(e.status).padEnd(9)} closed ${a.closed_trades ?? "—"}`, color: "green" });
  }
  const laneMeta = [
    ["mom-k5", "fx lane (daily)", "momentum top-2 · 17:10"],
    ["c08-fade", "fx lane (daily)", "mr_fade_ma20_cot · 17:25"],
    ["h1-mom", "fx lane (hourly)", "H1 momentum · evidence"],
    ["crash", "crash-test (max margin)", "unprotected by design"],
    ["watchdog", "shock response", `checked ${String(watchdog.checked || "—").slice(0, 19)}`],
  ];
  for (const [tag, kind, note] of laneMeta) {
    const s = lanes[tag] || {};
    agentLines.push({ text: ` ● ${tag.padEnd(22)} ${kind.padEnd(26)} ${s.rounds || 0} RT · WR ${s.winrate == null ? "—" : s.winrate.toFixed(0) + "%"} · realized ${(s.realized || 0) >= 0 ? "+" : ""}${(s.realized || 0).toFixed(2)}`, color: laneColor(tag) });
  }
  agentLines.push({ text: ` ◇ proposal_loop   discovery          ${proposals.survivors || 0} survivor(s) / ${proposals.batches || 0} batches · ~$0.01/batch  (${proposals.last || "—"})`, dim: true });
  L.push(...box("AGENTS — registry · lanes · discovery", agentLines, "cyan"));

  const routerLines = [];
  for (const regime of ["up", "down"]) {
    const w = (router && router.weights || {})[regime] || {};
    const track = (router && router.track || {})[regime] || {};
    const parts = Object.entries(w).sort((a, b) => b[1] - a[1]).slice(0, 4)
      .map(([e, wt]) => { const t = track[e] || {}; return `${e} ${Number(wt).toFixed(2)}${e !== "rule" ? ` [fwd ${t.fwd_n ?? 0}/5]` : ""}`; });
    routerLines.push({ text: ` ${regime.toUpperCase().padEnd(5)} ${parts.join("  ·  ") || "(none)"}` });
  }
  routerLines.push({ text: ` fills-ledger ${ledgerLines}`, dim: true });

  const eqLines = [
    { text: ` main   $${money(last ? parseFloat(last[2]) : null)}  ${sparkline(mainSeries, 44)}`, color: "green" },
    { text: ` shadow $${money(last ? parseFloat(last[6]) : null)}  ${sparkline(shadowSeries, 44)}`, color: "yellow" },
  ];
  const bookLines = [];
  for (const [title, paper, color] of [
    ["CRYPTO BOOK — MAIN", paperMain, "green"],
    ["CRYPTO BOOK — SHADOW", paperShadow, "yellow"],
  ]) {
    bookLines.push({ text: ` ${title}   value $${money(paper && paper.portfolio_value)} · cash $${money(paper && paper.cash)}`, color, bold: true });
    const pos = (paper && paper.positions) || [];
    if (!pos.length) bookLines.push({ text: "  (no positions)", dim: true });
    for (const p of pos) {
      const cur = Number(p.current_price || 0), ent = Number(p.entry_price || 0);
      const pnl = cur && ent ? ((cur - ent) / ent) * 100 : null;
      bookLines.push({ text: `   ${String(p.symbol).padEnd(10)} ${money(ent).padStart(10)}  ${money(cur).padStart(10)}  ${pnl == null ? "—" : (pnl >= 0 ? "+" : "") + pnl.toFixed(2) + "%"}`, color: pnl == null ? null : pnl >= 0 ? "green" : "red" });
    }
  }
  const deployLines = [];
  if (!deploy) deployLines.push({ text: "  run job-v11 (opentask) to compute", dim: true });
  else {
    const c1 = deploy.clause1_plumbing || {}, c2 = deploy.clause2_edge || {}, c3 = deploy.clause3_calendar || {};
    const fd = c1.fatal_defects || {};
    const fatal = (fd.silent_hold || 0) + (fd.state_corruption || 0) + (fd.order_rejection || 0);
    const CLOCK_START = "2026-08-31";
    const postFixGap = (c3.gaps || []).some((g) => String(g).slice(0, 10) >= CLOCK_START);
    const c1State = fatal > 0 ? ["✗ FAIL — fatal defect", "red"] : ["accruing", "yellow"];
    const c2State = c2.pass === true ? ["✓ PASS", "green"] : c2.pass === false ? ["✗ FAIL — decayed", "red"] : ["accruing — measurable at fwd 5/5", "yellow"];
    const c3State = postFixGap ? ["✗ FAIL — continuity broken", "red"] : [`${c3.continuous_days ?? 0}/70 days — accruing`, "yellow"];
    deployLines.push({ text: ` C1 plumbing   closed ${String(c1.closed_trades ?? "?").padStart(3)} · fatal ${fatal}`.padEnd(56) + c1State[0], color: c1State[1] });
    deployLines.push({ text: ` C2 edge       fwd_mean ${String(c2.rule_floor_impact_mean ?? "?").padStart(6)} (n=${c2.n ?? "?"})`.padEnd(56) + c2State[0], color: c2State[1] });
    deployLines.push({ text: ` C3 calendar   ${String(c3.continuous_days ?? "?").padStart(3)} / 70 days continuous`.padEnd(56) + c3State[0], color: c3State[1] });
  }
  const events = state.events || "—";
  const queue = (fx && fx.queue) || { events: 0, labeled: 0 };

  L.push(...box("BOARDS — paper equity · crypto books", eqLines.concat(bookLines), "green"));
  L.push(...box("DEPLOYABILITY — ADR-0002" + (deploy ? ` · computed ${String(deploy.generated || "").slice(0, 10)}` : ""), deployLines, "yellow"));
  L.push(...box("ROUTER — MoT", routerLines, "cyan"));
  L.push(...box("CALENDAR · QUEUE", [
    { text: ` next decisions: ${events}` },
    { text: ` preference queue: ${queue.events ?? 0} events, ${queue.labeled ?? 0} labeled` },
    { text: ` timeline: Sep 7-14 FX gate review → D4 deposit decision · ~Nov 8 crypto mark`, dim: true },
  ], "cyan"));
  return L;
}

function buildForex(state, fx) {
  const lanes = state.lanes || {};
  const crash = state.crash || {};
  const book = (fx && fx.book) || [];
  const bal = fx && fx.balance, nav = fx && fx.nav;
  const openPl = book.reduce((a, t) => a + Number(t.pl || 0), 0);
  const L = [];
  L.push({ text: ` FX PRACTICE BOOK   balance $${money(bal)}  NAV $${money(nav)}  unrealized ${openPl >= 0 ? "+" : ""}${openPl.toFixed(2)}  ·  ${book.length} position(s)  ·  venue is authoritative`,
           bold: true, bg: "blue" });
  L.push({ text: "" });

  const posLines = [];
  if (!book.length) posLines.push({ text: "  (flat)", dim: true });
  for (const t of book) {
    const pl = Number(t.pl || 0);
    const prot = t.protected ? "yes" : "NO —";
    posLines.push({ text: ` trade ${String(t.trade_id).padEnd(4)} ${String(t.instrument).padEnd(9)} ${String(t.units).padStart(6)}u @ ${String(t.price).padEnd(9)} opened ${String(t.opened).slice(0, 19)}  unrealized ${pl >= 0 ? "+" : ""}${pl.toFixed(2)}  SL/TP: ${prot}`, color: laneColor(t.owner) === "grey" ? null : laneColor(t.owner) });
  }
  L.push(...box("OPEN BOOK — by owner tag", posLines, "cyan"));
  L.push({ text: "" });

  const laneLines = [];
  for (const tag of ["mom-k5", "c08-fade", "h1-mom", "crash", "watchdog"]) {
    laneLines.push(laneRow(tag, lanes[tag] || {}));
  }
  const events = state.events || "—";
  const queue = (fx && fx.queue) || { events: 0, labeled: 0 };
  laneLines.push({ text: "" });
  laneLines.push({ text: ` next decisions: ${events}`, dim: true });
  laneLines.push({ text: ` preference queue: ${queue.events ?? 0} events, ${queue.labeled ?? 0} labeled`, dim: true });
  L.push(...box("LANES — realized · round trips", laneLines, "green"));
  L.push({ text: "" });

  const fillLines = [];
  const fills = (fx && fx.fills) || [];
  if (!fills.length) fillLines.push({ text: "  (no fills yet)", dim: true });
  for (const f of fills.slice(0, 12)) {
    const reason = f.reason || "";
    const lane = reason.startsWith("c08") || reason.startsWith("mr-fade") ? "c08-fade"
      : reason.startsWith("intraday") ? "h1-mom"
      : reason.startsWith("watchdog") ? "watchdog"
      : reason.startsWith("crash") ? "crash"
      : ["momentum-entry", "out-of-target", "max-hold"].includes(reason) ? "mom-k5" : "reconciled";
    fillLines.push({ text: ` ${String(f.timestamp).slice(0, 19)}  ${String(f.symbol).padEnd(9)} ${String(f.side).padEnd(4)} ${String(f.quantity).padStart(6)} @ ${String(f.price).padEnd(9)} [${lane}] ${reason}`, dim: lane === "reconciled" });
  }
  L.push(...box("FILL STREAM — newest first", fillLines, "cyan"));
  L.push({ text: "" });

  const equity = 300 + (crash.realized || 0);
  L.push(...box("CRASH-TEST — $300-equivalent · max margin · unprotected by design", [
    { text: ` equity $${money(equity)}  ·  realized ${(crash.realized || 0) >= 0 ? "+" : ""}${(crash.realized || 0).toFixed(2)}  ·  peak $${money(crash.peak_equity || 300)}  ·  max DD $${money(crash.max_dd || 0)}`, bold: true },
    { text: ` this book measures what a liquidity crisis does to an aggressive account — for free`, dim: true },
  ], "red"));
  return L;
}

function App() {
  const { exit } = useApp();
  const [page, setPage] = useState(process.argv.includes("--forex") ? "forex" : "home");
  const [state, setState] = useState(loadState);
  const [fx, setFx] = useState(null);
  const [events] = useState(nextEvents);

  useInput((input) => {
    if (input === "q") exit();
    if (input === "r") setState(loadState());
    if (input === "1") setPage("home");
    if (input === "2") setPage("forex");
  });
  useEffect(() => {
    const t = setInterval(() => setState(loadState()), 2000);
    const f = setInterval(() => fetchFx(setFx), 5000);
    fetchFx(setFx);
    return () => { clearInterval(t); clearInterval(f); };
  }, []);

  const lanes = laneStats();
  const withAll = { ...state, lanes, events, proposals: proposals() };
  const lines = page === "home" ? buildHome(withAll, fx) : buildForex(withAll, fx);
  return React.createElement(
    Box, { flexDirection: "column", paddingX: 1 },
    lines.map((l, i) =>
      React.createElement(
        Text, { key: `${page}-${i}`, bold: !!l.bold, color: l.color, backgroundColor: l.bg, dimColor: !!l.dim },
        l.text || " "
      )
    ),
    React.createElement(Text, { dimColor: true, marginTop: 1 },
      `  [1] home  [2] forex  [r] refresh  [q] quit  —  page: ${page}  ·  polls 2s (files) / 5s (venue)`)
  );
}

render(React.createElement(App));
