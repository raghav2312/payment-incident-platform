import os
from pathlib import Path

# Set the database before Alembic imports our application settings.
os.environ["POSTGRES_DB"] = "payments_migration_check_db"

from alembic import command
from alembic.config import Config
from app.database import engine


def main():
    # Refuse to proceed if the engine targets another database.
    if engine.url.database != "payments_migration_check_db":
        raise RuntimeError(
            "Migration check must use payments_migration_check_db."
        )

    project_root = Path(__file__).resolve().parent
    config = Config(str(project_root / "alembic.ini"))                                                      #loads alembic configuration as per alembic.ini

    command.upgrade(config, "head")                                                                         #use the migrations/env,py file to bring the db to its latest state/migration


if __name__ == "__main__":
    main()