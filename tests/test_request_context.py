import json
import logging
from io import StringIO
from uuid import UUID
import pytest

import asyncio

from app.middleware.request_context import (
    RequestContextMiddleware,
    request_id_context,
)

from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.main import app


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


#test for "If my application crashes, will my middleware record what happened and clean up properly"
def test_unhandled_exception_is_logged(client, monkeypatch):
    logger = logging.getLogger("payment_platform")
    handler = next(
        handler
        for handler in logger.handlers
        if handler.get_name() == "payment_platform_console"
    )
    output = StringIO()
    observed = {}

    # A fake application that deliberately fails.
    async def failing_app(scope, receive, send):
        observed["request_id"] = request_id_context.get()
        raise RuntimeError("Synthetic test failure")


    #receive() and send() function are declared and explained here cuz middleware's interface expects them
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        pass

    async def run_request():
        previous_id = request_id_context.get()
        middleware = RequestContextMiddleware(failing_app)                 ## Creates a middleware instance, passing the failing_app function without calling it.

        # The middleware must log the exception and let it propagate.
        with pytest.raises(RuntimeError, match="Synthetic test failure"):
            await middleware(
                {"type": "http", "method": "GET", "path": "/test-error"},
                receive,
                send,
            )

        # Cleanup must happen even when the application fails.
        assert request_id_context.get() == previous_id                  #This checks that the middleware restored the context after the failure.

    with monkeypatch.context() as patch:
        patch.setattr(handler, "stream", output)                        #This temporarily directs the logger’s output into our StringIO buffer.
        asyncio.run(run_request())

    #Convert captured JSON text into dictionaries
    log_entries = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if line.strip()
    ]


    #This keeps only entries with that exact message, filtering out the request-finished log.
    error_logs = [
        entry
        for entry in log_entries
        if entry.get("message")
        == "Unhandled exception while handling HTTP request"
    ]

    assert len(error_logs) == 1
    error_log = error_logs[0]

    assert error_log["level"] == "ERROR"
    assert UUID(error_log["request_id"]).version == 4
    assert error_log["request_id"] == observed["request_id"]
    assert error_log["method"] == "GET"
    assert error_log["path"] == "/test-error"
    assert error_log["status_code"] is None
    assert "Traceback" in error_log["exception"]
    assert "RuntimeError: Synthetic test failure" in error_log["exception"]


#test for checking if the app crashes unexpectedly, the user gets a safe error response and I get a useful error log with the same request id connecting them
#deliberately creates a fake failure to check my erro handling code
def test_unhandled_error_response_includes_request_id(client, monkeypatch):
    logger = logging.getLogger("payment_platform")
    handler = next(
        handler
        for handler in logger.handlers
        if handler.get_name() == "payment_platform_console"
    )
    output = StringIO()

    # Fail before any database work happens.
    def failing_get_db():                                                               #temporarily replaces the db dependency and deliberately raises an error before accessing postgres
        raise RuntimeError("Synthetic database dependency failure")

    #replace the dependency and log destination
    with monkeypatch.context() as patch:
        patch.setitem(app.dependency_overrides, get_db, failing_get_db)                 #whenever an endpoint  asks for get_db, use failing_get_db instead
        patch.setattr(handler, "stream", output)

        with TestClient(app, raise_server_exceptions=False) as error_client:            #Test Client requests the application and triggers the crash
            response = error_client.get("/payments")

# The sequence for the above commands:
# 1. The test requests GET /payments.
# 2. FastAPI tries to resolve the database dependency.
# 3. The replacement dependency raises RuntimeError.
# 4. Your application’s error handling should log the failure and return an error response.

    assert response.status_code == 500                                                  #checks that the client receives a safe response
    assert response.json() == {"detail": "Internal server error."}
    assert "Synthetic database dependency failure" not in response.text                 #checks that the internal exception doesnot appear in the response

    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id).version == 4

    log_entries = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if line.strip()
    ]

    error_logs = [                                                                      #assign error_logs only those entries where the message produced by unhandled-exception handler
        entry
        for entry in log_entries
        if entry.get("message")
        == "Unhandled exception while handling HTTP request"
    ]

    assert len(error_logs) == 1
    assert error_logs[0]["request_id"] == request_id
    assert (
        "RuntimeError: Synthetic database dependency failure"
        in error_logs[0]["exception"]
    )
#Passing this test means this simulated failure returns a safe 500 response, includes a valid request ID, and produces exactly one matching error log with the underlying exception details.