import os
import sys

# Repo root isn't on sys.path by default under pytest's per-module rootpath
# resolution (tests/ has no __init__.py, so only tests/ gets auto-inserted).
# Insert it here so `scripts.*` imports resolve in test modules.
sys.path.insert(0, os.path.dirname(__file__))
