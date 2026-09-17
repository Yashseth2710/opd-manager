"""The rules behind a rota, without a database in the way.

Overlap and slot arithmetic are the parts that decide whether two people end
up in one chair, so they are worth testing directly rather than only through
the routes that use them.
"""

from __future__ import annotations

import datetime as dt
from typing import get_args

import pytest

from app.core.exceptions import ValidationFailed
from app.models.doctor import DAY_NAMES, TITLES, DoctorLeave
from app.schemas.doctor import LeaveWrite, ScheduleBlock, Title, tidy_languages
from app.services.doctors import check_blocks, check_leave, describe_leave

MONDAY = 0
TUESDAY = 1


def at(value: str) -> dt.time:
    hours, minutes = value.split(":")
    return dt.time(int(hours), int(minutes))


def block(
    day: int = MONDAY, start: str = "09:00", end: str = "13:00", **rest: object
) -> ScheduleBlock:
    return ScheduleBlock(
        day_of_week=day,
        start_time=at(start),
        end_time=at(end),
        break_start=at(str(rest["break_start"])) if "break_start" in rest else None,
        break_end=at(str(rest["break_end"])) if "break_end" in rest else None,
        slot_duration_minutes=rest.get("slot"),  # type: ignore[arg-type]
    )


def problems(blocks: list[ScheduleBlock]) -> dict[str, str]:
    with pytest.raises(ValidationFailed) as raised:
        check_blocks(blocks)
    return raised.value.fields


class TestTheWeekHoldsTogether:
    def test_an_ordinary_week_passes(self) -> None:
        check_blocks([block(MONDAY), block(TUESDAY, "17:00", "20:00")])

    def test_an_empty_week_passes(self) -> None:
        """Clearing a rota is a thing somebody does on purpose."""
        check_blocks([])

    def test_two_blocks_over_the_same_hour_are_refused(self) -> None:
        found = problems([block(MONDAY, "09:00", "13:00"), block(MONDAY, "12:00", "15:00")])
        assert "Monday" in next(iter(found.values()))

    def test_a_block_inside_another_is_refused(self) -> None:
        found = problems([block(MONDAY, "09:00", "17:00"), block(MONDAY, "11:00", "12:00")])
        assert found

    def test_blocks_that_touch_are_allowed(self) -> None:
        """A morning ending at one and an afternoon starting at one is a
        normal week, not a double booking."""
        check_blocks([block(MONDAY, "09:00", "13:00"), block(MONDAY, "13:00", "17:00")])

    def test_the_same_hours_on_different_days_are_allowed(self) -> None:
        check_blocks([block(MONDAY), block(TUESDAY)])

    def test_the_problem_names_the_block_that_caused_it(self) -> None:
        """So the screen can put the message on the right row rather than at
        the top of a form with seven days on it."""
        found = problems(
            [
                block(MONDAY, "09:00", "13:00"),
                block(TUESDAY, "09:00", "13:00"),
                block(MONDAY, "12:00", "14:00"),
            ]
        )
        # Reported against the position in the sorted week, which is what the
        # editor lays the blocks out in.
        assert any(key.startswith("blocks.") for key in found)


class TestBreaks:
    def test_a_break_inside_the_hours_is_fine(self) -> None:
        check_blocks([block(MONDAY, "09:00", "17:00", break_start="13:00", break_end="14:00")])

    def test_a_break_outside_them_is_refused(self) -> None:
        found = problems(
            [block(MONDAY, "09:00", "12:00", break_start="14:00", break_end="15:00")]
        )
        assert "blocks.0.break_start" in found

    def test_a_break_that_ends_before_it_starts_is_refused(self) -> None:
        found = problems(
            [block(MONDAY, "09:00", "17:00", break_start="14:00", break_end="13:00")]
        )
        assert "blocks.0.break_end" in found


class TestSlotsHaveToFit:
    def test_a_block_shorter_than_one_appointment_is_refused(self) -> None:
        found = problems([block(MONDAY, "09:00", "09:10", slot=30)])
        assert "30-minute" in found["blocks.0.end_time"]

    def test_exactly_one_appointment_long_is_fine(self) -> None:
        check_blocks([block(MONDAY, "09:00", "09:30", slot=30)])


class TestLeave:
    def test_one_day_off_fills_in_its_own_end(self) -> None:
        ends = check_leave(LeaveWrite(starts_on=dt.date(2026, 10, 2)))
        assert ends == dt.date(2026, 10, 2)

    def test_leave_cannot_end_before_it_starts(self) -> None:
        with pytest.raises(ValidationFailed) as raised:
            check_leave(
                LeaveWrite(starts_on=dt.date(2026, 10, 10), ends_on=dt.date(2026, 10, 2))
            )
        assert "ends_on" in raised.value.fields

    def test_half_a_time_range_is_refused(self) -> None:
        with pytest.raises(ValidationFailed):
            check_leave(LeaveWrite(starts_on=dt.date(2026, 10, 2), start_time=at("14:00")))

    def test_it_reads_as_a_sentence(self) -> None:
        today = dt.date(2026, 9, 17)
        one_day = DoctorLeave(starts_on=today, ends_on=today, reason="Conference")
        assert describe_leave(one_day, today) == "On leave today — Conference"

        longer = DoctorLeave(starts_on=today, ends_on=dt.date(2026, 10, 4), reason=None)
        assert describe_leave(longer, today) == "On leave until 4 October"

    def test_leave_crossing_a_year_says_which_year(self) -> None:
        today = dt.date(2026, 12, 20)
        leave = DoctorLeave(starts_on=today, ends_on=dt.date(2027, 1, 4), reason=None)
        assert describe_leave(leave, today) == "On leave until 4 January 2027"


class TestTheseStayInStep:
    def test_the_schema_lists_the_titles_the_model_holds(self) -> None:
        assert get_args(Title) == TITLES

    def test_there_are_seven_days_named_from_monday(self) -> None:
        assert len(DAY_NAMES) == 7
        assert DAY_NAMES[0] == "Monday"
        # Python counts weekdays the same way, which is what keeps the
        # conversion at availability time to nothing at all.
        assert dt.date(2026, 9, 14).weekday() == 0


class TestLanguages:
    def test_duplicates_and_blanks_are_dropped(self) -> None:
        assert tidy_languages(["Hindi", " hindi ", "Marathi", "  "]) == ["Hindi", "Marathi"]

    def test_nothing_left_means_none_at_all(self) -> None:
        assert tidy_languages(["", "   "]) is None

    def test_absent_stays_absent(self) -> None:
        assert tidy_languages(None) is None
