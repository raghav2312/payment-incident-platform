from app.database import engine                              #Imports our database connection manager.
from app.models import Base                                  #Loads models.py, including the Payment class and its table definition.


#Base: Holds the table definitions registered with Base.
try:
    Base.metadata.create_all(bind=engine)                    #Connects to PostgreSQL and creates any missing registered tables, including their constraints and indexes.
    print("Database tables created or already present.")
finally:                                                     #Runs cleanup whether table creation succeeds or raises an error.
    engine.dispose()                                         #Releases pooled database connections before the script finishes.