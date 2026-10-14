#This creates two endpoints—URL paths that accept requests and return responses: /health and /health/db
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine

#@asynccontextmanager lets FastAPI use this function as a lifecycle handler.
# The application runs while execution pauses at yield; during normal shutdown, engine.dispose() releases pooled database connections.
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    engine.dispose()


app = FastAPI(
    title="Payment Processing & Incident Investigation Platform",
    version="0.1.0",
    lifespan=lifespan,
)

#Checks whether the API can respond
@app.get("/health")
def health_check():
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