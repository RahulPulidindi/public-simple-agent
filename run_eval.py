#!/usr/bin/env python
"""Entry point for the eval framework. Run with: uv run python run_eval.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from evals.framework.runner import main

if __name__ == "__main__":
    main()
