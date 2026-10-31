# ruff: noqa: E501
"""Smart Service ECL in Home Assistant against the fake ECL (CI only)."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from tests.ecl_registers import a237_registers
from tests.fake_ecl import FakeEcl

from custom_components.smartservice_ecl.const import CONF_UNIT, DOMAIN

SERIAL = "11009763"


# The fake ECL listens on 127.0.0.1 (conftest.fake_ecl_tcp).
pytestmark = pytest.mark.usefixtures("fake_ecl_tcp")


@pytest.fixture
async def fake(fake_ecl_tcp: None) -> FakeEcl:
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


def the_device(hass: HomeAssistant) -> dr.DeviceEntry | None:
    """The controller's device of the one entry (device_registry.async_get_device
    is an error in tests since Home Assistant 2026.10: identifiers are no longer
    unique across entries)."""

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entries[0].entry_id)
    assert len(devices) <= 1
    if not devices:
        return None
    assert (DOMAIN, SERIAL) in devices[0].identifiers
    return devices[0]


def entity(hass: HomeAssistant, domain: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{SERIAL}_{key}")
    assert entity_id is not None, key
    return entity_id


async def test_add_a237_and_read_only(hass: HomeAssistant, fake: FakeEcl) -> None:
    result = await add(hass, fake)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # 0.1.2: "ECL <model> - <key>"; the device "Danfoss ECL310".
    assert result["title"] == "ECL 296/310 - A237.1"
    device = the_device(hass)
    assert device is not None
    assert (device.name, device.manufacturer, device.model) == ("Danfoss ECL310", "Danfoss", "ECL Comfort 296/310")
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
    # 192.00 °C, unavailable); 0.1.1: no entity for S4, S7, S9, S10 (unused).
    registry = er.async_get(hass)
    assert registry.async_get(entity(hass, "sensor", "room_temperature")).disabled_by is None
    assert hass.states.get(entity(hass, "sensor", "dhw_tank_bottom_temperature")).state == STATE_UNAVAILABLE
    for n in (2, 4, 7, 8, 9, 10):
        assert registry.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_input_s{n}") is None
    # 0.1.1: the references of circuit 1 (R2, R5).
    assert state("sensor", "room_target") == "21.0"
    assert state("sensor", "return_target") == "40.0"
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


async def test_a237_2_offers_its_other_inputs_and_a_0_is_no_reading(hass: HomeAssistant) -> None:
    """A237.2 (roles not confirmed): S2, S4, S7… stay offered, disabled; a raw
    0 on such an input (S7 of a controller in service) is unavailable."""

    registers = a237_registers(sub=2)
    registers[10207 - 1] = 0  # S7 reads a plain 0
    server = await FakeEcl(registers=registers).start()
    try:
        await add(hass, server)
        registry = er.async_get(hass)
        input_s7 = entity(hass, "sensor", "input_s7")
        assert registry.async_get(input_s7).disabled_by is not None
        assert registry.async_get(entity(hass, "sensor", "input_s4")).disabled_by is not None
        registry.async_update_entity(input_s7, disabled_by=None)
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get(input_s7).state == STATE_UNAVAILABLE
        # A role keeps its value (S1 -3.5 °C).
        assert hass.states.get(entity(hass, "sensor", "outdoor_temperature")).state == "-3.5"
    finally:
        await server.stop()


def old_entry(title: str, port: int) -> MockConfigEntry:
    """An entry as 0.1.0 / 0.1.1 created it (title "ECL A237.1")."""

    return MockConfigEntry(domain=DOMAIN, title=title, unique_id=SERIAL, data={CONF_HOST: "127.0.0.1", CONF_PORT: port, CONF_UNIT: 1})


async def test_the_update_renames_the_default_title_and_keeps_every_entity_id(hass: HomeAssistant, fake: FakeEcl) -> None:
    """0.1.2: the old default title becomes "ECL 296/310 - A237.1"; the
    entities of 0.1.1 keep their entity_id (the registry holds it by the
    unchanged unique_id), even though the device is now "Danfoss ECL310"."""

    entry = old_entry("ECL A237.1", fake.port)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    kept = {
        key: registry.async_get_or_create(domain, DOMAIN, f"{SERIAL}_{key}", suggested_object_id=object_id, config_entry=entry).entity_id
        for domain, key, object_id in (
            ("sensor", "outdoor_temperature", "regulator_ecl_a237_1_outdoor_temp_s1"),
            ("sensor", "flow_temperature", "regulator_ecl_a237_1_flow_temp_hc1_s3"),
            ("binary_sensor", "manual_mode", "regulator_ecl_a237_1_manual_mode_hc1"),
        )
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.title == "ECL 296/310 - A237.1"
    for key, entity_id in kept.items():
        assert entity(hass, entity_id.split(".")[0], key) == entity_id, key
        assert hass.states.get(entity_id) is not None, key
    assert hass.states.get(kept["outdoor_temperature"]).state == "-3.5"
    device = the_device(hass)
    assert device is not None and device.name == "Danfoss ECL310"


async def test_a_title_changed_by_hand_stays(hass: HomeAssistant, fake: FakeEcl) -> None:
    entry = old_entry("Mój węzeł", fake.port)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.title == "Mój węzeł"


async def test_without_the_code_number_no_model_is_guessed(hass: HomeAssistant) -> None:
    server = await FakeEcl(registers=a237_registers(code=None)).start()
    try:
        result = await add(hass, server)
        assert result["title"] == "ECL - A237.1"
        device = the_device(hass)
        assert device is not None and (device.name, device.model) == ("Danfoss ECL310", "ECL Comfort")
    finally:
        await server.stop()


async def test_reconfigure_keeps_the_controller(hass: HomeAssistant, fake: FakeEcl) -> None:
    await add(hass, fake)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    # A real ConfigEntry (added through the flow): reconfigure as Home Assistant
    # starts it (MockConfigEntry.start_reconfigure_flow does the same).
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: fake.port, CONF_UNIT: 254}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    # The service address 254 (one controller on the connection).
    assert entry.data[CONF_UNIT] == 254
