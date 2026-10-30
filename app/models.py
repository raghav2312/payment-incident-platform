#This file doesn’t create any database tables yet. It establishes the foundation we’ll use to define them.

#Imports SQLAlchemy’s foundation for defining database tables using Python classes. 
#ORM means Object-Relational Mapping: connecting Python objects to rows in database tables.
from sqlalchemy.orm import DeclarativeBase

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy import UniqueConstraint

#Creates our own base class. Our upcoming Payment model will inherit from Base, allowing SQLAlchemy to register its table definition.
class Base(DeclarativeBase):
    pass                                        #Means “no additional code here.” The class inherits the functionality it needs from DeclarativeBase.


#defining the class Payment, which has a table name payments
class Payment(Base):
    __tablename__ = "payments"

    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="ck_payments_positive_amount",
        ),
        CheckConstraint(                            #default="pending" unchanged—new payments should still start as pending.
            "status IN ('pending', 'processing', 'succeeded', 'failed', 'unknown')",
            name="ck_payments_valid_status",
        ),
        CheckConstraint(
            "currency = 'CAD'",
            name="ck_payments_cad_currency",
        ),
    )

    id: Mapped[UUID] = mapped_column(                             #Mapped: defines python value type ; mapped: defines db column type
        primary_key=True,
        default=uuid4,
    )

    customer_reference: Mapped[str] = mapped_column(              #Fictional customer identifier; one customer can have multiple payments.
        String(100),
        index=True,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        default="CAD",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


# Your current endpoint creates a new payment on every successful POST. We’ll add a separate idempotency_requests table to remember completed creation requests.

# Here’s the design for this first version:
# Column	Purpose
# key	Caller-provided Idempotency-Key; primary key so duplicates cannot be stored.
# request_fingerprint	SHA-256 hash of the normalized, validated payment details.
# payment_id	Foreign key linking the request to its created payment.
# response_body	Saved creation response as PostgreSQL JSONB.
# response_status	Saved HTTP status, initially 201.
# created_at	UTC timestamp recording when the entry was created.


# Why save the response body?
# A payment might later change from pending to succeeded. Retrying its original creation request should return the saved creation result, rather than reconstructing it from the payment’s newer state.

# We’ll use these rules:
# - The header will initially be optional, preserving existing callers. Requests without it won’t have duplicate protection.
# - Keys will be case-sensitive, with a maximum length of 100 characters.
# - Equivalent validated values, such as amounts 50 and 50.00, will produce the same fingerprint.
# - The payment and completed idempotency record will commit together. A failure before commit rolls both back.
# - PostgreSQL’s unique key will help resolve simultaneous requests; a lookup alone isn’t enough.
# - We won’t expire keys in this first version.
# Because creation currently involves only database work, we can keep it in one transaction without persisting an intermediate “processing” record. Payment processing will remain a separate operation.



#defining the table and constraints for python objects
class IdempotencyRequest(Base):
    __tablename__ = "idempotency_requests"

    __table_args__ = (
        CheckConstraint(
            "char_length(key) >= 1",
            name="ck_idempotency_requests_nonempty_key",
        ),
        CheckConstraint(
            "response_status = 201",
            name="ck_idempotency_requests_creation_status",
        ),
    )

    key: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    request_fingerprint: Mapped[str] = mapped_column(                           #holds a SHA-256 hash represented as 64 hexadecimal characters.
        String(64),
    )

    payment_id: Mapped[UUID] = mapped_column(                                   #requires the referenced payment to exist. RESTRICT prevents deleting it while an idempotency record references it.
        ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=False,
    )

    response_body: Mapped[dict[str, Any]] = mapped_column(                      #JSONB: stores the original response as structured JSON. dict[str, Any] describes its Python representation.
        JSONB,
    )

    response_status: Mapped[int] = mapped_column(
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

#add the payment_attempts model. Each row will record one attempt to process a payment.
class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    __table_args__ = (
        UniqueConstraint(
            "payment_id",
            "attempt_number",
            name="uq_payment_attempts_payment_number",
        ),
        CheckConstraint(
            "attempt_number >= 1",
            name="ck_payment_attempts_positive_number",
        ),
        CheckConstraint(
            "status IN ('processing', 'succeeded', 'failed', 'unknown')",
            name="ck_payment_attempts_valid_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=False,
    )

    attempt_number: Mapped[int] = mapped_column(
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="processing",
    )

    # Reference returned by the simulated processor, when available.
    processor_reference: Mapped[str | None] = mapped_column(
        String(100),
    )

    # An outcome code, such as a decline or timeout code.
    error_code: Mapped[str | None] = mapped_column(
        String(100),
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Remains empty until this attempt finishes or times out.
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )


#to record a payment’s history for investigations. An attempt records one processing try
# For example, one payment could have these event rows:
# payment_id	event_type	details
# P1	payment_created	{"amount": "50.00", "currency": "CAD"}
# P1	processing_started	{"attempt_number": 1}
# P1	processor_timed_out	{"timeout_seconds": 30}
class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    #The payment_id index helps retrieve a payment’s history.
    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"),     #Do not allow payment P1 to be deleted while events still reference it
        index=True,
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(50),
    )

    # Links the event to the HTTP request that caused it, when available. request_id here refers to the middleware request_id
    request_id: Mapped[str | None] = mapped_column(
        String(36),
    )

    # Structured information describing the event.
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )