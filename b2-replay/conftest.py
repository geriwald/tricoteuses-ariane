"""Put this directory on sys.path so tests import `replay`/`server` directly
(the brick is a flat module set, not a package)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
