"""Adding a Danfoss ECL: its address, a test read and the application key.

Only supported application keys (registers 2060-2063) are added; another key
stops with its name ("Klucz aplikacji A266.1 nie jest jeszcze obsługiwany") -
there is no "read everything" mode. The serial number (PNU 36-37) is the
entry's unique id, so a new IP address is a reconfiguration, not a new
controller.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from . import ecl, read_identity
from .const import CONF_UNIT, DEFAULT_PORT, DEFAULT_UNIT, DOMAIN
from .modbus import EclConnectionError, EclModbusClient, EclModbusError


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(CONF_UNIT, default=defaults.get(CONF_UNIT, DEFAULT_UNIT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=254)
            ),
        }
    )


async def _probe(data: dict[str, Any]) -> tuple[ecl.Identity | None, str | None]:
    """The identity of the controller, or the form's error key."""

    client = EclModbusClient(data[CONF_HOST].strip(), data[CONF_PORT], data[CONF_UNIT])
    try:
        return await read_identity(client), None
    except EclConnectionError:
        return None, "cannot_connect"
    except EclModbusError:
        return None, "not_ecl"
    finally:
        await client.close()


class EclConfigFlow(ConfigFlow, domain=DOMAIN):
    """Smart Service ECL."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"key": ""}
        if user_input is not None:
            identity, error = await _probe(user_input)
            if identity is not None and identity.application is None:
                error = "unsupported"
                placeholders["key"] = identity.key
            if error is None and identity is not None:
                await self.async_set_unique_id(str(identity.serial))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"ECL {identity.key}",
                    data={**user_input, CONF_HOST: user_input[CONF_HOST].strip()},
                )
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"key": ""}
        if user_input is not None:
            identity, error = await _probe(user_input)
            if identity is not None and identity.application is None:
                error = "unsupported"
                placeholders["key"] = identity.key
            if error is None and identity is not None:
                await self.async_set_unique_id(str(identity.serial))
                self._abort_if_unique_id_mismatch(reason="another_controller")
                return self.async_update_reload_and_abort(
                    entry, data_updates={**user_input, CONF_HOST: user_input[CONF_HOST].strip()}
                )
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or dict(entry.data)),
            errors=errors,
            description_placeholders=placeholders,
        )
