#the test_ in the filename and the function lets pytest discover the test
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.models import Payment


def test_create_and_get_payment(client):                                         #client tells pytest to supply our fixture
    # Create/posting a synthetic payment.
    response = client.post(                                                      #client.post(...) sends the payment request; json= supplies its body.
        "/payments",
        json={
            "customer_reference": "test_customer",
            "amount": "50.00",
            "currency": "CAD",
        },
    )

    # Check that creation succeeded.
    assert response.status_code == 201, response.text                            #assert checks each expected result. The response.text shows the response body if the status check fails.

    #response.json() converts the response into a Python dictionary.
    payment = response.json()

    assert payment["customer_reference"] == "test_customer"
    assert payment["amount"] == "50.00"
    assert payment["currency"] == "CAD"
    assert payment["status"] == "pending"

    # Retrieve the payment using its generated ID.
    payment_id = payment["id"]

    #checks the GET payment[payamnet_id] api
    get_response = client.get(f"/payments/{payment_id}")                          #f"/payments/{payment_id}" inserts the new ID into the retrieval URL.

    assert get_response.status_code == 200, get_response.text
    assert get_response.json() == payment



#The error specifically identifies amount as violating the greater-than rule. any(...) checks that at least one error matches.
def test_create_payment_rejects_zero_amount(client):
    response = client.post(
        "/payments",
        json={
            "customer_reference": "test_customer",
            "amount": "0.00",
            "currency": "CAD",
        },
    )

    assert response.status_code == 422, response.text

    errors = response.json()["detail"]

    #validate the error format
    assert any(
        error["loc"] == ["body", "amount"]
        and error["type"] == "greater_than"
        for error in errors
    )

    # Confirm the rejected request didn't create a payment.
    list_response = client.get(
        "/payments",
        params={"customer_reference": "test_customer"},
    )

    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == []





#automate the missing-payment check
def test_get_payment_returns_404_when_missing(client):
    missing_id = "00000000-0000-0000-0000-000000000000"

    response = client.get(f"/payments/{missing_id}")

    assert response.status_code == 404, response.text
    assert response.json() == {
        "detail": "Payment not found."
    }



#automate valid uuid check
def test_get_payment_rejects_invalid_uuid(client):
    response = client.get("/payments/not-a-uuid")

    assert response.status_code == 422, response.text

    errors = response.json()["detail"]

    assert any(
        error["loc"] == ["path", "payment_id"]
        and error["type"] == "uuid_parsing"
        for error in errors
    )



#automate valid currency check
def test_create_payment_rejects_unsupported_currency(client):
    response = client.post(
        "/payments",
        json={
            "customer_reference": "test_currency",
            "amount": "50.00",
            "currency": "USD",
        },
    )

    assert response.status_code == 422, response.text                           #validates the error thrown when invalid currency entered

    errors = response.json()["detail"]

    assert any(
        error["loc"] == ["body", "currency"]
        and error["type"] == "literal_error"
        for error in errors
    )

    list_response = client.get(                                                 #validates that a new test_currency customer id has not been created in the db
        "/payments",
        params={"customer_reference": "test_currency"},
    )

    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == []




#This checks two validation rules working together:
#- str_strip_whitespace=True removes the spaces, leaving "".
#- min_length=1 rejects that empty value.
def test_create_payment_rejects_blank_customer_reference(client):
    response = client.post(
        "/payments",
        json={
            "customer_reference": "   ",
            "amount": "50.00",
            "currency": "CAD",
        },
    )

    assert response.status_code == 422, response.text

    errors = response.json()["detail"]

    assert any(
        error["loc"] == ["body", "customer_reference"]
        and error["type"] == "string_too_short"
        for error in errors
    )




#automate the customer filter check.
def test_list_payments_filters_by_customer(client):
    # Create payments for two different customers.
    for customer in ["customer_a", "customer_b"]:
        response = client.post(
            "/payments",
            json={
                "customer_reference": customer,
                "amount": "50.00",
                "currency": "CAD",
            },
        )
        assert response.status_code == 201, response.text

    # Request only customer_a's payments.
    response = client.get(
        "/payments",
        params={"customer_reference": "customer_a"},
    )

    assert response.status_code == 200, response.text

    payments = response.json()

    assert len(payments) == 1
    assert payments[0]["customer_reference"] == "customer_a"



#test pagination with three payments
def test_list_payments_paginates(client):
    created_ids = []

    for amount in ["10.00", "20.00", "30.00"]:
        response = client.post(
            "/payments",
            json={
                "customer_reference": "pagination_customer",
                "amount": amount,
                "currency": "CAD",
            },
        )
        assert response.status_code == 201, response.text
        created_ids.append(response.json()["id"])

    # Get the complete ordered list for this customer.
    response = client.get(
        "/payments",
        params={
            "customer_reference": "pagination_customer",
            "limit": 10,
            "offset": 0,
        },
    )
    assert response.status_code == 200, response.text

    ordered_ids = [payment["id"] for payment in response.json()]

    assert len(ordered_ids) == 3
    assert set(ordered_ids) == set(created_ids)

    # Retrieve one payment per page.
    for offset in range(3):
        response = client.get(
            "/payments",
            params={
                "customer_reference": "pagination_customer",
                "limit": 1,
                "offset": offset,
            },
        )
        assert response.status_code == 200, response.text

        page_ids = [payment["id"] for payment in response.json()]                           #stores all the payment["id"] as a list in page_ids
        assert page_ids == [ordered_ids[offset]]                                            #varifies and validates that the ids collected after the GET operation are the same to the ones declared in the POST operation

    # Skipping all three payments should leave an empty page.
    response = client.get(
        "/payments",
        params={
            "customer_reference": "pagination_customer",
            "limit": 1,
            "offset": 3,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == []




#rejects if the limit value = 0
def test_list_payments_rejects_zero_limit(client):
    response = client.get(
        "/payments",
        params={"limit": 0},
    )

    assert response.status_code == 422, response.text

    errors = response.json()["detail"]

    assert any(
        error["loc"] == ["query", "limit"]
        and error["type"] == "greater_than_equal"
        for error in errors
    )




#rejects if the offset is negative
def test_list_payments_rejects_negative_offset(client):
    response = client.get(
        "/payments",
        params={"offset": -1},
    )

    assert response.status_code == 422, response.text

    errors = response.json()["detail"]

    assert any(
        error["loc"] == ["query", "offset"]
        and error["type"] == "greater_than_equal"
        for error in errors
    )




#reject if the 'limit' value > 100
def test_list_payments_rejects_limit_above_maximum(client):
    response = client.get(
        "/payments",
        params={"limit": 101},
    )

    assert response.status_code == 422, response.text

    errors = response.json()["detail"]

    assert any(
        error["loc"] == ["query", "limit"]
        and error["type"] == "less_than_equal"
        for error in errors
    )



#rejects invalid 'status' value
def test_list_payments_rejects_invalid_status(client):
    response = client.get(
        "/payments",
        params={"status": "cancelled"},
    )

    assert response.status_code == 422, response.text

    errors = response.json()["detail"]

    assert any(
        error["loc"] == ["query", "status"]
        and error["type"] == "literal_error"
        for error in errors
    )




#rejects excess decimal places for the 'amount' value
def test_create_payment_rejects_excess_decimal_places(client):
    response = client.post(
        "/payments",
        json={
            "customer_reference": "precision_customer",
            "amount": "10.001",
            "currency": "CAD",
        },
    )

    assert response.status_code == 422, response.text

    errors = response.json()["detail"]

    assert any(
        error["loc"] == ["body", "amount"]
        and error["type"] == "decimal_max_places"
        for error in errors
    )

    list_response = client.get(
        "/payments",
        params={"customer_reference": "precision_customer"},
    )

    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == []



#list the payments as per the 'status' value
def test_list_payments_filters_by_status(client):
    create_response = client.post(
        "/payments",
        json={
            "customer_reference": "status_customer",
            "amount": "50.00",
            "currency": "CAD",
        },
    )

    assert create_response.status_code == 201, create_response.text
    payment = create_response.json()
    assert payment["status"] == "pending"

    response = client.get(
        "/payments",
        params={
            "customer_reference": "status_customer",
            "status": "pending",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == [payment]

    for status in ["failed", "succeeded"]:
        response = client.get(
            "/payments",
            params={
                "customer_reference": "status_customer",
                "status": status,
            },
        )

        assert response.status_code == 200, response.text
        assert response.json() == []





#posting to the db and then validating and verifying that the return ids are sorted as per the latest date
def test_list_payments_orders_by_created_at_and_id(client, db_session):
    older_payment = Payment(
        id=UUID("00000000-0000-0000-0000-000000000003"),
        customer_reference="ordering_customer",
        amount=Decimal("10.00"),
        currency="CAD",
        status="pending",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    newer_lower_id = Payment(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        customer_reference="ordering_customer",
        amount=Decimal("20.00"),
        currency="CAD",
        status="pending",
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    newer_higher_id = Payment(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        customer_reference="ordering_customer",
        amount=Decimal("30.00"),
        currency="CAD",
        status="pending",
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    expected_ids = [
        str(newer_higher_id.id),
        str(newer_lower_id.id),
        str(older_payment.id),
    ]

    db_session.add_all([
        older_payment,
        newer_lower_id,
        newer_higher_id,
    ])
    db_session.commit()

    response = client.get(
        "/payments",
        params={"customer_reference": "ordering_customer"},
    )

    assert response.status_code == 200, response.text

    returned_ids = [payment["id"] for payment in response.json()]
    assert returned_ids == expected_ids