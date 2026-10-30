"""What the integration reads from a Danfoss ECL Comfort 296/310 and how it
decodes it - plain data, no Home Assistant.

Source: Danfoss "ECL Comfort 210 / 296 / 310, communication description"
VI.LG.V5.02 (2017.02); page numbers are the document's own. The roles of the
inputs of application A237 (S1 outdoor, S3 flow, S5 return, S6 tank) are the
installation guide's (087H3806) and must be checked against the controller's
"input overview" on site; inputs without a sure role are offered as "Wejście
Sn", disabled by default.

Every value is read only. A parameter the controller does not have answers
Modbus exception 02 and stays unavailable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# p. 54: raw inputs S1-S10, scale 100.
RAW_SENSOR_PNU = 10200  # + n
# p. 15 and 59: the heat curve of circuit 1 - six points (°C, scale 1).
CURVE_POINTS: tuple[tuple[str, int, int], ...] = (
    ("curve_m30", 11400, -30),
    ("curve_m15", 11401, -15),
    ("curve_m5", 11402, -5),
    ("curve_0", 11403, 0),
    ("curve_p5", 11404, 5),
    ("curve_p15", 11405, 15),
)
# p. 14 and 52: modes 4201-4206, status 4211-4216.
MODES = ("manual", "scheduled", "comfort", "saving", "frost_protection", "cooling")
STATUSES = (
    "saving",
    "pre_comfort",
    "comfort",
    "pre_saving",
    "holiday_comfort",
    "holiday_comfort_7_23",
    "holiday_saving",
    "holiday_frost_protection",
)
# p. 54: an input without a sensor reads 192.00 °C (Danfoss Pt1000 open
# circuit; the community integration reports the same) - unavailable.
DISCONNECTED_RAW = 19200
TEMPERATURE_RANGE = (-50.0, 150.0)
CURVE_RANGE = (10.0, 150.0)
NO_METER = 255

# p. 25 and 48: the application key.
PNU_APP_PREFIX = 2060
PNU_APP_TYPE = 2061
PNU_APP_SUB = 2062
PNU_APP_VERSION = 2063
# p. 47: identity.
PNU_SOFTWARE = 35
PNU_SERIAL_HIGH = 36
PNU_SERIAL_LOW = 37
PNU_SALES_NUMBER = 19


@dataclass(frozen=True, slots=True)
class Application:
    """A supported application key and the roles of its inputs."""

    name: str
    roles: Mapping[int, str]
    dhw: bool = True


# A237 (installation guide 087H3806 and the "A237_1 ex. a" diagram of a
# controller in service, 30.10): S3 is the flow of circuit 1 after the heat
# exchanger, S5 the return of the PRIMARY side at the control valve M1 (the
# district network's return the return limit acts on) - not the radiators'
# return. A237.1 uses six inputs (the guide's table): S1, S2 (room), S3, S5,
# S6 (tank top) and S8 (tank bottom / charging).
A237_ROLES = {
    1: "outdoor_temperature",
    3: "flow_temperature",
    5: "primary_return_temperature",
    6: "dhw_tank_temperature",
}
A237_1_ROLES = {
    **A237_ROLES,
    2: "room_temperature",
    8: "dhw_tank_bottom_temperature",
}
APPLICATIONS: Mapping[tuple[str, int, int], Application] = {
    ("A", 237, 1): Application("A237.1", A237_1_ROLES),
    # A237.2 (seven inputs): only the roles common with A237.1 until a diagram
    # of A237.2 is seen; its other inputs stay "Wejście Sn", disabled.
    ("A", 237, 2): Application("A237.2", A237_ROLES),
}


@dataclass(frozen=True, slots=True)
class Identity:
    prefix: str
    number: int
    sub: int
    version: str
    software: str
    serial: int

    @property
    def key(self) -> str:
        return f"{self.prefix}{self.number}.{self.sub}"

    @property
    def application(self) -> Application | None:
        return APPLICATIONS.get((self.prefix, self.number, self.sub))


def version_text(raw: int) -> str:
    """p. 25: two bytes, major then minor - 257 is "1.01"."""

    return f"{raw >> 8}.{raw & 0xFF:02d}"


def identity_from(registers: Mapping[int, int]) -> Identity:
    """The identity from the registers of PNU 35-37 and 2060-2063."""

    prefix = registers[PNU_APP_PREFIX]
    return Identity(
        prefix=chr(prefix) if 32 < prefix < 127 else "?",
        number=registers[PNU_APP_TYPE],
        sub=registers[PNU_APP_SUB],
        version=version_text(registers[PNU_APP_VERSION]),
        software=version_text(registers[PNU_SOFTWARE]),
        serial=(registers[PNU_SERIAL_HIGH] << 16) | registers[PNU_SERIAL_LOW],
    )


IDENTITY_PNUS = (
    PNU_SOFTWARE,
    PNU_SERIAL_HIGH,
    PNU_SERIAL_LOW,
    PNU_APP_PREFIX,
    PNU_APP_TYPE,
    PNU_APP_SUB,
    PNU_APP_VERSION,
)


def signed(raw: int) -> int:
    return raw - 0x10000 if raw & 0x8000 else raw


@dataclass(frozen=True, slots=True)
class Value:
    """A decoded reading: ``value`` or None with the ``reason``."""

    value: float | int | str | bool | None
    reason: str | None = None


MISSING = Value(None, "Regulator nie ma tego parametru.")


def temperature(raw: int | None, scale: float = 0.01) -> Value:
    """An input or a reference (scale 100): 192.00 °C is no sensor."""

    if raw is None:
        return MISSING
    if raw == DISCONNECTED_RAW:
        return Value(None, "Czujnik niepodłączony (regulator podaje 192 °C).")
    value = round(signed(raw) * scale, 2)
    if not TEMPERATURE_RANGE[0] <= value <= TEMPERATURE_RANGE[1]:
        return Value(None, f"Odczyt poza zakresem czujnika ({value} °C).")
    return Value(value)


def setpoint(raw: int | None) -> Value:
    """A comfort / saving setpoint, scale 10 (p. 37, 59)."""

    if raw is None:
        return MISSING
    return Value(round(signed(raw) / 10, 1))


def curve_point(raw: int | None) -> Value:
    """A point of the heat curve, °C (p. 15: 10-150 °C)."""

    if raw is None:
        return MISSING
    value = float(signed(raw))
    if not CURVE_RANGE[0] <= value <= CURVE_RANGE[1]:
        return Value(None, f"Punkt krzywej poza zakresem 10-150 °C ({value:.0f}).")
    return Value(value)


def plain(raw: int | None, scale: float = 1.0) -> Value:
    if raw is None:
        return MISSING
    value = signed(raw) * scale
    return Value(round(value, 1) if scale != 1.0 else int(value))


def mode(raw: int | None) -> Value:
    if raw is None:
        return MISSING
    return Value(MODES[raw]) if raw < len(MODES) else Value(None, f"Nieznany tryb {raw}.")


def status(raw: int | None, mode_raw: int | None) -> Value:
    """p. 14: the status reads 0 when the mode is above 3 - then none."""

    if raw is None:
        return MISSING
    if mode_raw is not None and mode_raw > 3:
        return Value(None, "Regulator nie podaje statusu w tym trybie.")
    return Value(STATUSES[raw]) if raw < len(STATUSES) else Value(None, f"Nieznany status {raw}.")


def manual(mode_raw: int | None) -> Value:
    """p. 14: mode 0 - the whole controller follows its manual settings."""

    return MISSING if mode_raw is None else Value(mode_raw == 0)


def return_limit(raw: int | None) -> Value:
    """p. 33: limiter word 1, bits 0-1 - the return limit moves the
    reference (1 up, 2 down, 3 changed). From software 1.32."""

    return MISSING if raw is None else Value(raw & 0b11 != 0)


def alarms(high: int | None, low: int | None) -> tuple[Value, list[int]]:
    """p. 20: PNU 1025 bit 0 is alarm 1, PNU 1024 holds alarms 17-32."""

    if high is None or low is None:
        return MISSING, []
    numbers = [bit + 1 for bit in range(16) if low >> bit & 1]
    numbers += [bit + 17 for bit in range(16) if high >> bit & 1]
    return Value(bool(numbers)), numbers


def any_bit(first: int | None, second: int | None) -> Value:
    if first is None or second is None:
        return MISSING
    return Value(bool(first or second))


def output(raw: int | None) -> Value:
    """p. 28: the output's current value, 0 off."""

    return MISSING if raw is None else Value(raw != 0)


# p. 21-22 and 53: energy meter 1 over M-bus (ECL 296/310).
METER_BASE = 6000
METER_ADDRESS = METER_BASE
METER_TYPE = METER_BASE + 1
METER_FLOW_T = METER_BASE + 6
METER_RETURN_T = METER_BASE + 7
METER_POWER = METER_BASE + 10
METER_ENERGY = METER_BASE + 14


def meter_present(address: int | None) -> bool:
    return address is not None and address != NO_METER


def meter_uint32(high: int | None, low: int | None, scale: float, meter_type: int | None) -> Value:
    """Power (0.1 kW) and energy (0.1 kWh) of a type 0 meter ("small
    units"); another type has other units - not shown (p. 41, 42)."""

    if high is None or low is None:
        return MISSING
    if meter_type != 0:
        return Value(None, f"Licznik typu {meter_type} — jednostki nieobsługiwane w tej wersji.")
    return Value(round(((high << 16) | low) * scale, 1))


def fast_pnus(meter: bool) -> list[int]:
    """Read every 30 s."""

    pnus = [RAW_SENSOR_PNU + n for n in range(1, 11)]
    pnus += [11253, 12256, 4201, 4202, 4211, 4212, 4220, 1024, 1025, 2054, 2055]
    pnus += list(range(4000, 4012))
    if meter:
        pnus += [METER_FLOW_T, METER_RETURN_T, *range(METER_POWER, METER_POWER + 2)]
        pnus += list(range(METER_ENERGY, METER_ENERGY + 2))
    return pnus


def slow_pnus() -> list[int]:
    """Read every hour: settings, the curve, the meter's setup."""

    return [
        11175,
        11177,
        11178,
        11180,
        11181,
        12190,
        12191,
        *(pnu for _key, pnu, _outdoor in CURVE_POINTS),
        METER_ADDRESS,
        METER_TYPE,
    ]
