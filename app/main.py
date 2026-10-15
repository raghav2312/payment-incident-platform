#This creates two endpoints—URL paths that accept requests and return responses: /health and /health/db
from contextlib import asynccontextmanager

from uuid import UUID

from typing import Literal

from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import Payment
from app.schemas import PaymentCreate, PaymentRead

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import text, select
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine

# @asynccontextmanager lets FastAPI use this function as a lifecycle handler.
# The application runs while execution pauses at yield; during normal shutdown, engine.dispose() releases pooled database connections.
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    engine.dispose()


app = FastAPI(
    title="Payment Processing & Incident Investigation Platform",
    version="0.1.0",
    lifespan=lifespan,
)

#Checks whether the API can respond
@app.get("/health")
def health_check():
    return {"status": "ok"}



#Checks whether the API can connect to PostgreSQL and execute SQL.
@app.get("/health/db")
def database_health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()           #asks PostgreSQL to return the number 1. It tests query execution without needing a table or changing data. Only one row result(1) expected

        return {"status": "ok", "database": "connected"}                #sends a Python dictionary that FastAPI converts into a JSON response.

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from None                                                     #suppresses the chained database exception if this exception is displayed as a traceback.



@app.post(
    "/payments",
    response_model=PaymentRead,                                         #Validates and formats the payment using our response schema, returns 201 if successful
    status_code=201,
)
def create_payment(
    payment_data: PaymentCreate,                                        #Tells FastAPI to validate the request body before running the function. Invalid input normally receives 422.
    session: Session = Depends(get_db),                                 #Asks FastAPI to obtain a database session using our dependency.
):
    payment = Payment(                                                  #Builds a Python payment object using the validated input.
        customer_reference=payment_data.customer_reference,
        amount=payment_data.amount,
        currency=payment_data.currency,
    )

    try:
        session.add(payment)                                            #Registers the object with the session for insertion.
        session.commit()                                                #Flushes the insert to PostgreSQL and commits the transaction.
        session.refresh(payment)                                        #Reads the saved row back, including generated values such as timestamps.

    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to complete the payment creation request.",
        ) from None

    return payment                                                      #Sends the payment through PaymentRead as a JSON response.


#Reads the payment from the postgres db
@app.get(
    "/payments/{payment_id}",                                           #takes the payment_id from the url
    response_model=PaymentRead,
)
def get_payment(
    payment_id: UUID,                                                   #validates that the supplied id has a valid uuid format. If invlid, recieve 422
    session: Session = Depends(get_db),
):
    try:
        payment = session.get(Payment, payment_id)

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Unable to retrieve payment.",
        ) from None

    if payment is None:
        raise HTTPException(
            status_code=404,
            detail="Payment not found.",
        )

    return payment




@app.get("/payments", response_model=list[PaymentRead])                   #The following parameters controls which records are returned
def list_payments(
    customer_reference: str | None = Query(                               #exact match for a customer
        default=None,
        min_length=1,
        max_length=100,
    ),
    status: Literal["pending", "succeeded", "failed"] | None = None,
    limit: int = Query(default=20, ge=1, le=100),                         #maximum number of records found
    offset: int = Query(default=0, ge=0),                                 #number of maching records to skip
    session: Session = Depends(get_db),
):
    statement = select(Payment)

    if customer_reference is not None:
        statement = statement.where(
            Payment.customer_reference == customer_reference
        )

    if status is not None:
        statement = statement.where(
            Payment.status == status
        )

    statement = (
        statement
        .order_by(Payment.created_at.desc(), Payment.id.desc())
        .limit(limit)
        .offset(offset)
    )

    try:
        payments = session.scalars(statement).all()                       #executes the query and collects the resulting payment

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Unable to retrieve payments.",
        ) from None

    return payments