#checks if the db connection is successful
from sqlalchemy import text                                                        #wraps our sql query so sqlalchemy can execute it
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine


try:
    with engine.connect() as connection:                                           #Opens a real connection using the settings from .env.
        result = connection.execute(                                               #Ensures the connection is returned to the pool when the block finishes, including after an error.
            text("SELECT current_database(), current_user")                        #Sends SQL query to PostgreSQL, asking which db and account this connection is using
        )
        database_name, username = result.one()                                     #Retrieves the expected single result row, which we unpack into two variables.

        print("Database connection successful!")
        print(f"Database: {database_name}")
        print(f"User: {username}")

except SQLAlchemyError:                                                            #Handles database errors with a message that doesn’t print connection credentials.
    print(
        "Database connection failed. "
        "Check that Docker is running and your .env settings are correct."
    )
    raise SystemExit(1)                                                            #Exits with a failure code, useful for automated checks later.

finally:
    engine.dispose()                                                               #Releases the engine’s pooled connections when this standalone check finishes.