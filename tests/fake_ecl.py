"""A fake Modbus/TCP server (standard library only) answering as an ECL
Comfort 310: registers by address, Modbus exceptions, and on request the
faults a real network gives (a wrong transaction id, another unit id, a
wrong byte count, silence, a dropped connection). 0.2.0: 0x06 writes one
register and echoes the request; a register can refuse writes (an exception)
or ignore them (the answer is right, the value stays - a control reading
then differs)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import struct


@dataclass
class FakeEcl:
    registers: dict[int, int] = field(default_factory=dict)
    unit: int = 1
    # Functions the device refuses with exception 01 (Illegal function).
    refused_functions: set[int] = field(default_factory=set)
    # Registers it does not have: exception 02 for a request touching them.
    missing: set[int] = field(default_factory=set)
    # One-shot faults, consumed by the next request.
    faults: list[str] = field(default_factory=list)
    exception_code: int = 0x04
    # 0x06: register -> exception code; registers that keep their value.
    refused_writes: dict[int, int] = field(default_factory=dict)
    ignored_writes: set[int] = field(default_factory=set)
    requests: list[tuple[int, int, int, int]] = field(default_factory=list)
    connections: int = 0
    server: asyncio.base_events.Server | None = None
    _writers: list[asyncio.StreamWriter] = field(default_factory=list)
    _stopped: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def port(self) -> int:
        assert self.server is not None
        return self.server.sockets[0].getsockname()[1]

    async def start(self) -> FakeEcl:
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        return self

    async def stop(self) -> None:
        # A silent connection must not keep the server open (wait_closed
        # waits for every connection since Python 3.12).
        self._stopped.set()
        for writer in self._writers:
            writer.close()
        if self.server is not None:
            self.server.close()
            await asyncio.wait_for(self.server.wait_closed(), 5)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        self._writers.append(writer)
        try:
            while True:
                header = await reader.readexactly(7)
                transaction, _protocol, length, unit = struct.unpack(">HHHB", header)
                pdu = await reader.readexactly(length - 1)
                function, address, count = struct.unpack(">BHH", pdu)
                self.requests.append((transaction, unit, function, address))
                fault = self.faults.pop(0) if self.faults else None
                if fault == "drop":
                    writer.close()
                    return
                if fault == "silence":
                    await self._stopped.wait()
                    return
                answer = self._answer(function, address, count, fault)
                answer_transaction = transaction + 1 if fault == "transaction" else transaction
                answer_unit = (unit + 1) % 256 if fault == "unit" else unit
                writer.write(
                    struct.pack(">HHHB", answer_transaction, 0, len(answer) + 1, answer_unit)
                    + answer
                )
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    def _answer(self, function: int, address: int, count: int, fault: str | None) -> bytes:
        if fault == "exception":
            return bytes([function | 0x80, self.exception_code])
        if function in self.refused_functions:
            return bytes([function | 0x80, 0x01])
        if function == 0x06:
            # ``count`` is the value of a write.
            if address in self.missing:
                return bytes([function | 0x80, 0x02])
            if address in self.refused_writes:
                return bytes([function | 0x80, self.refused_writes[address]])
            if address not in self.ignored_writes:
                self.registers[address] = count
            return bytes([function]) + struct.pack(">HH", address, count)
        if not 1 <= count <= 123:
            return bytes([function | 0x80, 0x03])
        wanted = range(address, address + count)
        if any(item in self.missing for item in wanted):
            return bytes([function | 0x80, 0x02])
        values = [self.registers.get(item, 0) for item in wanted]
        data = struct.pack(f">{count}H", *values)
        if fault == "bytes":
            return bytes([function, len(data) + 2]) + data
        return bytes([function, len(data)]) + data
