#!/usr/bin/env python3
"""Autonomous task: re-run + push the best value-head config through the holdout."""

import subprocess
import sys

from setup_search.value_head_1m import main as vh_main


def main():
    print("[value-push] running value_head_1m (cross-sectional + FRED) holdout...")
    vh_main()
    print("[value-push] done; see data/research_gate/value_head_1m_report.json")


if __name__ == "__main__":
    main()
