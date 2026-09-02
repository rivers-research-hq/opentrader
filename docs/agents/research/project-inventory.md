# Project Inventory & Secret Sweep

> Research ticket #104 — wayfinder, map "System overhaul & optimization for opentrader development".
> Method: read-only sweep of `/home/mrc` git repos, working trees, history, and running docker stacks.
> Secrets are redacted everywhere (prefix + suffix). Report date: 2026-08-10.

## Summary verdicts (push perspective)

| Project dir | Owner class | Remote | Secret risk | Push verdict |
|---|---|---|---|---|
| `opentrader` | OWN (active, exclude) | `github.com/darylerivers/opentrader.git` | LOW — real keys only in gitignored `config/alt_data_keys.json`; history clean | push (active) |
| `cappuccino` (`/home/mrc/cappuccino`) | OWN | `github.com/darylerivers/Cappuccino.git` | NONE — 2 commits, no secrets | push |
| `moonberg-work` | OWN | `github` remote = `https://ghp_NDw4EF…OWEG9@github.com/darylerivers/moonberg.git` — **embedded PAT**; `origin` = local bare `/home/mrc/moonberg-backup` | **HIGH** — live `ghp_` PAT baked into remote URL; `.env` (gitignored) holds wallet keys + Anthropic key; PAT NOT in commit history | sanitize-then-push |
| `nicheiqs-frontend` | OWN | `github.com/darylerivers/nichieiqs-frontend.git` | NONE — 3 commits clean | push |
| `atlantis` | OWN | `github.com/mrc-lab/atlantis.git` (origin + upstream) | NONE — 8 commits clean | push |
| `niche-engine` | OWN | none | **HIGH** — `.env.example` committed with **real** `STRIPE_SECRET_KEY=sk_live_…`, `STRIPE_WEBHOOK_SECRET=whsec_…`, `ANTHROPIC_API_KEY=sk-ant-…`; `.env` (gitignored) full prod secrets | sanitize-then-push |
| `niche-engine/mcp-server-ts` | OWN | `github.com/darylerivers/nicheiqs-mcp.git` | **HIGH** — **tracked + in HEAD**: `.mcpregistry_github_token` (`ghu_w6LU…lF0zBl0k`) and `.mcpregistry_registry_token` (JSON); commit `e49f8e3` contains them; local branch is **ahead 2 of origin/master** → leak on next push | sanitize-then-push (also rotate) |
| `token-accountant` | OWN | none | NONE — empty repo (0 commits) | leave |
| `clauseguard` | OWN | none | NONE — 0 commits; only `.env.example` (placeholders) | leave |
| `/opt/user-data/experiment/cappuccino/Version 0.0.1` (version001 compose owner) | OWN | `git@github.com:darylerivers/Cappuccino` (SSH) | **HIGH** — **tracked, not ignored**: `key/cdp_api_key.json` with **real Coinbase Developer Platform private key** (`Opn7in…`); commit `0789991`; separate checkout/history from `/home/mrc/cappuccino` | sanitize-then-push |
| `odysseus` | THIRD-PARTY (upstream checkout, HEAD == origin/main; dirty working tree, no local commits) | `github.com/pewdiepie-archdaemon/odysseus.git` | NONE — history/tree clean (only placeholder `ghp_XXX…` in vendored autogen lib) | leave |
| `Whiteboard/excalidraw` | THIRD-PARTY | `github.com/excalidraw/excalidraw.git` | NONE | leave |
| `claude-code` | THIRD-PARTY | `github.com/alesha-pro/claude-code.git` | NONE | leave |
| `ML-From-Scratch` | THIRD-PARTY | `github.com/eriklindernoren/ML-From-Scratch.git` | NONE | leave |
| `quantstats` | THIRD-PARTY | `github.com/ranaroussi/quantstats.git` | NONE | leave |
| `steelseriesgg-rs` | THIRD-PARTY | `github.com/Ven0m0/steelseriesgg-rs.git` | NONE | leave |
| `scientific-calculator` | THIRD-PARTY | `github.com/A-Badiry/scientific-calculator.git` | NONE | leave |
| `G17-Gen-3` | THIRD-PARTY | `github.com/japan44/G17-Gen-3.git` | NONE | leave |
| `Orca-Flashforge` | THIRD-PARTY | `github.com/FlashForge/Orca-Flashforge.git` | NONE | leave |
| `Autodesk-Fusion-360-for-Linux` | THIRD-PARTY | `github.com/cryinkfly/Autodesk-Fusion-360-for-Linux.git` | NONE | leave |
| `MultiVNC/multivnc` | THIRD-PARTY | `github.com/bk138/multivnc.git` | NONE | leave |
| `rstudio-desktop` (+ `quarto-cli-bin`) | AUR | `aur.archlinux.org/rstudio-desktop.git`, `…/quarto-cli-bin.git` | NONE | n/a |
| `snapd` / `yay` / `kdeconnect-git` / `notepadpp` / `miniconda3` | AUR build | `aur.archlinux.org/…git` | NONE | n/a |
| `src/llama-swap` | THIRD-PARTY | `github.com/mostlygeek/llama-swap.git` | NONE | n/a |
| `src/prismml-llama.cpp` | THIRD-PARTY | `github.com/PrismML-Eng/llama.cpp` | NONE | n/a |
| `src/modelai-llama.cpp` | THIRD-PARTY (fork) | `github.com/jandhyala-dev/modelai-llama.cpp.git` | NONE | n/a |
| `src/llama.cpp` | THIRD-PARTY | `github.com/ggml-org/llama.cpp.git` | NONE | n/a |
| `.nvm` / `.pyenv` | TOOL | `github.com/nvm-sh/nvm.git`, `github.com/pyenv/pyenv.git` | NONE | n/a |
| `.openclaw/workspace` | tool scratch | none | NONE | n/a |

## Non-git project dirs (no push surface, local only)

| Dir | Content / notes | Risk |
|---|---|---|
| `Research/Thesis` | Contains **`cdp_api_key.json`** — a **second** real CDP private key (`eN5/dO…`), distinct from the `/opt` copy (different sha256) | MED — plaintext private key on disk, not git |
| `opentrader-sandbox` | Not a git repo; contains a copy of `config/alt_data_keys.json` (real EIA/USDA/Alpaca keys) + empty HF `.env` | LOW — duplicate secrets, no push path |
| `upwork` | Client work area (resumes, proposals), no git, no secrets found | NONE |
| `vllm-rocm` | `docker-compose.yml` present, no git, no secrets | NONE |
| `Whiteboard`, `builder`, `atelier`, `awesome`, `Applications`, `data`, `bin` | Local working areas, no git, no high-signal secrets (one `.so` filename false-positive) | NONE |

## Docker compose stacks → owning dir

| Stack | Owning dir / compose file | Notes |
|---|---|---|
| `version001` | `/opt/user-data/experiment/cappuccino/Version 0.0.1/docker-compose.yml` | **This dir is a git repo pushing to `darylerivers/Cappuccino` and contains the tracked CDP private key** |
| `cappuccino` | `/opt/user-data/experiment/cappuccino/docker-compose.yml` | Not a git repo |
| `odysseus` | `/home/mrc/odysseus/docker-compose.yml` | Env passed via `${…}` interpolation from `.env`; no hardcoded secrets; `.env` has only benign `LLM_HOST`/`SEARXNG_INSTANCE`/`APP_BIND` |
| `niche-engine` | `/home/mrc/niche-engine/docker-compose.yml` | `POSTGRES_PASSWORD: password` (dev default); cloudflared reads `CLOUDFLARE_TUNNEL_TOKEN` from `.env` (real, gitignored) |
| `open-webui` | **standalone `docker run`** (no compose; `com.docker.compose.project` label absent) | `OPENAI_API_KEY=lm-studio` placeholder (points at local LM Studio); `WEBUI_SECRET_KEY` empty; LOW risk |

## Standalone secrets on the box (plaintext, not in git)

- `~/.git-credentials` — GitHub PAT `ghp_30…x2Qk` (live) and HuggingFace token `hf_jBZ…JMVN`.
- `~/.config/opencode/opencode.jsonc` — DeepSeek `sk-d4711…` and Context7 `ctx7sk-c6b9144d…`.
- `~/.npmrc` — npm registry `_authToken`; `~/.mcp_publisher_token` — GitHub MCP publisher token (JSON).
- `~/opentrader/config/alt_data_keys.json` — EIA `21XS…`, USDA `7D69…`, Alpaca `PKQD…`/`AEyx…` (gitignored in repo).
- `~/moonberg-work/.env` — `MOONBERG_TOKEN` JWT (`eyJhbG…`), `WALLET_KEY` (`cPLanF…`), `WALLET_KEY_B` (`36AQtG…`), `ANTHROPIC_API_KEY` (`sk-ant…`) — all gitignored.
- `~/niche-engine/.env` — full production set: Stripe live `sk_liv…`, `whsec_…`, Cloudflare `cfut_Z…`/tunnel JWT, Google/GitHub OAuth client secrets — gitignored.

## Repos requiring sanitization before push

1. **`moonberg-work`** — strip embedded `ghp_` PAT from remote URL (rewrite without creds); rotate the PAT (it is live and was used in transport); `.env` is ignored so no history rewrite needed.
2. **`niche-engine`** — rewrite `.env.example` back to placeholders (it contains **real live Stripe keys**); rotate Stripe keys + Anthropic key.
3. **`niche-engine/mcp-server-ts`** — remove `.mcpregistry_github_token` + `.mcpregistry_registry_token` from working tree AND history (filter-branch/filter-repo on commit `e49f8e3`); **rotate both tokens** — branch is ahead 2 of origin, leak on next push; check whether any prior push already exposed them.
4. **`/opt/user-data/experiment/cappuccino/Version 0.0.1`** — untrack + purge `key/cdp_api_key.json` (real CDP private key) from history (`0789991`); rotate the CDP key; add `key/` to `.gitignore`; do NOT push any branch containing it.

No third-party/AUR repos require action (nothing user-owned to push; odysseus working-tree modifications are uncommitted and don't affect its upstream remote).

## Surprises

- `/home/mrc/cappuccino` (momentum/xgboost, clean) and `/opt/user-data/experiment/cappuccino/Version 0.0.1` (trading system, **contains the key**) are two unrelated histories pushing to the **same** GitHub repo `darylerivers/Cappuccino` — key-leak surface is real on next push.
- `niche-engine` and its nested `mcp-server-ts` are separate git repos; the nested one already has a `darylerivers/nicheiqs-mcp` remote with committed tokens.
- Two **different** real CDP private keys exist on disk (the tracked `/opt` one and a second one in `Research/Thesis`).
- `open-webui` is not a compose stack — it runs standalone with a placeholder LM Studio key.
- Live GitHub PATs exist in 3 places: embedded in `moonberg-work` remote, `~/.git-credentials`, and committed (unpushed) in `niche-engine/mcp-server-ts`.
