#Migrations are saved instructions for building and changing your database structure. We use Alembic to run those instructions and track which ones have been applied.


from logging.config import fileConfig

from alembic import context

from app.database import database_url, engine
from app.models import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# Give Alembic the table definitions registered with Base.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without connecting to PostgreSQL."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,

        #True enables this behavior for supported values. It does not mean every Python value can automatically be converted into SQL.
        literal_binds=True,

        #How should remaining placeholders look?
        dialect_opts={"paramstyle": "named"},
    )


    #Alembic goes through the requested migrations and outputs SQL, including transaction statements where appropriate. Nothing is executed against PostgreSQL.
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migration operations using a database connection."""
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
            )


            #For a migration upgrade, Alembic runs the requested changes inside a database transaction.
            #With PostgreSQL’s usual transactional schema operations, success commits the changes; an error rolls them back.
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()