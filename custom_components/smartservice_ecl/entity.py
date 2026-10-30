"""The base of every Smart Service ECL entity: one device per controller,
unique id "<serial number>_<key>" (stable keys - MIGIELS proposes the
entities by them), unavailable with the reason logged once."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ecl
from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import EclCoordinator, EclData


@dataclass(frozen=True, kw_only=True)
class EclDescription(EntityDescription):
    """``value``: the decoded reading from the registers."""

    value: Callable[[EclData], ecl.Value]


class EclEntity(CoordinatorEntity[EclCoordinator]):
    """A read-only reading of the controller."""

    _attr_has_entity_name = True
    entity_description: EclDescription

    def __init__(self, coordinator: EclCoordinator, description: EclDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        identity = coordinator.identity
        self._attr_unique_id = f"{identity.serial}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(identity.serial))},
            manufacturer=MANUFACTURER,
            model=f"{MODEL} ({identity.key})",
            sw_version=identity.software,
            hw_version=f"{identity.key} v{identity.version}",
            serial_number=str(identity.serial),
            name=f"Regulator ECL {identity.key}",
        )

    def _reading(self) -> ecl.Value:
        reading = self.entity_description.value(self.coordinator.data)
        self.coordinator.note_reason(self.entity_description.key, reading.reason)
        return reading

    @property
    def available(self) -> bool:
        return super().available and self._reading().value is not None
