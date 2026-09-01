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
async function fetchCalendar(setCal) {
  try {
    const r = await fetch("http://127.0.0.1:8097/api/calendar", { signal: AbortSignal.timeout(8000) });
    setCal(await r.json());
  } catch { /* keep last */ }
}

async function fetchFx(setFx) {
  try {
    const r = await fetch("http://127.0.0.1:8097/api/fx", { signal: AbortSignal.timeout(8000) });
    setFx(await r.json());
  } catch { /* keep last snapshot; page shows offline state */ }
}

// ledger → per-lane realized P&L / round trips / win rate (FIFO, USD-approx)
export function laneStats() {
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

export function buildHome(state, fx) {
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

export function buildForex(state, fx) {
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
  const flat = (fx && fx.flat) || {};
  const laneOwners = new Set(book.map((t) => t.owner));
  for (const tag of ["mom-k5", "c08-fade", "h1-mom", "crash", "watchdog"]) {
    const row = laneRow(tag, lanes[tag] || {});
    laneLines.push(row);
    const isFlat = !laneOwners.has(tag);  // no open position carries this tag
    if (tag === "watchdog" || isFlat) {
      const why = tag === "watchdog"
        ? "response-only — flattens shocks, never opens"
        : String(flat[tag] || "no signal — entry condition not met");
      laneLines.push({ text: `     ↳ flat: ${why}`.slice(0, W - 4), dim: true, color: laneColor(tag) });
    }
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

function buildCalendar(state, fx, cal) {
  const L = [];
  const now = new Date();
  const year = now.getUTCFullYear(), month = now.getUTCMonth();
  const months = ["January", "February", "March", "April", "May", "June", "July",
                  "August", "September", "October", "November", "December"];
  const BANK_TAG = { FED: "FED", ECB: "ECB", BOE: "BOE", BOJ: "BOJ",
                     SNB: "SNB", BOC: "BOC", RBA: "RBA", RBNZ: "RBNZ" };
  const BANK_COLOR = { FED: "cyan", ECB: "green", BOE: "yellow", BOJ: "yellow",
                       SNB: "magenta", BOC: "cyan", RBA: "green", RBNZ: "magenta" };
  const decisions = (cal && cal.decisions) || [];
  const byDay = {};
  for (const d of decisions) {
    const day = parseInt(d.date.slice(8, 10), 10);
    (byDay[day] = byDay[day] || []).push(BANK_TAG[d.bank] || d.bank.slice(0, 3));
  }
  for (const e of (cal && cal.ff_events) || []) {
    const day = parseInt(e.date.slice(8, 10), 10);
    (byDay[day] = byDay[day] || []).push(e.impact === "High" ? "!" : "*");
  }

  // month grid: Mon-Sun columns
  const first = new Date(Date.UTC(year, month, 1));
  const startDow = (first.getUTCDay() + 6) % 7; // Mon=0
  const daysIn = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const cells = [];
  for (let i = 0; i < startDow; i++) cells.push(null);
  for (let d = 1; d <= daysIn; d++) cells.push(d);
  while (cells.length % 7) cells.push(null);
  const grid = [];
  grid.push({ text: `  ${months[month]} ${year}  ·  [bank] = decision (pattern-approx for non-FED)  ·  ! = high-impact release  ·  * = medium`, dim: true });
  grid.push({ text: `  ${"MON".padEnd(14)}${"TUE".padEnd(14)}${"WED".padEnd(14)}${"THU".padEnd(14)}${"FRI".padEnd(14)}${"SAT".padEnd(14)}SUN`, dim: true, bold: true });
  for (let w = 0; w < cells.length / 7; w++) {
    let row = "  ";
    for (let c = 0; c < 7; c++) {
      const day = cells[w * 7 + c];
      if (day == null) { row += "".padEnd(14); continue; }
      const tags = (byDay[day] || []).join(",").slice(0, 9);
      const mark = day === now.getUTCDate() ? ">" : " ";
      row += `${mark}${String(day).padStart(2)}${tags.padEnd(11)}`;
    }
    grid.push({ text: row });
  }
  L.push(...box(`CALENDAR — ${months[month]} ${year}`, grid, "cyan"));
  L.push({ text: "" });

  const inhouse = (cal && cal.inhouse) || {};
  const decLines = [];
  for (const d of decisions.slice(0, 8)) {
    const cur = { FED: "USD", ECB: "EUR", BOE: "GBP", BOJ: "JPY",
                  SNB: "CHF", BOC: "CAD", RBA: "AUD", RBNZ: "NZD" }[d.bank];
    const ih = inhouse[cur] || {};
    const ihS = ih.rate != null
      ? `rate ${ih.rate}%  90dΔ ${ih.chg90 >= 0 ? "+" : ""}${ih.chg90 ?? "—"}${ih.cot_z != null ? `  COT z ${ih.cot_z}` : ""}`
      : (ih.note || "state n/a");
    const approx = d.bank === "FED" ? "" : " (approx)";
    decLines.push({ text: ` ${d.date}  ${d.bank.padEnd(5)} ${cur}  in-house state: ${ihS}${approx}`, color: BANK_COLOR[d.bank] || null });
  }
  if (!decLines.length) decLines.push({ text: "  (none in window)", dim: true });
  L.push(...box("CENTRAL-BANK DECISIONS — next 45 days · in-house state (not a forecast)", decLines, "yellow"));
  L.push({ text: "" });

  const ffLines = [];
  for (const e of ((cal && cal.ff_events) || []).slice(0, 12)) {
    const when = `${e.date.slice(5, 10)} ${e.date.slice(11, 16)} UTC`;
    ffLines.push({ text: ` ${when}  ${String(e.currency).padEnd(4)} [${String(e.impact).padEnd(6)}] ${String(e.title).padEnd(34).slice(0, 34)} analyst: ${String(e.forecast).padEnd(7)} prev: ${e.previous}`, dim: e.impact !== "High" });
  }
  if (!ffLines.length) ffLines.push({ text: "  (feed unavailable)", dim: true });
  L.push(...box("MACRO RELEASES — next 14 days · analyst consensus (ForexFactory feed)", ffLines, "green"));
  L.push({ text: "" });
  L.push({ text: "  in-house columns are STATE reads (policy rate, 90d trend, positioning) — not predictions. The system does not forecast decisions; it avoids holding through them (event gate) and measures what they do (crash book).", dim: true });
  return L;
}

function App() {
  const { exit } = useApp();
  const [page, setPage] = useState(
    process.argv.includes("--forex") ? "forex" : process.argv.includes("--calendar") ? "calendar" : "home");
  const [state, setState] = useState(loadState);
  const [fx, setFx] = useState(null);
  const [cal, setCal] = useState(null);
  const [events] = useState(nextEvents);

  useInput((input) => {
    if (input === "q") exit();
    if (input === "r") setState(loadState());
    if (input === "1") setPage("home");
    if (input === "2") setPage("forex");
    if (input === "3") setPage("calendar");
  });
  useEffect(() => {
    const t = setInterval(() => setState(loadState()), 2000);
    const f = setInterval(() => fetchFx(setFx), 5000);
    const c = setInterval(() => fetchCalendar(setCal), 60000);
    fetchFx(setFx);
    fetchCalendar(setCal);
    return () => { clearInterval(t); clearInterval(f); clearInterval(c); };
  }, []);

  const lanes = laneStats();
  const withAll = { ...state, lanes, events, proposals: proposals() };
  const lines = page === "home" ? buildHome(withAll, fx)
    : page === "forex" ? buildForex(withAll, fx)
    : buildCalendar(withAll, fx, cal);
  return React.createElement(
    Box, { flexDirection: "column", paddingX: 1 },
    lines.map((l, i) =>
      React.createElement(
        Text, { key: `${page}-${i}`, bold: !!l.bold, color: l.color, backgroundColor: l.bg, dimColor: !!l.dim },
        l.text || " "
      )
    ),
    React.createElement(Text, { dimColor: true, marginTop: 1 },
      `  [1] home  [2] forex  [3] calendar  [r] refresh  [q] quit  —  page: ${page}  ·  polls 2s (files) / 5s (venue) / 60s (calendar)`)
  );
}

import { pathToFileURL } from "node:url";
const _isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (_isMain) render(React.createElement(App));
