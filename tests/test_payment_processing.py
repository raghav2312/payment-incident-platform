import pytest
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.models import Payment, PaymentAttempt, PaymentEvent

from app.services.processor import ProcessorResult

from app.services.payments import (
    PaymentProcessingConflictError,
    process_payment,
)

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock
from uuid import UUID

from sqlalchemy.orm import Session

from app.database import engine
from app.services.processor import simulate_payment


def test_process_payment_succeeds(db_session):
    # Arrange: create a pending payment.
    payment = Payment(
        customer_reference=f"processing_{uuid4().hex}",
        amount=Decimal("25.00"),
        currency="CAD",
        status="pending",
    )
    db_session.add(payment)
    db_session.commit()
    payment_id = payment.id

    # Act: run the start, simulate, and finish workflow.
    response = process_payment(db_session, payment_id)

    # Assert: check the response and stored payment.
    assert response["id"] == str(payment_id)
    assert response["status"] == "succeeded"

    db_session.refresh(payment)
    assert payment.status == "succeeded"

    # There should be exactly one completed attempt.
    attempt = db_session.scalars(
        select(PaymentAttempt).where(
            PaymentAttempt.payment_id == payment_id
        )
    ).one()

    assert attempt.attempt_number == 1
    assert attempt.status == "succeeded"
    assert attempt.processor_reference == f"sim-{payment_id}"
    assert attempt.error_code is None
    assert attempt.completed_at is not None

    # Both processing events must reference this attempt.
    events = db_session.scalars(
        select(PaymentEvent).where(
            PaymentEvent.payment_id == payment_id
        )
    ).all()

    assert len(events) == 2
    assert {event.event_type for event in events} == {
        "processing_started",
        "payment_succeeded",
    }
    assert all(
        event.details["attempt_id"] == str(attempt.id)
        for event in events
    )




# Why this works: monkeypatch temporarily replaces the simulator where the payment service uses it. If the second request reaches the simulator, the test fails immediately. pytest.raises checks that the service rejects the request with the expected conflict. 
# The remaining checks confirm no extra attempt or event was created.
# This tests sequential duplicate processing; we’ll test simultaneous requests separately.
def test_processed_payment_cannot_be_processed_again(
    db_session, monkeypatch
):
    # Arrange: create and successfully process a payment.
    payment = Payment(
        customer_reference=f"processing_{uuid4().hex}",
        amount=Decimal("25.00"),
        currency="CAD",
        status="pending",
    )
    db_session.add(payment)
    db_session.commit()
    payment_id = payment.id

    process_payment(db_session, payment_id)

    # Any second call to the simulator must fail this test.
    def unexpected_processor_call(payment_id):
        pytest.fail("The processor must not run a second time.")

    monkeypatch.setattr(
        "app.services.payments.simulate_payment",
        unexpected_processor_call,
    )

    # Act: try processing the same payment again.
    with pytest.raises(
        PaymentProcessingConflictError,
        match="Only pending payments can begin processing.",
    ):
        process_payment(db_session, payment_id)

    # Assert: the original outcome and records remain intact.
    db_session.refresh(payment)
    assert payment.status == "succeeded"

    attempt = db_session.scalars(
        select(PaymentAttempt).where(
            PaymentAttempt.payment_id == payment_id
        )
    ).one()

    assert attempt.status == "succeeded"
    assert attempt.attempt_number == 1

    events = db_session.scalars(
        select(PaymentEvent).where(
            PaymentEvent.payment_id == payment_id
        )
    ).all()

    assert len(events) == 2
    assert {event.event_type for event in events} == {
        "processing_started",
        "payment_succeeded",
    }



# Next, let’s test declined payments and unknown outcomes. An unknown result means we cannot confirm whether processing succeeded—for example, after a timeout.
# parametrize runs this test twice, once for each outcome. We check that the response, payment, attempt, and event consistently record the supplied result. 
# This simulates a returned timeout outcome; it doesn’t raise a Python exception


@pytest.mark.parametrize(
    "outcome, error_code, expected_event",
    [
        ("failed", "sim_declined", "payment_failed"),
        ("unknown", "sim_timeout", "payment_outcome_unknown"),
    ],
)
def test_processing_records_unsuccessful_outcomes(
    db_session,
    monkeypatch,
    outcome,
    error_code,
    expected_event,
):
    # Arrange: create a pending payment.
    payment = Payment(
        customer_reference=f"processing_{uuid4().hex}",
        amount=Decimal("25.00"),
        currency="CAD",
        status="pending",
    )
    db_session.add(payment)
    db_session.commit()
    payment_id = payment.id

    # Supply a controlled result instead of the usual success.
    def simulated_outcome(received_payment_id):
        assert received_payment_id == payment_id
        return ProcessorResult(
            status=outcome,
            error_code=error_code,
        )

    monkeypatch.setattr(
        "app.services.payments.simulate_payment",
        simulated_outcome,
    )

    # Act.
    response = process_payment(db_session, payment_id)

    # Assert: payment and attempt record the same outcome.
    assert response["status"] == outcome

    db_session.refresh(payment)
    assert payment.status == outcome

    attempt = db_session.scalars(
        select(PaymentAttempt).where(
            PaymentAttempt.payment_id == payment_id
        )
    ).one()

    assert attempt.status == outcome
    assert attempt.error_code == error_code
    assert attempt.processor_reference is None
    assert attempt.completed_at is not None

    events = db_session.scalars(
        select(PaymentEvent).where(
            PaymentEvent.payment_id == payment_id
        )
    ).all()

    assert len(events) == 2
    assert {event.event_type for event in events} == {
        "processing_started",
        expected_event,
    }

    outcome_event = next(
        event for event in events
        if event.event_type == expected_event
    )
    assert outcome_event.details["attempt_id"] == str(attempt.id)
    assert outcome_event.details["error_code"] == error_code



#Why this matters: an unexpected crash supplies no confirmed outcome.
#The test checks that we retain the started attempt without inventing a success or failure event. 
#It verifies this through your test session; a separate-connection test will be needed to prove real commit visibility.
def test_processor_exception_leaves_payment_processing(
    db_session, monkeypatch
):
    payment = Payment(
        customer_reference=f"processing_{uuid4().hex}",
        amount=Decimal("25.00"),
        currency="CAD",
        status="pending",
    )
    db_session.add(payment)
    db_session.commit()
    payment_id = payment.id

    def crashing_processor(received_payment_id):
        assert received_payment_id == payment_id
        raise RuntimeError("Simulated processor crash")

    monkeypatch.setattr(
        "app.services.payments.simulate_payment",
        crashing_processor,
    )

    with pytest.raises(
        RuntimeError,
        match="Simulated processor crash",
    ):
        process_payment(db_session, payment_id)

    # End any current transaction before reading the saved state.
    db_session.rollback()
    db_session.refresh(payment)
    assert payment.status == "processing"

    attempt = db_session.scalars(
        select(PaymentAttempt).where(
            PaymentAttempt.payment_id == payment_id
        )
    ).one()

    assert attempt.status == "processing"
    assert attempt.completed_at is None
    assert attempt.processor_reference is None
    assert attempt.error_code is None

    event = db_session.scalars(
        select(PaymentEvent).where(
            PaymentEvent.payment_id == payment_id
        )
    ).one()

    assert event.event_type == "processing_started"
    assert event.details["attempt_id"] == str(attempt.id)


#test the new endpoint that processes a payment through the API. This is an integration test that uses the test client to make HTTP requests to the application.
def test_process_payment_endpoint_succeeds(client):
    # Create a payment through the API.
    creation_response = client.post(
        "/payments",
        json={
            "customer_reference": f"api_processing_{uuid4().hex}",
            "amount": "25.00",
            "currency": "CAD",
        },
    )

    assert creation_response.status_code == 201
    payment_id = creation_response.json()["id"]
    assert creation_response.json()["status"] == "pending"

    # Process that payment through the new endpoint.
    processing_response = client.post(
        f"/payments/{payment_id}/process"
    )

    assert processing_response.status_code == 200
    body = processing_response.json()
    assert body["id"] == payment_id
    assert body["status"] == "succeeded"

    # Read it again to verify that the updated status was saved.
    retrieval_response = client.get(f"/payments/{payment_id}")

    assert retrieval_response.status_code == 200
    assert retrieval_response.json()["status"] == "succeeded"



#Let’s test what happens when a second request arrives while the first payment is still processing. We’ll pause the first request inside the simulator, send the second request for the same payment, and check that it gets 409 Conflict. Then we’ll let the first request finish and verify that PostgreSQL contains exactly one attempt.
def test_overlapping_processing_requests_create_one_attempt(
    concurrency_client, monkeypatch
):
    client = concurrency_client["client"]
    created = client.post(
        "/payments",
        json={
            "customer_reference": concurrency_client["customer_reference"],
            "amount": "25.00",
            "currency": "CAD",
        },
    )
    assert created.status_code == 201, created.text
    payment_id = UUID(created.json()["id"])
    path = f"/payments/{payment_id}/process"

    processor_entered = Event()
    allow_completion = Event()

    def paused_processor(received_payment_id):
        processor_entered.set()
        assert allow_completion.wait(timeout=15), "Simulator was never released"
        return simulate_payment(received_payment_id)

    processor = Mock(side_effect=paused_processor)
    monkeypatch.setattr("app.services.payments.simulate_payment", processor)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_request = pool.submit(client.post, path)
        try:
            assert processor_entered.wait(timeout=5), "First request never reached simulator"

            second_request = pool.submit(client.post, path)
            conflict = second_request.result(timeout=5)
            assert conflict.status_code == 409, conflict.text
        finally:
            allow_completion.set()

        success = first_request.result(timeout=5)

    assert success.status_code == 200, success.text
    assert success.json()["status"] == "succeeded"
    processor.assert_called_once_with(payment_id)

    # A fresh session checks what the HTTP requests committed.
    with Session(engine) as session:
        attempt = session.scalars(
            select(PaymentAttempt).where(PaymentAttempt.payment_id == payment_id)
        ).one()
        assert attempt.attempt_number == 1
        assert attempt.status == "succeeded"