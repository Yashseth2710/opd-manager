"""The list of common tests, and how a value on a report is judged."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services import lab_catalogue as catalogue


def judged(
    value: str, low: str | None = None, high: str | None = None, expected: str | None = None
) -> str | None:
    return catalogue.judge(
        value,
        low=Decimal(low) if low is not None else None,
        high=Decimal(high) if high is not None else None,
        expected=expected,
    )


class TestJudging:
    @pytest.mark.parametrize(
        ("value", "flag"),
        [
            ("11.9", "low"),
            ("12", None),
            ("13.4", None),
            ("15", None),
            ("15.1", "high"),
            (" 16 ", "high"),
            ("-1", "low"),
        ],
    )
    def test_a_number_against_its_range(self, value: str, flag: str | None) -> None:
        assert judged(value, "12", "15") == flag

    def test_a_range_open_at_one_end(self) -> None:
        assert judged("210", high="200") == "high"
        assert judged("5", high="200") is None
        assert judged("38", low="40") == "low"
        assert judged("400", low="40") is None

    def test_no_range_says_nothing(self) -> None:
        assert judged("9999") is None

    def test_thousands_written_with_commas(self) -> None:
        assert judged("4,50,000", "150000", "410000") == "high"
        assert judged("2,10,000", "150000", "410000") is None

    @pytest.mark.parametrize(
        ("value", "flag"),
        [
            # Somewhere below 11, which could be anywhere in the range.
            ("<11", None),
            ("<0.5", "low"),
            # Below 3 where 4 is the bottom: all of that is low.
            ("<3", "low"),
            ("< 4", "low"),
            ("<5", None),
            ("≤3", "low"),
            (">20", "high"),
            (">=11", "high"),
            ("> 10", None),
            ("≥ 25", "high"),
        ],
    )
    def test_a_number_written_as_below_or_above(self, value: str, flag: str | None) -> None:
        assert judged(value, "4", "11") == flag

    @pytest.mark.parametrize(
        ("value", "expected", "flag"),
        [
            ("Negative", "Negative", None),
            ("negative", "Negative", None),
            ("NIL", "Nil", None),
            ("Nil", "Negative", None),
            ("Absent", "Nil", None),
            ("Not detected", "Negative", None),
            ("Not seen", "Not seen", None),
            ("-ve", "Negative", None),
            ("Non reactive", "Non-reactive", None),
            ("NR", "Non-reactive", None),
            ("Positive", "Negative", "abnormal"),
            ("Trace", "Nil", "abnormal"),
            ("++", "Nil", "abnormal"),
            ("Reactive", "Non-reactive", "abnormal"),
            ("Slightly turbid", "Clear", "abnormal"),
            ("Clear", "Clear", None),
        ],
    )
    def test_a_word_against_the_word_it_should_be(
        self, value: str, expected: str, flag: str | None
    ) -> None:
        assert judged(value, expected=expected) == flag

    def test_a_word_where_nothing_is_expected(self) -> None:
        assert judged("Pale yellow") is None
        assert judged("B positive") is None
        assert judged("1:160") is None

    def test_a_range_typed_as_a_range_is_left_to_the_eye(self) -> None:
        assert judged("8-10", "0", "5") is None


class TestTheList:
    def test_codes_and_names_are_distinct(self) -> None:
        tests = catalogue.tests()
        codes = [test.code for test in tests]
        assert len(codes) == len(set(codes))
        names = [test.name.lower() for test in tests]
        assert len(names) == len(set(names))
        # A name one test goes by must not be another test's name, or typing
        # it would order the wrong thing.
        also = [other.lower() for test in tests for other in test.also]
        assert len(also) == len(set(also))
        assert not set(also) & set(names)

    def test_every_test_is_filed_somewhere_that_exists(self) -> None:
        for test in catalogue.tests():
            assert test.category in catalogue.categories(), test.code

    def test_every_range_runs_the_right_way(self) -> None:
        for test in catalogue.tests():
            names = [part.name.lower() for part in test.parts]
            assert len(names) == len(set(names)), test.code
            for part in test.parts:
                for span in (part.both, part.male, part.female):
                    if span is None:
                        continue
                    low, high = span
                    assert low is not None or high is not None, (test.code, part.name)
                    if low is not None and high is not None:
                        assert low < high, (test.code, part.name)
                # A range for one sex only would leave the other with none.
                assert (part.male is None) == (part.female is None), (test.code, part.name)
                assert not (part.both and part.male), (test.code, part.name)

    def test_names_find_their_test(self) -> None:
        assert catalogue.named("CBC").code == "cbc"  # type: ignore[union-attr]
        assert catalogue.named("  lipid   profile ").code == "lipid"  # type: ignore[union-attr]
        assert catalogue.named("Thyroid profile").code == "thyroid"  # type: ignore[union-attr]
        assert catalogue.named("Serum amylase") is None


class TestTheLinesToFillIn:
    def test_an_adult_gets_the_ranges_for_their_sex(self) -> None:
        kft = catalogue.find("kft")
        assert kft is not None
        for gender, creatinine in (("male", (0.7, 1.3)), ("female", (0.6, 1.1))):
            lines, left_out = catalogue.template(kft, gender=gender, age=40)
            found = {line["name"]: line for line in lines}
            assert (found["Creatinine"]["low"], found["Creatinine"]["high"]) == creatinine
            assert (found["Sodium"]["low"], found["Sodium"]["high"]) == (136, 145)
            assert left_out is False

    def test_eighteen_is_an_adult(self) -> None:
        tsh = catalogue.find("tsh")
        assert tsh is not None
        assert catalogue.template(tsh, gender="female", age=18)[0][0]["high"] == 4.2
        lines, left_out = catalogue.template(tsh, gender="female", age=17)
        assert (lines[0]["low"], lines[0]["high"], left_out) == (None, None, True)

    def test_no_age_recorded_is_treated_like_a_child(self) -> None:
        tsh = catalogue.find("tsh")
        assert tsh is not None
        lines, left_out = catalogue.template(tsh, gender="male", age=None)
        assert (lines[0]["high"], left_out) == (None, True)

    def test_a_test_without_ranges_leaves_nothing_out(self) -> None:
        malaria = catalogue.find("malaria")
        assert malaria is not None
        lines, left_out = catalogue.template(malaria, gender=None, age=3)
        assert [line["expected"] for line in lines] == ["Negative", "Negative"]
        assert left_out is False
