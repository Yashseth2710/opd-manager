"""Request and response shapes for bills and the money taken against them.

Money is a string both ways. A JSON number is a double in the browser, and a
bill is the last place for 0.1 + 0.2 to come out wrong.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.schemas.appointment import DoctorRef, PatientRef

InvoiceStatus = Literal["draft", "unpaid", "partly_paid", "paid", "refunded", "void"]
ItemType = Literal["consultation", "procedure", "lab", "medicine", "other"]
Method = Literal["cash", "upi", "card", "bank_transfer", "cheque", "other"]
Kind = Literal["payment", "refund"]
Channel = Literal["desk", "online"]
LinkStatus = Literal["open", "paid", "cancelled", "expired"]

# More lines than this on one visit's bill is a slip somewhere.
MAX_LINES = 50
# Ten lakh for one line, and a crore for the whole bill, is more than any
# outpatient visit comes to and well inside what the columns hold.
MAX_PRICE = Decimal("1000000.00")
MAX_TOTAL = Decimal("10000000.00")

Price = Annotated[Decimal, Field(ge=0, le=MAX_PRICE, max_digits=10, decimal_places=2)]
Amount = Annotated[Decimal, Field(gt=0, le=MAX_TOTAL, max_digits=10, decimal_places=2)]
Rupees = Annotated[Decimal, PlainSerializer(lambda value: f"{value:.2f}", return_type=str)]


class _Trimmed(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class LineIn(_Trimmed):
    item_type: ItemType = "other"
    description: str = Field(min_length=1, max_length=120)
    quantity: int = Field(default=1, ge=1, le=999)
    unit_price: Price


class InvoiceIn(_Trimmed):
    patient_id: uuid.UUID
    # The visit it is for. Without one, the bill stands on its own.
    queue_entry_id: uuid.UUID | None = None
    items: list[LineIn] = Field(min_length=1, max_length=MAX_LINES)
    discount_amount: Annotated[
        Decimal, Field(ge=0, le=MAX_TOTAL, max_digits=10, decimal_places=2)
    ] = Decimal("0.00")
    discount_reason: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=500)
    # Straight out as a numbered bill, rather than kept as a draft.
    issue: bool = False


class InvoiceChange(_Trimmed):
    """A draft only. Whatever is sent replaces what was there; the lines
    are always the whole list."""

    items: list[LineIn] | None = Field(default=None, min_length=1, max_length=MAX_LINES)
    discount_amount: (
        Annotated[Decimal, Field(ge=0, le=MAX_TOTAL, max_digits=10, decimal_places=2)] | None
    ) = None
    discount_reason: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=500)


class PaymentIn(_Trimmed):
    amount: Amount
    method: Method
    reference: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=200)


class RefundIn(_Trimmed):
    amount: Amount
    method: Method
    reason: str = Field(min_length=1, max_length=200)
    reference: str | None = Field(default=None, max_length=60)


class VoidIn(_Trimmed):
    reason: str = Field(min_length=1, max_length=200)


class LineOut(BaseModel):
    item_type: ItemType
    description: str
    quantity: int
    unit_price: Rupees
    amount: Rupees


class PaymentOut(BaseModel):
    id: uuid.UUID
    kind: Kind
    amount: Rupees
    method: Method
    channel: Channel
    reference: str | None
    note: str | None
    received_at: dt.datetime
    received_by: str | None


class VisitRef(BaseModel):
    queue_entry_id: uuid.UUID
    date: dt.date
    token: int
    consultation_id: uuid.UUID | None


class LinkIn(_Trimmed):
    """Raising a link, and sending it on if there is an address to send to."""

    send: bool = False
    # Where to send it. Left out, the patient's own address is used.
    email: str | None = Field(default=None, max_length=255)


class LinkOut(BaseModel):
    id: uuid.UUID
    status: LinkStatus
    amount: Rupees
    # Paid through the link but with nothing left on the bill to put it
    # against, because the desk took the money first.
    excess_amount: Rupees
    currency: str
    expires_at: dt.datetime
    sent_to: str | None
    sent_at: dt.datetime | None
    opened_at: dt.datetime | None
    paid_at: dt.datetime | None
    created_at: dt.datetime
    created_by: str | None


class LinkMade(LinkOut):
    """The one answer that carries the address itself. Only the hash is kept,
    so asking again raises a new link rather than showing this one twice."""

    url: str
    # Whether the email actually went. False says so plainly rather than
    # leaving the desk to assume it did.
    sent: bool


class Totals(BaseModel):
    subtotal: Rupees
    discount_amount: Rupees
    tax_percent: Rupees
    tax_amount: Rupees
    total: Rupees
    amount_paid: Rupees
    refunded_amount: Rupees
    balance: Rupees


class InvoiceListed(Totals):
    id: uuid.UUID
    invoice_number: str | None
    status: InvoiceStatus
    patient: PatientRef
    doctor: DoctorRef | None
    # What the first line says, and how many more there are, for the list.
    headline: str
    lines: int
    created_at: dt.datetime
    issued_at: dt.datetime | None


class InvoiceOut(InvoiceListed):
    currency: str
    items: list[LineOut]
    payments: list[PaymentOut]
    discount_reason: str | None
    notes: str | None
    visit: VisitRef | None
    created_by: str | None
    issued_by: str | None
    voided_at: dt.datetime | None
    voided_by: str | None
    void_reason: str | None
    can_edit: bool
    can_pay: bool
    can_refund: bool
    can_void: bool
    # Why the bill cannot be voided, when it is issued and cannot.
    void_blocked: str | None
    # The most recent link raised against this bill, whatever became of it.
    payment_link: LinkOut | None
    can_send_link: bool
    # Whether the clinic can take money online at all. Without it the option
    # is not offered rather than offered and then refused.
    online_payments: bool


class InvoicePage(BaseModel):
    items: list[InvoiceListed]
    total: int
    counts: dict[str, int]
    # Still owed on issued bills, for the patient asked about or the clinic.
    owed: Rupees


class MethodTotal(BaseModel):
    method: Method
    received: Rupees
    refunded: Rupees
    net: Rupees
    count: int


class DaySummary(BaseModel):
    """What came in on one day, by how it was paid, for counting the drawer."""

    date: dt.date
    currency: str
    methods: list[MethodTotal]
    received: Rupees
    refunded: Rupees
    net: Rupees
    # Of what came in, the part that was paid from a link rather than handed
    # over at the desk.
    online: Rupees
    bills_issued: int
    billed: Rupees
    # Across every day, still owed on bills already issued.
    outstanding: Rupees
    outstanding_bills: int


class Unbilled(BaseModel):
    queue_entry_id: uuid.UUID
    token: int
    status: str
    patient: PatientRef
    doctor: DoctorRef
    completed_at: dt.datetime | None


class UnbilledPage(BaseModel):
    date: dt.date
    items: list[Unbilled]


class Suggestion(BaseModel):
    item_type: ItemType
    description: str
    quantity: int
    unit_price: Rupees


class Starting(BaseModel):
    """What a new bill for this patient, or this visit, starts from."""

    patient: PatientRef
    doctor: DoctorRef | None
    visit: VisitRef | None
    currency: str
    tax_percent: Rupees
    items: list[Suggestion]
    # Tests ordered at the visit, offered as lines if the clinic charges
    # for them.
    lab_tests: list[str]
    # The bill already raised for this visit, if there is one.
    existing: uuid.UUID | None
    existing_number: str | None


class PastLine(BaseModel):
    item_type: ItemType
    description: str
    unit_price: Rupees
    times: int


class Removed(BaseModel):
    removed: bool = True


# --- What the patient sees ----------------------------------------------------------
#
# Opened without signing in, from a link. It says only what somebody holding
# the link already has to be told to pay: the clinic, the bill number, and
# what is owed. No address, no phone number, and nothing clinical.


class PayView(BaseModel):
    clinic: str
    clinic_phone: str | None
    # Enough for the patient to know the bill is theirs, and no more.
    patient_name: str
    invoice_number: str | None
    issued_on: dt.date | None
    amount: Rupees
    currency: str
    status: LinkStatus
    expires_at: dt.datetime
    paid_at: dt.datetime | None
    # What the checkout on the page needs. Both are meant to be public.
    key_id: str | None
    order_id: str | None


class CheckoutIn(_Trimmed):
    """What the checkout hands back to the page once a payment goes through.

    It is checked against the gateway before anything is recorded, so a made
    up one gets nowhere; it is here so the patient sees the bill marked paid
    without waiting for the webhook.
    """

    razorpay_payment_id: str = Field(min_length=1, max_length=64)
    razorpay_order_id: str = Field(min_length=1, max_length=64)
    razorpay_signature: str = Field(min_length=1, max_length=128)
