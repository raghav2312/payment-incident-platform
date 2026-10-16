#conftest.py is the shared setup file for your automated tests. 
#Pytest finds it automatically, so you don’t have to repeat the same database setup in every test.

import os

# Select the test database before importing application modules.
os.environ["POSTGRES_DB"] = "payments_test_db"

from app.database import engine

# Stop immediately if the engine points to another database.
if engine.url.database != "payments_test_db":
    raise RuntimeError("Tests must use payments_test_db.")


import pytest
from sqlalchemy import text

from app.models import Base

#@pytest.fixture: defines setup and cleanup that pytest manages.
@pytest.fixture(scope="session", autouse=True)                                  #scope="session" runs this once for the entire test run. autouse = True makes it run automatically
def prepare_test_database():                             
    with engine.begin() as connection:                                          #engine.begin() opens a connection and transaction, committing on success or rolling back on an error.
        database_name = connection.execute(
            text("SELECT current_database()")
        ).scalar_one()

        if database_name != "payments_test_db":
            raise RuntimeError(
                "Refusing to prepare tables outside payments_test_db."
            )

        Base.metadata.create_all(bind=connection)                               #Base.metadata.create_all(...) creates missing tables from your models, including payments. It does not migrate existing tables.

    yield                                                                       #This is the dividing line: “Everything is ready. Here’s the client—run your test. When you finish, I’ll clean up.”

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

