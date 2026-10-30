# ruff: noqa: E501
"""Smart Service ECL in Home Assistant against the fake ECL (CI only)."""

from __future__ import annotations

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from tests.ecl_registers import a237_registers
from tests.fake_ecl import FakeEcl

from custom_components.smartservice_ecl.const import CONF_UNIT, DOMAIN

SERIAL = "11009763"


@pytest.fixture
async def fake() -> FakeEcl:
    server = await FakeEcl(registers=a237_registers()).start()
    yield server
    await server.stop()


async def add(hass: HomeAssistant, fake: FakeEcl) -> config_entries.ConfigFlowResult:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: " 127.0.0.1 ", CONF_PORT: fake.port, CONF_UNIT: 1}
    )
    await hass.async_block_till_done()
    return result


def entity(hass: HomeAssistant, domain: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{SERIAL}_{key}")
    assert entity_id is not None, key
    return entity_id


async def test_add_a237_and_read_only(hass: HomeAssistant, fake: FakeEcl) -> None:
    result = await add(hass, fake)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "ECL A237.1"
    assert result["data"] == {CONF_HOST: "127.0.0.1", CONF_PORT: fake.port, CONF_UNIT: 1}
    assert result["result"].unique_id == SERIAL

    def state(domain: str, key: str) -> str:
        return hass.states.get(entity(hass, domain, key)).state

    assert state("sensor", "outdoor_temperature") == "-3.5"
    assert state("sensor", "flow_temperature") == "52.3"
    assert state("sensor", "primary_return_temperature") == "38.1"
    assert state("sensor", "dhw_tank_temperature") == "54.2"
    assert state("sensor", "flow_target") == "52.0"
    assert state("sensor", "dhw_target") == "55.0"
    assert state("sensor", "room_comfort_setpoint") == "21.0"
    assert state("sensor", "dhw_comfort_setpoint") == "55.0"
    assert state("sensor", "curve_m30") == "75.0"
    assert state("sensor", "curve_p15") == "28.0"
    assert state("sensor", "heating_mode") == "scheduled"
    assert state("sensor", "heating_status") == "comfort"
    assert state("sensor", "dhw_mode") == "comfort"
    assert state("binary_sensor", "return_limit_active") == "on"
    assert state("binary_sensor", "manual_mode") == "off"
    assert state("binary_sensor", "alarm") == "off"
    # A237.1: S2 the room, S8 the tank bottom - both enabled (here no sensor:
    # 192.00 °C, unavailable); S4, S7 without a role are disabled by default.
    registry = er.async_get(hass)
    assert registry.async_get(entity(hass, "sensor", "room_temperature")).disabled_by is None
    assert hass.states.get(entity(hass, "sensor", "dhw_tank_bottom_temperature")).state == STATE_UNAVAILABLE
    assert registry.async_get(entity(hass, "sensor", "input_s4")).disabled_by is not None
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_input_s2") is None
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_meter_power") is None
    # Read only: every request was a read (0x04 or 0x03).
    assert {function for _t, _u, function, _a in fake.requests} <= {0x03, 0x04}


async def test_a_disconnected_sensor_is_unavailable(hass: HomeAssistant, fake: FakeEcl) -> None:
    fake.registers[10206 - 1] = 19200  # S6 (PNU 10206) now reads 192.00 °C
    await add(hass, fake)
    assert hass.states.get(entity(hass, "sensor", "dhw_tank_temperature")).state == STATE_UNAVAILABLE
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    assert "192 °C" in coordinator.reasons["dhw_tank_temperature"]


async def test_another_key_is_not_supported(hass: HomeAssistant) -> None:
    server = await FakeEcl(registers=a237_registers(application=266)).start()
    try:
        result = await add(hass, server)
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "unsupported"}
        assert result["description_placeholders"]["key"] == "A266.1"
    finally:
        await server.stop()


async def test_no_controller_and_a_second_add(hass: HomeAssistant, fake: FakeEcl) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: 1, CONF_UNIT: 1}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    await add(hass, fake)
    again = await add(hass, fake)
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "already_configured"


async def test_the_heat_meter(hass: HomeAssistant) -> None:
    server = await FakeEcl(registers=a237_registers(meter=True)).start()
    try:
        await add(hass, server)
        assert hass.states.get(entity(hass, "sensor", "meter_power")).state == "12.3"
        assert hass.states.get(entity(hass, "sensor", "meter_energy")).state == "7456.5"
        assert hass.states.get(entity(hass, "sensor", "meter_flow_temperature")).state == "70.1"
    finally:
        await server.stop()


async def test_reconfigure_keeps_the_controller(hass: HomeAssistant, fake: FakeEcl) -> None:
    await add(hass, fake)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: fake.port, CONF_UNIT: 254}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    # The service address 254 (one controller on the connection).
    assert entry.data[CONF_UNIT] == 254
