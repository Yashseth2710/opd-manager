"""The prescription as the patient takes it away: one A4 page, printed or sent.

Laid out the way an Indian prescription pad is read: the clinic and the
doctor's registration across the top, the patient and the date beneath, then
the medicines, each with its dose, when to take it and for how long. A
prescription that has been replaced says so above everything else, because a
copy of it may still turn up at a pharmacy.
"""

from __future__ import annotations

import datetime as dt
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"

INK = colors.HexColor("#15304A")
MUTED = colors.HexColor("#4E5A66")
RULE = colors.HexColor("#C2CDD6")
WARNING = colors.HexColor("#A32E2B")

TIMING_WORDS = {
    "before_food": "Before food",
    "after_food": "After food",
    "with_food": "With food",
    "empty_stomach": "Empty stomach",
    "bedtime": "At bedtime",
    "as_needed": "When needed",
}


@cache
def _fonts() -> None:
    pdfmetrics.registerFont(TTFont("Plex", str(FONTS / "IBMPlexSans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Plex-SemiBold", str(FONTS / "IBMPlexSans-SemiBold.ttf")))
    pdfmetrics.registerFont(TTFont("Plex-Mono", str(FONTS / "IBMPlexMono-Regular.ttf")))


def _style(name: str, **overrides: Any) -> ParagraphStyle:
    base: dict[str, Any] = {
        "fontName": "Plex",
        "fontSize": 9.5,
        "leading": 13,
        "textColor": INK,
    }
    base.update(overrides)
    return ParagraphStyle(name, **base)


def _text(value: str | None) -> str:
    """Escaped for the paragraph markup, with the doctor's line breaks kept."""
    return escape(value or "").replace("\n", "<br/>")


def _day(value: dt.date) -> str:
    return f"{value:%a} {value.day} {value:%b %Y}"


def _moment(value: dt.datetime) -> str:
    """ "19 Sep 2026, 12:55 am", the way the rest of the clinic writes it."""
    hour = value.hour % 12 or 12
    noon = "am" if value.hour < 12 else "pm"
    return f"{value.day} {value:%b %Y}, {hour}:{value.minute:02d} {noon}"


def _gender(value: str | None) -> str | None:
    return {"male": "Male", "female": "Female", "other": "Other"}.get(value or "", value)


def render(found: dict[str, Any], *, issued_local: dt.datetime | None) -> bytes:
    """The whole page for one prescription, as the detail endpoint shapes it."""
    _fonts()
    buffer = BytesIO()
    number = found["number"] or ""
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Prescription {number}",
        author=found["doctor"]["display_name"],
        subject=f"Prescription for {found['patient']['full_name']}",
        creator=found["clinic"]["name"],
    )

    clinic_name = _style("clinic", fontName="Plex-SemiBold", fontSize=15, leading=19)
    small = _style("small", fontSize=8.5, leading=11.5, textColor=MUTED)
    small_right = _style(
        "small-right", fontSize=8.5, leading=11.5, textColor=MUTED, alignment=2
    )
    doctor_style = _style(
        "doctor", fontName="Plex-SemiBold", fontSize=11, leading=14, alignment=2
    )
    label = _style("label", fontSize=8, leading=10, textColor=MUTED)
    value = _style("value", fontName="Plex-SemiBold", fontSize=10, leading=13)
    mono = _style("mono", fontName="Plex-Mono", fontSize=9.5, leading=13)
    heading = _style("heading", fontName="Plex-SemiBold", fontSize=18, leading=22)
    cell = _style("cell", fontSize=9.5, leading=12.5)
    cell_strong = _style("cell-strong", fontName="Plex-SemiBold", fontSize=10, leading=13)
    cell_muted = _style("cell-muted", fontSize=8.5, leading=11, textColor=MUTED)
    head_cell = _style("head-cell", fontSize=8, leading=10, textColor=MUTED)
    body = _style("body", fontSize=10, leading=14)

    story: list[Any] = []

    if found["status"] == "replaced":
        replaced_by = found["replaced_by"]
        story.append(
            Paragraph(
                "Replaced"
                + (f" by {escape(replaced_by['number'] or '')}" if replaced_by else "")
                + ". Do not dispense from this copy.",
                _style("void", fontName="Plex-SemiBold", fontSize=11, textColor=WARNING),
            )
        )
        story.append(Spacer(1, 4 * mm))

    clinic = found["clinic"]
    reach = ", ".join(part for part in (clinic["phone"], clinic["email"]) if part)
    doctor = found["doctor"]
    left = [Paragraph(_text(clinic["name"]), clinic_name)]
    left += [Paragraph(_text(line), small) for line in clinic["address"]]
    if reach:
        left.append(Paragraph(_text(reach), small))
    right = [Paragraph(_text(doctor["display_name"]), doctor_style)]
    for line in (doctor["qualifications"], doctor["speciality"]):
        if line:
            right.append(Paragraph(_text(line), small_right))
    if doctor["registration_number"]:
        right.append(Paragraph(f"Reg. no. {_text(doctor['registration_number'])}", small_right))
    header = Table([[left, right]], colWidths=["58%", "42%"])
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story += [header, Spacer(1, 4 * mm), HRFlowable(width="100%", color=RULE, thickness=0.8)]

    patient = found["patient"]
    facts = ", ".join(
        part
        for part in (patient["age"], _gender(patient["gender"]), patient["patient_number"])
        if part
    )
    when = issued_local or dt.datetime.combine(found["visit_date"], dt.time())
    identity = Table(
        [
            [
                [Paragraph("Patient", label), Paragraph(_text(patient["full_name"]), value)],
                [Paragraph("Date", label), Paragraph(_day(when.date()), value)],
                [Paragraph("Prescription", label), Paragraph(escape(number), mono)],
            ],
            [Paragraph(_text(facts), small), "", ""],
        ],
        colWidths=["50%", "25%", "25%"],
    )
    identity.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story += [Spacer(1, 4 * mm), identity, Spacer(1, 5 * mm), Paragraph("Rx", heading)]

    if found["items"]:
        rows: list[list[Any]] = [
            [
                Paragraph("", head_cell),
                Paragraph("Medicine", head_cell),
                Paragraph("Dose", head_cell),
                Paragraph("When", head_cell),
                Paragraph("For", head_cell),
            ]
        ]
        for index, item in enumerate(found["items"], start=1):
            medicine = [Paragraph(_text(item["medicine_name"]), cell_strong)]
            if item["presentation"]:
                medicine.append(Paragraph(_text(item["presentation"]), cell_muted))
            if item["instructions"]:
                medicine.append(Paragraph(_text(item["instructions"]), cell_muted))
            days = item["duration_days"]
            rows.append(
                [
                    Paragraph(str(index), cell_muted),
                    medicine,
                    Paragraph(_text(item["dose"]), mono),
                    Paragraph(TIMING_WORDS.get(item["timing"] or "", ""), cell),
                    Paragraph(
                        "" if days is None else f"{days} day{'s' if days != 1 else ''}", cell
                    ),
                ]
            )
        table = Table(rows, colWidths=["6%", "46%", "16%", "18%", "14%"], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.8, RULE),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 1), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(table)

    if found["instructions"]:
        story += [
            Spacer(1, 6 * mm),
            KeepTogether(
                [Paragraph("Advice", label), Paragraph(_text(found["instructions"]), body)]
            ),
        ]
    if found["follow_up_date"]:
        story += [
            Spacer(1, 5 * mm),
            Paragraph(f"Come back on <b>{_day(found['follow_up_date'])}</b>.", body),
        ]
    if found["replaces"]:
        story += [
            Spacer(1, 4 * mm),
            Paragraph(
                f"Replaces {escape(found['replaces']['number'] or '')}"
                + (
                    f": {_text(found['correction_reason'])}"
                    if found["correction_reason"]
                    else "."
                ),
                small,
            ),
        ]

    signed = [
        Spacer(1, 16 * mm),
        HRFlowable(width="38%", color=INK, thickness=0.6, hAlign="RIGHT"),
        Paragraph(_text(doctor["display_name"]), small_right),
    ]
    if issued_local:
        signed.append(Paragraph(f"Issued {_moment(issued_local)}", small_right))
    story.append(KeepTogether(signed))

    document.build(story)
    return buffer.getvalue()
