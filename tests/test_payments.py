#the test_ in the filename and the function lets pytest discover the test

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