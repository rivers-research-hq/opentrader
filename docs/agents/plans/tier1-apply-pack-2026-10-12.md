# Tier-1 ops tickets — human-apply pack (2026-10-12)

Tickets #291, #294, #301, #302, #304 (all part of #286). Every apply step below
is **human-gated by the tickets' own definitions** (root actions, protected paths,
key custody). This pack is the agent-prepared material; nothing here has been
applied. Provenance: coredump math from
`docs/agents/research/coredump-blast-radius-2026-09-28.md` (§8), statuses verified
via `gh issue view` today.

---

## #291 — autonomous agent account (runbook, requires root)

Prereq verified: blocker #288 is CLOSED, so the runbook is unblocked.

```bash
# 1. unprivileged account (no sudo)
sudo useradd -m -s /bin/bash otagent
sudo loginctl enable-linger otagent

# 2. GPU device groups (render/render2x per ROCm group on this host)
for g in $(getent group | grep -E '^(render|video)' | cut -d: -f1); do sudo gpasswd -a otagent "$g"; done

# 3. move Tier-1 units (list from: systemctl --user list-unit-files | grep -E 'opentrader|hermes|gpu-sync')
#    per-unit: copy ~/.config/systemd/user/<unit> to ~otagent/.config/systemd/user/,
#    fix EnvironmentFile/User= paths, then:
sudo -u otagent XDG_RUNTIME_DIR=/run/user/$(id -u otagent) systemctl --user daemon-reload
sudo -u otagent XDG_RUNTIME_DIR=/run/user/$(id -u otagent) systemctl --user enable --now <unit>

# 4. repo plane read-only for the account, sandbox + data writable
sudo chown -R mrc:mrc /home/mrc/opentrader           # owner unchanged
sudo setfacl -R -m u:otagent:rx /home/mrc/opentrader  # read+traverse only
sudo setfacl -R -m u:otagent:rwx /home/mrc/opentrader-data 2>/dev/null || echo "set data path"

# 5. verification (ticket's own bar: verified, not asserted)
sudo -u otagent systemctl --user is-active <unit>            # expect active
sudo -u otagent test -w /home/mrc/opentrader/AGENTS.md && echo FAIL || echo PASS   # plane unwritable
```

Open items the human must decide during apply: exact Tier-1 unit list; data-path
location; whether hermes-gateway (socket-owning) moves in this pass or a follow-up.

## #294 — Hermes re-provision (depends on #291 landing)

Copy-not-chmod rule (from the ticket): `~/.hermes`, `~/.local`, and the memory-MCP
store are uid-1000-owned and 0700/0750 — they must be REPROVISIONED under
~otagent (fresh config, keys re-entered), never share-permissioned. Applies only
after #291's account exists.

## #301 — coredump bounds (drop-in ready; sandbox verification pending)

Drop-in `/etc/systemd/coredump.conf.d/10-bound.conf` (both ProcessSizeMax AND
ExternalSizeMax — the read cap is MAX of the two; §8.1):

```ini
[Coredump]
Storage=external
Compress=yes
ProcessSizeMax=1G
ExternalSizeMax=1G
MaxUse=2G
KeepFree=8G
```

Plus per-unit `LimitCORE=1G` on the large units, `MemoryMax=2G` on
`systemd-coredump@.service`. Verification steps (§8.6 of the research doc) MUST
run before apply — the truncation path was never exercised on this host:

```bash
# in a systemd-capable sandbox: crash a ≥2GiB-anon test process with the drop-in
# in place, then: coredumpctl info | grep -E 'Size on Disk|TRUNCATED'  (expect ≤1G, TRUNCATED=1)
# journal _SYSTEMD_UNIT=systemd-coredump@... memory peak ≲1GiB
```

## #302 — tirith receipts (key custody is the human step)

1. **Human generates the audit key off-agent** (e.g. on the live session's own
   terminal): `tirith keygen --output ~/.tirith-audit/audit.key` — the file must
   be 0600, owned by the human, and NOT under any agent-readable path. If agents
   can read it, signatures prove nothing (ticket's own words).
2. Start the daemon: `tirith daemon` (systemd unit recommended after start).
3. Route plane changes: `tirith attest build --bind-policy ...` per #290's decision.
4. #304's re-pin then goes through a tirith receipt instead of bare `pin.py`.

## #304 — meta_pass exit code (protected: human applies, then pin)

One-line semantic change in `/home/mrc/harness-policy/meta_agent/meta_pass.py`:

```diff
     bad = [r for r in results if r["rc"] not in (0,)]
     print(f"meta pass done: {len(results)} verifiers, {len(bad)} failing -> {QUEUE}")
-    return 1 if bad else 0
+    # #304: findings are DELIVERED to REVIEW_QUEUE.md / logs/meta_pass.jsonl.
+    # Non-zero is reserved for "the pass could not run" — verifier findings
+    # are not a pass failure.
+    return 0
```

Apply order: edit → `verifiers/pin.py` (or tirith receipt once #302 lands) →
confirm `harness-meta-pass.service` runs (note: its idle gate is unsatisfiable
per the 2026-09-28 inventory, C-B — separate defect, tracked in the inventory doc).
