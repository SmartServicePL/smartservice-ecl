# ruff: noqa: E501
"""The read-only Modbus/TCP client against a fake ECL (standard library only -
runs without Home Assistant)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
import struct
from typing import Any

import pytest

from tests.fake_ecl import FakeEcl
from tests.pure import load

modbus = load("modbus")

# The fake ECL listens on 127.0.0.1 (conftest.fake_ecl_tcp).
pytestmark = pytest.mark.usefixtures("fake_ecl_tcp")


def run(test: Callable[[], Awaitable[Any]]) -> Any:
    return asyncio.run(test())


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def started(**kwargs: Any) -> tuple[FakeEcl, Any]:
    fake = await FakeEcl(**kwargs).start()
    client = modbus.EclModbusClient("127.0.0.1", fake.port, fake.unit, timeout=0.5)
    return fake, client


def test_the_frames_of_the_specification() -> None:
    """Modbus Application Protocol V1.1b3, 6.3: "read registers 108 to 110"
    is the PDU 03 006B 0003, the answer 03 06 022B 0000 0064; Danfoss 7.5:
    PNU 11180 is register 11179 (0x2BAB), 0x00C8 = 200 = 20.0 °C."""

    async def test() -> None:
        fake, client = await started(registers={0x6B: 0x022B, 0x6C: 0x0000, 0x6D: 0x0064, 0x2BAB: 0x00C8})
        fake.refused_functions = {0x04}
        assert await client.read_registers(0x6B, 3) == [555, 0, 100]
        assert client.function == 0x03
        assert await client.read_pnu(11180) == [200]
        # The PDUs sent: function 03, the address and the count as in the specification.
        assert [(function, address) for _t, _u, function, address in fake.requests][-1] == (0x03, 0x2BAB)
        await client.close()
        await fake.stop()

    run(test)


def test_the_mbap_header_and_the_transaction_id() -> None:
    sent: list[bytes] = []

    class Writer:
        def write(self, data: bytes) -> None:
            sent.append(data)

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def test() -> None:
        reader = asyncio.StreamReader()
        for transaction in (1, 2):
            reader.feed_data(struct.pack(">HHHB", transaction, 0, 5, 1) + bytes([0x04, 2, 0x08, 0x60]))

        async def connector(_host: str, _port: int) -> tuple[Any, Any]:
            return reader, Writer()

        client = modbus.EclModbusClient("ecl", 502, 1, connector=connector)
        assert await client.read_pnu(10202) == [0x0860]  # S2: 21.44 °C (Danfoss 7.5)
        assert await client.read_pnu(10202) == [0x0860]
        # Transaction 1 then 2, protocol 0, length 6 (unit + 5 bytes of PDU), unit 1, register 10201.
        assert sent[0] == bytes.fromhex("0001 0000 0006 01 04 27D9 0001")
        assert sent[1][:2] == b"\x00\x02"

    run(test)


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        (0x01, "nie obsługuje tej funkcji"),
        (0x02, "nie ma tego parametru"),
        (0x03, "zła liczba rejestrów"),
        (0x04, "Błąd regulatora"),
        (0x06, "zajęty"),
        (0x0B, "Bramka nie dostała odpowiedzi"),
    ],
)
def test_the_exceptions_have_a_polish_reason(code: int, reason: str) -> None:
    async def test() -> None:
        fake, client = await started(registers={10: 1})
        fake.exception_code = code
        # "Illegal function" to 0x04 switches the client to 0x03 - refused too.
        fake.faults = ["exception"] * (2 if code == 0x01 else 1)
        with pytest.raises(modbus.EclModbusError) as raised:
            await client.read_registers(10, 1)
        assert raised.value.code == code
        assert reason in raised.value.reason
        # The connection stays: the next read works.
        assert await client.read_registers(10, 1) == [1]
        await client.close()
        await fake.stop()

    run(test)


def test_a_missing_parameter_is_exception_02_and_the_function_stays() -> None:
    async def test() -> None:
        fake, client = await started(registers={20: 7})
        fake.missing = {21}
        with pytest.raises(modbus.EclModbusError) as raised:
            await client.read_registers(20, 2)
        assert raised.value.code == 0x02
        assert client.function == 0x04
        assert await client.read_registers(20, 1) == [7]
        await client.close()
        await fake.stop()

    run(test)


@pytest.mark.parametrize(("fault", "message"), [("transaction", "inne zapytanie"), ("unit", "innego urządzenia"), ("bytes", "Liczba bajtów")])
def test_an_answer_that_cannot_be_trusted_is_refused(fault: str, message: str) -> None:
    async def test() -> None:
        fake, client = await started(registers={1: 5})
        fake.faults = [fault]
        with pytest.raises(modbus.EclConnectionError, match=message):
            await client.read_registers(1, 1)
        assert not client.connected
        await client.close()
        await fake.stop()

    run(test)


def test_a_dropped_idle_connection_reconnects_once() -> None:
    """The ECL closes an idle connection after about 75 s: the next read
    connects once more and gets its answer."""

    async def test() -> None:
        fake, client = await started(registers={3: 9})
        assert await client.read_registers(3, 1) == [9]
        fake.faults = ["drop"]
        assert await client.read_registers(3, 1) == [9]
        assert fake.connections == 2
        await client.close()
        await fake.stop()

    run(test)


def test_a_timeout_then_one_attempt_and_a_back_off_without_a_storm() -> None:
    async def test() -> None:
        fake = await FakeEcl(registers={3: 9}).start()
        clock = Clock()
        client = modbus.EclModbusClient("127.0.0.1", fake.port, 1, timeout=0.2, clock=clock)
        assert await client.read_registers(3, 1) == [9]
        # Silence on the open connection and on the one new connection.
        fake.faults = ["silence", "silence"]
        with pytest.raises(modbus.EclConnectionError, match="nie odpowiedział"):
            await client.read_registers(3, 1)
        assert fake.connections == 2
        # Within the back-off: no new connection at all.
        with pytest.raises(modbus.EclConnectionError, match="kolejna próba za 5 s"):
            await client.read_registers(3, 1)
        assert fake.connections == 2
        clock.now += 5.1
        assert await client.read_registers(3, 1) == [9]
        assert fake.connections == 3
        await client.close()
        await fake.stop()

    run(test)


def test_no_controller_back_off_doubles_up_to_five_minutes() -> None:
    attempts = 0

    async def refuse(_host: str, _port: int) -> Any:
        nonlocal attempts
        attempts += 1
        raise ConnectionRefusedError

    async def test() -> None:
        clock = Clock()
        client = modbus.EclModbusClient("ecl", 502, 1, connector=refuse, clock=clock)
        waits = []
        for _ in range(9):
            with pytest.raises(modbus.EclConnectionError):
                await client.read_registers(0, 1)
            waits.append(client._retry_at - clock.now)
            with pytest.raises(modbus.EclConnectionError, match="kolejna próba"):
                await client.read_registers(0, 1)
            clock.now = client._retry_at
        assert waits == [5, 10, 20, 40, 80, 160, 300, 300, 300]
        assert attempts == 9

    run(test)


def test_limits_and_decoding() -> None:
    client = modbus.EclModbusClient("ecl")
    for address, count in ((0, 0), (0, 124), (-1, 1), (65535, 2)):
        with pytest.raises(ValueError):
            run(lambda a=address, c=count: client.read_registers(a, c))
    with pytest.raises(ValueError):
        run(lambda: client.read_pnu(0))
    assert modbus.as_int16(0xFF38) == -200  # -2.00 °C at scale 100
    assert modbus.as_int16(0x0860) == 2144
    assert modbus.as_uint32(0x00A7, 0xFEE3) == 11009763  # Danfoss 6.11 example
    # 0.2.0: one write function - 0x06, one register (no 05, 0F, 10, 16, 17).
    text = Path(load("modbus").__file__ or "").read_text(encoding="utf-8")
    import re

    assert modbus.READ_FUNCTIONS == (0x04, 0x03)
    assert re.findall(r"^[A-Z_]+ = (0x[0-9A-F]{2})$", text, re.M) == ["0x03", "0x04", "0x06"]
    assert modbus.WRITE_SINGLE_REGISTER == 0x06
    assert "write_register" not in text and "write_multiple" not in text
    for value in (-1, 0x10000):
        with pytest.raises(ValueError):
            run(lambda v=value: client.write_pnu(11180, v))
    with pytest.raises(ValueError):
        run(lambda: client.write_pnu(0, 1))


def test_write_single_register() -> None:
    """Modbus Application Protocol 6.6: the request 06 0001 0003 is echoed;
    PNU 11180 is register 11179 (0x2BAB)."""

    async def test() -> None:
        fake, client = await started(registers={0x2BAB: 250})
        await client.write_pnu(11180, 210)
        assert fake.registers[0x2BAB] == 210
        assert fake.requests[-1][2:] == (0x06, 0x2BAB)
        assert await client.read_pnu(11180) == [210]
        # A value outside the controller's range: exception 03.
        fake.refused_writes = {0x2BAB: 0x03}
        with pytest.raises(modbus.EclModbusError) as err:
            await client.write_pnu(11180, 999)
        assert err.value.code == 0x03
        assert fake.registers[0x2BAB] == 210
        await client.close()
        await fake.stop()

    run(test)


def test_a_write_answer_that_does_not_echo_is_an_error() -> None:
    """An answer with another value is not a confirmation."""

    async def test() -> None:
        fake, client = await started(registers={0x2BAB: 250})
        original = fake._answer

        def wrong(function: int, address: int, count: int, fault: str | None) -> bytes:
            answer = original(function, address, count, fault)
            if function == 0x06:
                return answer[:-1] + bytes([answer[-1] ^ 1])
            return answer

        fake._answer = wrong
        with pytest.raises(modbus.EclConnectionError, match="nie potwierdził"):
            await client.write_pnu(11180, 210)
        assert not client.connected
        await client.close()
        await fake.stop()

    run(test)
