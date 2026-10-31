"""Smart Service ECL - reads a Danfoss ECL Comfort 296/310 heat substation
controller over Modbus/TCP. Read only: the client has no write function."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from . import ecl
from .const import CONF_UNIT
from .coordinator import EclCoordinator
from .modbus import EclConnectionError, EclModbusClient, EclModbusError
from .reader import EclReader

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

type EclConfigEntry = ConfigEntry[EclCoordinator]


async def read_identity(client: EclModbusClient) -> ecl.Identity:
    """The controller's application key, versions and serial number."""

    # 0.1.2: the code number (PNU 19) too - optional (a controller without
    # it keeps working, its model is then "ECL Comfort").
    registers = await EclReader(client).read((*ecl.IDENTITY_PNUS, ecl.PNU_SALES_NUMBER))
    missing = [pnu for pnu in ecl.IDENTITY_PNUS if pnu not in registers]
    if missing:
        raise EclModbusError(0x02)
    return ecl.identity_from(registers)


async def async_setup_entry(hass: HomeAssistant, entry: EclConfigEntry) -> bool:
    client = EclModbusClient(
        entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data[CONF_UNIT]
    )
    try:
        identity = await read_identity(client)
    except (EclConnectionError, EclModbusError) as err:
        await client.close()
        raise ConfigEntryNotReady(str(err)) from err
    # 0.1.2: the old default title becomes "ECL <model> -
    # <key>"; a title changed by hand stays as the user wrote it.
    if entry.title == ecl.old_entry_title(identity) and entry.title != ecl.entry_title(identity):
        hass.config_entries.async_update_entry(entry, title=ecl.entry_title(identity))
    coordinator = EclCoordinator(hass, entry, client, identity)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await client.close()
        raise
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EclConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.close()
    return unloaded
