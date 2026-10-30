"""The controller's flags: return limit, manual mode, alarm, sensor error and
its outputs - read only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EclConfigEntry, ecl
from .entity import EclDescription, EclEntity


@dataclass(frozen=True, kw_only=True)
class EclBinaryDescription(EclDescription, BinarySensorEntityDescription):
    """A flag of the controller."""


def _output(key: str, pnu: int) -> EclBinaryDescription:
    return EclBinaryDescription(
        key=key,
        translation_key=key,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=lambda data, pnu=pnu: ecl.output(data.get(pnu)),
    )


DESCRIPTIONS: tuple[EclBinaryDescription, ...] = (
    EclBinaryDescription(
        key="return_limit_active",
        translation_key="return_limit_active",
        value=lambda data: ecl.return_limit(data.get(4220)),
    ),
    EclBinaryDescription(
        key="manual_mode",
        translation_key="manual_mode",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value=lambda data: ecl.manual(data.get(4201)),
    ),
    EclBinaryDescription(
        key="alarm",
        translation_key="alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value=lambda data: ecl.alarms(data.get(1024), data.get(1025))[0],
    ),
    EclBinaryDescription(
        key="sensor_error",
        translation_key="sensor_error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda data: ecl.any_bit(data.get(2054), data.get(2055)),
    ),
    *(_output(f"relay_{n}", 4005 + n) for n in range(1, 7)),
    *(_output(f"triac_{n}", 3999 + n) for n in range(1, 7)),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EclConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(EclBinarySensor(coordinator, item) for item in DESCRIPTIONS)


class EclBinarySensor(EclEntity, BinarySensorEntity):
    """A flag of the controller."""

    @property
    def is_on(self) -> bool | None:
        value = self._reading().value
        return value if isinstance(value, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "alarm":
            return None
        _value, numbers = ecl.alarms(
            self.coordinator.data.get(1024), self.coordinator.data.get(1025)
        )
        return {"alarm_numbers": numbers}
