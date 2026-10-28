import json
import logging
from io import StringIO
from uuid import UUID
import pytest

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


#Test for /health, making sure it logs the correct method, path, status, request Id, and a non-negative duration
@pytest.mark.parametrize(
    "path, expected_status",
    [
        ("/health", 200),
        ("/payments/not-a-uuid", 422),
    ],
)
def test_request_log_includes_response_details(
    client, monkeypatch, path, expected_status
):
    logger = logging.getLogger("payment_platform")
    handler = next(
        handler
        for handler in logger.handlers
        if handler.get_name() == "payment_platform_console"
    )

    output = StringIO()

    with monkeypatch.context() as patch:
        patch.setattr(handler, "stream", output)
        response = client.get(path)

    assert response.status_code == expected_status, response.text

    log_entries = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if line.strip()
    ]

#Original log msg:
# {"message": "Application health check requested", "request_id": "abc123"}
# {"message": "HTTP request finished", "request_id": "abc123", "method": "GET", "path": "/health", "status_code": 200, "duration_ms": 2.45}


#Log msg after going through functions mentioned above and then stored in Log entries
# [
#     {
#         "message": "Application health check requested",
#         "request_id": "abc123",
#     },
#     {
#         "message": "HTTP request finished",
#         "request_id": "abc123",
#         "method": "GET",
#         "path": "/health",
#         "status_code": 200,
#         "duration_ms": 2.45,
#     },
# ]

    request_logs = [
        entry
        for entry in log_entries
        if entry.get("message") == "HTTP request finished"
    ]


#Keeping only the request finished logs in request_logs
#     [
#     {
#         "message": "HTTP request finished",
#         "request_id": "abc123",
#         "method": "GET",
#         "path": "/health",
#         "status_code": 200,
#         "duration_ms": 2.45,
#     }
# ]

    assert len(request_logs) == 1           #only one log will exist

    request_log = request_logs[0]           #taking the dictionary out of the list

    assert request_log["request_id"] == response.headers["X-Request-ID"]
    assert request_log["method"] == "GET"
    assert request_log["path"] == path
    assert request_log["status_code"] == expected_status
    assert isinstance(request_log["duration_ms"], (int, float))
    assert request_log["duration_ms"] >= 0