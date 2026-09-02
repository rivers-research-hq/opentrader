## Chapter 1 — 2026-08-20 07:29:09
Live state: opencode-server is UP (:4096), Hollama is UP (:4173 local/tailnet), the qwen backend is UP on :5804 (health ok, `llama-server` listening), and a second `llama-server` listener is present on :5802; dashboard/MCP claimed-stopped endpoints show no live listeners, but harness/Codesage/runner unit statuses were not directly captured in recon. Top 3 items: (1) the claimed `gpu-sync` LLM router on :5801 has no live listener even though the handoff says the LLM stack was left running and the harness would talk to :5801; (2) pinned context claims qwen effectively owns GPU1 VRAM while the handoff also claims a ~9.6GB DeepSeek `llama-server` is LIVE on the same GPU, yet live evidence only proves two `llama-server` sockets (:5802/:5804) with no VRAM proof; (3) many claimed systemd user units lack direct status in the provided recon, so several “running” or “stopped” claims are partly unverified.

## Services

| Service | Claimed unit / claim | Claimed port/status | Live evidence from recon | Current state | Drift flag |
|---|---|---|---:|---|---|
| opencode server | `opencode_server` | 0.0.0.0:4096, running | `=== opencode_server === active`; `LISTEN 0 ... 0.0.0:40 users:("opencode

