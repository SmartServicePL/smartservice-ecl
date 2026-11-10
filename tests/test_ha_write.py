# ruff: noqa: E501
"""0.2.0: the services zapisz_parametr / przywroc_parametr in Home Assistant
against the fake ECL (CI only)."""

from __future__ import annotations

from typing import Any

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from tests.ecl_registers import a237_registers, reg
from tests.fake_ecl import FakeEcl
from tests.test_ha_integration import add, entity

from custom_components.smartservice_ecl import coordinator as coordinator_module
from custom_components.smartservice_ecl.const import DOMAIN

pytestmark = pytest.mark.usefixtures("fake_ecl_tcp")


@pytest.fixture(autouse=True)
def no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control reading without its 3 s."""

    monkeypatch.setattr(coordinator_module, "CHECK_DELAY", 0)


def registers(**kwargs: Any) -> dict[int, int]:
    """A237.1 version 4.00, room setpoints 25.0 / 25.0 °C (a controller in
    service before any change), the factory curve, maximum flow 90 °C."""

    values = a237_registers(**kwargs)
    values[reg(2063)] = 0x0400
    values[reg(11180)] = 250
    values[reg(11181)] = 250
    return values


@pytest.fixture
async def fake(fake_ecl_tcp: None) -> FakeEcl:
    server = await FakeEcl(registers=registers()).start()
    yield server
    await server.stop()


async def call(hass: HomeAssistant, service: str, **data: Any) -> dict[str, Any]:
    return await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=True)


def writes(fake: FakeEcl) -> list[int]:
    return [address for _t, _u, function, address in fake.requests if function == 0x06]


async def test_write_check_and_restore(hass: HomeAssistant, fake: FakeEcl, hass_storage: dict[str, Any]) -> None:
    await add(hass, fake)
    assert writes(fake) == []
    # 25.0 -> 21.0 °C: saving first (never above comfort), then comfort.
    result = await call(hass, "zapisz_parametr", pnu=11181, wartosc=19.0)
    assert result == {"pnu": 11181, "nazwa": "zadana pokojowa oszczędna", "zapisano": True, "poprzednio": 25.0, "wartosc": 19.0, "odczyt": 19.0, "zgodny": True}
    result = await call(hass, "zapisz_parametr", pnu=11180, wartosc=21.0)
    assert (result["poprzednio"], result["odczyt"], result["zgodny"]) == (25.0, 21.0, True)
    assert fake.registers[reg(11180)] == 210
    assert writes(fake) == [reg(11181), reg(11180)]
    # The entity shows the new value at once (not after the hourly read).
    assert hass.states.get(entity(hass, "sensor", "room_comfort_setpoint")).state == "21.0"
    # The record is stored: the owner's copy 25.0 °C.
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    stored = hass_storage[f"{DOMAIN}.{entry.entry_id}.writes"]["data"]
    assert stored["pnu"]["11180"]["original"] == 250
    assert stored["total"] == 2
    # Once a day per parameter.
    with pytest.raises(HomeAssistantError, match="już dziś"):
        await call(hass, "zapisz_parametr", pnu=11180, wartosc=20.5)
    assert len(writes(fake)) == 2
    # Restore: comfort first, then saving (saving never above comfort).
    result = await call(hass, "przywroc_parametr", pnu=11180)
    assert (result["wartosc"], result["odczyt"], result["zgodny"]) == (25.0, 25.0, True)
    result = await call(hass, "przywroc_parametr", pnu=11181)
    assert fake.registers[reg(11181)] == 250
    with pytest.raises(HomeAssistantError, match="nie zmieniała"):
        await call(hass, "przywroc_parametr", pnu=11180)


async def test_off_the_list_and_outside_the_limits_nothing_is_sent(hass: HomeAssistant, fake: FakeEcl) -> None:
    await add(hass, fake)
    for pnu, value, match in (
        (11175, 1.0, "nie jest na liście"),
        (4201, 2, "nie jest na liście"),
        (11177, 15, "nie jest na liście"),
        (11180, 40.5, "poza granicami"),
        (11400, 151, "poza granicami"),
        (11178, 9, "poza granicami"),
        (11180, 21.2, "wielokrotnością"),
        # Never above the owner's value (room 25.0 °C, maximum flow 90 °C).
        (11180, 25.5, "powyżej wartości właściciela"),
        (11178, 95, "powyżej wartości właściciela"),
        # The factory curve from the cold end crosses the warmer point.
        (11400, 40, "od najcieplejszego"),
        # Saving above comfort (25.0 °C now) is fine; comfort below saving not.
        (11180, 20.0, "najpierw obniż 11181"),
    ):
        with pytest.raises(HomeAssistantError, match=match):
            await call(hass, "zapisz_parametr", pnu=pnu, wartosc=value)
    assert writes(fake) == []
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    log = entry.runtime_data.ledger.data["log"]
    assert [item["action"] for item in log] == ["write_refused"] * 11


async def test_the_curve_from_the_warm_end(hass: HomeAssistant, fake: FakeEcl) -> None:
    await add(hass, fake)
    for pnu, value in zip((11405, 11404, 11403, 11402, 11401, 11400), (27, 33, 35, 36, 38, 40), strict=True):
        assert (await call(hass, "zapisz_parametr", pnu=pnu, wartosc=value))["zgodny"]
    assert [fake.registers[reg(pnu)] for pnu in range(11400, 11406)] == [40, 38, 36, 35, 33, 27]
    assert hass.states.get(entity(hass, "sensor", "curve_0")).state == "35.0"


async def test_down_from_the_factory_curve_in_steps(hass: HomeAssistant, fake: FakeEcl, freezer: Any) -> None:
    """75 °C at -30 °C: 70 one day, 65 the next, back to 75 allowed, 76 never."""

    freezer.move_to("2026-11-12 06:00:00+01:00")
    await add(hass, fake)
    assert (await call(hass, "zapisz_parametr", pnu=11400, wartosc=70))["zgodny"]
    freezer.move_to("2026-11-13 06:00:00+01:00")
    assert (await call(hass, "zapisz_parametr", pnu=11400, wartosc=65))["zgodny"]
    freezer.move_to("2026-11-14 06:00:00+01:00")
    with pytest.raises(HomeAssistantError, match=r"powyżej wartości właściciela \(75 °C\)"):
        await call(hass, "zapisz_parametr", pnu=11400, wartosc=76)
    assert (await call(hass, "zapisz_parametr", pnu=11400, wartosc=75))["zgodny"]
    assert fake.registers[reg(11400)] == 75


async def test_the_same_value_is_not_written(hass: HomeAssistant, fake: FakeEcl) -> None:
    await add(hass, fake)
    result = await call(hass, "zapisz_parametr", pnu=11403, wartosc=45)
    assert result["zapisano"] is False
    assert writes(fake) == []


async def test_a_control_reading_that_differs(hass: HomeAssistant, fake: FakeEcl) -> None:
    """The ECL answers but keeps its value: not agreed, one repeat allowed,
    then the restore puts the owner's value back."""

    await add(hass, fake)
    fake.ignored_writes = {reg(11405)}
    result = await call(hass, "zapisz_parametr", pnu=11405, wartosc=25)
    assert (result["zapisano"], result["odczyt"], result["zgodny"]) == (True, 28.0, False)
    result = await call(hass, "zapisz_parametr", pnu=11405, wartosc=25)
    assert result["zgodny"] is False
    with pytest.raises(HomeAssistantError, match="powtórzony"):
        await call(hass, "zapisz_parametr", pnu=11405, wartosc=25)
    assert len(writes(fake)) == 2
    # The controller shows yet another value: still the owner's copy back.
    fake.ignored_writes = set()
    fake.registers[reg(11405)] = 27
    result = await call(hass, "przywroc_parametr", pnu=11405)
    assert (result["wartosc"], result["odczyt"], result["zgodny"]) == (28.0, 28.0, True)


async def test_the_controller_refuses_the_value(hass: HomeAssistant, fake: FakeEcl) -> None:
    await add(hass, fake)
    fake.refused_writes = {reg(11404): 0x03}
    with pytest.raises(HomeAssistantError, match="wyjątek 03"):
        await call(hass, "zapisz_parametr", pnu=11404, wartosc=38)
    assert fake.registers[reg(11404)] == 40
    # Nothing was taken: no copy to restore, the day's write not used.
    fake.refused_writes = {}
    assert (await call(hass, "zapisz_parametr", pnu=11404, wartosc=38))["zgodny"]


async def test_a_change_by_hand_wins(hass: HomeAssistant, fake: FakeEcl) -> None:
    await add(hass, fake)
    await call(hass, "zapisz_parametr", pnu=11181, wartosc=19.0)
    fake.registers[reg(11181)] = 200  # set to 20.0 °C on the controller
    with pytest.raises(HomeAssistantError, match="zmieniono na regulatorze"):
        await call(hass, "przywroc_parametr", pnu=11181)
    assert fake.registers[reg(11181)] == 200
    assert writes(fake) == [reg(11181)]


async def test_manual_mode_and_another_application(hass: HomeAssistant, fake: FakeEcl) -> None:
    await add(hass, fake)
    fake.registers[reg(4201)] = 0
    with pytest.raises(HomeAssistantError, match="trybie ręcznym"):
        await call(hass, "zapisz_parametr", pnu=11181, wartosc=19.0)
    assert writes(fake) == []


async def test_a237_2_is_not_written(hass: HomeAssistant) -> None:
    server = await FakeEcl(registers=registers(sub=2)).start()
    try:
        await add(hass, server)
        with pytest.raises(HomeAssistantError, match=r"tylko dla aplikacji A237.1"):
            await call(hass, "zapisz_parametr", pnu=11181, wartosc=19.0)
        assert writes(server) == []
    finally:
        await server.stop()


async def test_the_record_survives_a_reload(hass: HomeAssistant, fake: FakeEcl) -> None:
    await add(hass, fake)
    await call(hass, "zapisz_parametr", pnu=11181, wartosc=19.0)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError, match="już dziś"):
        await call(hass, "zapisz_parametr", pnu=11181, wartosc=18.0)
    result = await call(hass, "przywroc_parametr", pnu=11181)
    assert result["odczyt"] == 25.0


async def test_no_controller(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError, match="Żaden regulator"):
        await call(hass, "zapisz_parametr", pnu=11180, wartosc=21.0)


async def test_diagnostics_hold_the_writes(hass: HomeAssistant, fake: FakeEcl) -> None:
    from custom_components.smartservice_ecl.diagnostics import async_get_config_entry_diagnostics

    await add(hass, fake)
    await call(hass, "zapisz_parametr", pnu=11181, wartosc=19.0)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["writes"]["pnu"]["11181"]["original"] == 250
    assert diagnostics["writes"]["log"][-1]["action"] == "write"


async def test_the_error_codes(hass: HomeAssistant, fake: FakeEcl) -> None:
    """0.2.1: every refusal carries its fixed code as translation_key, the
    reason as the message and as the placeholder."""

    await add(hass, fake)

    async def code(service: str, **data: Any) -> str:
        with pytest.raises(HomeAssistantError) as err:
            await call(hass, service, **data)
        assert err.value.translation_domain == DOMAIN
        assert err.value.translation_placeholders == {"reason": str(err.value)}
        return err.value.translation_key

    assert await code("zapisz_parametr", pnu=11175, wartosc=1.0) == "pnu_niedozwolony"
    assert await code("zapisz_parametr", pnu=11180, wartosc=40.5) == "poza_zakresem"
    assert await code("zapisz_parametr", pnu=11400, wartosc=40) == "poza_zakresem"
    assert await code("zapisz_parametr", pnu=11180, wartosc=25.5) == "powyzej_wlasciciela"
    assert await code("przywroc_parametr", pnu=11180) == "brak_kopii"
    fake.registers[reg(4201)] = 0
    assert await code("zapisz_parametr", pnu=11181, wartosc=19.0) == "tryb_reczny"
    fake.registers[reg(4201)] = 1
    await call(hass, "zapisz_parametr", pnu=11181, wartosc=19.0)
    assert await code("zapisz_parametr", pnu=11181, wartosc=18.0) == "limit_doby"
    fake.registers[reg(11181)] = 200
    assert await code("przywroc_parametr", pnu=11181) == "zmiana_reczna"
    # The controller refuses the value (exception 03) or fails (04).
    fake.refused_writes = {reg(11404): 0x03, reg(11403): 0x04}
    assert await code("zapisz_parametr", pnu=11404, wartosc=38) == "poza_zakresem"
    assert await code("zapisz_parametr", pnu=11403, wartosc=40) == "brak_polaczenia"
    fake.refused_writes = {}
    # The control reading fails: four reads before, the write, then the read.
    fake.exception_code = 0x04
    fake.faults = ["", "", "", "", "", "exception"]
    assert await code("zapisz_parametr", pnu=11405, wartosc=25) == "odczyt_niezgodny"
    assert fake.registers[reg(11405)] == 25


async def test_no_controller_has_a_code(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "zapisz_parametr", pnu=11180, wartosc=21.0)
    assert err.value.translation_key == "brak_polaczenia"
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "przywroc_parametr", pnu=11180, config_entry_id="nie-ma")
    assert err.value.translation_key == "brak_regulatora"
