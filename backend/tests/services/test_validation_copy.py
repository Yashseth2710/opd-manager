"""What a refused form actually says.

Pydantic writes for whoever is holding the schema. The person reading these
messages is at a reception desk with a queue behind them, so the test here is
that nothing machine-shaped reaches them, and that a validator which took the
trouble to write a sentence keeps it.
"""

from __future__ import annotations

from typing import Any

from app.core.messages import readable


def error(kind: str, message: str = "", **context: Any) -> dict[str, Any]:
    return {"type": kind, "msg": message, "ctx": context}


class TestPlainLanguage:
    def test_an_address_without_an_at_sign(self) -> None:
        said = readable(
            error(
                "value_error",
                "value is not a valid email address: An email address must have an @-sign.",
            )
        )
        assert said == "That does not look like an email address."

    def test_a_missing_field_says_it_is_needed(self) -> None:
        assert readable(error("missing", "Field required")) == "This is needed."

    def test_a_length_limit_names_the_limit(self) -> None:
        said = readable(
            error("string_too_long", "String should have at most 80 characters", max_length=80)
        )
        assert said == "Keep this to 80 characters."

    def test_a_range_names_the_bound(self) -> None:
        assert readable(error("greater_than_equal", "", ge=5)) == "Has to be 5 or more."
        assert readable(error("less_than_equal", "", le=240)) == "Has to be 240 or less."

    def test_a_date_that_cannot_be_read(self) -> None:
        said = readable(error("date_from_datetime_parsing", "Input should be a valid date"))
        assert said == "That is not a date we can read."


class TestWhatIsNotSaid:
    def test_a_pattern_is_not_handed_back(self) -> None:
        """It is a schema detail, and it spells out the values the field
        takes, which is not something a refusal should give away."""
        said = readable(
            error(
                "string_pattern_mismatch",
                "String should match pattern '^(active|archived|all)$'",
                pattern="^(active|archived|all)$",
            )
        )
        assert "^" not in said
        assert "archived" not in said

    def test_nothing_reaches_a_form_still_calling_it_a_value(self) -> None:
        for kind in ("int_parsing", "uuid_parsing", "literal_error", "bool_parsing"):
            said = readable(error(kind, "Input should be a valid something"))
            assert not said.startswith("Input should")
            assert said.endswith(".")


class TestValidatorsKeepTheirWords:
    def test_a_sentence_written_for_a_person_survives(self) -> None:
        """The phone check writes its own message. Replacing it with
        something generic would throw away the better copy."""
        said = readable(
            error("value_error", "Value error, Enter a phone number with 7 to 15 digits.")
        )
        assert said == "Enter a phone number with 7 to 15 digits."

    def test_something_opaque_from_a_library_does_not_leak(self) -> None:
        said = readable(error("value_error", "unparseable internal representation"))
        assert said == "That does not look right."

    def test_an_unmapped_kind_still_answers_in_a_sentence(self) -> None:
        said = readable(error("some_new_pydantic_type", "the thing was wrong"))
        assert said == "The thing was wrong"
