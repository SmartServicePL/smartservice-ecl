# ruff: noqa: E501
"""Translations, the manifest and the stable entity keys (no Home Assistant)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.pure import COMPONENT, load

ecl = load("ecl")
# The names' dash (U+2013), as in the translations.
DASH = chr(0x2013)

# The stable keys MIGIELS proposes the entities by (PLAN_INTEGRACJA_ECL.md 5a).
STABLE_SENSORS = {
    "outdoor_temperature",
    "flow_temperature",
    "primary_return_temperature",
    "dhw_tank_temperature",
    "room_temperature",
    "dhw_tank_bottom_temperature",
    *(f"input_s{n}" for n in (2, 4, 7, 8, 9, 10)),
    "room_target",
    "flow_target",
    "return_target",
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


def test_the_names_follow_danfoss_with_the_input() -> None:
    """0.1.1 (GŁÓWNY 31.10): the names of ECL Portal (Graph -> Configuration):
    en as Danfoss with the input, pl "obieg 1" / "obieg 2 (c.w.u.)"; the keys
    (and so unique_id and entity_id) never change."""

    en = read(COMPONENT / "strings.json")["entity"]["sensor"]
    pl = read(COMPONENT / "translations" / "pl.json")["entity"]["sensor"]
    for n, key in ecl.APPLICATIONS[("A", 237, 1)].roles.items():
        assert f"S{n})" in en[key]["name"] and f"S{n})" in pl[key]["name"], key
    assert en["flow_temperature"]["name"] == "Flow temp. (HC1, S3)"
    assert en["primary_return_temperature"]["name"] == "Return temp. (HC1, S5)"
    assert en["dhw_tank_temperature"]["name"] == "Upper temp. (DHW2, S6)"
    assert en["dhw_tank_bottom_temperature"]["name"] == "Lower temp. (DHW2, S8)"
    assert en["flow_target"]["name"] == "Flow temp. ref. (HC1)"
    assert en["dhw_mode"]["name"] == "Mode (HC2)"
    assert pl["flow_temperature"]["name"] == f"Temperatura zasilania {DASH} obieg 1 (S3)"
    assert pl["primary_return_temperature"]["name"] == f"Temperatura powrotu {DASH} obieg 1 (S5)"
    assert pl["dhw_mode"]["name"] == f"Tryb {DASH} obieg 2 (c.w.u.)"
    for key in ("dhw_tank_temperature", "dhw_tank_bottom_temperature", "dhw_target", "dhw_comfort_setpoint", "dhw_saving_setpoint", "dhw_status"):
        assert "obieg 2 (c.w.u." in pl[key]["name"], key
    # The outputs stay neutral until their pumps are confirmed.
    binary = read(COMPONENT / "translations" / "pl.json")["entity"]["binary_sensor"]
    assert binary["relay_1"]["name"] == "Przekaźnik 1" and binary["triac_1"]["name"] == "Triak 1"


def test_the_manifest_needs_nothing_to_install() -> None:
    manifest = read(COMPONENT / "manifest.json")
    assert manifest["domain"] == "smartservice_ecl"
    assert manifest["requirements"] == []
    assert manifest["iot_class"] == "local_polling"
    assert manifest["config_flow"] is True
    hacs = read(COMPONENT.parents[1] / "hacs.json")
    assert hacs["name"] == "Smart Service ECL"
