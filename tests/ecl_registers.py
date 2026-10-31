"""The registers of a synthetic ECL Comfort 310 with A237.1 (no real
controller's data): register = PNU - 1."""

from __future__ import annotations


def reg(pnu: int) -> int:
    return pnu - 1


def a237_registers(
    *, meter: bool = False, application: int = 237, sub: int = 1, code: int | None = 3040
) -> dict[int, int]:
    values = {
        # Identity: software 1.01, serial 11009763, A237.1 version 1.02.
        35: 257,
        36: 0x00A7,
        37: 0xFEE3,
        2060: 65,
        2061: application,
        2062: sub,
        2063: 0x0102,
        # S1 -3.50 °C (negative), S2 none (192.00 °C), S3 52.30, S4 none,
        # S5 38.10, S6 54.20 °C; S7-S10 none.
        10201: 0x10000 - 350,
        10202: 19200,
        10203: 5230,
        10204: 19200,
        10205: 3810,
        10206: 5420,
        **{10200 + n: 19200 for n in range(7, 11)},
        # Targets: room 21.00 °C (R2), flow 52.00 °C (R3), return 40.00 °C (R5),
        # hot water 55.00 °C.
        11252: 2100,
        11253: 5200,
        11255: 4000,
        12256: 5500,
        # Setpoints (x10) and the curve (Danfoss defaults).
        11175: 10,
        11177: 10,
        11178: 90,
        11180: 210,
        11181: 165,
        12190: 550,
        12191: 100,
        11400: 75,
        11401: 60,
        11402: 50,
        11403: 45,
        11404: 40,
        11405: 28,
        # Modes: circuit 1 scheduled, circuit 2 constant comfort; status comfort.
        4201: 1,
        4202: 2,
        4211: 2,
        4212: 2,
        # Limiter: the return limit lowers the reference (bit 1).
        4220: 0b10,
        # Alarms none; sensor errors none; relay 1 on.
        1024: 0,
        1025: 0,
        2054: 0,
        2055: 0,
        **{pnu: 0 for pnu in range(4000, 4012)},
        4006: 1,
        # No heat meter.
        6000: 255,
        6001: 0,
    }
    # 0.1.2: the code number (PNU 19) - 087H3040, ECL Comfort 296 / 310.
    if code is not None:
        values[19] = code
    if meter:
        values.update(
            {
                6000: 1,
                6001: 0,
                6006: 7010,
                6007: 4020,
                6010: 0,
                6011: 123,
                6014: 0x0001,
                6015: 0x2345,
            }
        )
    return {reg(pnu): value for pnu, value in values.items()}
