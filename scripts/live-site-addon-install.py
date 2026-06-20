#!/usr/bin/env -S uv run python
from __future__ import annotations

import sys

from app.dev.live_site_addon_install import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
