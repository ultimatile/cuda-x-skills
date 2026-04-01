"""Add parent directory to sys.path so tests can import skill modules."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
