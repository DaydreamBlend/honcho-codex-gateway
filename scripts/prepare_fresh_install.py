#!/usr/bin/env python3
"""Compatibility wrapper for the packaged prepare command."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from honcho_codex_gateway.prepare import main

if __name__ == "__main__":
    main()
