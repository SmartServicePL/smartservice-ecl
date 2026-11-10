"""0.2.0: the services that write a setting of the list in write.py - the
only way the integration changes anything in the controller (no writable
entities)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import EclCoordinator

SERVICE_WRITE = "zapisz_parametr"
SERVICE_RESTORE = "przywroc_parametr"
ATTR_PNU = "pnu"
ATTR_VALUE = "wartosc"
ATTR_ENTRY = "config_entry_id"

WRITE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PNU): vol.Coerce(int),
        vol.Required(ATTR_VALUE): vol.Coerce(float),
        vol.Optional(ATTR_ENTRY): cv.string,
    }
)
RESTORE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PNU): vol.Coerce(int),
        vol.Optional(ATTR_ENTRY): cv.string,
    }
)


def _coordinator(hass: HomeAssistant, data: dict[str, Any]) -> EclCoordinator:
    """The controller of ``config_entry_id``, or the only one loaded."""

    loaded = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if ATTR_ENTRY in data:
        loaded = [entry for entry in loaded if entry.entry_id == data[ATTR_ENTRY]]
        if not loaded:
            raise ServiceValidationError("Nie ma działającego regulatora o tym config_entry_id.")
    if not loaded:
        raise ServiceValidationError("Żaden regulator ECL nie jest teraz połączony.")
    if len(loaded) > 1:
        raise ServiceValidationError("Jest kilka regulatorów — podaj config_entry_id.")
    return loaded[0].runtime_data


def async_setup_services(hass: HomeAssistant) -> None:
    async def write(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call.data)
        return await coordinator.async_write(call.data[ATTR_PNU], call.data[ATTR_VALUE])

    async def restore(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call.data)
        return await coordinator.async_restore(call.data[ATTR_PNU])

    hass.services.async_register(
        DOMAIN, SERVICE_WRITE, write, WRITE_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESTORE,
        restore,
        RESTORE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
