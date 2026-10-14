#This file defines how our application connects to PostgreSQL.

from sqlalchemy import URL, create_engine

from app.config import settings


database_url = URL.create(
    drivername="postgresql+psycopg",                            #Selects PostgreSQL and the Psycopg driver.
    username=settings.POSTGRES_USER,
    password=settings.POSTGRES_PASSWORD.get_secret_value(),
    host=settings.POSTGRES_HOST,
    port=settings.POSTGRES_PORT,
    database=settings.POSTGRES_DB,
)

engine = create_engine(
    database_url,
    pool_pre_ping=True,                                          #checks connections when taking them from the connection pool, helping detect stale connections.
    connect_args={"connect_timeout": 5},
)

#Creating the engine does not connect immediately. The first connection happens when we ask it to execute database work.