#!/usr/bin/env python3
"""Generate an ot-updater Manifest for a release artifact (ticket #392).

Usage: make_manifest.py <artifact> --version X.Y.Z --channel stable|beta|nightly \
         --min-version X.Y.Z [--out manifest.json]
The sha256 + size are computed from the actual bytes — never hand-entered
(house rule: no fabricated integrity values).
"""
import argparse, hashlib, json, pathlib, re, sys

def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact")
    ap.add_argument("--version", required=True)
    ap.add_argument("--channel", required=True, choices=["stable", "beta", "nightly"])
    ap.add_argument("--min-version", default="0.1.0")
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        print(f"version must be X.Y.Z, got {a.version!r}", file=sys.stderr)
        return 1
    p = pathlib.Path(a.artifact)
    if not p.is_file():
        print(f"artifact missing: {p}", file=sys.stderr)
        return 1
    manifest = {
        "version": a.version,
        "channel": a.channel,
        "artifact_sha256": sha256(p),
        "artifact_size": p.stat().st_size,
        "released_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "min_version": a.min_version,
    }
    out = json.dumps(manifest, indent=2) + "\n"
    if a.out == "-":
        sys.stdout.write(out)
    else:
        pathlib.Path(a.out).write_text(out)
        print(f"manifest written: {a.out}", file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())
