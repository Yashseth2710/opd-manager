"""The list of common tests, and how a value on a report is judged.

The list ships with the code rather than living in a table: it is short,
the same for every clinic, and only changes when the code does. What a
clinic has ordered that the list does not carry is found from its own
orders instead.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path
from typing import Any

from app.services.vitals import ADULT

SOURCE = Path(__file__).resolve().parents[1] / "data" / "lab-tests.json"


@dataclass(frozen=True)
class Part:
    name: str
    unit: str | None
    # Low and high for everyone, or for one sex. Either end can be open.
    both: tuple[float | None, float | None] | None
    male: tuple[float | None, float | None] | None
    female: tuple[float | None, float | None] | None
    expected: str | None

    @property
    def has_range(self) -> bool:
        return any((self.both, self.male, self.female))


@dataclass(frozen=True)
class Test:
    code: str
    name: str
    also: tuple[str, ...]
    category: str
    prepare: str | None
    parts: tuple[Part, ...]


def _pair(raw: Any) -> tuple[float | None, float | None] | None:
    if raw is None:
        return None
    low, high = raw
    return (low, high)


@cache
def _loaded() -> tuple[dict[str, str], dict[str, Test]]:
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    tests = {
        item["code"]: Test(
            code=item["code"],
            name=item["name"],
            also=tuple(item.get("also", ())),
            category=item["category"],
            prepare=item.get("prepare"),
            parts=tuple(
                Part(
                    name=part["name"],
                    unit=part.get("unit"),
                    both=_pair(part.get("range")),
                    male=_pair(part.get("male")),
                    female=_pair(part.get("female")),
                    expected=part.get("expected"),
                )
                for part in item["values"]
            ),
        )
        for item in raw["tests"]
    }
    return raw["categories"], tests


def categories() -> dict[str, str]:
    return _loaded()[0]


def tests() -> list[Test]:
    return list(_loaded()[1].values())


def find(code: str) -> Test | None:
    return _loaded()[1].get(code)


def named(name: str) -> Test | None:
    """The listed test a typed name means, by its name or one it goes by, so
    "cbc" typed into the box is the same order as picking it."""
    wanted = " ".join(name.lower().split())
    for test in tests():
        if wanted == test.name.lower() or wanted in (other.lower() for other in test.also):
            return test
    return None


def template(
    test: Test, *, gender: str | None, age: int | None
) -> tuple[list[dict[str, Any]], bool]:
    """The lines a report of this test has, with the ranges that fit this
    patient. Ranges are left for the lab's report to supply for a child,
    whose normal depends on their age, and for somebody whose sex is not
    recorded where the range depends on it. Says whether any were left out."""
    adult = age is not None and age >= ADULT
    left_out = False
    lines = []
    for part in test.parts:
        span: tuple[float | None, float | None] | None = None
        if part.has_range:
            if not adult:
                left_out = True
            elif part.both is not None:
                span = part.both
            elif gender == "male":
                span = part.male
            elif gender == "female":
                span = part.female
            else:
                left_out = True
        lines.append(
            {
                "name": part.name,
                "unit": part.unit,
                "low": span[0] if span else None,
                "high": span[1] if span else None,
                "expected": part.expected,
            }
        )
    return lines, left_out


# --- Judging a value -----------------------------------------------------------

_NUMBER = re.compile(r"^([<>]=?|≤|≥)?\s*(-?\d+(?:\.\d+)?)$")

# The different ways a report says the same thing.
_SAME = {
    "negative": ("negative", "nil", "absent", "not detected", "none", "neg", "-ve", "not seen"),
    "non-reactive": ("non-reactive", "non reactive", "nonreactive", "nr"),
}


def _plain(word: str) -> str:
    said = " ".join(word.lower().replace(".", "").split())
    for meaning, ways in _SAME.items():
        if said in ways:
            return meaning
    return said


def reading(value: str) -> tuple[str | None, Decimal] | None:
    """The number in a value, and whether it was written as below or above
    it: "<0.5" is a value under half, not half. None for words."""
    match = _NUMBER.match(value.replace(",", "").strip())
    if not match:
        return None
    try:
        return match.group(1), Decimal(match.group(2))
    except InvalidOperation:
        return None


def judge(
    value: str, *, low: Decimal | None, high: Decimal | None, expected: str | None
) -> str | None:
    """High, low, abnormal, or nothing to say."""
    number = reading(value)
    if number is not None:
        bound, figure = number
        if bound in ("<", "<=", "≤"):
            # Somewhere under the figure: low only if all of that is.
            return "low" if low is not None and figure <= low else None
        if bound in (">", ">=", "≥"):
            return "high" if high is not None and figure >= high else None
        if high is not None and figure > high:
            return "high"
        if low is not None and figure < low:
            return "low"
        return None
    if expected and value.strip() and _plain(value) != _plain(expected):
        return "abnormal"
    return None
