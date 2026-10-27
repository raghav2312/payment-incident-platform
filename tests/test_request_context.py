import json
import logging
from io import StringIO
from uuid import UUID

#checks that two successful requests receive valid, different tracking IDs.
def test_requests_receive_distinct_request_ids(client):
    first_response = client.get("/health")
    second_response = client.get("/health")

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    first_id = first_response.headers["X-Request-ID"]
    second_id = second_response.headers["X-Request-ID"]

    assert UUID(first_id).version == 4
    assert UUID(second_id).version == 4
    assert first_id != second_id



#checks that a validation-error response also includes a valid tracking ID.
def test_validation_error_includes_request_id(client):
    response = client.get("/payments/not-a-uuid")

    assert response.status_code == 422, response.text

    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4



#to verify that the log for the get.("/health") is logging the same msg that we have defined within that get command
#the the uuid for generated for this command is same in the logs and the headers
def test_health_log_matches_response_request_id(client, monkeypatch):
    logger = logging.getLogger("payment_platform")

    handler = next(
        handler
        for handler in logger.handlers
        if handler.get_name() == "payment_platform_console"
    )

    output = StringIO()                                                             #creates a temporary memory buffer

    with monkeypatch.context() as patch:
        patch.setattr(handler, "stream", output)                                    #patch.setattr(...) temporarily sends that handler’s output into the buffer. Its real JSON formatter still runs.

        response = client.get("/health")
# Leaving the with block restores the original stream automatically.



    assert response.status_code == 200, response.text

    log_entries = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if line.strip()
    ]

    health_logs = [
        entry
        for entry in log_entries
        if entry.get("message") == "Application health check requested"
    ]


# The assertions check the emitted JSON and its request ID.
    assert len(health_logs) == 1
    assert health_logs[0]["request_id"] == response.headers["X-Request-ID"]