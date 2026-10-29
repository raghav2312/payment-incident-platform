from typing import Any

from sqlalchemy.orm import Session

from app.models import IdempotencyRequest, Payment

import hashlib
import json

from app.schemas import PaymentCreate, PaymentRead

from sqlalchemy.exc import IntegrityError, SQLAlchemyError


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
# 1. Insert the payment into payments using flush()—still uncommitted.
# 2. Insert its key, fingerprint, payment ID, and saved response into idempotency_requests.
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