"""Reads the controller every 30 s (settings once an hour) - read only."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import ecl
from .const import DOMAIN, SCAN_INTERVAL, SLOW_INTERVAL
from .modbus import EclConnectionError, EclModbusClient, EclModbusError
from .reader import EclReader

_LOGGER = logging.getLogger(__name__)


@dataclass
class EclData:
    """The registers by PNU (a parameter the controller has not: absent)."""

    registers: dict[int, int] = field(default_factory=dict)

    def get(self, pnu: int) -> int | None:
        return self.registers.get(pnu)


class EclCoordinator(DataUpdateCoordinator[EclData]):
    """One connection, one reader, two cadences."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: EclModbusClient,
        identity: ecl.Identity,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.reader = EclReader(client)
        self.identity = identity
        self._slow: dict[int, int] = {}
        self._slow_at = None
        self._reasons: dict[str, str] = {}

    @property
    def meter(self) -> bool:
        return ecl.meter_present(self._slow.get(ecl.METER_ADDRESS))

    async def _async_update_data(self) -> EclData:
        now = dt_util.utcnow()
        try:
            if self._slow_at is None or now - self._slow_at >= SLOW_INTERVAL:
                self._slow = await self.reader.read(ecl.slow_pnus())
                self._slow_at = now
            fast = await self.reader.read(ecl.fast_pnus(self.meter))
        except EclConnectionError as err:
            raise UpdateFailed(str(err)) from err
        except EclModbusError as err:
            raise UpdateFailed(err.reason) from err
        return EclData({**self._slow, **fast})

    def note_reason(self, key: str, reason: str | None) -> None:
        """Why an entity is unavailable - logged once per change (an
        unavailable entity has no attributes in Home Assistant)."""

        if reason is None:
            self._reasons.pop(key, None)
            return
        if self._reasons.get(key) != reason:
            self._reasons[key] = reason
            _LOGGER.info("%s: %s", key, reason)

    @property
    def reasons(self) -> dict[str, str]:
        return dict(self._reasons)

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.client.close()
