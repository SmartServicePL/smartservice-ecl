"""Load the integration's pure modules (no Home Assistant) for local tests:
a stand-in package keeps the integration's __init__.py (which imports Home
Assistant) from running, the modules' relative imports still work."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

COMPONENT = Path(__file__).parents[1] / "custom_components" / "smartservice_ecl"
PACKAGE = "smartservice_ecl_pure"


def load(name: str) -> types.ModuleType:
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(COMPONENT)]
        sys.modules[PACKAGE] = package
    return importlib.import_module(f"{PACKAGE}.{name}")
