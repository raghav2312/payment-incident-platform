# Creates payments and prevents duplicate creation when an idempotency key is reused.
# Uses SQLAlchemy to handle new requests, saved responses, and database errors.
# When a key is supplied, one transaction saves the payments table and idempotency tables record together.
from typing import Any

from sqlalchemy.orm import Session

from app.middleware.request_context import request_id_context

import hashlib
import json

from app.schemas import PaymentCreate, PaymentRead

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from uuid import UUID, uuid4

from sqlalchemy import select

from app.models import (
    IdempotencyRequest,
    Payment,
    PaymentAttempt,
    PaymentEvent,
)


from datetime import datetime, timezone

from app.services.processor import ProcessorResult, simulate_payment


def create_request_fingerprint(payment_data: PaymentCreate) -> str:
    normalized_request = {
        "customer_reference": payment_data.customer_reference,
        "amount": format(payment_data.amount, ".2f"),                        #format(..., ".2f") represents amounts such as 50 and 50.00 identically as "50.00".
        "currency": payment_data.currency,
    }

    serialized_request = json.dumps(
        normalized_request,
        sort_keys=True,                                                      #sort_keys=True gives the JSON fields a consistent order.
        separators=(",", ":"),                                               #separators=(",", ":") removes unnecessary spaces.
    )

    return hashlib.sha256(                                                   #SHA-256 produces the 64-character hexadecimal fingerprint stored in our new table.
        serialized_request.encode("utf-8")                                   #encode("utf-8") converts the JSON text into bytes.
    ).hexdigest()



class IdempotencyConflictError(Exception):
    """An existing key was reused with different payment details."""

class PaymentNotFoundError(Exception):
    """The requested payment does not exist."""

class PaymentProcessingConflictError(Exception):
    """The payment is not eligible to begin processing."""


# Look up a previously completed request by its idempotency key.
def find_saved_creation_response(
    session: Session,
    idempotency_key: str,
    request_fingerprint: str,
) -> dict[str, Any] | None:
    existing_request = session.get(
        IdempotencyRequest,
        idempotency_key,
    )

    if existing_request is None:                                                        #if the key doesn't exist, return None; creation can proceed
        return None

    if existing_request.request_fingerprint != request_fingerprint:                     #raise conflict exception. http 409
        raise IdempotencyConflictError(
            "Idempotency key was already used with different payment details."
        )

    return existing_request.response_body                                               #key exists with a matching fingerprint




# For a request with an idempotency key, the flow will be:
# 1. Insert the payment into payments table using flush()—still uncommitted.
# 2. Insert its key, fingerprint, payment ID, and saved response into idempotency_requests table.
# 3. Call session.commit() once to save both.
def _create_payment_record(
    session: Session,
    payment_data: PaymentCreate,
) -> tuple[Payment, dict[str, Any]]:
    payment = Payment(
        customer_reference=payment_data.customer_reference,
        amount=payment_data.amount,
        currency=payment_data.currency,
    )

    session.add(payment)                                                                #session.add() registers the payment for insertion.
    session.flush()                                                                     #session.flush() sends the insert to PostgreSQL, but doesn’t commit. We can still roll it back.
    session.refresh(payment)                                                            #session.refresh() reads the stored values, including timestamps and the database-formatted amount.


    #Adding payment events to the payment_events table. The event_type is "payment_created" and the details include the amount and currency of the payment.
    #The request_id is obtained from the request_id_context, which is a context variable that holds the unique identifier for the current request. This allows us to trace the event back to the specific request that created it.
    session.add(
        PaymentEvent(
            payment_id=payment.id,
            event_type="payment_created",
            request_id=request_id_context.get(),
            details={
                "amount": format(payment.amount, ".2f"),
                "currency": payment.currency,
            },
        )
    )

    response_body = PaymentRead.model_validate(payment).model_dump(                     #PaymentRead.model_validate() checks the payment against our response schema.
        mode="json"                                                                     #model_dump(mode="json") produces a dictionary with JSON-compatible values—for example, UUIDs and timestamps become strings. We can store it in response_body.
    )

    return payment, response_body




# The following function’s main outcomes are:
# Situation	Result
# No idempotency key	Create a new payment
# New key	Create payment and save its response together
# Existing key with matching details	Return the saved response
# Two requests race with the same key and details	One saves; the other rolls back and retrieves its result
# Unrelated database failure	Roll back and raise the error

#This function creates a payment while preventing retries with the same idempotency key from creating duplicate payments.
def create_payment_with_idempotency(
    session: Session,
    payment_data: PaymentCreate,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    fingerprint = create_request_fingerprint(payment_data)


    #check whether the request has already succeeded
    try:
        if idempotency_key is not None:                           #use the assigned idempotent key to find the response
            saved_response = find_saved_creation_response(
                session,
                idempotency_key,
                fingerprint,
            )
            if saved_response is not None:
                return saved_response                              #return the existing saved_response and the function ends


        #prepare a new payment. will return two values, payment: db model object and response body: dictionary returned to the client
        try:
            payment, response_body = _create_payment_record(
                session,
                payment_data,
            )


            #if the key is supplied, create an associated idempotency record
            if idempotency_key is not None:
                session.add(
                    IdempotencyRequest(
                        key=idempotency_key,
                        request_fingerprint=fingerprint,
                        payment_id=payment.id,
                        response_body=response_body,
                        response_status=201,                       #doesnot itself set an https response status. the function only returns the response dictionary and the api layer controls the http status
                    )
                )

            session.commit()            #commit both the records together; which means all the pending changes in the session's transaction, not to one particular table
            return response_body

        except IntegrityError as error:           #incase theirs a db constraint failure - eg: duplcate primary key, rollback will undo the uncommitted changes in the transaction and the session will be usable again
            session.rollback()

            # Only treat a duplicate idempotency key as a retry.
            diagnostic = getattr(error.orig, "diag", None)          #identify exactly which rule failed. error.orig is the underlying db driver's exception
            constraint_name = getattr(                              #getattr() safely reads the attribute
                diagnostic, "constraint_name", None                 #if constraint_name doesn't exist, use None
            )
            sqlstate = getattr(error.orig, "sqlstate", None)        #sqlstate: db error code; prob 23505, incase of unique constraint violation

            #recovery allowed only when all three are true: idempotency key is supplied; error is uniqueness violation; failed constraint is "idempotency_requests_pkey"
            if (
                idempotency_key is None
                or sqlstate != "23505"
                or constraint_name != "idempotency_requests_pkey"
            ):
                raise                                               #reraise the current exception so that the caller can handle it


            #read the response saved by the winning request
            saved_response = find_saved_creation_response(
                session,
                idempotency_key,
                fingerprint,
            )

            #function will reraise the Integrity Error if there's no saved response
            if saved_response is None:
                raise

            return saved_response


    #for capturing SQLAlchemy erros that escape the inner logic, including errors from the lookups
    except SQLAlchemyError:
        session.rollback()
        raise


def _finish_payment_processing(
    session: Session,
    payment_id: UUID,     #identify the payment and its attempt to update their status and record an event based on the outcome of the processing.   
    attempt_id: UUID,
    result: ProcessorResult,
) -> dict[str, Any]:
    event_types = {
        "succeeded": "payment_succeeded",
        "failed": "payment_failed",
        "unknown": "payment_outcome_unknown",
    }

    if result.status not in event_types:
        raise ValueError("Unsupported processor outcome.")


    # Fetch and lock the payment
    try:
        payment = session.scalars(
            select(Payment)
            .where(Payment.id == payment_id)
            .with_for_update()      #locks the matching db row until this transaction commits or rolls back
            .execution_options(populate_existing=True)     #populate_existing=True refreshes any Payment object already held by this session with the queried database values.
        ).one_or_none()

        if payment is None:
            raise PaymentNotFoundError("Payment not found.")

        attempt = session.scalars(
            select(PaymentAttempt)                  #Fetch and lock the correct attempt, making sure both conditions must match
            .where(
                PaymentAttempt.id == attempt_id,
                PaymentAttempt.payment_id == payment_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()


        #check both are still processing. If either is not, raise a conflict error. This prevents a second request from overwriting the first request’s result.
        if (
            payment.status != "processing"
            or attempt is None
            or attempt.status != "processing"
        ):
            raise PaymentProcessingConflictError(
                "Payment and attempt must both be processing."
            )

        payment.status = result.status
        attempt.status = result.status
        attempt.processor_reference = result.processor_reference
        attempt.error_code = result.error_code
        attempt.completed_at = datetime.now(timezone.utc)

        session.add(
            PaymentEvent(
                payment_id=payment.id,
                event_type=event_types[result.status],
                request_id=request_id_context.get(),
                details={
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                    "processor_reference": result.processor_reference,
                    "error_code": result.error_code,
                },
            )
        )

        session.flush()
        session.refresh(payment)

        response_body = PaymentRead.model_validate(payment).model_dump(
            mode="json"
        )

        session.commit()
        return response_body

    except (
        PaymentNotFoundError,
        PaymentProcessingConflictError,
        SQLAlchemyError,
    ):
        session.rollback()
        raise



def _start_payment_processing(
    session: Session,
    payment_id: UUID,
) -> UUID:
    try:
        statement = (
            select(Payment)
            .where(Payment.id == payment_id)
            .with_for_update()              #.with_for_update() locks the matching payment row until this transaction ends. Another request trying to lock it must wait.
            .execution_options(populate_existing=True)      #populate_existing=True refreshes an already-loaded payment object with the values returned by this query.
        )

        payment = session.scalars(statement).one_or_none()

        if payment is None:
            raise PaymentNotFoundError("Payment not found.")


        # The status check happens while holding the lock. After the first request commits processing, a waiting request sees that status and is rejected.
        if payment.status != "pending":
            raise PaymentProcessingConflictError(
                "Only pending payments can begin processing."
            )

        attempt_id = uuid4()

        payment.status = "processing"

        session.add(
            PaymentAttempt(
                id=attempt_id,
                payment_id=payment.id,
                attempt_number=1,
                status="processing",
            )
        )

        session.add(
            PaymentEvent(
                payment_id=payment.id,
                event_type="processing_started",
                request_id=request_id_context.get(),
                details={
                    "attempt_id": str(attempt_id),
                    "attempt_number": 1,
                },
            )
        )


        # One commit saves the status change, attempt, and event together.
        session.commit()
        return attempt_id
#We commit this step before calling the simulator, releasing the database lock and preserving a record that processing began.
# If the application stops afterward, the payment remains processing for investigation.
    

    except (
        PaymentNotFoundError,
        PaymentProcessingConflictError,
        SQLAlchemyError,
    ):
        session.rollback()
        raise



def process_payment(
    session: Session,                                 #_start_payment_processing() checks that the payment is pending, creates its attempt, and commits the processing state. It returns the attempt’s ID.
    payment_id: UUID,
) -> dict[str, Any]:
    attempt_id = _start_payment_processing(
        session=session,
        payment_id=payment_id,
    )


    #simulate_payment() produces the simulated outcome. The start transaction has already committed, so its row lock is released before this call.
    result = simulate_payment(payment_id)


    #_finish_payment_processing() saves the outcome against that payment and attempt, records the event, and returns the payment response.
    return _finish_payment_processing(
        session=session,
        payment_id=payment_id,
        attempt_id=attempt_id,
        result=result,
    )