#!/usr/bin/env python3
"""Search Hugging Face Hub for models via HuggingHack API."""

import sys, json, urllib.request, urllib.parse

BASE = "http://127.0.0.1:7860/api/hub/models"


def search(query="", sort="trending", limit=10, task="", library=""):
    params = {"search": query, "sort": sort, "limit": min(limit, 50)}
    if task:
        params["task"] = task
    if library:
        params["library"] = library
    url = f"{BASE}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    for m in data.get("items", []):
        print(
            json.dumps(
                {
                    "id": m.get("id"),
                    "downloads": m.get("downloads"),
                    "likes": m.get("likes"),
                    "task": m.get("pipeline_tag", ""),
                    "library": m.get("library_name", ""),
                    "local": m.get("local", False),
                    "gated": m.get("gated", False),
                }
            )
        )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Search Hugging Face Hub models")
    p.add_argument("query", nargs="?", default="", help="Search terms")
    p.add_argument(
        "--sort",
        default="trending",
        choices=["trending", "downloads", "updated", "likes"],
    )
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--task", default="", help="Filter by task (text-generation, etc)")
    p.add_argument(
        "--library", default="", help="Filter by library (transformers, llama.cpp, etc)"
    )
    args = p.parse_args()
    search(args.query, args.sort, args.limit, args.task, args.library)
