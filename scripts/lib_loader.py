"""Tiny shim so scripts can `import lib` regardless of how they're invoked.

Without this, calling `python3 /path/to/scripts/prime-context.py` doesn't put
the scripts/ directory on sys.path on every platform.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
