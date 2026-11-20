# verify that creating a payment saves exactly one event with the correct details and request ID.
from uuid import UUID

from sqlalchemy import select

from app.models import PaymentEvent


def test_create_payment_records_event(client, db_session):
    response = client.post(
        "/payments",
        json={
            "customer_reference": "event_test_customer",
            "amount": "50.00",
            "currency": "CAD",
        },
    )

    assert response.status_code == 201, response.text

    payment_id = UUID(response.json()["id"])

    events = db_session.scalars(
        select(PaymentEvent).where(
            PaymentEvent.payment_id == payment_id
        )
    ).all()

    assert len(events) == 1

    event = events[0]

    assert event.event_type == "payment_created"
    assert event.request_id == response.headers["X-Request-ID"]
    assert event.details == {
        "amount": "50.00",
        "currency": "CAD",
    }
    assert event.created_at is not None

def test_event_history_for_processed_payment(client):
    created = client.post(
        "/payments",
        json={
            "customer_reference": "event-history-test",
            "amount": "25.00",
            "currency": "CAD",
        },
    )
    assert created.status_code == 201, created.text
    payment_id = created.json()["id"]

    processed = client.post(f"/payments/{payment_id}/process")
    assert processed.status_code == 200, processed.text

    history = client.get(f"/payments/{payment_id}/events")
    assert history.status_code == 200, history.text
    events = history.json()

    assert len(events) == 3
    assert all(event["payment_id"] == payment_id for event in events)

    by_type = {event["event_type"]: event for event in events}
    assert set(by_type) == {
        "payment_created",
        "processing_started",
        "payment_succeeded",
    }

    started = by_type["processing_started"]
    succeeded = by_type["payment_succeeded"]

    assert by_type["payment_created"]["request_id"] == created.headers["X-Request-ID"]
    assert started["request_id"] == processed.headers["X-Request-ID"]
    assert succeeded["request_id"] == processed.headers["X-Request-ID"]
    assert started["details"]["attempt_id"] == succeeded["details"]["attempt_id"]