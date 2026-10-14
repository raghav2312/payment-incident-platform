#This file doesn’t create any database tables yet. It establishes the foundation we’ll use to define them.

#Imports SQLAlchemy’s foundation for defining database tables using Python classes. 
#ORM means Object-Relational Mapping: connecting Python objects to rows in database tables.
from sqlalchemy.orm import DeclarativeBase

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4


from sqlalchemy import CheckConstraint, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

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
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
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