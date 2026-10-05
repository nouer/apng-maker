#!/usr/bin/env python3
"""apngmk — APNG をローカルで作る。使い方は `python3 apngmk.py -h`。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apng_maker.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
