## Chapter 1 — 2026-08-20 05:57:14
The live agent/LLM services are UP (opencode active on :409, hollama UP on :41, qwen38 healthy and listening on :5); the trading/routing layer is DOWN or UNVERIFIED (no :5 listener; no :80/:80 listeners in recon). Top 3 drif: (1) handoff/next-session claim a live gpu-sync route from :5 to llama-server :5, but :5 is not listening; (2 docs conflict on the active model — pinned says qwen3 owns GPU1 while handoff/next say DeepSeek-9B-on-5 is live — and recon shows two separate llm-server listeners (:5, :5); (3) harne/dashboard/MCP/Codesage are claimed STOPPED, but recon does not capture unit state, so down status is inferred from absent ports/processes only.

Services
| Service | Claimed | Live evidence in recon | Status |
|---|---:|---:|---:|
| opencode-server | `opencode-server.service`, 0.0:409, tailscale 5→409 | active; LISTEN `0.:409` user `opencode` pid=4826 fd=22; tailscale shows `http://archlinux:540 proxy http://127.0.0:4096` | UP |
| hollama UI | docker `hollama`, 127:4, tailnet exposure | container “Up 1 hours”; LISTEN on `127:4`, `10.3.:4`, IPv6 `[fd…]:4`; tailscale serves to `127:4` | UP |
| qwen38 backend / llama-server :5804 | pinned says `qwen-serve.service`, 127:58, al

