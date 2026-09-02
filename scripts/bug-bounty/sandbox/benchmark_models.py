#!/usr/bin/env python3
"""Benchmark llama.cpp models for debate latency.

Tests each model with/without speculative decoding using a standardized
debate prompt matching the Bull agent's actual workload.

Usage:
    python3 benchmark_models.py [--skip-gemma] [--skip-qwythos]
"""
import json, time, subprocess, sys, os, argparse, urllib.request

DEBATE_PROMPT = (
    "You are a Bull trading agent. Analyze the market and decide: BUY, SELL, or HOLD.\n\n"
    "Symbol: BTC/USDT\n"
    "Recent price action (15m bars):\n"
    "  O=63250 H=63320 L=63180 C=63290 V=45.2\n"
    "  O=63290 H=63410 L=63270 C=63380 V=52.1\n"
    "  O=63380 H=63520 L=63350 C=63490 V=48.7\n"
    "  O=63490 H=63540 L=63380 C=63410 V=38.3\n"
    "  O=63410 H=63450 L=63290 C=63320 V=41.5\n\n"
    "Market regime: trending_up (confidence: 85%)\n"
    "RSI(14): 62.3  MACD: +45.2  Volume ratio: 1.15\n"
    "Fear & Greed Index: 72 (Greed)\n\n"
    "Current position: HOLD (no position)\n"
    "Portfolio: $100,000 cash\n\n"
    "Your analysis and recommendation. Output as JSON:\n"
    '{"action": "BUY"|"SELL"|"HOLD", "confidence": 0.0-1.0, '
    '"position_pct": 0.01-0.25, "reason": "..."}\n'
)

SYSTEM_PROMPT = "You are a crypto trading analysis agent. Be concise, data-driven, and decisive."

MODELS = {
    "gemma": {
        "name": "Gemma-4-12B (draft-simple)",
        "alias": "gemma-4-12B-agentic",
        "port": 5802,
        "spec_types": ["none", "draft-simple"],
        "env_extra": {},
    },
    "qwythos": {
        "name": "Qwythos-9B-MTP",
        "alias": "qwythos-9b-mtp",
        "port": 5803,
        "spec_types": ["none", "draft-mtp"],
        "env_extra": {},
    },
}


def wait_for_server(port, timeout=60):
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
            if r.status == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def call_chat(port, prompt, max_tokens=200):
    """Call llama.cpp /v1/chat/completions and measure timing."""
    payload = {
        "model": "local",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": False,
    }
    data = json.dumps(payload).encode()
    
    t0 = time.perf_counter()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except Exception as e:
        return {"error": str(e), "elapsed": time.perf_counter() - t0}
    
    elapsed = time.perf_counter() - t0
    
    choice = result.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content", "")
    
    # Extract timing info from response
    usage = result.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    
    # llama.cpp returns timing in the response
    timing = result.get("timings", {})
    prompt_ms = timing.get("prompt_ms", 0)
    predicted_ms = timing.get("predicted_ms", 0)
    predicted_n = timing.get("predicted_n", 0)
    tokens_per_sec = predicted_n / (predicted_ms / 1000) if predicted_ms > 0 else 0
    
    return {
        "elapsed": elapsed,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "prompt_ms": prompt_ms,
        "predicted_ms": predicted_ms,
        "predicted_n": predicted_n,
        "tokens_per_sec": tokens_per_sec,
        "content_preview": content[:80] if content else "(empty)",
        "content_length": len(content),
    }


def run_benchmark(model_key, spec_type, runs=3):
    """Run N benchmark rounds for a model+spec combination."""
    import urllib.request
    
    model = MODELS[model_key]
    port = model["port"]
    alias = model["alias"]
    name = f"{model['name']} [{spec_type}]"
    
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    
    # Start server
    if spec_type == "draft-simple":
        spec_args = ["--spec-draft-model", "/home/mrc/models/draft/qwen2.5-0.5b-instruct-q2_k.gguf",
                      "--spec-type", "draft-simple", "--spec-draft-n-max", "5", "--spec-draft-n-min", "2",
                      "--gpu-layers-draft", "99"]
    elif spec_type == "draft-mtp":
        spec_args = ["--spec-type", "draft-mtp"]
    else:
        spec_args = ["--spec-type", "none"]
    
    server_cmd = model.get("server_cmd", None)
    if server_cmd:
        cmd = server_cmd + [f"--port", str(port), "--alias", alias] + spec_args
    else:
        print(f"  SKIP: no server_cmd defined for {model_key}")
        return None
    
    # Kill any existing server on this port
    subprocess.run(["pkill", "-f", f"port {port}"], capture_output=True)
    time.sleep(1)
    
    print(f"  Starting server on port {port}...")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if not wait_for_server(port):
        print(f"  ERROR: server failed to start on port {port}")
        proc.kill()
        return None
    
    print(f"  Server ready. Running {runs} warmup + {runs} benchmark rounds...")
    
    # Warmup
    for i in range(runs):
        call_chat(port, DEBATE_PROMPT)
    
    # Benchmark
    results = []
    for i in range(runs):
        r = call_chat(port, DEBATE_PROMPT)
        if "error" not in r:
            results.append(r)
            print(f"  Run {i+1}/{runs}: {r['elapsed']:.2f}s, {r['tokens_per_sec']:.1f} t/s, "
                  f"{r['prompt_ms']:.0f}ms prompt, {r['completion_tokens']} tok → "
                  f"\"{r['content_preview']}\"")
        else:
            print(f"  Run {i+1}/{runs}: ERROR — {r['error']}")
    
    # Kill server
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    time.sleep(1)
    
    if not results:
        return None
    
    # Aggregate
    avg_elapsed = sum(r["elapsed"] for r in results) / len(results)
    avg_tps = sum(r["tokens_per_sec"] for r in results) / len(results)
    avg_prompt_ms = sum(r["prompt_ms"] for r in results) / len(results)
    avg_tokens = sum(r["completion_tokens"] for r in results) / len(results)
    
    return {
        "model": name,
        "runs": len(results),
        "avg_elapsed_s": round(avg_elapsed, 2),
        "avg_tokens_per_sec": round(avg_tps, 1),
        "avg_prompt_ms": round(avg_prompt_ms, 0),
        "avg_completion_tokens": round(avg_tokens, 0),
        "estimated_cycle_s": round(avg_elapsed * 1.05, 1),  # 3 agents + overhead
    }


def compare(bench_results):
    """Print comparison table."""
    print(f"\n{'='*70}")
    print(f"  BENCHMARK SUMMARY")
    print(f"{'='*70}")
    print(f"  {'Model':<42} {'Elapsed':>8} {'t/s':>8} {'Prompt':>8} {'Est.Cycle':>10}")
    print(f"  {'-'*42} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")
    
    for r in bench_results:
        if r:
            print(f"  {r['model']:<42} {r['avg_elapsed_s']:>6.1f}s {r['avg_tokens_per_sec']:>7.1f} "
                  f"{r['avg_prompt_ms']:>6.0f}ms {r['estimated_cycle_s']:>8.1f}s")

    print()
    
    if len([r for r in bench_results if r]) >= 2:
        gemma = next((r for r in bench_results if r and "Gemma" in r["model"] and "none" in r["model"]), None)
        qwythos = next((r for r in bench_results if r and "Qwythos" in r["model"] and "none" in r["model"]), None)
        gemma_spec = next((r for r in bench_results if r and "Gemma" in r["model"] and "draft-simple" in r["model"]), None)
        qwythos_spec = next((r for r in bench_results if r and "Qwythos" in r["model"] and "draft-mtp" in r["model"]), None)
        
        if gemma and qwythos:
            speedup = gemma["avg_elapsed_s"] / qwythos["avg_elapsed_s"]
            print(f"  Qwythos vs Gemma (no spec-dec): {speedup:.1f}x faster")
        if gemma_spec and qwythos_spec:
            speedup = gemma_spec["avg_elapsed_s"] / qwythos_spec["avg_elapsed_s"]
            print(f"  Qwythos-MTP vs Gemma-draft (spec-dec): {speedup:.1f}x faster")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-gemma", action="store_true")
    parser.add_argument("--skip-qwythos", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    # Define server commands
    LLAMA = "/home/mrc/src/modelai-llama.cpp/build-wmma/bin/llama-server"
    LIB = "/home/mrc/src/modelai-llama.cpp/build-wmma/bin:/opt/rocm/lib:/opt/rocm/hip/lib"
    
    MODELS["gemma"]["server_cmd"] = [
        LLAMA,
        "--model", "/home/mrc/models/gemma-4-12B-agentic-fable5/gemma4-v2-Q4_K_M.gguf",
        "--host", "127.0.0.1",
        "--ctx-size", "16384",
        "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
        "--jinja", "--reasoning", "off",
        "--parallel", "1", "--cont-batching",
        "--threads", "8", "--batch-size", "4096", "--ubatch-size", "1024",
        "--n-predict", "512",
    ]
    
    MODELS["qwythos"]["server_cmd"] = [
        LLAMA,
        "--model", "/home/mrc/models/qwythos-9b-mtp/Qwythos-9B-Claude-Mythos-5-1M-MTP-Q4_K_M.gguf",
        "--host", "127.0.0.1",
        "--ctx-size", "16384",
        "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
        "--jinja", "--reasoning", "off",
        "--parallel", "1", "--cont-batching",
        "--threads", "8", "--batch-size", "4096", "--ubatch-size", "1024",
        "--n-predict", "512",
        "--n-gpu-layers", "99",
    ]
    
    os.environ["LD_LIBRARY_PATH"] = f"{LIB}:{os.environ.get('LD_LIBRARY_PATH', '')}"
    
    results = []
    
    for model_key in ["gemma", "qwythos"]:
        if (model_key == "gemma" and args.skip_gemma) or (model_key == "qwythos" and args.skip_qwythos):
            continue
        
        for spec in MODELS[model_key]["spec_types"]:
            r = run_benchmark(model_key, spec, runs=args.runs)
            results.append(r)
    
    compare(results)


if __name__ == "__main__":
    main()
