"""JSON snapshots for the live arena viewer.

Writes data/arena/arena_state.json (polled by arena_view.html) and an
inline-embedded snapshot page for double-click viewing. To watch live:
  cd data/arena && python3 -m http.server 8098
then open http://localhost:8098/arena_view.html
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "arena"

HTML_TEMPLATE = Path(PROJECT / "arena" / "arena_view.html").read_text()


def write_snapshot(report):
    OUT.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **report,
    }
    (OUT / "arena_state.json").write_text(json.dumps(snapshot, indent=1, default=str))
    inline = HTML_TEMPLATE.replace(
        "const STATE = null;",
        f"const STATE = {json.dumps(snapshot, default=str)};",
    )
    (OUT / "arena_snapshot.html").write_text(inline)
    return OUT / "arena_state.json"
