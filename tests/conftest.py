"""Tests with Home Assistant (test_ha_*.py) need pytest-homeassistant-custom-
component - in CI (Home Assistant does not run on Windows). Without it only
the tests of the client, the map and the reader run."""

from __future__ import annotations

import importlib.util

import pytest

HA = importlib.util.find_spec("pytest_homeassistant_custom_component") is not None

if HA:
    pytest_plugins = ["pytest_homeassistant_custom_component"]

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Load integrations from custom_components."""
        return
else:
    collect_ignore_glob = ["test_ha_*.py"]
