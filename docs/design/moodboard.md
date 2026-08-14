# Dashboard Mood Board — "Living Institutional Terminal"

Research synthesis (4 agents, primary sources measured live): Bloomberg Terminal,
TradingView, Binance, Kraken Pro, Coinbase, Robinhood, Linear, Vercel Geist,
Raycast, Jane Street/Bonsai, Distill, TensorFlow Playground, Wolfram Net Explorer,
Apple HIG, Material motion. See `docs/design/dashboard-research.md` for the full
source-by-source report.

## Design thesis

**"Alive but institutional."** Near-black canvas + one warm accent + monospace
tabular numerals + extreme information density (Bloomberg/Jane Street) meets the
modern dark-fintech grammar (TradingView/Binance/Linear: hairline borders, 6-8px
radius, 150ms transitions). The neural-network view is the ONE living element and
follows the Distill/Playground discipline: **every channel maps to exactly one
data variable; pulse only on real events; default state reads as a legible map,
not a creature.**

## Design pillars

1. **DARK FIRST** — near-black `#0a0f1c` canvas (Bloomberg/Jane Street ceiling),
   slate surfaces, 1px hairlines. Color is meaning: bars are the only color field,
   everything else grayscale.
2. **MONOSPACE NUMBERS** — all figures in `tabular-nums` mono at 11-13px. No
   misaligned digits ever (Bloomberg/Linear rule).
3. **USEFUL DENSITY** — command bar top, ticker strip, tiled panes. "Spreadsheet"
   table mode + "Mosaic" tiled mode (TWS precedent). No wasted whitespace.
4. **KEYBOARD-FIRST** — mnemonic command palette as the spine (Bloomberg `<GO>`,
   Classic TWS hotkeys). Mouse for situational awareness only.
5. **ONE LIVING ELEMENT** — the expert-router neural graph. Ambient channels:
   node size = capital, color = family, edge opacity = staleness. Transient pulse
   ONLY on real events (weight shift / live attribution). Never auto-orbit, never
   perpetual rotation, respect `prefers-reduced-motion`.
6. **SEMANTIC STATUS** — live/ok/warn/degraded/error as green→amber→orange→red
   dots + chips, never color-only (add glyphs, WCAG AA backstop).

## Color tokens (exact hex, measured)

```css
--bg-deepest:#0a0f1c; --bg:#0f172a; --surface:#111827; --surface-2:#1e293b;
--surface-3:#334155; --border:#1e293b; --border-hair:rgba(148,163,184,.14);
--text-primary:#e2e8f0; --text-secondary:#cbd5e1; --text-muted:#94a3b8; --text-faint:#64748b;
--up:#34d399; --up-strong:#10b981; --down:#fb7185; --down-strong:#f43f5e;
--accent:#22d3ee; --accent-blue:#3b82f6; --accent-amber:#fbbf24; --accent-violet:#8b5cf6;
--up-soft:rgba(52,211,153,.12); --down-soft:rgba(251,113,133,.12); --accent-soft:rgba(34,211,238,.12);
--font-sans:Inter,ui-sans-serif,system-ui,"Segoe UI",sans-serif;
--font-mono:"JetBrains Mono","IBM Plex Mono",ui-monospace,"SF Mono",monospace;
--radius-sm:4px; --radius:8px; --radius-lg:12px;
--status-live:#34d399; --status-ok:#10b981; --status-warn:#fbbf24;
--status-degraded:#fb923c; --status-error:#f43f5e; --status-idle:#64748b;
```

## The neural graph (the living element) — revised

- **Canvas**: deep navy `#0a0f16`, structure at 40-60% gray, active at 100%.
- **Nodes**: icosahedra, size = OOS Calmar (capital), color = family
  (drawdown cyan / regime amber / participation violet / floor gray).
- **Edges**: thin neutral, opacity = staleness (fade unused paths); ONE cyan
  flow accent for live attribution.
- **Pulse**: transient, event-driven (weight shift / live trade), decaying —
  NOT perpetual. Slow "breathing" of ambient glow proportional to weight only.
- **Camera**: user-driven slow orbit or static; NO auto-rotate. Play/pause.
- **Interaction**: hover → highlight + one-hop dim + tooltip (details-on-demand);
  click → drill with breadcrumb.
- **Reduce motion**: `prefers-reduced-motion` → static, no pulse, no drift.

## What gets applied product-wide

- Global CSS variables (the token block above).
- All numbers → `--font-mono` + `tabular-nums`.
- Status pills → semantic green/amber/orange/red + glyph, not color-only.
- Hairline borders, 8px radius, 150ms transitions across all panels.
- The expert-router graph rebuilt to the "alive but institutional" spec above
  (remove perpetual rotation; event-driven pulse; staleness-fading edges).
