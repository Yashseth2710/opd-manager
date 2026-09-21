"""The bill as the patient takes it away: one A4 page, printed or sent.

The clinic across the top with its GSTIN when it has one, the bill's number
and date beside it, then who it is for, what was charged, and the sums. What
was paid, and how, sits underneath, so the same sheet serves as the receipt.
A voided bill says so above everything else, since a copy may turn up later.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models import Organization
from app.services.billing import rupees
from app.services.prescription_pdf import INK, MUTED, RULE, WARNING, _fonts, _style, _text
from app.services.prescriptions import _address

METHOD_WORDS = {
    "cash": "Cash",
    "upi": "UPI",
    "card": "Card",
    "bank_transfer": "Bank transfer",
    "cheque": "Cheque",
    "other": "Other",
}


def _day(value: dt.date) -> str:
    return f"{value.day} {value:%b %Y}"


def _moment(value: dt.datetime) -> str:
    hour = value.hour % 12 or 12
    noon = "am" if value.hour < 12 else "pm"
    return f"{value.day} {value:%b %Y}, {hour}:{value.minute:02d} {noon}"


def _money(value: Any) -> str:
    return rupees(Decimal(str(value)))


def render(found: dict[str, Any], *, clinic: Organization, zone: dt.tzinfo) -> bytes:
    """The whole page for one issued bill, as the detail endpoint shapes it."""
    _fonts()
    buffer = BytesIO()
    number = found["invoice_number"] or ""
    patient = found["patient"]
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Bill {number}",
        author=clinic.name,
        subject=f"Bill for {patient['full_name']}",
        creator=clinic.name,
    )

    clinic_name = _style("clinic", fontName="Plex-SemiBold", fontSize=15, leading=19)
    small = _style("small", fontSize=8.5, leading=11.5, textColor=MUTED)
    heading = _style("heading", fontName="Plex-SemiBold", fontSize=18, leading=22, alignment=2)
    label = _style("label", fontSize=8, leading=10, textColor=MUTED)
    label_right = _style("label-right", fontSize=8, leading=10, textColor=MUTED, alignment=2)
    value = _style("value", fontName="Plex-SemiBold", fontSize=10, leading=13)
    mono_right = _style(
        "mono-right", fontName="Plex-Mono", fontSize=10, leading=13, alignment=2
    )
    cell = _style("cell", fontSize=9.5, leading=12.5)
    cell_right = _style(
        "cell-right", fontName="Plex-Mono", fontSize=9.5, leading=12.5, alignment=2
    )
    cell_muted = _style("cell-muted", fontSize=8.5, leading=11, textColor=MUTED)
    head_cell = _style("head-cell", fontSize=8, leading=10, textColor=MUTED)
    head_right = _style("head-right", fontSize=8, leading=10, textColor=MUTED, alignment=2)
    sum_label = _style("sum-label", fontSize=9.5, leading=13, alignment=2)
    sum_value = _style("sum-value", fontName="Plex-Mono", fontSize=9.5, leading=13, alignment=2)
    total_label = _style(
        "total-label", fontName="Plex-SemiBold", fontSize=11, leading=15, alignment=2
    )
    total_value = _style(
        "total-value", fontName="Plex-SemiBold", fontSize=11, leading=15, alignment=2
    )
    body = _style("body", fontSize=9.5, leading=13.5)

    story: list[Any] = []

    if found["status"] == "void":
        story.append(
            Paragraph(
                "Void. This bill has been cancelled"
                + (f": {_text(found['void_reason'])}" if found["void_reason"] else ".")
                + " Nothing is owed on it.",
                _style("void", fontName="Plex-SemiBold", fontSize=11, textColor=WARNING),
            )
        )
        story.append(Spacer(1, 4 * mm))

    gstin = str(clinic.effective_settings.get("gstin") or "")
    reach = ", ".join(part for part in (clinic.phone, clinic.email) if part)
    left = [Paragraph(_text(clinic.name), clinic_name)]
    left += [Paragraph(_text(line), small) for line in _address(clinic)]
    if reach:
        left.append(Paragraph(_text(reach), small))
    if gstin:
        left.append(Paragraph(f"GSTIN {escape(gstin)}", small))
    issued = found["issued_at"].astimezone(zone) if found["issued_at"] else None
    right = [
        Paragraph("Bill", heading),
        Paragraph(escape(number), mono_right),
    ]
    if issued:
        right.append(Paragraph(_day(issued.date()), label_right))
    header = Table([[left, right]], colWidths=["62%", "38%"])
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

    facts = ", ".join(
        part for part in (patient["patient_number"], patient["age"], patient["phone"]) if part
    )
    doctor = found["doctor"]
    who: list[list[Any]] = [
        [
            [Paragraph("Billed to", label), Paragraph(_text(patient["full_name"]), value)],
            [
                Paragraph("Seen by", label),
                Paragraph(_text(doctor["display_name"]) if doctor else "", value),
            ],
        ],
        [Paragraph(_text(facts), small), ""],
    ]
    identity = Table(who, colWidths=["60%", "40%"])
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
    story += [Spacer(1, 4 * mm), identity, Spacer(1, 6 * mm)]

    rows: list[list[Any]] = [
        [
            Paragraph("", head_cell),
            Paragraph("Item", head_cell),
            Paragraph("Qty", head_right),
            Paragraph("Rate", head_right),
            Paragraph("Amount", head_right),
        ]
    ]
    for index, item in enumerate(found["items"], start=1):
        rows.append(
            [
                Paragraph(str(index), cell_muted),
                Paragraph(_text(item["description"]), cell),
                Paragraph(str(item["quantity"]), cell_right),
                Paragraph(_money(item["unit_price"]), cell_right),
                Paragraph(_money(item["amount"]), cell_right),
            ]
        )
    lines = Table(rows, colWidths=["6%", "52%", "8%", "17%", "17%"], repeatRows=1)
    lines.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, RULE),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 1), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(lines)

    sums: list[list[Any]] = []
    discount = Decimal(str(found["discount_amount"]))
    tax = Decimal(str(found["tax_amount"]))
    if discount > 0 or tax > 0:
        sums.append(
            [Paragraph("Subtotal", sum_label), Paragraph(_money(found["subtotal"]), sum_value)]
        )
    if discount > 0:
        why = f" ({_text(found['discount_reason'])})" if found["discount_reason"] else ""
        sums.append(
            [
                Paragraph(f"Discount{why}", sum_label),
                Paragraph(f"-{_money(discount)}", sum_value),
            ]
        )
    if tax > 0:
        rate = Decimal(str(found["tax_percent"])).normalize()
        name = "GST" if gstin else "Tax"
        sums.append(
            [Paragraph(f"{name} at {rate:f}%", sum_label), Paragraph(_money(tax), sum_value)]
        )
    at_total = len(sums)
    sums.append(
        [Paragraph("Total", total_label), Paragraph(_money(found["total"]), total_value)]
    )
    paid = Decimal(str(found["amount_paid"]))
    refunded = Decimal(str(found["refunded_amount"]))
    if found["status"] != "void":
        if paid > 0:
            sums.append([Paragraph("Paid", sum_label), Paragraph(_money(paid), sum_value)])
        if refunded > 0:
            sums.append(
                [
                    Paragraph("Given back", sum_label),
                    Paragraph(f"-{_money(refunded)}", sum_value),
                ]
            )
        balance = Decimal(str(found["balance"]))
        if balance > 0 and refunded == 0:
            sums.append(
                [
                    Paragraph("Still to pay", total_label),
                    Paragraph(_money(balance), total_value),
                ]
            )
    totals = Table(sums, colWidths=["83%", "17%"], hAlign="RIGHT")
    totals.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LINEABOVE", (1, at_total), (1, at_total), 0.8, INK),
            ]
        )
    )
    story += [Spacer(1, 3 * mm), KeepTogether([totals])]

    if found["payments"]:
        received: list[list[Any]] = [
            [
                Paragraph("Received", head_cell),
                Paragraph("How", head_cell),
                Paragraph("Reference", head_cell),
                Paragraph("Amount", head_right),
            ]
        ]
        for payment in found["payments"]:
            back = payment["kind"] == "refund"
            how = METHOD_WORDS.get(payment["method"], payment["method"])
            received.append(
                [
                    Paragraph(_moment(payment["received_at"].astimezone(zone)), cell),
                    Paragraph(f"{how}, given back" if back else how, cell),
                    Paragraph(_text(payment["reference"]), cell_muted),
                    Paragraph(
                        f"-{_money(payment['amount'])}" if back else _money(payment["amount"]),
                        cell_right,
                    ),
                ]
            )
        table = Table(received, colWidths=["34%", "22%", "27%", "17%"])
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 1), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story += [Spacer(1, 8 * mm), KeepTogether([table])]

    if found["notes"]:
        story += [
            Spacer(1, 6 * mm),
            KeepTogether([Paragraph("Note", label), Paragraph(_text(found["notes"]), body)]),
        ]

    signed = []
    if found["issued_by"] and issued:
        signed.append(
            Paragraph(f"Issued by {_text(found['issued_by'])}, {_moment(issued)}", small)
        )
    if signed:
        story += [Spacer(1, 10 * mm), HRFlowable(width="100%", color=RULE, thickness=0.4)]
        story += [Spacer(1, 2 * mm), *signed]

    document.build(story)
    return buffer.getvalue()
