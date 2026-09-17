"""Turns a validation failure into something a person can act on.

Pydantic writes for whoever is holding the schema. "value is not a valid
email address: An email address must have an @-sign." is precise and it is
not what somebody at a clinic reception desk should read, so the messages
that reach a form are written here instead.

Anything without an entry falls back to a tidied version of what Pydantic
said, which is worse copy but still true.
"""

from __future__ import annotations

from typing import Any

BY_TYPE: dict[str, str] = {
    "missing": "This is needed.",
    "string_too_short": "This is needed.",
    "literal_error": "Pick one of the options.",
    "enum": "Pick one of the options.",
    "bool_parsing": "That has to be yes or no.",
    "int_parsing": "That has to be a whole number.",
    "int_type": "That has to be a whole number.",
    "int_from_float": "That has to be a whole number.",
    "float_parsing": "That has to be a number.",
    "decimal_parsing": "That has to be an amount.",
    "string_type": "That has to be text.",
    "list_type": "That has to be a list.",
    "date_parsing": "That is not a date we can read.",
    "date_from_datetime_parsing": "That is not a date we can read.",
    "date_type": "That is not a date we can read.",
    "time_parsing": "That is not a time we can read.",
    "time_type": "That is not a time we can read.",
    "datetime_parsing": "That is not a date and time we can read.",
    "uuid_parsing": "That is not something we can look up.",
    "uuid_type": "That is not something we can look up.",
    "extra_forbidden": "This is not something you can set here.",
    # The pattern itself is a schema detail and spells out the allowed
    # values, which is not something an error should hand out.
    "string_pattern_mismatch": "That is not one of the values this takes.",
}

# Where the limit is part of the sentence, so the person knows what to change
# rather than only that they were wrong.
WITH_LIMIT: dict[str, str] = {
    "string_too_long": "Keep this to {max_length} characters.",
    "too_long": "That is more than {max_length} of them.",
    "too_short": "At least {min_items} needed.",
    "greater_than": "Has to be more than {gt}.",
    "greater_than_equal": "Has to be {ge} or more.",
    "less_than": "Has to be less than {lt}.",
    "less_than_equal": "Has to be {le} or less.",
    "decimal_max_places": "Two decimal places at most.",
}


def readable(error: dict[str, Any]) -> str:
    """One field's failure, said plainly."""
    kind = str(error.get("type", ""))
    context: dict[str, Any] = error.get("ctx") or {}

    # Email is a value_error like any other, and the one everybody meets.
    raw = str(error.get("msg", ""))
    if "email" in raw.lower():
        return "That does not look like an email address."

    template = WITH_LIMIT.get(kind)
    if template:
        try:
            return template.format(**context)
        except (KeyError, IndexError):
            pass

    plain = BY_TYPE.get(kind)
    if plain:
        return plain

    # Pydantic prefixes anything raised from a validator. Dropping the prefix
    # leaves the sentence the validator wrote, which was written for a person
    # and is better than anything that could be substituted for it.
    trimmed = raw.removeprefix("Value error, ").removeprefix("Assertion failed, ").strip()
    if not trimmed or (trimmed == raw.strip() and kind == "value_error"):
        return "That does not look right."
    return trimmed[0].upper() + trimmed[1:] if trimmed[0].islower() else trimmed
