"""Reading patient records.

Everything here goes through the scoped repository, so a record belonging to
another clinic reads as absent rather than forbidden.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import ACTIVE, ARCHIVED, Patient, PatientAllergy
from app.repositories.base import TenantScopedRepository

# Matches the expression the trigram index is built on, which is what lets
# the contains-match below use an index despite its leading wildcard. If one
# changes and the other does not, search still works and quietly starts
# scanning instead.
FULL_NAME = func.lower(Patient.first_name + " " + Patient.last_name)

# Search compares the typed term against the closest run of words in the
# name rather than against the whole of it, because somebody searching
# "deshmuk" has typed part of a name, not a bad version of all of it. On the
# names in this register that scores 0.875 where whole-string similarity
# scores 0.438, and 0.6 is where a partial name still matches while an
# unrelated one stays at zero. Written as a function rather than as the
# operator that would use the index, because the operator takes its threshold
# from a server setting, and a search that quietly loosens when somebody
# changes that is worse than scanning one clinic's few thousand rows.
SEARCH_SIMILARITY = 0.6

# Duplicate detection compares one whole name against another, so the
# whole-string measure is the right one there.
DUPLICATE_SIMILARITY = 0.45

_NON_DIGITS = re.compile(r"\D")
LIKE_ESCAPE = "\\"
_LIKE_WILDCARDS = (LIKE_ESCAPE, "%", "_")


def _literal(term: str) -> str:
    """Escapes what LIKE would otherwise read as a pattern.

    Without this a search for a bare % returns the whole register, which is
    surprising rather than dangerous, and a name containing an underscore
    matches names that do not.
    """
    escaped = term
    for character in _LIKE_WILDCARDS:
        escaped = escaped.replace(character, LIKE_ESCAPE + character)
    return escaped


@dataclass(frozen=True)
class Listed:
    patient: Patient
    allergy_count: int


def _allergy_count() -> ColumnElement[int]:
    return (
        select(func.count())
        .select_from(PatientAllergy)
        .where(PatientAllergy.patient_id == Patient.id)
        .correlate(Patient)
        .scalar_subquery()
    )


class PatientRepository(TenantScopedRepository[Patient]):
    model = Patient

    def _conditions(self, *, query: str, status: str | None) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if status in (ACTIVE, ARCHIVED):
            conditions.append(Patient.status == status)

        term = query.strip()
        if not term:
            return conditions

        lowered = term.lower()
        like = f"%{_literal(lowered)}%"
        alternatives: list[ColumnElement[bool]] = [
            FULL_NAME.like(like, escape="\\"),
            func.lower(Patient.preferred_name).like(like, escape="\\"),
            Patient.patient_number.ilike(f"%{_literal(term)}%", escape="\\"),
            func.word_similarity(lowered, FULL_NAME) > SEARCH_SIMILARITY,
        ]

        digits = _NON_DIGITS.sub("", term)
        # Four is where a run of numbers stops being a fragment of every
        # record and starts being somebody's phone number.
        if len(digits) >= 4:
            alternatives.append(Patient.phone.like(f"%{digits}%"))
            alternatives.append(Patient.alternate_phone.like(f"%{digits}%"))
        if "@" in term:
            alternatives.append(func.lower(Patient.email).like(like, escape="\\"))

        conditions.append(or_(*alternatives))
        return conditions

    async def search(
        self,
        *,
        query: str = "",
        status: str | None = ACTIVE,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[Listed], int]:
        conditions = self._conditions(query=query, status=status)

        counted = (
            select(func.count())
            .select_from(Patient)
            .where(Patient.organization_id == self.organization_id)
        )
        for condition in conditions:
            counted = counted.where(condition)
        total = int((await self.session.execute(counted)).scalar_one())

        statement: Select[tuple[Patient, int]] = select(Patient, _allergy_count()).where(
            Patient.organization_id == self.organization_id
        )
        for condition in conditions:
            statement = statement.where(condition)

        term = query.strip().lower()
        if term:
            # Closest match first: somebody searching a name expects the
            # person they meant at the top, not the oldest record that
            # happened to match.
            order = [
                func.word_similarity(term, FULL_NAME).desc(),
                Patient.last_name,
                Patient.first_name,
            ]
        else:
            order = [Patient.created_at.desc()]

        # Two people registered in the same second share a timestamp, and an
        # order with ties is not an order: the second page can repeat a row
        # the first already showed. The key breaks every tie, and being a
        # UUIDv7 it breaks them in the order the rows were created.
        statement = statement.order_by(*order, Patient.id.desc())

        rows = await self.session.execute(statement.limit(limit).offset(offset))
        return [Listed(patient=row[0], allergy_count=row[1]) for row in rows.all()], total

    async def with_allergy_count(self, patient_id: uuid.UUID) -> Listed | None:
        result = await self.session.execute(
            select(Patient, _allergy_count())
            .where(Patient.organization_id == self.organization_id)
            .where(Patient.id == patient_id)
        )
        row = result.first()
        return Listed(patient=row[0], allergy_count=row[1]) if row else None

    async def possible_duplicates(
        self,
        *,
        first_name: str = "",
        last_name: str = "",
        phone: str | None = None,
        email: str | None = None,
        date_of_birth: dt.date | None = None,
        exclude_id: uuid.UUID | None = None,
        limit: int = 5,
    ) -> list[Listed]:
        """Advisory only.

        Three signals, any one of which is worth a second look: the same
        phone, the same email, or a name close enough to be the same person
        born on the same day. Nothing is merged and nothing is refused on the
        strength of this. The person at the desk decides.
        """
        signals: list[ColumnElement[bool]] = []

        if phone:
            signals.append(or_(Patient.phone == phone, Patient.alternate_phone == phone))
        if email:
            signals.append(func.lower(Patient.email) == email.lower())

        name = f"{first_name} {last_name}".strip().lower()
        if name and date_of_birth is not None:
            signals.append(
                and_(
                    Patient.date_of_birth == date_of_birth,
                    func.similarity(FULL_NAME, name) > DUPLICATE_SIMILARITY,
                )
            )

        if not signals:
            return []

        statement = (
            select(Patient, _allergy_count())
            .where(Patient.organization_id == self.organization_id)
            .where(or_(*signals))
        )
        if exclude_id is not None:
            statement = statement.where(Patient.id != exclude_id)

        rows = await self.session.execute(
            statement.order_by(Patient.created_at.desc()).limit(limit)
        )
        return [Listed(patient=row[0], allergy_count=row[1]) for row in rows.all()]


class AllergyRepository(TenantScopedRepository[PatientAllergy]):
    model = PatientAllergy

    async def for_patient(self, patient_id: uuid.UUID) -> list[PatientAllergy]:
        # Severe first. The reason this list exists is the one line somebody
        # needs to read before they write a prescription.
        ranked = case(
            (PatientAllergy.severity == "severe", 0),
            (PatientAllergy.severity == "moderate", 1),
            else_=2,
        )
        result = await self.session.execute(
            self.query()
            .where(PatientAllergy.patient_id == patient_id)
            .order_by(ranked, PatientAllergy.substance)
        )
        return list(result.scalars().all())

    async def belonging_to(
        self, patient_id: uuid.UUID, allergy_id: uuid.UUID
    ) -> PatientAllergy | None:
        result = await self.session.execute(
            self.query()
            .where(PatientAllergy.patient_id == patient_id)
            .where(PatientAllergy.id == allergy_id)
        )
        return result.scalar_one_or_none()


async def names_of(session: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Who registered a record, resolved in one query rather than per row."""
    if not user_ids:
        return {}

    from app.models import User

    result = await session.execute(
        select(User.id, User.first_name, User.last_name).where(User.id.in_(user_ids))
    )
    return {row[0]: f"{row[1]} {row[2]}".strip() for row in result.all()}
