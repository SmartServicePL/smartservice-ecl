# ruff: noqa: E501
"""0.2.0: the list, the limits and the day's count of the writes (no Home
Assistant)."""

from __future__ import annotations

import pytest

from tests.pure import load

write = load("write")
Refused = write.WriteRefused
DAY = "2026-11-12"
NEXT_DAY = "2026-11-13"
# The factory curve and the room setpoints of a controller in service.
CURRENT = {4201: 1, 11178: 90, 11180: 250, 11181: 250} | dict(
    zip(write.CURVE, (75, 60, 50, 45, 40, 28), strict=True)
)


def test_the_list_is_exactly_the_one_of_the_project() -> None:
    assert sorted(write.WRITABLE) == [11178, 11180, 11181, 11400, 11401, 11402, 11403, 11404, 11405]
    assert sorted(write.ONCE) == [11178]
    assert write.MAX_WRITES_PER_DAY == 10
    assert write.APPLICATION_KEY == "A237.1"
    limits = {pnu: (limit.low, limit.high, limit.scale, limit.step) for pnu, limit in write.WRITABLE.items()}
    # The controller's own ranges - the narrow targets are the caller's.
    assert limits[11180] == (5.0, 40.0, 10, 0.5)
    assert limits[11181] == (5.0, 40.0, 10, 0.5)
    assert all(limits[pnu] == (10, 150, 1, 1) for pnu in write.CURVE)
    assert limits[11178] == (10, 150, 1, 1)


@pytest.mark.parametrize(
    "pnu",
    # The slope (recomputes every point), the modes, the clock, the hot water,
    # the minimum flow, an output - never.
    [11175, 4201, 4202, 11177, 12190, 12191, 11043, 1000, 4006, 64, 0, 99999],
)
def test_a_parameter_off_the_list_is_refused(pnu: int) -> None:
    with pytest.raises(Refused, match="nie jest na liście"):
        write.to_raw(pnu, 21.0)


@pytest.mark.parametrize(
    ("pnu", "value", "raw"),
    [
        (11180, 5.0, 50),
        (11180, 21.5, 215),
        (11180, 25.0, 250),
        (11180, 40.0, 400),
        (11181, 16.0, 160),
        (11400, 75, 75),
        (11405, 10, 10),
        (11400, 150, 150),
        (11178, 50, 50),
        (11178, 90, 90),
    ],
)
def test_values_inside_the_limits(pnu: int, value: float, raw: int) -> None:
    assert write.to_raw(pnu, value) == raw


@pytest.mark.parametrize(
    ("pnu", "value", "match"),
    [
        (11180, 4.5, "poza granicami"),
        (11180, 40.5, "poza granicami"),
        (11180, 21.3, "wielokrotnością"),
        (11181, 4.5, "poza granicami"),
        (11181, 41.0, "poza granicami"),
        (11400, 151, "poza granicami"),
        (11403, 9, "poza granicami"),
        (11404, 37.5, "wielokrotnością"),
        (11178, 9, "poza granicami"),
        (11178, 151, "poza granicami"),
    ],
)
def test_values_outside_the_limits_are_refused(pnu: int, value: float, match: str) -> None:
    with pytest.raises(Refused, match=match):
        write.to_raw(pnu, value)


def test_saving_never_above_comfort() -> None:
    current = CURRENT | {11180: 210, 11181: 190}
    write.check_against(11181, 210, current)
    with pytest.raises(Refused, match="oszczędna"):
        write.check_against(11181, 215, current)
    # Comfort below the saving one: lower the saving one first.
    with pytest.raises(Refused, match="najpierw obniż 11181"):
        write.check_against(11180, 185, current)
    write.check_against(11180, 190, current)


def test_the_curve_never_rises_with_the_outdoor_temperature() -> None:
    # Lowering the factory curve from the warm end works point by point.
    current = dict(CURRENT)
    for pnu, raw in zip(reversed(write.CURVE), (27, 33, 35, 36, 38, 40), strict=True):
        write.check_against(pnu, raw, current)
        current[pnu] = raw
    assert [current[pnu] for pnu in write.CURVE] == [40, 38, 36, 35, 33, 27]
    # From the cold end it would cross the warmer point.
    with pytest.raises(Refused, match="od najcieplejszego"):
        write.check_against(11400, 40, CURRENT)
    # Raising above the colder point.
    with pytest.raises(Refused, match="od najzimniejszego"):
        write.check_against(11405, 41, CURRENT)


def test_never_above_the_owners_value() -> None:
    """The factory 75 °C at -30 °C comes down in steps (70, 65...) and may go
    back up to 75 - never above it."""

    ledger = write.Ledger()
    ledger.check_owner(11400, 75, 75)
    ledger.check_owner(11400, 70, 75)
    with pytest.raises(Refused, match="powyżej wartości właściciela"):
        ledger.check_owner(11400, 76, 75)
    ledger.record_write(11400, 70, 75, True, DAY)
    ledger.check_owner(11400, 65, 70)
    ledger.check_owner(11400, 75, 70)
    with pytest.raises(Refused, match=r"powyżej wartości właściciela \(75 °C\)"):
        ledger.check_owner(11400, 80, 70)
    # Room 25.0 °C of the owner: 21.0 is fine, 25.5 is not.
    ledger.check_owner(11180, 210, 250)
    with pytest.raises(Refused, match=r"25,5 °C powyżej wartości właściciela \(25,0 °C\)"):
        ledger.check_owner(11180, 255, 250)


def test_a_change_by_hand_is_the_new_owners_value() -> None:
    ledger = write.Ledger()
    ledger.record_write(11180, 210, 250, True, DAY)
    # Someone set 22.0 °C on the controller: 22.0 is now the owner's.
    ledger.check_owner(11180, 220, 220)
    with pytest.raises(Refused, match="powyżej"):
        ledger.check_owner(11180, 225, 220)
    # A control reading that differed is not a change by hand.
    ledger = write.Ledger()
    ledger.record_write(11403, 40, 45, False, DAY)
    ledger.check_owner(11403, 45, 44)
    with pytest.raises(Refused, match="powyżej"):
        ledger.check_owner(11403, 46, 44)


def test_once_a_day_per_parameter_and_ten_in_all() -> None:
    ledger = write.Ledger()
    ledger.allow_write(11180, 215, DAY)
    ledger.record_write(11180, 215, 250, True, DAY)
    with pytest.raises(Refused, match="już dziś"):
        ledger.allow_write(11180, 210, DAY)
    ledger.allow_write(11180, 210, NEXT_DAY)
    # Ten writes a day in all.
    ledger = write.Ledger()
    for n, pnu in enumerate((11180, 11181, *write.CURVE, 11178)):
        ledger.allow_write(pnu, 20 + n, DAY)
        ledger.record_write(pnu, 20 + n, 0, True, DAY)
    ledger.data["total"] = 10
    with pytest.raises(Refused, match="limit 10"):
        ledger.allow_write(11180, 200, DAY)
    ledger.allow_write(11180, 200, NEXT_DAY)


def test_one_repeat_after_a_control_reading_that_differs() -> None:
    ledger = write.Ledger()
    ledger.record_write(11180, 215, 250, False, DAY)
    # The same value again - allowed once; another value - no.
    with pytest.raises(Refused, match="już dziś"):
        ledger.allow_write(11180, 210, DAY)
    ledger.allow_write(11180, 215, DAY)
    ledger.record_write(11180, 215, 250, False, DAY)
    with pytest.raises(Refused, match="powtórzony"):
        ledger.allow_write(11180, 215, DAY)
    # The owner's copy stays the first value read.
    assert ledger.data["pnu"]["11180"]["original"] == 250


def test_the_maximum_flow_once() -> None:
    ledger = write.Ledger()
    ledger.allow_write(11178, 50, DAY)
    ledger.record_write(11178, 50, 90, True, DAY)
    with pytest.raises(Refused, match="jednorazowo"):
        ledger.allow_write(11178, 48, NEXT_DAY)
    assert ledger.restore_target(11178, 50) == 90
    ledger.record_restore(11178, True, NEXT_DAY)
    ledger.allow_write(11178, 50, "2026-11-20")


def test_restore_the_owners_value() -> None:
    ledger = write.Ledger()
    with pytest.raises(Refused, match="nie zmieniała"):
        ledger.restore_target(11180, 250)
    ledger.record_write(11180, 210, 250, True, DAY)
    ledger.record_write(11180, 205, 210, True, NEXT_DAY)
    # The copy is the value before the first write (25.0 °C - outside the
    # write limits, still restored: it is the owner's own setting).
    assert ledger.restore_target(11180, 205) == 250
    ledger.record_restore(11180, True, NEXT_DAY)
    with pytest.raises(Refused, match="nie zmieniała"):
        ledger.restore_target(11180, 250)


def test_a_change_by_hand_wins() -> None:
    ledger = write.Ledger()
    ledger.record_write(11180, 210, 250, True, DAY)
    # Someone set 22.0 °C on the controller: no restore, the record closes.
    with pytest.raises(Refused, match="zmieniono na regulatorze"):
        ledger.restore_target(11180, 220)
    assert ledger.data["pnu"]["11180"]["original"] is None
    # A write after a change by hand keeps the new value as the owner's copy.
    ledger.record_write(11180, 210, 250, True, DAY)
    ledger.record_write(11180, 205, 225, True, NEXT_DAY)
    assert ledger.restore_target(11180, 205) == 225


def test_restore_when_the_controller_has_the_value_already() -> None:
    ledger = write.Ledger()
    ledger.record_write(11181, 190, 250, True, DAY)
    assert ledger.restore_target(11181, 250) is None
    assert ledger.data["pnu"]["11181"]["original"] is None


def test_restore_after_a_control_reading_that_differs() -> None:
    """The controller kept another value than written: the restore still
    writes the owner's copy (not a change by hand)."""

    ledger = write.Ledger()
    ledger.record_write(11403, 40, 45, False, DAY)
    assert ledger.restore_target(11403, 44) == 45


def test_the_log_keeps_the_last_entries() -> None:
    ledger = write.Ledger()
    for n in range(write.LOG_SIZE + 5):
        ledger.note(f"t{n}", 11180, "write", value=n)
    assert len(ledger.data["log"]) == write.LOG_SIZE
    assert ledger.data["log"][0]["value"] == 5


def test_texts() -> None:
    assert write.text(11180, 215) == "21,5 °C"
    assert write.text(11403, 37) == "37 °C"
    assert write.text(11178, 50) == "50 °C"
