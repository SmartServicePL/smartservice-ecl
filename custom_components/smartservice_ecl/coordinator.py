"""Reads the controller every 30 s (settings once an hour); 0.2.0: writes a
setting of the list in write.py when the service asks - through the same
connection (the ECL accepts practically one client)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import ecl, write
from .const import DOMAIN, SCAN_INTERVAL, SLOW_INTERVAL
from .modbus import EclConnectionError, EclModbusClient, EclModbusError
from .reader import EclReader

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1
# The control reading after a write (Danfoss: a real read, 2-5 s later).
CHECK_DELAY = 3.0


def storage_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}.writes"


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
        self.store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self.ledger = write.Ledger()
        self._write_lock = asyncio.Lock()

    async def async_load_ledger(self) -> None:
        self.ledger = write.Ledger(await self.store.async_load())

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

    # 0.2.0: the writes (services zapisz_parametr / przywroc_parametr).

    async def async_write(self, pnu: int, value: float) -> dict[str, Any]:
        """Write ``value`` to ``pnu`` after the list, the limits, the fresh
        values and the day's count; then the control reading."""

        async with self._write_lock:
            try:
                raw = write.to_raw(pnu, value)
                self._check_application()
                current = await self._read_context(pnu)
                before = current[pnu]
                write.check_against(pnu, raw, current)
                self.ledger.check_owner(pnu, raw, before)
                if raw == before:
                    return self._result(pnu, before, before, written=False)
                self.ledger.allow_write(pnu, raw, self._day())
            except write.WriteRefused as err:
                await self._refused(pnu, "write", err.reason, value=value)
            read_back = await self._write_and_check(pnu, raw, before, "write")
            ok = read_back == raw
            self.ledger.record_write(pnu, raw, before, ok, self._day())
            self.ledger.note(
                self._now(), pnu, "write", before=before, value=raw, read=read_back, ok=ok
            )
            await self._save()
            _LOGGER.info(
                "Zapis %s: %s -> %s, odczyt kontrolny %s",
                pnu,
                write.text(pnu, before),
                write.text(pnu, raw),
                write.text(pnu, read_back),
            )
            return self._result(pnu, before, read_back, written=True, target=raw)

    async def async_restore(self, pnu: int) -> dict[str, Any]:
        """Write back the owner's value kept before our first write."""

        async with self._write_lock:
            try:
                self._check_application()
                current = (await self._read_context(pnu))[pnu]
                target = self.ledger.restore_target(pnu, current)
            except write.WriteRefused as err:
                await self._refused(pnu, "restore", err.reason)
            if target is None:
                await self._save()
                return self._result(pnu, current, current, written=False)
            read_back = await self._write_and_check(pnu, target, current, "restore")
            ok = read_back == target
            self.ledger.record_restore(pnu, ok, self._day())
            self.ledger.note(
                self._now(), pnu, "restore", before=current, value=target, read=read_back, ok=ok
            )
            await self._save()
            _LOGGER.info(
                "Przywrócono %s: %s -> %s, odczyt kontrolny %s",
                pnu,
                write.text(pnu, current),
                write.text(pnu, target),
                write.text(pnu, read_back),
            )
            return self._result(pnu, current, read_back, written=True, target=target)

    def _check_application(self) -> None:
        if self.identity.key != write.APPLICATION_KEY:
            raise write.WriteRefused(
                f"Zapis tylko dla aplikacji {write.APPLICATION_KEY} "
                f"(ten regulator: {self.identity.key})."
            )

    async def _read_context(self, pnu: int) -> dict[int, int]:
        try:
            current = await self.reader.read({*write.CONTEXT_PNUS, pnu})
        except EclConnectionError as err:
            raise HomeAssistantError(str(err)) from err
        except EclModbusError as err:
            raise HomeAssistantError(err.reason) from err
        if current.get(write.PNU_MODE) == 0:
            raise write.WriteRefused("Obieg 1 jest w trybie ręcznym — zapis wstrzymany.")
        if pnu not in current:
            raise write.WriteRefused(f"Regulator nie ma parametru {pnu}.")
        return current

    async def _write_and_check(self, pnu: int, raw: int, before: int, action: str) -> int:
        try:
            await self.client.write_pnu(pnu, raw)
        except EclModbusError as err:
            reason = write.WRITE_EXCEPTION_REASONS.get(err.code, err.reason)
            await self._refused(pnu, action, reason, value=raw)
        except EclConnectionError as err:
            # Unknown whether the controller took it: counted as a write whose
            # control reading did not match (a repeat or a restore stays open).
            await self._unsure(pnu, raw, before, action, str(err))
            raise HomeAssistantError(str(err)) from err
        await asyncio.sleep(CHECK_DELAY)
        try:
            read_back = (await self.client.read_pnu(pnu))[0]
        except (EclConnectionError, EclModbusError) as err:
            await self._unsure(pnu, raw, before, action, str(err))
            raise HomeAssistantError(
                f"Zapis wysłany, ale odczyt kontrolny się nie udał: {err}"
            ) from err
        self._slow[pnu] = read_back
        if self.data is not None:
            self.data.registers[pnu] = read_back
            self.async_update_listeners()
        return read_back

    async def _unsure(self, pnu: int, raw: int, before: int, action: str, error: str) -> None:
        if action == "write":
            self.ledger.record_write(pnu, raw, before, False, self._day())
        self.ledger.note(self._now(), pnu, action, before=before, value=raw, error=error)
        await self._save()

    async def _refused(self, pnu: int, action: str, reason: str, **details: Any) -> None:
        _LOGGER.warning("Odmowa zapisu %s: %s", pnu, reason)
        self.ledger.note(self._now(), pnu, f"{action}_refused", reason=reason, **details)
        await self._save()
        raise HomeAssistantError(reason)

    async def _save(self) -> None:
        await self.store.async_save(dict(self.ledger.data))

    @staticmethod
    def _result(
        pnu: int, before: int, read_back: int, *, written: bool, target: int | None = None
    ) -> dict[str, Any]:
        limit = write.WRITABLE[pnu]
        target = before if target is None else target
        return {
            "pnu": pnu,
            "nazwa": limit.name,
            "zapisano": written,
            "poprzednio": before / limit.scale,
            "wartosc": target / limit.scale,
            "odczyt": read_back / limit.scale,
            "zgodny": read_back == target,
        }

    @staticmethod
    def _day() -> str:
        return dt_util.now().date().isoformat()

    @staticmethod
    def _now() -> str:
        return dt_util.now().isoformat(timespec="seconds")

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.client.close()
