# ruff: noqa: E501
"""Translations, the manifest and the stable entity keys (no Home Assistant)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.pure import COMPONENT, load

ecl = load("ecl")

# The stable keys MIGIELS proposes the entities by (PLAN_INTEGRACJA_ECL.md 5a).
STABLE_SENSORS = {
    "outdoor_temperature",
    "flow_temperature",
    "return_temperature",
    "dhw_tank_temperature",
    *(f"input_s{n}" for n in (2, 4, 7, 8, 9, 10)),
    "flow_target",
    "dhw_target",
    "room_comfort_setpoint",
    "room_saving_setpoint",
    "dhw_comfort_setpoint",
    "dhw_saving_setpoint",
    "curve_m30",
    "curve_m15",
    "curve_m5",
    "curve_0",
    "curve_p5",
    "curve_p15",
    "flow_min",
    "flow_max",
    "curve_slope",
    "heating_mode",
    "heating_status",
    "dhw_mode",
    "dhw_status",
    "meter_flow_temperature",
    "meter_return_temperature",
    "meter_power",
    "meter_energy",
}
STABLE_BINARY = {
    "return_limit_active",
    "manual_mode",
    "alarm",
    "sensor_error",
    *(f"relay_{n}" for n in range(1, 7)),
    *(f"triac_{n}" for n in range(1, 7)),
}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def keys(data: dict, prefix: str = "") -> set[str]:
    out = set()
    for key, value in data.items():
        out.add(prefix + key)
        if isinstance(value, dict):
            out |= keys(value, f"{prefix}{key}.")
    return out


def test_english_is_the_strings_and_polish_has_every_key() -> None:
    strings = read(COMPONENT / "strings.json")
    assert read(COMPONENT / "translations" / "en.json") == strings
    assert keys(read(COMPONENT / "translations" / "pl.json")) == keys(strings)


def test_every_stable_key_has_a_name_and_the_roles_are_among_them() -> None:
    strings = read(COMPONENT / "strings.json")
    assert set(strings["entity"]["sensor"]) == STABLE_SENSORS
    assert set(strings["entity"]["binary_sensor"]) == STABLE_BINARY
    for application in ecl.APPLICATIONS.values():
        assert set(application.roles.values()) <= STABLE_SENSORS
    assert set(strings["entity"]["sensor"]["heating_mode"]["state"]) == set(ecl.MODES)
    assert set(strings["entity"]["sensor"]["heating_status"]["state"]) == set(ecl.STATUSES)
    pl = read(COMPONENT / "translations" / "pl.json")
    assert pl["config"]["error"]["unsupported"] == "Klucz aplikacji {key} nie jest jeszcze obsługiwany."


def test_the_manifest_needs_nothing_to_install() -> None:
    manifest = read(COMPONENT / "manifest.json")
    assert manifest["domain"] == "smartservice_ecl"
    assert manifest["requirements"] == []
    assert manifest["iot_class"] == "local_polling"
    assert manifest["config_flow"] is True
    hacs = read(COMPONENT.parents[1] / "hacs.json")
    assert hacs["name"] == "Smart Service ECL"
