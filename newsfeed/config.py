"""newsfeed.config — path resolution and defaults."""

from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT / "data" / "newsfeed"
DB_PATH = DATA_DIR / "newsfeed.db"
SCHEMA_VERSION = 1

DEFAULTS = {
    "timeout_s": 15.0,
    "retries": 3,
    "rate_limit_s": {"default": 2.0, "api.gdeltproject.org": 5.0},
    "user_agent": "newsfeed/0.1 (local research store; contact: local)",
}

# Query-parameter keys stripped during URL canonicalization (case-insensitive
# prefix match on utm_*)
STRIP_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "cmpid", "ncid"}


def ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
