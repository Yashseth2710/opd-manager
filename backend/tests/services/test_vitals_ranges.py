"""What reads as out of range, and for whom."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.models import Vitals
from app.services.vitals import assess


def reading(**values: Any) -> Vitals:
    return Vitals(**values)


class TestAnyAge:
    def test_a_fever_and_a_chill(self) -> None:
        assert assess(reading(temperature_c=Decimal("37.5")), 30)["flags"] == {
            "temperature": "high"
        }
        assert assess(reading(temperature_c=Decimal("37.4")), 30)["flags"] == {}
        assert assess(reading(temperature_c=Decimal("34.9")), 30)["flags"] == {
            "temperature": "low"
        }

    def test_oxygen_below_ninety_five(self) -> None:
        assert assess(reading(spo2_percent=94), 3)["flags"] == {"spo2": "low"}
        assert assess(reading(spo2_percent=95), 3)["flags"] == {}

    def test_sugar_is_read_against_when_it_was_taken(self) -> None:
        def flag(value: int, timing: str) -> str | None:
            flags: dict[str, str] = assess(
                reading(glucose_mg_dl=value, glucose_timing=timing), 40
            )["flags"]
            return flags.get("glucose")

        assert flag(125, "fasting") is None
        assert flag(126, "fasting") == "high"
        assert flag(139, "after_meal") is None
        assert flag(140, "after_meal") == "high"
        assert flag(199, "random") is None
        assert flag(200, "random") == "high"
        assert flag(69, "random") == "low"
        assert flag(70, "fasting") is None


class TestAdults:
    def test_pressure_high_on_either_number(self) -> None:
        def flag(systolic: int, diastolic: int) -> str | None:
            found = assess(reading(systolic_mmhg=systolic, diastolic_mmhg=diastolic), 45)
            flags: dict[str, str] = found["flags"]
            return flags.get("blood_pressure")

        assert flag(120, 80) is None
        assert flag(140, 80) == "high"
        assert flag(130, 90) == "high"
        assert flag(89, 70) == "low"
        assert flag(100, 59) == "low"

    def test_pulse_and_breathing(self) -> None:
        flags = assess(reading(pulse_bpm=101, respiratory_rate=21), 30)["flags"]
        assert flags == {"pulse": "high", "respiratory_rate": "high"}
        flags = assess(reading(pulse_bpm=59, respiratory_rate=11), 30)["flags"]
        assert flags == {"pulse": "low", "respiratory_rate": "low"}
        assert assess(reading(pulse_bpm=60, respiratory_rate=12), 30)["flags"] == {}

    def test_bmi_uses_the_cut_offs_for_indian_adults(self) -> None:
        def band(weight: str, height: str = "170") -> tuple[float | None, str | None]:
            found = assess(reading(weight_kg=Decimal(weight), height_cm=Decimal(height)), 30)
            return found["bmi"], found["bmi_band"]

        assert band("53") == (18.3, "underweight")
        assert band("60") == (20.8, "normal")
        assert band("68") == (23.5, "overweight")
        assert band("80") == (27.7, "obese")
        found = assess(reading(weight_kg=Decimal("80"), height_cm=Decimal("170")), 30)
        assert found["flags"] == {"bmi": "high"}

    def test_weight_alone_has_no_bmi(self) -> None:
        found = assess(reading(weight_kg=Decimal("70")), 30)
        assert found == {"bmi": None, "bmi_band": None, "flags": {}}


class TestChildren:
    def test_a_childs_pulse_pressure_and_breathing_are_not_judged_as_an_adults(self) -> None:
        values: dict[str, Any] = {
            "systolic_mmhg": 95,
            "diastolic_mmhg": 55,
            "pulse_bpm": 115,
            "respiratory_rate": 26,
            "weight_kg": Decimal("16"),
            "height_cm": Decimal("102"),
        }
        assert assess(reading(**values), 4) == {"bmi": None, "bmi_band": None, "flags": {}}

    def test_a_childs_fever_still_shows(self) -> None:
        found = assess(reading(temperature_c=Decimal("38.6"), pulse_bpm=130), 4)
        assert found["flags"] == {"temperature": "high"}

    def test_an_unknown_age_is_not_taken_for_an_adult(self) -> None:
        found = assess(reading(pulse_bpm=130, spo2_percent=90), None)
        assert found["flags"] == {"spo2": "low"}

    def test_eighteen_counts_as_grown_up(self) -> None:
        assert assess(reading(pulse_bpm=130), 18)["flags"] == {"pulse": "high"}
        assert assess(reading(pulse_bpm=130), 17)["flags"] == {}
