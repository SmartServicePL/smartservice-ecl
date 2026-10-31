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

    @pytest.fixture
    def fake_ecl_tcp(socket_enabled):
        """The fake ECL is a real TCP server on 127.0.0.1: pytest-socket (loaded
        by pytest-homeassistant-custom-component) blocks sockets in every test,
        so the tests of the fake controller open them - to 127.0.0.1 only (its
        allowed host stays)."""
        return
else:
    collect_ignore_glob = ["test_ha_*.py"]

    @pytest.fixture
    def fake_ecl_tcp():
        """Without pytest-socket nothing is blocked."""
        return
