"""The controller's temperatures, targets, setpoints, curve, modes and the
heat meter - read only."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EclConfigEntry, ecl
from .entity import EclDescription, EclEntity


@dataclass(frozen=True, kw_only=True)
class EclSensorDescription(EclDescription, SensorEntityDescription):
    """A sensor of the controller."""


def _temperature(
    key: str,
    pnu: int,
    *,
    enabled: bool = True,
    measured: bool = True,
    decode: Callable[[int | None], ecl.Value] = ecl.temperature,
) -> EclSensorDescription:
    return EclSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT if measured else None,
        suggested_display_precision=1,
        entity_registry_enabled_default=enabled,
        value=lambda data, pnu=pnu, decode=decode: decode(data.get(pnu)),
    )


def _setting(
    key: str, pnu: int, decode: Callable[[int | None], ecl.Value], *, diagnostic: bool = False
) -> EclSensorDescription:
    return EclSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,
        value=lambda data, pnu=pnu: decode(data.get(pnu)),
    )


def _mode(key: str, pnu: int) -> EclSensorDescription:
    return EclSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENUM,
        options=list(ecl.MODES),
        value=lambda data, pnu=pnu: ecl.mode(data.get(pnu)),
    )


def _status(key: str, pnu: int, mode_pnu: int) -> EclSensorDescription:
    return EclSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENUM,
        options=list(ecl.STATUSES),
        value=lambda data, pnu=pnu, mode_pnu=mode_pnu: ecl.status(
            data.get(pnu), data.get(mode_pnu)
        ),
    )


def descriptions(
    roles: dict[int, str], meter: bool, complete: bool = False
) -> list[EclSensorDescription]:
    """Every sensor of this controller (its application's input roles). With
    ``complete`` (0.1.1, A237.1) no entity for an input the application does
    not use; otherwise such an input is offered disabled, a raw 0 unavailable."""

    out = [
        _temperature(roles[n], ecl.RAW_SENSOR_PNU + n)
        if n in roles
        else _temperature(
            f"input_s{n}", ecl.RAW_SENSOR_PNU + n, enabled=False, decode=ecl.free_input
        )
        for n in range(1, 11)
        if n in roles or not complete
    ]
    out += [
        # p. 59: the references of circuit 1 (R2, R3, R5) and circuit 2 (R6).
        _temperature("room_target", 11252),
        _temperature("flow_target", 11253),
        _temperature("return_target", 11255),
        _temperature("dhw_target", 12256),
        _setting("room_comfort_setpoint", 11180, ecl.setpoint),
        _setting("room_saving_setpoint", 11181, ecl.setpoint),
        _setting("dhw_comfort_setpoint", 12190, ecl.setpoint),
        _setting("dhw_saving_setpoint", 12191, ecl.setpoint),
        *(_setting(key, pnu, ecl.curve_point) for key, pnu, _outdoor in ecl.CURVE_POINTS),
        _setting("flow_min", 11177, ecl.plain, diagnostic=True),
        _setting("flow_max", 11178, ecl.plain, diagnostic=True),
        EclSensorDescription(
            key="curve_slope",
            translation_key="curve_slope",
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=1,
            value=lambda data: ecl.plain(data.get(11175), 0.1),
        ),
        _mode("heating_mode", 4201),
        _status("heating_status", 4211, 4201),
        _mode("dhw_mode", 4202),
        _status("dhw_status", 4212, 4202),
    ]
    if meter:
        out += [
            _temperature("meter_flow_temperature", ecl.METER_FLOW_T),
            _temperature("meter_return_temperature", ecl.METER_RETURN_T),
            EclSensorDescription(
                key="meter_power",
                translation_key="meter_power",
                device_class=SensorDeviceClass.POWER,
                native_unit_of_measurement=UnitOfPower.KILO_WATT,
                state_class=SensorStateClass.MEASUREMENT,
                value=lambda data: ecl.meter_uint32(
                    data.get(ecl.METER_POWER),
                    data.get(ecl.METER_POWER + 1),
                    0.1,
                    data.get(ecl.METER_TYPE),
                ),
            ),
            EclSensorDescription(
                key="meter_energy",
                translation_key="meter_energy",
                device_class=SensorDeviceClass.ENERGY,
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                state_class=SensorStateClass.TOTAL_INCREASING,
                value=lambda data: ecl.meter_uint32(
                    data.get(ecl.METER_ENERGY),
                    data.get(ecl.METER_ENERGY + 1),
                    0.1,
                    data.get(ecl.METER_TYPE),
                ),
            ),
        ]
    return out


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EclConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    application = coordinator.identity.application
    roles = dict(application.roles) if application else {}
    async_add_entities(
        EclSensor(coordinator, description)
        for description in descriptions(
            roles, coordinator.meter, bool(application and application.inputs_complete)
        )
    )


class EclSensor(EclEntity, SensorEntity):
    """A sensor of the controller."""

    @property
    def native_value(self) -> float | int | str | None:
        value = self._reading().value
        return None if isinstance(value, bool) else value

