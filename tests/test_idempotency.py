from app.schemas import PaymentCreate
from app.services.payments import create_request_fingerprint

from uuid import UUID

from app.models import Payment

import pytest

from sqlalchemy.exc import SQLAlchemyError

from app.services import payments as payment_service

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier


def test_equivalent_payment_requests_have_same_fingerprint():
    first = PaymentCreate(
        customer_reference="  customer001  ",
        amount="50",
    )

    second = PaymentCreate(
        customer_reference="customer001",
        amount="50.00",
        currency="CAD",
    )

    first_fingerprint = create_request_fingerprint(first)
    second_fingerprint = create_request_fingerprint(second)

    assert first_fingerprint == second_fingerprint
    assert len(first_fingerprint) == 64


def test_different_payment_amounts_have_different_fingerprints():
    first = PaymentCreate(
        customer_reference="customer001",
        amount="50.00",
    )

    second = PaymentCreate(
        customer_reference="customer001",
        amount="75.00",
    )

    assert (
        create_request_fingerprint(first)
        != create_request_fingerprint(second)
    )



def test_same_key_and_details_return_original_payment(client):
    payload = {
        "customer_reference": "idempotency_retry_customer",
        "amount": "50.00",
        "currency": "CAD",
    }
    headers = {"Idempotency-Key": "test-payment-retry-001"}

    first_response = client.post(
        "/payments",
        json=payload,
        headers=headers,
    )
    assert first_response.status_code == 201, first_response.text

    retry_response = client.post(
        "/payments",
        json=payload,
        headers=headers,
    )
    assert retry_response.status_code == 201, retry_response.text

    # The retry returns the complete original payment response.
    assert retry_response.json() == first_response.json()

    # Only one payment exists for this test customer.
    list_response = client.get(
        "/payments",
        params={"customer_reference": payload["customer_reference"]},
    )
    assert list_response.status_code == 200, list_response.text

    payments = list_response.json()
    assert len(payments) == 1
    assert payments[0]["id"] == first_response.json()["id"]



def test_same_key_with_different_amount_returns_conflict(client):
    payload = {
        "customer_reference": "idempotency_conflict_customer",
        "amount": "50.00",
        "currency": "CAD",
    }
    headers = {"Idempotency-Key": "test-payment-conflict-001"}

    first_response = client.post(
        "/payments",
        json=payload,
        headers=headers,
    )
    assert first_response.status_code == 201, first_response.text

    changed_payload = {**payload, "amount": "75.00"}

    conflict_response = client.post(
        "/payments",
        json=changed_payload,
        headers=headers,
    )
    assert conflict_response.status_code == 409, conflict_response.text
    assert conflict_response.json() == {
        "detail": "Idempotency key was already used with different payment details."
    }

    list_response = client.get(
        "/payments",
        params={"customer_reference": payload["customer_reference"]},
    )
    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == [first_response.json()]

    # The conflict must not replace the original saved result.
    retry_response = client.post(
        "/payments",
        json=payload,
        headers=headers,
    )
    assert retry_response.status_code == 201, retry_response.text
    assert retry_response.json() == first_response.json()



def test_different_keys_allow_identical_payments(client):
    payload = {
        "customer_reference": "idempotency_separate_payments",
        "amount": "50.00",
        "currency": "CAD",
    }

    first_response = client.post(
        "/payments",
        json=payload,
        headers={"Idempotency-Key": "separate-payment-001"},
    )
    second_response = client.post(
        "/payments",
        json=payload,
        headers={"Idempotency-Key": "separate-payment-002"},
    )

    assert first_response.status_code == 201, first_response.text
    assert second_response.status_code == 201, second_response.text

    first_id = first_response.json()["id"]
    second_id = second_response.json()["id"]
    assert first_id != second_id

    list_response = client.get(
        "/payments",
        params={"customer_reference": payload["customer_reference"]},
    )
    assert list_response.status_code == 200, list_response.text

    payments = list_response.json()
    assert len(payments) == 2
    assert {payment["id"] for payment in payments} == {
        first_id,
        second_id,
    }


#verify that a retry returns the saved creation response even if the payment’s status later changes.
def test_retry_returns_saved_response_after_payment_changes(
    client, db_session
):
    payload = {
        "customer_reference": "idempotency_saved_response",
        "amount": "50.00",
        "currency": "CAD",
    }
    headers = {"Idempotency-Key": "saved-response-001"}

    first_response = client.post(
        "/payments",
        json=payload,
        headers=headers,
    )
    assert first_response.status_code == 201, first_response.text
    original_response = first_response.json()
    assert original_response["status"] == "pending"

    # Simulate a later state change using the isolated test database.
    payment = db_session.get(Payment, UUID(original_response["id"]))
    assert payment is not None
    payment.status = "succeeded"
    db_session.commit()

    current_response = client.get(
        f"/payments/{original_response['id']}"
    )
    assert current_response.status_code == 200, current_response.text
    assert current_response.json()["status"] == "succeeded"

    retry_response = client.post(
        "/payments",
        json=payload,
        headers=headers,
    )
    assert retry_response.status_code == 201, retry_response.text
    assert retry_response.json() == original_response



@pytest.mark.parametrize(
    "invalid_key",
    ["", "   ", "key with spaces", "invalid/key", "x" * 101],
)
def test_invalid_idempotency_key_creates_no_payment(client, invalid_key):
    payload = {
        "customer_reference": "invalid_key_customer",
        "amount": "50.00",
        "currency": "CAD",
    }

    response = client.post(
        "/payments",
        json=payload,
        headers={"Idempotency-Key": invalid_key},
    )

    assert response.status_code == 422, response.text
    assert any(
        error["loc"] == ["header", "Idempotency-Key"]
        for error in response.json()["detail"]
    )

    list_response = client.get(
        "/payments",
        params={"customer_reference": payload["customer_reference"]},
    )
    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == []


def test_failed_creation_rolls_back_and_allows_retry(client, monkeypatch):
    payload = {
        "customer_reference": "rollback_customer",
        "amount": "50.00",
        "currency": "CAD",
    }
    headers = {"Idempotency-Key": "rollback-test-001"}

    original_create = payment_service._create_payment_record

    def fail_after_insert(session, payment_data):
        original_create(session, payment_data)
        raise SQLAlchemyError("Synthetic failure before commit")

    with monkeypatch.context() as patch:
        patch.setattr(
            payment_service,
            "_create_payment_record",
            fail_after_insert,
        )

        failed_response = client.post(
            "/payments",
            json=payload,
            headers=headers,
        )

    assert failed_response.status_code == 500, failed_response.text

    list_response = client.get(
        "/payments",
        params={"customer_reference": payload["customer_reference"]},
    )
    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == []

    # The temporary failure is removed; the same key can now succeed.
    retry_response = client.post(
        "/payments",
        json=payload,
        headers=headers,
    )
    assert retry_response.status_code == 201, retry_response.text

    final_list = client.get(
        "/payments",
        params={"customer_reference": payload["customer_reference"]},
    )
    assert final_list.status_code == 200, final_list.text
    assert final_list.json() == [retry_response.json()]


def test_requests_without_key_create_separate_payments(client):
    payload = {
        "customer_reference": "no_key_customer",
        "amount": "50.00",
        "currency": "CAD",
    }

    first_response = client.post("/payments", json=payload)
    second_response = client.post("/payments", json=payload)

    assert first_response.status_code == 201, first_response.text
    assert second_response.status_code == 201, second_response.text

    first_id = first_response.json()["id"]
    second_id = second_response.json()["id"]
    assert first_id != second_id

    list_response = client.get(
        "/payments",
        params={"customer_reference": payload["customer_reference"]},
    )
    assert list_response.status_code == 200, list_response.text

    payments = list_response.json()
    assert len(payments) == 2
    assert {payment["id"] for payment in payments} == {
        first_id,
        second_id,
    }


def test_concurrent_identical_requests_create_one_payment(
    concurrency_client, monkeypatch
):
    test_client = concurrency_client["client"]
    customer_reference = concurrency_client["customer_reference"]
    idempotency_key = concurrency_client["idempotency_key"]

    payload = {
        "customer_reference": customer_reference,
        "amount": "50.00",
        "currency": "CAD",
    }
    headers = {"Idempotency-Key": idempotency_key}

    barrier = Barrier(2, timeout=10)
    original_create = payment_service._create_payment_record

    def synchronized_create(session, payment_data):
        # Both requests must finish their initial key lookup first.
        barrier.wait()
        return original_create(session, payment_data)

    def send_request():
        return test_client.post(
            "/payments",
            json=payload,
            headers=headers,
        )

    with monkeypatch.context() as patch:
        patch.setattr(
            payment_service,
            "_create_payment_record",
            synchronized_create,
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(send_request)
            second_future = executor.submit(send_request)

            first_response = first_future.result(timeout=20)
            second_response = second_future.result(timeout=20)

    assert first_response.status_code == 201, first_response.text
    assert second_response.status_code == 201, second_response.text
    assert first_response.json() == second_response.json()

    list_response = test_client.get(
        "/payments",
        params={"customer_reference": customer_reference},
    )
    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == [first_response.json()]