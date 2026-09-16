#!/usr/bin/env python3
"""llama_bench — throughput probe for a running llama-server.

Reports prefill (prompt-eval) and decode (generation) tokens/second, plus the
draft-acceptance counters when speculative decoding is enabled. The point is to
make "faster" a measured claim: run the SAME fixed prompts against two server
configs and diff the numbers.

    python3 scripts/llama_bench.py --url http://127.0.0.1:5808/v1/chat/completions \
        --label baseline --gen 256

Numbers come from the server's own `timings` block (llama.cpp build 10989
returns prompt_n/prompt_per_second/predicted_n/predicted_per_second and, with
speculative decoding, draft_n/draft_n_accepted). Wall-clock is recorded as a
cross-check. VRAM is read from rocm-smi when available, so every result carries
the footprint it was measured at.
"""
import argparse, json, subprocess, time, urllib.request

FILLER = ("the desk executes at the venue and the ledger records the fill while "
          "liquidity drifts across sessions without any particular signal ")


def make_prompt(target_tokens):
    """Deterministic filler so prefill cost is reproducible across configs."""
    n_words = max(40, int(target_tokens / 1.3))
    words = (FILLER * (n_words // len(FILLER.split()) + 1)).split()[:n_words]
    return ("Summarise the text below in one sentence.\n\n" + " ".join(words))


def ask(url, prompt, max_tokens):
    body = json.dumps({"model": "local",
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": max_tokens, "temperature": 0}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        d = json.loads(r.read().decode())
    return d, round(time.time() - t0, 2)


def vram():
    try:
        out = subprocess.run(["rocm-smi", "--showmeminfo", "vram", "--csv"],
                             capture_output=True, text=True, timeout=10).stdout
        return out.strip().splitlines()[-1] if out.strip() else None
    except Exception:
        return None


def server_info(base):
    try:
        with urllib.request.urlopen(base + "/v1/models", timeout=10) as r:
            m = json.loads(r.read().decode())["data"]
        return [x.get("id") for x in m]
    except Exception as e:
        return f"unreachable: {e}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:5808/v1/chat/completions")
    ap.add_argument("--label", default="run")
    ap.add_argument("--gen", type=int, default=256, help="max tokens to generate")
    ap.add_argument("--prefill-tokens", type=int, default=800)
    ap.add_argument("--runs", type=int, default=2, help="decode runs to average")
    a = ap.parse_args()
    base = a.url.rsplit("/v1/", 1)[0]

    prefill_prompt = make_prompt(a.prefill_tokens)
    decode_prompt = "Write two sentences about order execution."

    runs = []
    for _ in range(a.runs):
        pre, pre_s = ask(a.url, prefill_prompt, 8)        # prefill-dominated
        dec, dec_s = ask(a.url, decode_prompt, a.gen)     # decode-dominated
        pt = pre.get("timings", {})
        dt = dec.get("timings", {})
        runs.append({
            "prefill_tokens_per_s": pt.get("prompt_per_second"),
            "decode_tokens_per_s": dt.get("predicted_per_second"),
            "predicted_n": dt.get("predicted_n"),
            "draft_n": dt.get("draft_n"),
            "draft_n_accepted": dt.get("draft_n_accepted"),
            "wall_s": {"prefill": pre_s, "decode": dec_s},
        })
    dec_tps = [r["decode_tokens_per_s"] for r in runs if r["decode_tokens_per_s"]]
    pre_tps = [r["prefill_tokens_per_s"] for r in runs if r["prefill_tokens_per_s"]]
    acc = [r for r in runs if r.get("draft_n")]
    accept_rate = (sum(r["draft_n_accepted"] for r in acc) / sum(r["draft_n"] for r in acc)
                   if acc else None)

    print(json.dumps({
        "label": a.label, "url": a.url, "served_models": server_info(base),
        "gen_max_tokens": a.gen, "runs": a.runs,
        "decode_tokens_per_s_mean": round(sum(dec_tps) / len(dec_tps), 2) if dec_tps else None,
        "prefill_tokens_per_s_mean": round(sum(pre_tps) / len(pre_tps), 2) if pre_tps else None,
        "draft_accept_rate": round(accept_rate, 3) if accept_rate is not None else None,
        "vram": vram(), "detail": runs,
    }, indent=1))