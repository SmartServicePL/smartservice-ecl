"""The ECL map and the block reader (standard library only - runs without
Home Assistant)."""

from __future__ import annotations

import asyncio

import pytest

from tests.fake_ecl import FakeEcl
from tests.pure import load

ecl = load("ecl")
modbus = load("modbus")
reader_module = load("reader")


def test_temperatures_disconnected_and_negative() -> None:
    assert ecl.temperature(2144) == ecl.Value(21.44)  # Danfoss 7.5: S2 21.44 °C
    assert ecl.temperature(0xFF38) == ecl.Value(-2.0)
    off = ecl.temperature(19200)
    assert off.value is None and "192 °C" in str(off.reason)
    assert ecl.temperature(0x7FFF).value is None  # 327.67 °C - out of range
    assert ecl.temperature(None) == ecl.MISSING
    assert ecl.setpoint(200) == ecl.Value(20.0)  # Danfoss 7.5: comfort 20.0 °C
    assert ecl.curve_point(75) == ecl.Value(75.0)
    assert ecl.curve_point(192).value is None
    assert ecl.curve_point(5).value is None


def test_modes_statuses_and_flags() -> None:
    assert ecl.mode(0) == ecl.Value("manual")
    assert ecl.mode(1) == ecl.Value("scheduled")
    assert ecl.mode(9).value is None
    assert ecl.status(2, 1) == ecl.Value("comfort")
    # p. 14: the status reads 0 when the mode is above 3 - no status then.
    assert ecl.status(0, 4).value is None
    assert ecl.manual(0) == ecl.Value(True) and ecl.manual(1) == ecl.Value(False)
    assert ecl.return_limit(0b10) == ecl.Value(True)
    assert ecl.return_limit(0b1100) == ecl.Value(False)  # room limit only
    value, numbers = ecl.alarms(0b10, 0b101)
    assert value == ecl.Value(True) and numbers == [1, 3, 18]
    assert ecl.alarms(0, 0) == (ecl.Value(False), [])
    assert ecl.output(1) == ecl.Value(True) and ecl.output(0) == ecl.Value(False)


def test_the_identity_and_the_supported_keys() -> None:
    registers = {35: 257, 36: 0x00A7, 37: 0xFEE3, 2060: 65, 2061: 237, 2062: 1, 2063: 0x0102}
    identity = ecl.identity_from(registers)
    assert identity.key == "A237.1" and identity.version == "1.02" and identity.software == "1.01"
    assert identity.serial == 11009763
    assert identity.application is not None and identity.application.roles[3] == "flow_temperature"
    other = ecl.identity_from({**registers, 2061: 266})
    assert other.key == "A266.1" and other.application is None


def test_the_meter_only_with_type_0() -> None:
    assert ecl.meter_present(255) is False and ecl.meter_present(1) is True
    assert ecl.meter_uint32(0, 1234, 0.1, 0) == ecl.Value(123.4)
    assert ecl.meter_uint32(1, 0, 0.1, 0) == ecl.Value(6553.6)
    assert ecl.meter_uint32(0, 1234, 0.1, 1).value is None


def test_blocks() -> None:
    assert reader_module.blocks([3, 1, 2, 10, 11, 20]) == [(1, 3), (10, 2), (20, 1)]
    assert reader_module.blocks(range(1, 300)) == [(1, 123), (124, 123), (247, 53)]


def test_a_block_with_a_missing_parameter_falls_back_and_remembers() -> None:
    async def test() -> None:
        # PNU 4220 (register 4219) missing - an older software than 1.32.
        fake = await FakeEcl(registers={4210: 2, 4211: 0, 4219: 1, 4200: 1}, missing={4219}).start()
        client = modbus.EclModbusClient("127.0.0.1", fake.port, 1, timeout=0.5)
        reader = reader_module.EclReader(client)
        values = await reader.read([4201, 4211, 4212, 4220])
        assert values == {4201: 1, 4211: 2, 4212: 0}
        assert reader.missing == {4220}
        before = len(fake.requests)
        values = await reader.read([4201, 4211, 4212, 4220])
        assert values == {4201: 1, 4211: 2, 4212: 0}
        # Not asked again: 4201 alone, 4211-4212 as one block.
        assert len(fake.requests) - before == 2
        await client.close()
        await fake.stop()

    asyncio.run(test())


def test_a_connection_error_is_raised() -> None:
    async def refuse(_host: str, _port: int) -> object:
        raise ConnectionRefusedError

    async def test() -> None:
        reader = reader_module.EclReader(modbus.EclModbusClient("ecl", connector=refuse))
        with pytest.raises(modbus.EclConnectionError):
            await reader.read([10201])

    asyncio.run(test())


def test_the_lists_hold_every_read_parameter_once() -> None:
    fast = ecl.fast_pnus(meter=True)
    slow = ecl.slow_pnus()
    assert len(fast) == len(set(fast)) and len(slow) == len(set(slow))
    assert not set(fast) & set(slow)
    assert {10201, 10210, 11253, 12256, 4220, 1024, 1025, 4011, 6015} <= set(fast)
    assert {11400, 11405, 12190, 6000, 6001} <= set(slow)
    assert 6010 not in ecl.fast_pnus(meter=False)
