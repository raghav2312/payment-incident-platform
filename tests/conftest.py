#conftest.py is the shared setup file for your automated tests.
#Pytest finds it automatically, so you don’t have to repeat the same database setup in every test.

import os

from uuid import uuid4

from sqlalchemy import delete

from app.models import IdempotencyRequest, Payment

# Select the test database before importing application modules.
os.environ["POSTGRES_DB"] = "payments_test_db"

from app.database import engine

# Stop immediately if the engine points to another database.
if engine.url.database != "payments_test_db":
    raise RuntimeError("Tests must use payments_test_db.")


import pytest
from sqlalchemy import text

from pathlib import Path

from alembic import command
from alembic.config import Config

#@pytest.fixture: defines setup and cleanup that pytest manages.
@pytest.fixture(scope="session", autouse=True)                                  #scope="session" runs this once for the entire test run. autouse = True makes it run automatically
def prepare_test_database():                                                    #prepares the payment test db and brings it upto date as per the migrations
    try:
        # Verify the actual database before running migrations.
        with engine.connect() as connection:
            database_name = connection.execute(
                text("SELECT current_database()")
            ).scalar_one()

            if database_name != "payments_test_db":
                raise RuntimeError(
                    "Refusing to run test migrations outside payments_test_db."
                )

        # Find alembic.ini in the project root.
        project_root = Path(__file__).resolve().parents[1]
        config = Config(str(project_root / "alembic.ini"))

        # Apply pending migrations before any tests run.
        command.upgrade(config, "head")

        yield
    finally:
        engine.dispose()



from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.main import app


@pytest.fixture                                                                 #@pytest.fixture — without a scope specified, this fixture runs separately for each test that requests client.
def client(prepare_test_database, monkeypatch):                                 #prepare_test_database — ensures our table-preparation fixture has run.
    with engine.connect() as connection:
        transaction = connection.begin()                                        #connection.begin() — starts an outer transaction controlled by the test.

        def override_get_db():                                                  #override_get_db() — supplies a fresh SQLAlchemy session for each request, using this test connection.
            with Session(
                bind=connection,
                join_transaction_mode="create_savepoint",                       #create_savepoint — keeps the endpoint’s session.commit() inside the test’s outer transaction.
            ) as session:                                                       #The endpoint can exercise its commit logic while the test retains the ability to undo its changes.
                yield session

        try:
            with monkeypatch.context() as patch:                                #monkeypatch — pytest’s helper for temporary changes. Here, it temporarily replaces FastAPI’s usual get_db dependency.
                patch.setitem(
                    app.dependency_overrides,                                   #The fixture temporarily tells FastAPI:
                    get_db,                                                     # “Whenever an endpoint asks for get_db, use override_get_db instead.”
                    override_get_db,
                )

                with TestClient(app) as test_client:                            #TestClient(app) — lets tests call your API directly in Python, without contacting your running server on port 8001.
                    yield test_client
        finally:
            transaction.rollback()                                              #finally: transaction.rollback() — undoes changes made through those test sessions, even if the test fails.




#inspecting records directly, without an api request
@pytest.fixture                                                                 #@pytest.fixture makes this setup available to tests that request db_session.
def db_session(client):                                                         #client tells pytest to prepare your existing client fixture first, including its isolated database transaction.
    override = app.dependency_overrides[get_db]                                 #app.dependency_overrides[get_db] retrieves the replacement database-session function your client fixture installed.

    yield from override()                                                       #yield from override() supplies that function’s test session and lets it perform its cleanup afterward.




#The direct database session and the API’s sessions are separate session objects sharing the same connection and outer transaction.
#We’ll commit the sample-data session before making the API request; the outer transaction will still roll everything back after the test.



# Imagine your payment app is a restaurant:
# - client is a customer ordering through the waiter—it sends requests through your API.
# - db_session is someone preparing ingredients in the kitchen—it works directly with the database.
# Both work in the same temporary restaurant set up for one test.

# 1. client: use the app like a customer
# response = client.get("/payments")


# This asks your API: “Show me the payments.”

# The request goes through your actual endpoint code, which reads the database and returns a response.

# Your client fixture also handles setup and cleanup: it prepares the test connection and rolls back the test’s database changes afterward.

# 2. db_session: prepare data directly

# For the ordering test, we want payments with specific dates:
# Payment	Created
# A	Monday
# B	Wednesday
# C	Tuesday


# We expect the API to return B, C, A—newest first.

# But your POST endpoint automatically sets the creation time. We cannot ask it to create a payment “last Monday.”

# So we use db_session to place those carefully chosen records directly into the test database. Then we use client to ask the API for the list and check its order.

# How does this little function work?
# @pytest.fixturedef db_session(client):    override = app.dependency_overrides[get_db]    yield from override()


# Think of it as three instructions:
# 1. db_session(client): “Make sure the client’s test setup is ready.”
# 2. override = ...: “Find the function that provides database sessions using our test connection.”
# 3. yield from override(): “Use that function to give the test a session, and let it clean up the session afterward.”
# It creates a separate session using the same test connection, so both ways of accessing the database work with the same test data.

# For our next test: db_session prepares the payments → client requests the list → assertions check the order → the fixtures clean up.







# Here’s how this differs from client:
# - Separate sessions: overlapping requests can use separate database connections.
# - Real commits: there’s no outer transaction trapping the service’s commits.
# - Unique test identifiers: each test gets its own customer reference and key.
# - Targeted cleanup: we delete only records belonging to that test, removing the idempotency record before its referenced payment.
# - Database guards: setup and cleanup both verify payments_test_db.
# Concurrency tests will request concurrency_client only, not the existing client or db_session fixtures.

@pytest.fixture
def concurrency_client(prepare_test_database, monkeypatch):
    # Verify the actual database before allowing real commits.
    with engine.connect() as connection:
        database_name = connection.execute(
            text("SELECT current_database()")
        ).scalar_one()

        if database_name != "payments_test_db":
            raise RuntimeError(
                "Concurrency tests must use payments_test_db."
            )

    unique_suffix = uuid4().hex
    customer_reference = f"concurrency_{unique_suffix}"
    idempotency_key = f"concurrency-{unique_suffix}"

    def override_get_db():
        # Each request receives its own session.
        with Session(engine) as session:
            yield session

    try:
        with monkeypatch.context() as patch:
            patch.setitem(
                app.dependency_overrides,
                get_db,
                override_get_db,
            )

            with TestClient(app) as test_client:
                yield {
                    "client": test_client,
                    "customer_reference": customer_reference,
                    "idempotency_key": idempotency_key,
                }
    finally:
        # Delete only this test's records, in foreign-key order.
        with engine.begin() as connection:
            database_name = connection.execute(
                text("SELECT current_database()")
            ).scalar_one()

            if database_name != "payments_test_db":
                raise RuntimeError(
                    "Refusing cleanup outside payments_test_db."
                )

            connection.execute(
                delete(IdempotencyRequest).where(
                    IdempotencyRequest.key == idempotency_key
                )
            )
            connection.execute(
                delete(Payment).where(
                    Payment.customer_reference == customer_reference
                )
            )