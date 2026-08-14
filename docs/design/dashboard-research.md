# Dashboard Design Research — Sources (2026-08-14)

Four research agents, primary sources fetched/measured live. Summaries:

## 1. Institutional terminals
- Bloomberg Terminal: near-black + amber accent (#FFB000 est.), monospace data,
  max density, keyboard-first mnemonics. src: bloomberg.com/company/stories
- TradingView dark: #000 bg, up #089981 / down #F23645, blue #2962FF,
  hairline borders, tabular numbers. src: charting-library-docs custom-themes
- Reuters/LSEG Workspace: tiled ribbon workspace, search-driven. src: lseg.com
- IBKR TWS: Mosaic (tiled) + Classic (spreadsheet, hotkeys). src: ibkr.com
- Jane Street/Optiver/Citadel: text/terminal-first, austere tiled, no chrome,
  Bonsai TUI renaissance. src: janestreet.com, blog.janestreet.com

## 2. Modern dark fintech (measured)
- Binance: bg #0B0E11, gold #F0B90B, green #0ECB81 / red #F6465D, radius 4-6px
- Kraken Pro: violet-black #0B0611, purple #855BFB, green #35DF8D / red #FF7386,
  alpha-stepped hairlines (.12/.16/.24)
- Coinbase: #0A0B0D, blue #0052FF, green #00D166, 8px radius
- Linear (alive-but-tasteful): #08090A bg, 150ms transitions, hover = +1 alpha
  step, periwinkle #5E6AD2, radius 6px, tabular-nums
- Vercel Geist: #000 bg, Geist Mono for numerals, hairline rgba(255,255,255,.14)
- Raycast: #161617, #0A84FF, keyboard-first

## 3. Neural/neuro viz (alive vs flashy)
- TensorFlow Playground: edge thickness = weight, blue/orange semantic, no glow
- Distill: details-on-demand, animation only for transitions/uncertainty
- Wolfram Net Explorer: circuit-on-navy, click layer -> detail
- Apple HIG Motion: "don't move things just to move them", respect Reduce Motion
- Principles: ONE ambient channel (breathing proportional to traffic), transient
  event pulse, no perpetual rotation, one data variable per visual channel,
  hover = highlight + one-hop dim + tooltip, staleness = edge fade

## 4. Design token spec (drop-in)
Full :root token block in `docs/design/moodboard.md`. Neutrals slate 900/800/700,
up emerald-400 #34d399, down rose-400 #fb7185, accent cyan-400 #22d3ee, amber
warning, radius 6-8px, Inter + JetBrains Mono/tabular-nums, status
live/ok/warn/degraded/error, WCAG-verified contrast.

## Application
- Global CSS :root updated to measured institutional values
- Expert-router neural graph rebuilt: event-driven pulse (weight change only),
  no auto-rotation (gentle ambient drift, pausable, reduced-motion aware),
  edge opacity = staleness+weight, neutral edges + single cyan accent
- Mono/tabular numerals + semantic status preserved across the dashboard
