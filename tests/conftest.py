#conftest.py is a special file pytest automatically loads to configure tests.

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

    yield

    engine.dispose()