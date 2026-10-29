#This creates two endpoints—URL paths that accept requests and return responses: /health and /health/db
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine
from app.routers.payments import router as payments_router
from app.middleware.request_context import RequestContextMiddleware

import logging

from app.logging_config import configure_logging

logger = logging.getLogger("payment_platform")

# @asynccontextmanager lets FastAPI use this function as a lifecycle handler.
# The application runs while execution pauses at yield; during normal shutdown, engine.dispose() releases pooled database connections.
@asynccontextmanager
async def lifespan(app: FastAPI):                                            #These lifecycle messages will have "request_id": null because startup and shutdown aren’t HTTP requests.
    configure_logging()
    logger.info("Application started")

    try:
        yield
    finally:
        engine.dispose()
        logger.info("Application stopped")


app = FastAPI(
    title="Payment Processing & Incident Investigation Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(RequestContextMiddleware)                                 #for adding a unique id to the outgoing response for log handling and errors fix

app.include_router(payments_router)                                          #Add the payment endpoints defined in payments_router to this FastAPI application.

@app.exception_handler(Exception)                                            #registers a handler for otherwise unhandled exceptions
async def unexpected_error_handler(
    request: Request,                                                        #gives access to the failed request, including its saved state
    exc: Exception,                                                          #the exception. middleware logs them
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)                  #returns the saved ID, returns None if its unavailable

    headers = {}
    if request_id is not None:
        headers["X-Request-ID"] = request_id

    return JSONResponse(                                                     #returns a generic error msg with status 500 and saved tracking id in its header
        status_code=500,
        content={"detail": "Internal server error."},
        headers=headers,
    )

#Checks whether the API can respond
@app.get("/health")
def health_check():
    logger.info("Application health check requested")
    return {"status": "ok"}



#Checks whether the API can connect to PostgreSQL and execute SQL.
@app.get("/health/db")
def database_health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()           #asks PostgreSQL to return the number 1. It tests query execution without needing a table or changing data. Only one row result(1) expected

        return {"status": "ok", "database": "connected"}                #sends a Python dictionary that FastAPI converts into a JSON response.

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from None                                                     #suppresses the chained database exception if this exception is displayed as a traceback.