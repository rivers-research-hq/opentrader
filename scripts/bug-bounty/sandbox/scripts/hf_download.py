#!/usr/bin/env python3
"""Download models from Hugging Face via HuggingHack API."""

import sys, json, urllib.request, time

BASE = "http://127.0.0.1:7860/api"


def download(
    repo_id, mode="full", revision="main", allow_patterns=None, ignore_patterns=None
):
    body = json.dumps(
        {
            "repo_id": repo_id,
            "revision": revision,
            "mode": mode,
            "allow_patterns": allow_patterns or [],
            "ignore_patterns": ignore_patterns or [],
        }
    ).encode()

    try:
        req = urllib.request.Request(
            f"{BASE}/downloads",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    download_id = result.get("id")
    print(json.dumps({"status": "queued", "id": download_id, "repo_id": repo_id}))

    # Poll until complete
    while True:
        time.sleep(3)
        try:
            with urllib.request.urlopen(
                f"{BASE}/downloads/{download_id}", timeout=10
            ) as resp:
                status = json.loads(resp.read())
        except Exception:
            continue

        state = status.get("status", "unknown")
        if state == "completed":
            print(
                json.dumps(
                    {
                        "status": "completed",
                        "id": download_id,
                        "path": status.get("local_path", ""),
                    }
                )
            )
            break
        elif state == "failed":
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "id": download_id,
                        "error": status.get("error", ""),
                    }
                )
            )
            break
        elif state == "cancelled":
            print(json.dumps({"status": "cancelled", "id": download_id}))
            break


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Download Hugging Face model")
    p.add_argument("repo_id", help="Repository ID (org/name)")
    p.add_argument(
        "--mode",
        default="full",
        choices=["full", "safetensors", "gguf", "metadata", "custom"],
        help="Download mode",
    )
    p.add_argument("--revision", default="main", help="Branch/tag/commit")
    p.add_argument(
        "--include",
        default="",
        help="Comma-separated file patterns to include (custom mode)",
    )
    p.add_argument(
        "--exclude",
        default="",
        help="Comma-separated file patterns to exclude (custom mode)",
    )
    p.add_argument(
        "--gguf", default="", help="GGUF quantization to download (e.g. Q4_K_M)"
    )
    args = p.parse_args()

    allow = []
    ignore = []
    if args.mode == "gguf" and args.gguf:
        allow = [f"*{args.gguf}.gguf", "*.json", "tokenizer*"]
        args.mode = "custom"
    elif args.mode == "custom":
        allow = [p.strip() for p in args.include.split(",") if p.strip()]
        ignore = [p.strip() for p in args.exclude.split(",") if p.strip()]

    download(args.repo_id, args.mode, args.revision, allow, ignore)
