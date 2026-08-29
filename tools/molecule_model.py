#!/usr/bin/env python3
"""Buildable physical molecule of the OpenTrader architecture.

A plastic ball-and-rod kit builds real molecules with fixed bond angles —
arbitrary 3D graph layouts are unbuildable. So this is the architecture as a
SMALL, buildable molecule: 8 core atoms (each = a major module) connected
with the kit's natural geometry (C=tetrahedral, N=trigonal, O=bent, S=bent,
Cl=monovalent). Emits an assembly guide + a viewer.

OLD NOBBY kit mapping: black=C (data), blue=N (harness), red=O (mot,training),
yellow=S (exchange), green=Cl (risk), purple=P (setup_search), black=C (state).

Structure (build this):
        state(C) -- data(C) -- harness(N) -- mot(O) -- training(O)
                        |            |             
                    setup_search(P)  +-- exchange(S)
                                     +-- risk(Cl)
"""

import json
import math
import random
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data"
random.seed(3)

# ── The buildable core: atom -> (element, role, kit_color) ──
ATOMS = [
    ("data", "C", "core", "#222222"),
    ("state", "C", "core", "#222222"),
    ("harness.py", "N", "hub", "#1f6feb"),
    ("mot", "O", "agents", "#d62828"),
    ("training", "O", "training", "#d62828"),
    ("exchange", "S", "data-io", "#f4d35e"),
    ("risk", "Cl", "risk", "#2a9d8f"),
    ("setup_search", "P", "research", "#8338ec"),
]
# bonds as (atom_i, atom_j) using a buildable geometry
BONDS = [(1, 0), (0, 2), (2, 3), (3, 4), (0, 7), (2, 5), (2, 6)]  # 0-indexed
# plus the pendant groups folded into their parent (for the legend only)
FOLDED = {
    "data": ["data", "connections.py", "data_mgmt.py"],
    "state": ["state"],
    "harness.py": ["harness.py", "mcp_server.py", "gpu_sync.py"],
    "mot": ["mot", "agent"],
    "training": ["training", "coordinator.py", "model_manager.py"],
    "exchange": ["exchange", "onchain.py"],
    "risk": ["risk"],
    "setup_search": ["setup_search", "tools", "tests"],
}


def build_positions():
    """Place atoms on the kit'"'"'s natural geometry: data as a tetrahedral-ish
    center in the x-y plane, harness on its right, branching trigonally, with
    light z-offsets so the physical model stands."""
    # 0 data at origin
    pos = {}
    pos["data"] = (0.0, 0.0, 0.0)
    # 1 state: behind data (a back bond, tetrahedral)
    pos["state"] = (-1.0, 0.3, 0.0)
    # 2 harness: to the right of data (main axis)
    pos["harness.py"] = (1.6, 0.0, 0.0)
    # 3 mot: from harness, up-right (trigonal ~120)
    pos["mot"] = (3.1, 0.9, 0.0)
    # 4 training: from mot, further (a chain)
    pos["training"] = (4.6, 1.3, 0.0)
    # 7 setup_search: from data, down-left
    pos["setup_search"] = (-1.6, -1.0, 0.0)
    # 5 exchange: from harness, down-right
    pos["exchange"] = (2.6, -1.1, 0.0)
    # 6 risk: from harness, down
    pos["risk"] = (1.2, -1.4, 0.0)
    return pos


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pos = build_positions()
    names = [a[0] for a in ATOMS]

    # PDB (atoms + conect)
    lines = []
    ai = 1
    for i, (n, el, role, c) in enumerate(ATOMS):
        p = pos[n]
        nm = (n[:4] + ".") if len(n) > 4 else (n + " ")
        lines.append(f"HETATM{ai:5d} {nm:5s} {n[:4].upper():3s} MOL     1    "
                     f"{p[0]:8.3f}{p[1]:8.3f}{p[2]:8.3f}  1.00  0.00          {el:>2s}")
        ai += 1
    for i, j in BONDS:
        lines.append(f"CONECT{i + 1:5d}{j + 1:5d}")
    (OUT / "codebase_molecule.pdb").write_text("\n".join(lines) + "\n")

    # Assembly guide (the physical recipe)
    g = ["# OpenTrader — buildable physical molecule (OLD NOBBY kit)",
         "",
         "8 atoms, 7 rods. Each atom = a major module; each rod = a key",
         "dependency. Geometry uses the kit's natural bond angles.",
         "",
         "## Atoms (your kit pieces)",
         "", "| # | Kit piece | Atom (module) | Also represents |",
         "|---|-----------|---------------|-----------------|"]
    for i, (n, el, role, c) in enumerate(ATOMS, 1):
        g.append(f"| {i} | {el} ({role}) | {n} | {', '.join(f for f in FOLDED[n] if f != n)} |")
    g += ["", "## Assembly (connect the rods)", ""]
    bond_guide = {
        (1, 0): "connect **state** to **data** (black-black, a back bond)",
        (0, 2): "connect **data** to **harness** (black to blue) — the main axis",
        (2, 3): "connect **harness** to **mot** (blue to red, up) — the agents branch",
        (3, 4): "connect **mot** to **training** (red to red) — the lifecycle chain",
        (0, 7): "connect **data** to **setup_search** (black to purple, down-left) — the research branch",
        (2, 5): "connect **harness** to **exchange** (blue to yellow, down-right) — the data-I/O branch",
        (2, 6): "connect **harness** to **risk** (blue to green, down) — the risk pendant",
    }
    for (i, j) in BONDS:
        g.append(f"  {bond_guide[(i, j)]}")
    g += ["", "## Reading the molecule", "",
          "- The blue **harness** hub bonds the agents (mot), data-I/O (exchange) and risk.",
          "- The black **data** core substrates the research branch (setup_search) and state.",
          "- **mot → training** is the model-lifecycle chain.",
          "- Peripheral modules (UI, services, tools) are folded into their parent atoms",
          "  — keep the model buildable; hang them as extra balls on the parent if you",
          "  have spare pieces.",
          "",
          "## Optimization reads",
          "- The blue hub holds 3 rods: if it's overloaded, that's the coupling you see.",
          "- mot/training are a red chain: they grow together.",
          "- setup_search hangs off data, not the hub: research is decoupled from the",
          "  trading loop — a good isolation to preserve."]
    (OUT / "codebase_molecule_recipe.md").write_text("\n".join(g) + "\n")

    # HTML viewer (simple, with the key)
    atoms_json = json.dumps([{"n": n, "c": c, "x": pos[n][0], "y": pos[n][1], "z": pos[n][2],
                              "el": el, "r": role} for n, el, role, c in ATOMS])
    bonds_json = json.dumps([[i, j] for i, j in BONDS])
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>OpenTrader molecule</title>
<style>body{{margin:0;background:#111;color:#eee;font-family:monospace}}
#info{{position:fixed;top:8px;left:8px;z-index:5;background:#000a;padding:8px;border-radius:6px;font-size:12px}}
#legend{{position:fixed;top:8px;right:8px;z-index:5;background:#000a;padding:8px;border-radius:6px;font-size:11px}}</style></head>
<body><div id="info">OpenTrader — buildable molecule. Rotate/zoom.<br/>BLUE=N harness · BLACK=C data/state · RED=O mot/training · YELLOW=S exchange · GREEN=Cl risk · PURPLE=P setup_search</div>
<div id="legend"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
var DATA={{atoms:{atoms_json},bonds:{bonds_json}}};
var scene=new THREE.Scene(), cam=new THREE.PerspectiveCamera(60,innerWidth/innerHeight,0.1,50); cam.position.set(4,3,6);
var r=new THREE.WebGLRenderer({{antialias:true}}); r.setSize(innerWidth,innerHeight); document.body.appendChild(r.domElement);
var c=new THREE.OrbitControls(cam,r.domElement); new THREE.AmbientLight(0xffffff,0.6);
var dl=new THREE.DirectionalLight(0xffffff,0.8); dl.position.set(5,5,5); scene.add(dl);
var N=DATA.atoms.map(function(a){{var m=new THREE.Mesh(new THREE.SphereGeometry(0.34,24,24),new THREE.MeshPhongMaterial({{color:new THREE.Color(a.c)}})); m.position.set(a.x*1.4,a.y*1.4,a.z*1.4); m.userData={{n:a.n}}; scene.add(m); return m;}});
DATA.bonds.forEach(function(b){{var p1=N[b[0]].position,p2=N[b[1]].position,d=p2.clone().sub(p1),L=d.length();
var cyl=new THREE.Mesh(new THREE.CylinderGeometry(0.035,0.035,L,6),new THREE.MeshPhongMaterial({{color:0x999}}));
cyl.position.copy(p1).add(d.clone().multiplyScalar(0.5)); cyl.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),d.normalize()); scene.add(cyl);}});
var leg=document.getElementById("legend"); DATA.atoms.forEach(function(a){{var row=document.createElement("div"); var sw=document.createElement("span"); sw.style.cssText="display:inline-block;width:12px;height:12px;background:"+a.c+";margin-right:6px;border:1px solid #888"; row.appendChild(sw); row.appendChild(document.createTextNode(a.el+" · "+a.n)); leg.appendChild(row);}});
function animate(){{requestAnimationFrame(animate); c.update(); r.render(scene,cam);}} animate();
</script></body></html>"""
    (OUT / "codebase_molecule.html").write_text(html)
    print("PDB, recipe, viewer written (8 atoms, 7 bonds)")


if __name__ == "__main__":
    main()
