# A request is a message someone sends to your API asking it to do something.
# We store a tracking ID temporarily, not the whole request.
# Like a restaurant ticket number, the ID helps us find related logs.

from contextvars import ContextVar
from uuid import uuid4

import logging
from time import perf_counter

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("payment_platform")


# ContextVar lets different parts of the code read the current request's ID
# without passing it into every function.
# The middleware sets it before handling the request and resets it afterward.
# The same ID is returned in the X-Request-ID response header.
request_id_context: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp):
        # Save the next application or middleware in the chain.
        self.app = app

    # Runs when the middleware instance is called to handle an ASGI scope.
    async def __call__(
        self,
        scope: Scope,      # Information such as the request's method and path.
        receive: Receive,  # Reads incoming ASGI messages.
        send: Send,        # Sends outgoing ASGI messages.
    ) -> None:
        # Pass non-HTTP scopes, such as application lifecycle events, onward.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = perf_counter()       #stores the stopwatch's starting reading, to measure how long does the api take to measure the request
        status_code: int | None = None    #starts at None cuz the application hasn't produced a response yet

        request_id = str(uuid4())

#         Why are we adding request state now?

#         Imagine a request gets ID abc123, then crashes:
#         1. Middleware stores abc123 in the ContextVar and request state.
#         2. Your error log reads the ContextVar and records abc123.
#         3. Middleware resets the ContextVar during cleanup.
#         4. The outer error handler prepares the 500 response.
#         5. That handler can still read abc123 from request state and put it in the response header.
#         Then someone can report:
#         “My request failed. Its ID was abc123.”

# You can find the matching error log using that ID.

        # Keep the ID available to error handlers for this request.
        scope.setdefault("state", {})["request_id"] = request_id

        # Set the current ID. The token remembers the previous context state.
        token = request_id_context.set(request_id)

        # Intercept outgoing response messages to attach the tracking ID.
        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code

            # Response headers are sent in the http.response.start message.
            if message["type"] == "http.response.start":
                status_code = message["status"]             #to record the status of the returned msg: 200/404/422
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id

            # Forward every response message to the original send function.
            await send(message)

        try:
            # Pass the request onward, using our wrapper to send its response.
            await self.app(scope, receive, send_with_request_id)

        #in case there's an exception, it will be raised. the formatter will convert its format to json, displaying its method, path and status_code
        #normal handled errors, such as validation 422, wont enter this exception block
        except Exception:
            logger.exception(
                "Unhandled exception while handling HTTP request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status_code": status_code,
                },
            )
            raise


        finally:
            duration_ms = (perf_counter() - started_at) * 1000

            try:
                logger.info(
                    "HTTP request finished",
                    extra={                                      #attaches the four fields to the log record. the formatter now knows how to include them in json
                        "method": scope["method"],               #method: HTTP action (GET/ POST)
                        "path": scope["path"],                   #path: part of the url identifying the endpoint
                        "status_code": status_code,
                        "duration_ms": round(duration_ms, 2),
                    }
                )

            finally:
                # Restore the previous context even if handling the request fails.
                request_id_context.reset(token)


# Imagine a school reception desk:
# - Router: "You're asking about payments? Go to the payment function."
# - Middleware: "Here's tracking number abc123 for this visit."
# - ContextVar: Keeps that number available while staff handle the visit.
# - Logs: Record events, labelled with the current request's tracking number.

# Normal HTTP request flow:
# 1. An HTTP request arrives.
# 2. Middleware checks that it is HTTP.
# 3. A UUID is generated and stored in the current execution context.
# 4. FastAPI handles the request, such as a payment or health-check request.
# 5. Outgoing response messages pass through our wrapper.
# 6. The wrapper adds X-Request-ID when the response headers are sent.
# 7. Response messages are forwarded to the client.
# 8. The previous context value is restored when application handling ends.


# ContextVar vs Request state
# The two storage locations have different jobs:
# - ContextVar: lets logging code read the ID without receiving a request object.
# - Request state: lets an error handler retrieve the ID from the request itself.