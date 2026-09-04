#!/usr/bin/env python3
"""Standalone training runner — downloads model, runs LoRA fine-tune, saves results."""
import sys, os, time, json, logging, signal

sys.path.insert(0, '/home/mrc/opentrader')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s"
)
logger = logging.getLogger("train_runner")

def main():
    logger.info("=" * 50)
    logger.info("  STARTING FINE-TUNE TRAINING")
    logger.info("=" * 50)
    
    t0 = time.time()
    def _training_timeout(signum, frame):
        raise TimeoutError("Training timed out after 30 minutes")
    signal.signal(signal.SIGALRM, _training_timeout)
    signal.alarm(1800)
    try:
        from training.finetune_cycle import run_finetune
        result = run_finetune('/home/mrc/opentrader/data')
        signal.alarm(0)
    except Exception as e:
        result = {"status": "error", "error": str(e)}
        import traceback
        traceback.print_exc()
    
    elapsed = time.time() - t0
    result["duration_s"] = round(elapsed, 1)
    
    with open('/home/mrc/opentrader/data/training/finetune_status.json', 'w') as f:
        json.dump(result, f, indent=2, default=str)
    
    logger.info(f"Result: {result.get('status')} ({elapsed:.0f}s)")
    if result.get("error"):
        logger.error(f"Error: {result['error'][:300]}")
    else:
        logger.info(f"Version: {result.get('version')}")
    
    return result

if __name__ == "__main__":
    main()
