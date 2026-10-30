"""Reads a set of Danfoss parameters (PNU) in as few requests as the ECL
allows - no Home Assistant.

Contiguous parameters go in one request (at most 123). A request touching a
parameter the controller does not have answers exception 02 for the whole
block: the block is then read one parameter at a time and the missing ones
are remembered (not asked again every cycle; again after ``FORGET_AFTER``
reads, a software update of the controller may add them).
"""

from __future__ import annotations

from collections.abc import Iterable

from .modbus import MAX_REGISTERS, EclModbusClient, EclModbusError

FORGET_AFTER = 120


def blocks(pnus: Iterable[int]) -> list[tuple[int, int]]:
    """Contiguous runs of PNUs as (first, count), each at most 123."""

    out: list[tuple[int, int]] = []
    for pnu in sorted(set(pnus)):
        if out and out[-1][0] + out[-1][1] == pnu and out[-1][1] < MAX_REGISTERS:
            out[-1] = (out[-1][0], out[-1][1] + 1)
        else:
            out.append((pnu, 1))
    return out


class EclReader:
    """Reads PNUs through one client and remembers the missing ones."""

    def __init__(self, client: EclModbusClient) -> None:
        self.client = client
        self.missing: set[int] = set()
        self._reads = 0

    async def read(self, pnus: Iterable[int]) -> dict[int, int]:
        """The registers by PNU; a missing parameter is not in the result.
        A connection error is raised (the caller marks everything unavailable)."""

        self._reads += 1
        if self._reads % FORGET_AFTER == 0:
            self.missing.clear()
        wanted = [pnu for pnu in set(pnus) if pnu not in self.missing]
        values: dict[int, int] = {}
        for first, count in blocks(wanted):
            try:
                registers = await self.client.read_pnu(first, count)
            except EclModbusError as err:
                if err.code != 0x02:
                    raise
                for pnu in range(first, first + count):
                    try:
                        values[pnu] = (await self.client.read_pnu(pnu, 1))[0]
                    except EclModbusError as single:
                        if single.code != 0x02:
                            raise
                        self.missing.add(pnu)
                continue
            values.update(zip(range(first, first + count), registers, strict=True))
        return values
