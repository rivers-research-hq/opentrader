"""Seed bug 2: future-dated daily bar crash-loop (missing sanitizer).

Historical ground truth: commit d632169 "fix: future-dated bars crash-loop the
rule path (root cause) + defect-log scanner". The stock waterfall emits a
NEXT-UTC-MIDNIGHT placeholder daily bar; the rule path took it as the latest
date and lookups on other series raised KeyError(Timestamp) — crash-looping the
harness for ~83 minutes (defect log: 522 events, 2026-08-05 22:33 UTC episode).

The fix added `_daily_bars()` with a cutoff filter and routed all six fetch
sites through it. The seed re-introduces the bug by bypassing the sanitizer:
the helper stays but the hottest call sites revert to raw `get_bars`.
"""

BUG_ID = "future-bar"
FILE = "harness.py"
FUNCTION = "_daily_bars"
SEVERITY = "critical"  # deterministic crash-loop of the trading harness
DETECTABLE_BY = "harness"
KEYWORDS = [
    "_daily_bars", "cutoff", "future-dated", "next-UTC-midnight",
    "placeholder bar", "crash-loop", "KeyError(Timestamp)", "waterfall",
]

# The buggy replacement for the _daily_bars body: no cutoff filter, returns the
# raw bars including any future-dated placeholder from the waterfall.
BUGGY_BODY = '''    def _daily_bars(self, sym: str, limit: int):
        """Fetch daily bars, returning them UNFILTERED. NOTE: the stock
        waterfall can emit a next-UTC-midnight placeholder bar; returning it
        can key other series' lookups on a future date."""
        bars = self.exchange.get_bars(sym, "1d", limit=limit)
        if not bars:
            return bars
        return bars
'''

FIXED_BODY = '''    def _daily_bars(self, sym: str, limit: int):
        """Fetch daily bars, DROPPING future-dated bars. The stock waterfall
        can emit a next-UTC-midnight placeholder bar; a future date keyed into
        other series' indexes raises KeyError(Timestamp) and crash-loops the
        harness (the 22:33->00:34 UTC marathon). Root fix: the bad date never
        enters any rule path."""
        bars = self.exchange.get_bars(sym, "1d", limit=limit)
        if not bars:
            return bars
        cutoff = datetime.now(timezone.utc) + timedelta(hours=1)
        clean = [b for b in bars if self._bar_ts(b) <= cutoff]
        if len(clean) != len(bars):
            logger.warning(
                f"  dropped {len(bars) - len(clean)} future-dated bar(s) for {sym}"
            )
        return clean
'''

# Static detector: the fixed method must contain the cutoff filter; the seed
# must not. We import the class and check the source text.
DETECTOR = '''
import inspect
from harness import OpenTraderHarness
src = inspect.getsource(OpenTraderHarness._daily_bars)
assert "cutoff" not in src and "clean" not in src, "expected unfiltered (bug present)"
print("future-bar seed present: no cutoff filter in _daily_bars")
'''
