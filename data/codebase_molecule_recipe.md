# OpenTrader — buildable physical molecule (OLD NOBBY kit)

8 atoms, 7 rods. Each atom = a major module; each rod = a key
dependency. Geometry uses the kit's natural bond angles.

## Atoms (your kit pieces)

| # | Kit piece | Atom (module) | Also represents |
|---|-----------|---------------|-----------------|
| 1 | C (core) | data | connections.py, data_mgmt.py |
| 2 | C (core) | state |  |
| 3 | N (hub) | harness.py | mcp_server.py, gpu_sync.py |
| 4 | O (agents) | mot | agent |
| 5 | O (training) | training | coordinator.py, model_manager.py |
| 6 | S (data-io) | exchange | onchain.py |
| 7 | Cl (risk) | risk |  |
| 8 | P (research) | setup_search | tools, tests |

## Assembly (connect the rods)

  connect **state** to **data** (black-black, a back bond)
  connect **data** to **harness** (black to blue) — the main axis
  connect **harness** to **mot** (blue to red, up) — the agents branch
  connect **mot** to **training** (red to red) — the lifecycle chain
  connect **data** to **setup_search** (black to purple, down-left) — the research branch
  connect **harness** to **exchange** (blue to yellow, down-right) — the data-I/O branch
  connect **harness** to **risk** (blue to green, down) — the risk pendant

## Reading the molecule

- The blue **harness** hub bonds the agents (mot), data-I/O (exchange) and risk.
- The black **data** core substrates the research branch (setup_search) and state.
- **mot → training** is the model-lifecycle chain.
- Peripheral modules (UI, services, tools) are folded into their parent atoms
  — keep the model buildable; hang them as extra balls on the parent if you
  have spare pieces.

## Optimization reads
- The blue hub holds 3 rods: if it's overloaded, that's the coupling you see.
- mot/training are a red chain: they grow together.
- setup_search hangs off data, not the hub: research is decoupled from the
  trading loop — a good isolation to preserve.
