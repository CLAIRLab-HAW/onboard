"""Puts ``scripts/`` on the import path so the tools there import by name.

They are deployed scripts, not a package: the installer copies each one to ``/usr/local/bin`` under its command
name, so there is no ``src/`` layout and nothing to ``pip install``.  Doing it here rather than in the test module
keeps the manipulation out of the tests and off ruff's E402 -- and pytest imports a conftest before the test
modules beside it, under both import modes (the workspace root run uses ``--import-mode=importlib``, CI's plain
``pytest tests`` the default one).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
