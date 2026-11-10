"""Diagnostics: the raw registers (to compare with the controller's display),
without its address and serial number."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import EclConfigEntry
from .ecl import PNU_SERIAL_HIGH, PNU_SERIAL_LOW

TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EclConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    identity = coordinator.identity
    registers = {
        str(pnu): value
        for pnu, value in sorted(coordinator.data.registers.items())
        if pnu not in (PNU_SERIAL_HIGH, PNU_SERIAL_LOW)
    }
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "application": identity.key,
        "application_version": identity.version,
        "software": identity.software,
        "supported": identity.application is not None,
        "read_function": f"0x{coordinator.client.function:02X}",
        "missing_parameters": sorted(coordinator.reader.missing),
        "unavailable_reasons": coordinator.reasons,
        "registers_by_pnu": registers,
        # 0.2.0: the owner's copies, our last values and the log of writes.
        "writes": coordinator.ledger.data,
    }
