"""The parts of a patient record that are worked out rather than stored."""

from __future__ import annotations

import datetime as dt
from typing import get_args

import pytest

from app.models.patient import BLOOD_GROUPS, GENDERS, SEVERITIES
from app.schemas.patient import BloodGroup, Gender, Severity, normalised_phone
from app.services.patients import age_in_years, age_label

TODAY = dt.date(2026, 9, 17)


class TestAge:
    @pytest.mark.parametrize(
        ("born", "expected"),
        [
            (dt.date(1988, 4, 12), "38 y"),
            # The day before a birthday is still the year before it.
            (dt.date(1988, 9, 18), "37 y"),
            (dt.date(1988, 9, 17), "38 y"),
            (dt.date(2025, 3, 17), "18 mo"),
            (dt.date(2026, 8, 20), "28 d"),
            (dt.date(2026, 9, 17), "0 d"),
        ],
    )
    def test_it_is_written_the_way_it_is_said(self, born: dt.date, expected: str) -> None:
        assert age_label(born, TODAY) == expected

    def test_an_unknown_birthday_has_no_age(self) -> None:
        assert age_label(None, TODAY) is None
        assert age_in_years(None, TODAY) is None

    def test_a_date_in_the_future_produces_nothing_rather_than_a_negative(self) -> None:
        assert age_label(dt.date(2027, 1, 1), TODAY) is None

    def test_years_are_counted_from_the_birthday_not_the_year(self) -> None:
        assert age_in_years(dt.date(1988, 12, 31), TODAY) == 37
        assert age_in_years(dt.date(1988, 1, 1), TODAY) == 38


class TestPhoneNumbers:
    @pytest.mark.parametrize(
        ("typed", "stored"),
        [
            ("+91 98200-11223", "+919820011223"),
            ("(022) 2555 0100", "02225550100"),
            ("9820011223", "9820011223"),
            ("   ", None),
            ("", None),
            (None, None),
        ],
    )
    def test_punctuation_is_dropped(self, typed: str | None, stored: str | None) -> None:
        assert normalised_phone(typed) == stored

    def test_the_country_code_survives(self) -> None:
        """Dropping the plus would turn +91 into a local prefix and quietly
        change whose number it is."""
        assert normalised_phone("+1 415 555 0142") == "+14155550142"


class TestValueSets:
    """The API schema spells these out so the generated documentation lists
    them. This holds the two copies in step."""

    def test_they_match_what_the_column_accepts(self) -> None:
        assert get_args(Gender) == GENDERS
        assert get_args(BloodGroup) == BLOOD_GROUPS
        assert get_args(Severity) == SEVERITIES


class TestDuplicateCandidateShape:
    """The screen renders a suspected duplicate with the same component it
    uses for a row in the patient list, so the two shapes have to agree."""

    def test_it_carries_a_list_row_plus_a_reason(self) -> None:
        from app.schemas.patient import DuplicateCandidate

        built = set(_candidate_keys())
        declared = set(DuplicateCandidate.model_fields)
        assert built == declared


def _candidate_keys() -> list[str]:
    import datetime as dt
    import uuid

    from app.models.patient import Patient
    from app.repositories.patients import Listed
    from app.services.patients import describe_candidates

    patient = Patient(
        id=uuid.uuid4(),
        patient_number="PT-000001",
        first_name="Aarti",
        last_name="Deshmukh",
        status="active",
    )
    patient.created_at = dt.datetime.now(dt.UTC)
    described = describe_candidates(
        [Listed(patient=patient, allergy_count=0)], phone=None, email=None
    )
    return list(described[0])


class TestSearchPatterns:
    def test_wildcards_are_escaped_before_they_reach_like(self) -> None:
        from app.repositories.patients import _literal

        assert _literal("100%") == r"100\%"
        assert _literal("a_b") == r"a\_b"
        assert _literal("Aarti") == "Aarti"
