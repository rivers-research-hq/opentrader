#!/usr/bin/env python3
"""Discover and download Hugging Face models.
Search via HuggingHack API, download via huggingface_hub directly."""

import sys, json, urllib.request, urllib.parse, os, time

BASE = "http://127.0.0.1:7860/api/hub/models"
MODEL_DIR = "/home/mrc/models"


def search_hub(query="", sort="trending", limit=10, task="", library=""):
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
    return data.get("items", [])


def list_hub():
    """List models already downloaded via huggingface_hub."""
    from huggingface_hub import scan_cache_dir

    try:
        cache = scan_cache_dir()
        repos = {}
        for repo in cache.repos:
            size = sum(getattr(r, "file_size", 0) or 0 for r in repo.revisions)
            repos[repo.repo_id] = {
                "repo_id": repo.repo_id,
                "size_gb": round(size / 1e9, 2),
                "revisions": len(repo.revisions),
            }
        return list(repos.values())
    except Exception as e:
        return [{"error": str(e)}]


def download(
    repo_id, revision="main", allow_patterns=None, ignore_patterns=None, gguf_quant=""
):
    """Download model files via huggingface_hub."""
    from huggingface_hub import snapshot_download

    # Build patterns for gguf mode
    if gguf_quant:
        allow = [f"*{gguf_quant}*.gguf", "*.json", "tokenizer*", "*.md"]
    elif allow_patterns:
        allow = [p.strip() for p in allow_patterns.split(",") if p.strip()]
    else:
        allow = None
    if ignore_patterns:
        ignore = [p.strip() for p in ignore_patterns.split(",") if p.strip()]
    else:
        ignore = None

    print(
        json.dumps({"status": "downloading", "repo_id": repo_id, "revision": revision})
    )

    try:
        local_dir = os.path.join(MODEL_DIR, repo_id.replace("/", os.sep))
        path = snapshot_download(
            repo_id=repo_id,
            revision=revision,
            local_dir=local_dir,
            allow_patterns=allow,
            ignore_patterns=ignore,
            resume_download=True,
        )
        print(json.dumps({"status": "completed", "repo_id": repo_id, "path": path}))
    except Exception as e:
        print(json.dumps({"status": "failed", "repo_id": repo_id, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Hugging Face model tools")
    sub = p.add_subparsers(dest="command")

    search_p = sub.add_parser("search", help="Search Hugging Face Hub")
    search_p.add_argument("query", nargs="?", default="")
    search_p.add_argument("--sort", default="trending")
    search_p.add_argument("--limit", type=int, default=10)
    search_p.add_argument("--task", default="")
    search_p.add_argument("--library", default="")

    dl_p = sub.add_parser("download", help="Download model")
    dl_p.add_argument("repo_id")
    dl_p.add_argument("--revision", default="main")
    dl_p.add_argument("--gguf", default="", help="GGUF quantization (e.g. Q4_K_M)")
    dl_p.add_argument("--include", default="", help="File patterns to include")
    dl_p.add_argument("--exclude", default="", help="File patterns to exclude")

    list_p = sub.add_parser("list", help="List downloaded models")

    args = p.parse_args()

    if args.command == "search":
        items = search_hub(args.query, args.sort, args.limit, args.task, args.library)
        for m in items:
            print(
                json.dumps(
                    {
                        "id": m.get("id"),
                        "downloads": m.get("downloads"),
                        "likes": m.get("likes"),
                        "task": m.get("pipeline_tag", ""),
                        "library": m.get("library_name", ""),
                        "local": m.get("local", False),
                    }
                )
            )
    elif args.command == "download":
        download(args.repo_id, args.revision, args.include, args.exclude, args.gguf)
    elif args.command == "list":
        items = list_hub()
        for m in items:
            print(json.dumps(m))
    else:
        p.print_help()
