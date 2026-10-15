from collections.abc import Generator

from sqlalchemy.orm import Session                  #SQLAlchemy’s object for working with database models and transactions.

from app.database import engine


def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:                #Ensures the session closes when its work finishes, including after an error.
        yield session                               #Gives the session to the endpoint, then lets cleanup happen afterward.


#Closing a session does not commit changes automatically. Our payment endpoint will explicitly call session.commit() to save a payment. Any unfinished transaction is rolled back when the session closes.
#When we connect this function using FastAPI’s Depends(get_db), FastAPI will manage providing the session and running its cleanup.

#In a restaurant scenario, session will be a waiter and engine will a telephone line to the kitchen(db)