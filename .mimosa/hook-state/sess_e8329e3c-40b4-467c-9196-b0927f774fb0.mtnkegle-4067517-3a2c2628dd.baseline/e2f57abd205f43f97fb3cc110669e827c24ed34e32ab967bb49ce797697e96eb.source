from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download one Hugging Face repository snapshot.")
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--target", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--allow-patterns", default="[]")
    parser.add_argument("--ignore-patterns", default="[]")
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def decode_patterns(raw: str) -> list[str] | None:
    values = json.loads(raw)
    if not isinstance(values, list):
        raise ValueError("Download patterns must be a JSON list.")
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    return cleaned or None


def main() -> None:
    args = parse_args()
    snapshot_download(
        repo_id=args.repo_id,
        revision=args.revision,
        local_dir=Path(args.target),
        token=os.getenv("HF_TOKEN") or False,
        endpoint=args.endpoint,
        allow_patterns=decode_patterns(args.allow_patterns),
        ignore_patterns=decode_patterns(args.ignore_patterns),
        max_workers=max(1, min(args.workers, 16)),
    )


if __name__ == "__main__":
    main()
