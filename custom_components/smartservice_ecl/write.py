"""What the integration may write to an ECL Comfort and how often - plain
data, no Home Assistant (0.2.0).

Only the service ``smartservice_ecl.zapisz_parametr`` writes; there are no
writable entities. A parameter outside the list below is refused before any
Modbus request. The ECL has no remote offset with a timeout (A237.1: no
11101, no 10400-10408), it keeps the last written value for good - so a
write never goes above the owner's value (the one read before our first
write of that parameter): the integration only lowers a setting and puts it
back. The target itself (e.g. the limits of a floor) is the caller's.

* 11180 / 11181 - room comfort / saving setpoint, the controller's range
  5-40 °C in steps of 0.5 K, saving never above comfort (scale 10, Danfoss
  p. 37 and 59).
* 11400-11405 - the heat curve of circuit 1 (flow at -30/-15/-5/0/5/15 °C),
  the controller's range 10-150 °C, not rising with the outdoor temperature
  (scale 1, p. 15). Lower the curve from the warm end (11405 first), raise it
  from the cold end.
* 11178 - maximum flow, 10-150 °C, once (scale 1).

Each parameter is written at most once a day (a second time only to repeat a
value whose control reading did not match), 10 writes a day in all. Before
its first write the integration keeps the controller's value as the owner's
copy; ``przywroc_parametr`` writes that copy back - unless the setting was
changed on the controller after our write (a change by hand wins).
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

PNU_MODE = 4201
PNU_FLOW_MAX = 11178
PNU_ROOM_COMFORT = 11180
PNU_ROOM_SAVING = 11181
CURVE = (11400, 11401, 11402, 11403, 11404, 11405)
MAX_WRITES_PER_DAY = 10
WRITES_PER_PNU_PER_DAY = 1
LOG_SIZE = 50
# The list holds for this application only (its parameter numbers and roles).
APPLICATION_KEY = "A237.1"


@dataclass(frozen=True, slots=True)
class Limit:
    name: str
    low: float
    high: float
    scale: int
    step: float
    unit: str = "°C"


WRITABLE: Mapping[int, Limit] = {
    # The controller's own ranges ([T] A237.1 V04, Danfoss p. 15, 37).
    PNU_ROOM_COMFORT: Limit("zadana pokojowa komfort", 5.0, 40.0, 10, 0.5),
    PNU_ROOM_SAVING: Limit("zadana pokojowa oszczędna", 5.0, 40.0, 10, 0.5),
    **{
        pnu: Limit(f"krzywa: zasilanie przy {outdoor} °C", 10, 150, 1, 1)
        for pnu, outdoor in zip(CURVE, (-30, -15, -5, 0, 5, 15), strict=True)
    },
    PNU_FLOW_MAX: Limit("maks. zasilania", 10, 150, 1, 1),
}
ONCE = frozenset({PNU_FLOW_MAX})
# Read fresh before every write: the mode and every parameter a check needs.
CONTEXT_PNUS = (PNU_MODE, PNU_FLOW_MAX, PNU_ROOM_COMFORT, PNU_ROOM_SAVING, *CURVE)

# Modbus exceptions of a write (Danfoss p. 35: a value outside the
# controller's range answers 03).
WRITE_EXCEPTION_REASONS: Mapping[int, str] = {
    0x01: "Regulator nie przyjmuje zapisu (wyjątek 01).",
    0x02: "Regulator nie ma tego parametru (wyjątek 02).",
    0x03: "Regulator odrzucił wartość — poza jego zakresem (wyjątek 03).",
    0x04: "Błąd regulatora przy zapisie (wyjątek 04).",
    0x06: "Regulator jest zajęty — zapis nie został wykonany (wyjątek 06).",
}


# 0.2.1: the fixed error codes (translation_key of the HomeAssistantError)
# a caller recognises - the reason text may change, the codes do not.
PNU_NOT_ALLOWED = "pnu_niedozwolony"
OUT_OF_RANGE = "poza_zakresem"
ABOVE_OWNER = "powyzej_wlasciciela"
DAY_LIMIT = "limit_doby"
MANUAL_MODE = "tryb_reczny"
NO_CONNECTION = "brak_polaczenia"
CHECK_FAILED = "odczyt_niezgodny"
NO_COPY = "brak_kopii"
CHANGED_BY_HAND = "zmiana_reczna"
NO_CONTROLLER = "brak_regulatora"
ERROR_CODES = (
    PNU_NOT_ALLOWED,
    OUT_OF_RANGE,
    ABOVE_OWNER,
    DAY_LIMIT,
    MANUAL_MODE,
    NO_CONNECTION,
    CHECK_FAILED,
    NO_COPY,
    CHANGED_BY_HAND,
    NO_CONTROLLER,
)


class WriteRefused(Exception):
    """A write the integration does not make - with the reason and its code."""

    def __init__(self, reason: str, code: str) -> None:
        self.reason = reason
        self.code = code
        super().__init__(reason)


def text(pnu: int, raw: int) -> str:
    """A raw value as the user reads it ("21,5 °C")."""

    limit = WRITABLE.get(pnu)
    if limit is None or limit.scale == 1:
        return f"{raw} °C" if limit else str(raw)
    return f"{raw / limit.scale:.1f}".replace(".", ",") + f" {limit.unit}"


def to_raw(pnu: int, value: float) -> int:
    """The register value of ``value`` - or WriteRefused (not on the list,
    outside the limits, not a whole step)."""

    limit = WRITABLE.get(pnu)
    if limit is None:
        raise WriteRefused(f"Parametr {pnu} nie jest na liście zapisu — odmowa.", PNU_NOT_ALLOWED)
    if not limit.low <= value <= limit.high:
        raise WriteRefused(
            f"{pnu} ({limit.name}): {value} poza granicami {limit.low}-{limit.high} {limit.unit}.",
            OUT_OF_RANGE,
        )
    steps = value / limit.step
    if abs(steps - round(steps)) > 1e-6:
        raise WriteRefused(
            f"{pnu} ({limit.name}): {value} nie jest wielokrotnością {limit.step}.", OUT_OF_RANGE
        )
    return round(value * limit.scale)


def check_against(pnu: int, raw: int, current: Mapping[int, int]) -> None:
    """The rules between parameters, against the values just read."""

    if pnu == PNU_ROOM_SAVING:
        comfort = current.get(PNU_ROOM_COMFORT)
        if comfort is None or raw > comfort:
            raise WriteRefused(
                "Zadana oszczędna nie może być wyższa niż komfort (11180).", OUT_OF_RANGE
            )
    if pnu == PNU_ROOM_COMFORT:
        saving = current.get(PNU_ROOM_SAVING)
        if saving is not None and saving > raw:
            raise WriteRefused(
                "Zadana komfort nie może być niższa niż oszczędna (11181) — najpierw obniż 11181.",
                OUT_OF_RANGE,
            )
    if pnu in CURVE:
        index = CURVE.index(pnu)
        colder = current.get(CURVE[index - 1]) if index > 0 else None
        warmer = current.get(CURVE[index + 1]) if index < len(CURVE) - 1 else None
        if colder is not None and raw > colder:
            raise WriteRefused(
                f"Krzywa nie może rosnąć z temperaturą zewnętrzną: {pnu} = {raw} °C, "
                f"a {CURVE[index - 1]} = {colder} °C. Podnoś krzywą od najzimniejszego punktu.",
                OUT_OF_RANGE,
            )
        if warmer is not None and raw < warmer:
            raise WriteRefused(
                f"Krzywa nie może rosnąć z temperaturą zewnętrzną: {pnu} = {raw} °C, "
                f"a {CURVE[index + 1]} = {warmer} °C. Obniżaj krzywą od najcieplejszego punktu.",
                OUT_OF_RANGE,
            )


class Ledger:
    """The writes kept in Home Assistant's storage: per PNU the owner's copy,
    our last value, the day and its count; the day's total; a short log.
    ``data`` is plain JSON (stored as it is)."""

    def __init__(self, data: MutableMapping[str, Any] | None = None) -> None:
        self.data: MutableMapping[str, Any] = data or {}
        self.data.setdefault("pnu", {})
        self.data.setdefault("day", None)
        self.data.setdefault("total", 0)
        self.data.setdefault("log", [])

    def _entry(self, pnu: int) -> MutableMapping[str, Any]:
        return self.data["pnu"].setdefault(
            str(pnu),
            {"original": None, "last": None, "day": None, "writes": 0, "check_ok": True},
        )

    def _roll(self, day: str) -> None:
        if self.data["day"] != day:
            self.data["day"] = day
            self.data["total"] = 0

    def note(self, when: str, pnu: int, action: str, **details: Any) -> None:
        self.data["log"].append({"time": when, "pnu": pnu, "action": action, **details})
        del self.data["log"][:-LOG_SIZE]

    def owner_value(self, pnu: int, current: int) -> int:
        """The owner's value: kept before our first write - or the current
        one (no write of ours yet, or the setting was changed on the
        controller since our write)."""

        entry = self.data["pnu"].get(str(pnu))
        if entry is None or entry["last"] is None:
            return current
        if entry["check_ok"] and current != entry["last"]:
            return current
        return int(entry["original"])

    def check_owner(self, pnu: int, raw: int, current: int) -> None:
        """Never above the owner's value."""

        owner = self.owner_value(pnu, current)
        if raw > owner:
            raise WriteRefused(
                f"{pnu}: {text(pnu, raw)} powyżej wartości właściciela ({text(pnu, owner)}) — "
                "integracja nastawę tylko obniża i przywraca.",
                ABOVE_OWNER,
            )

    def allow_write(self, pnu: int, raw: int, day: str) -> None:
        """WriteRefused when the day's limits or "once" forbid this write."""

        self._roll(day)
        entry = self._entry(pnu)
        repeat = entry["day"] == day and not entry["check_ok"] and raw == entry["last"]
        if self.data["total"] >= MAX_WRITES_PER_DAY:
            raise WriteRefused(
                f"Dzisiejszy limit {MAX_WRITES_PER_DAY} zapisów jest wyczerpany.", DAY_LIMIT
            )
        if entry["day"] == day and entry["writes"] >= WRITES_PER_PNU_PER_DAY and not repeat:
            raise WriteRefused(
                f"Parametr {pnu} był już dziś zapisany (najwyżej raz na dobę).", DAY_LIMIT
            )
        if entry["day"] == day and entry["writes"] > WRITES_PER_PNU_PER_DAY:
            raise WriteRefused(f"Parametr {pnu}: zapis już raz powtórzony dziś.", DAY_LIMIT)
        if pnu in ONCE and entry["last"] is not None and not repeat:
            raise WriteRefused(
                f"Parametr {pnu} ustawia się jednorazowo — najpierw przywróć poprzednią wartość.",
                DAY_LIMIT,
            )

    def record_write(self, pnu: int, raw: int, before: int, check_ok: bool, day: str) -> None:
        """A write made (also one whose control reading did not match)."""

        self._roll(day)
        entry = self._entry(pnu)
        if entry["last"] is None or (entry["check_ok"] and before != entry["last"]):
            # The first write, or the setting was changed on the controller
            # since our write: the value before is the owner's.
            entry["original"] = before
        entry["writes"] = entry["writes"] + 1 if entry["day"] == day else 1
        entry["day"] = day
        entry["last"] = raw
        entry["check_ok"] = check_ok
        self.data["total"] += 1

    def restore_target(self, pnu: int, current: int) -> int | None:
        """The owner's value to write back; None when the controller has it
        already (the record is then closed). WriteRefused without a copy or
        when the setting was changed on the controller (a change by hand
        wins - the record is closed, the owner's value stays)."""

        if pnu not in WRITABLE:
            raise WriteRefused(
                f"Parametr {pnu} nie jest na liście zapisu — odmowa.", PNU_NOT_ALLOWED
            )
        entry = self.data["pnu"].get(str(pnu))
        if entry is None or entry["original"] is None:
            raise WriteRefused(
                f"Integracja nie zmieniała parametru {pnu} — nie ma czego przywracać.", NO_COPY
            )
        if current == entry["original"]:
            self._close(entry)
            return None
        if entry["check_ok"] and current != entry["last"]:
            self._close(entry)
            raise WriteRefused(
                f"Parametr {pnu} zmieniono na regulatorze po zapisie integracji — "
                "zostaje wartość ustawiona ręcznie.",
                CHANGED_BY_HAND,
            )
        return int(entry["original"])

    def record_restore(self, pnu: int, check_ok: bool, day: str) -> None:
        self._roll(day)
        entry = self._entry(pnu)
        self.data["total"] += 1
        if check_ok:
            self._close(entry)

    @staticmethod
    def _close(entry: MutableMapping[str, Any]) -> None:
        entry["original"] = None
        entry["last"] = None
        entry["check_ok"] = True
