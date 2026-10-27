#This file adds a uniques uuid to each api request for error tracking and log handling

from contextvars import ContextVar
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#This creates a context-specific place to hold each request’s tracking ID. default=None means no ID has been assigned yet.
request_id_context: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)                                         #The .set() method returns a token that remembers the previous context state.
            return

        request_id = str(uuid4())
        token = request_id_context.set(request_id)

        async def send_with_request_id(message: Message) -> None:                        #ASGI  sends an https response using msg. two types of msg: https.response.start and http.response.body
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id

            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)                         #sending the api request onto the outgoing response with the new id
        finally:
            request_id_context.reset(token)                                              #This matters because we don't want a request ID accidentally remaining in a context after its request has finished.


# Even if process_payment() raises an error, cleanup() still executes.