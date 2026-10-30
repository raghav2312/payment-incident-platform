#Payment validation, defining api's payment request and response schemas

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Shared list of statuses accepted by payment responses and filters.
PaymentStatus = Literal[
    "pending",
    "processing",
    "succeeded",
    "failed",
    "unknown",
]

# Validates the information supplied when creating a payment.
class PaymentCreate(BaseModel):                                   #BaseModel: foundation for classes that check and organize the data coming into or going out of your api
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",                                           #rejects unexpected fields. A caller cannot sneak in a status or id.
    )

    customer_reference: str = Field(
        min_length=1,                                             #require a customer reference of 1–100 characters after trimming.
        max_length=100,
    )
    amount: Decimal = Field(
        gt=0,
        max_digits=12,                                            #match our database amount limits.
        decimal_places=2,
        allow_inf_nan=False,                                      #rejects special numeric values such as infinity.
    )
    currency: Literal["CAD"] = "CAD"                              #allows only CAD; the default supplies it when omitted.



#Defines the payment information returned by the API.
class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_reference: str
    amount: Decimal
    currency: Literal["CAD"]
    status: PaymentStatus
    created_at: datetime
    updated_at: datetime


