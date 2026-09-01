#!/usr/bin/env python3
"""Compatibility adapter for the standalone Webflow browser core."""

from pathlib import Path
import sys


LIB_DIR = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB_DIR))

from webflow_browser.core import main


if __name__ == "__main__":
    raise SystemExit(main())
