#!/usr/bin/env python3
"""List local models via HuggingHack API."""

import sys, json, urllib.request

BASE = "http://127.0.0.1:7860/api"


def list_local(query=""):
    try:
        url = f"{BASE}/local-models"
        if query:
            url += f"?query={urllib.parse.quote(query)}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    for m in data.get("items", []):
        size_gb = m.get("size_bytes", 0) / 1e9
        print(
            json.dumps(
                {
                    "id": m.get("repo_id"),
                    "files": m.get("file_count", 0),
                    "size_gb": round(size_gb, 2),
                    "formats": m.get("formats", []),
                }
            )
        )


if __name__ == "__main__":
    import argparse, urllib.parse

    p = argparse.ArgumentParser(description="List local Hugging Face models")
    p.add_argument("query", nargs="?", default="", help="Filter by name")
    args = p.parse_args()
    list_local(args.query)
