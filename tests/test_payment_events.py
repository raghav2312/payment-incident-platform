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