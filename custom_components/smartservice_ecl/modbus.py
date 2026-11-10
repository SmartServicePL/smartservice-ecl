"""A small Modbus/TCP client for the Danfoss ECL Comfort 296/310
(communication description VI.LG.V5.02).

Written from the Modbus specifications (Modbus Application Protocol V1.1b3,
Modbus Messaging on TCP/IP Implementation Guide V1.0b) and the Danfoss
document. It knows three function codes: 0x04 Read Input Registers, 0x03 Read
Holding Registers and (0.2.0) 0x06 Write Single Register - one register at a
time, used only by the service of write.py after its list and limits. No
other write function exists (no 05, 0F, 10, 16, 17).

* One TCP connection, one request at a time (a lock); the ECL closes an idle
  connection after about 75 s, a read every 30 s keeps it open.
* A register is the Danfoss parameter number minus one (PNU 11180 is
  register 11179); at most 123 registers per request (ADU <= 240 bytes).
* Every answer is checked: the transaction id, the protocol id, the length,
  the unit id, the function code and the byte count. Anything else is an
  error and the connection is closed (the stream can no longer be trusted).
* After a lost connection the next read connects once; when that fails, no
  new attempt is made before a back-off (5 s doubling to 5 min) - no storm of
  connections against a controller of the heat supplier.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import struct
import time

READ_HOLDING_REGISTERS = 0x03
READ_INPUT_REGISTERS = 0x04
READ_FUNCTIONS = (READ_INPUT_REGISTERS, READ_HOLDING_REGISTERS)
WRITE_SINGLE_REGISTER = 0x06
MAX_REGISTERS = 123
DEFAULT_PORT = 502
DEFAULT_UNIT = 1
DEFAULT_TIMEOUT = 5.0
BACKOFF_START = 5.0
BACKOFF_MAX = 300.0

# Modbus exception codes (Modbus Application Protocol V1.1b3, 7) with a
# reason in Polish for the user; ECL uses 1-4 (Danfoss 7.1.1).
EXCEPTION_REASONS: dict[int, str] = {
    0x01: "Regulator nie obsługuje tej funkcji odczytu (wyjątek 01).",
    0x02: "Regulator nie ma tego parametru (wyjątek 02).",
    0x03: "Regulator nie przyjął zapytania — zła liczba rejestrów (wyjątek 03).",
    0x04: "Błąd regulatora przy odczycie (wyjątek 04).",
    0x06: "Regulator jest zajęty — odczyt zostanie powtórzony (wyjątek 06).",
    0x0B: "Bramka nie dostała odpowiedzi od regulatora (wyjątek 0B).",
}

Connector = Callable[[str, int], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]


class EclModbusError(Exception):
    """A Modbus exception answer of the controller."""

    def __init__(self, code: int) -> None:
        self.code = code
        self.reason = EXCEPTION_REASONS.get(code, f"Nieznany wyjątek Modbus {code:02X}.")
        super().__init__(self.reason)


class EclConnectionError(Exception):
    """No connection, no answer in time or an answer that cannot be trusted."""


async def _open(host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    return await asyncio.open_connection(host, port)


class EclModbusClient:
    """Modbus/TCP client of one ECL controller: reads, and writes one
    register at a time (0x06)."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        unit: int = DEFAULT_UNIT,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        connector: Connector = _open,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 <= unit <= 255:
            raise ValueError("unit id 0-255")
        self.host = host
        self.port = port
        self.unit = unit
        self._timeout = timeout
        self._connector = connector
        self._clock = clock
        self._lock = asyncio.Lock()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._transaction = 0
        self._function = READ_INPUT_REGISTERS
        self._backoff = 0.0
        self._retry_at = 0.0

    @property
    def function(self) -> int:
        """The read function in use (0x04, or 0x03 after "Illegal function")."""

        return self._function

    @property
    def connected(self) -> bool:
        return self._writer is not None

    async def read_pnu(self, pnu: int, count: int = 1) -> list[int]:
        """``count`` registers from the Danfoss parameter number ``pnu``."""

        if pnu < 1:
            raise ValueError("PNU starts with 1")
        return await self.read_registers(pnu - 1, count)

    async def read_registers(self, address: int, count: int = 1) -> list[int]:
        """``count`` (1-123) 16-bit registers from ``address``. 0x04 first;
        "Illegal function" switches the client to 0x03 for good."""

        if not 0 <= address <= 0xFFFF or not 1 <= count <= MAX_REGISTERS:
            raise ValueError("address 0-65535, count 1-123")
        if address + count - 1 > 0xFFFF:
            raise ValueError("registers beyond 65535")
        async with self._lock:
            try:
                return await self._request(self._function, address, count)
            except EclModbusError as err:
                if err.code != 0x01 or self._function != READ_INPUT_REGISTERS:
                    raise
                self._function = READ_HOLDING_REGISTERS
                return await self._request(self._function, address, count)

    async def write_pnu(self, pnu: int, value: int) -> None:
        """0x06: one register of the Danfoss parameter number ``pnu``. The
        answer must echo the request (Modbus Application Protocol 6.6)."""

        if pnu < 1:
            raise ValueError("PNU starts with 1")
        if not 0 <= value <= 0xFFFF:
            raise ValueError("value 0-65535")
        async with self._lock:
            await self._request(WRITE_SINGLE_REGISTER, pnu - 1, value)

    async def close(self) -> None:
        async with self._lock:
            await self._drop()

    async def _connect(self) -> None:
        if self._writer is not None:
            return
        now = self._clock()
        if now < self._retry_at:
            raise EclConnectionError(
                f"Brak połączenia z regulatorem — kolejna próba za {self._retry_at - now:.0f} s."
            )
        try:
            self._reader, self._writer = await asyncio.wait_for(
                self._connector(self.host, self.port), self._timeout
            )
        except (OSError, TimeoutError) as err:
            self._backoff = min(BACKOFF_MAX, self._backoff * 2 if self._backoff else BACKOFF_START)
            self._retry_at = self._clock() + self._backoff
            raise EclConnectionError(
                f"Nie można połączyć się z regulatorem {self.host}:{self.port}."
            ) from err
        self._backoff = 0.0
        self._retry_at = 0.0

    async def _drop(self) -> None:
        writer, self._reader, self._writer = self._writer, None, None
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError, ConnectionError):
                await writer.wait_closed()

    def _next_transaction(self) -> int:
        self._transaction = self._transaction % 0xFFFF + 1
        return self._transaction

    async def _request(self, function: int, address: int, count: int) -> list[int]:
        """``count`` is the value for 0x06."""

        reconnected = False
        while True:
            fresh = self._writer is None
            await self._connect()
            try:
                return await self._exchange(function, address, count)
            except EclModbusError:
                raise
            except (OSError, TimeoutError, asyncio.IncompleteReadError, EclConnectionError) as err:
                await self._drop()
                # A connection the controller closed while idle (75 s): one
                # new connection at once; a fresh one that fails is an error.
                if fresh or reconnected:
                    self._backoff = min(
                        BACKOFF_MAX, self._backoff * 2 if self._backoff else BACKOFF_START
                    )
                    self._retry_at = self._clock() + self._backoff
                    if isinstance(err, EclConnectionError):
                        raise
                    raise EclConnectionError("Regulator nie odpowiedział.") from err
                reconnected = True

    async def _exchange(self, function: int, address: int, count: int) -> list[int]:
        assert self._reader is not None and self._writer is not None
        transaction = self._next_transaction()
        pdu = struct.pack(">BHH", function, address, count)
        self._writer.write(struct.pack(">HHHB", transaction, 0, len(pdu) + 1, self.unit) + pdu)
        await self._writer.drain()
        header = await asyncio.wait_for(self._reader.readexactly(7), self._timeout)
        answer_transaction, protocol, length, unit = struct.unpack(">HHHB", header)
        if not 2 <= length <= 254:
            raise EclConnectionError("Odpowiedź o złej długości.")
        body = await asyncio.wait_for(self._reader.readexactly(length - 1), self._timeout)
        if answer_transaction != transaction or protocol != 0:
            raise EclConnectionError("Odpowiedź na inne zapytanie.")
        if unit != self.unit:
            raise EclConnectionError(f"Odpowiedź innego urządzenia (adres {unit}).")
        answered = body[0]
        if answered == function | 0x80:
            if len(body) != 2:
                raise EclConnectionError("Wyjątek o złej długości.")
            raise EclModbusError(body[1])
        if answered != function:
            raise EclConnectionError("Odpowiedź z inną funkcją.")
        if function == WRITE_SINGLE_REGISTER:
            if body != pdu:
                raise EclConnectionError("Regulator nie potwierdził zapisu tej wartości.")
            return [count]
        if len(body) < 2 or body[1] != 2 * count or len(body) != 2 + 2 * count:
            raise EclConnectionError("Liczba bajtów nie zgadza się z liczbą rejestrów.")
        return list(struct.unpack(f">{count}H", body[2:]))


def as_int16(value: int) -> int:
    """A register as a signed 16-bit number (temperatures below zero)."""

    return value - 0x10000 if value & 0x8000 else value


def as_uint32(high: int, low: int) -> int:
    """Two registers, high word first (Danfoss: M-bus values, 6.11)."""

    return (high << 16) | low
