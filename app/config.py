#This file loads and validates database settings. It doesn’t connect to PostgreSQL yet.

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

#Retrieve the project root directory, which is two levels up from this file's location. This is used to locate the .env file for loading environment variables.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: SecretStr
    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = Field(default=5434, ge=1, le=65535)

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

#Creates the settings object and loads its values when this module is imported. 
#Missing required settings or an invalid port will produce a validation error.
settings = Settings()