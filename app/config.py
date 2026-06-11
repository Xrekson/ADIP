from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_NAME: str = "Auction DI Pipeline"
    DEBUG: bool = False
    SECRET_KEY: str                        # openssl rand -hex 32
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # PostgreSQL
    DATABASE_URL: str                      # postgresql+asyncpg://user:pass@host/db

    # Azure Document Intelligence
    AZURE_DI_ENDPOINT: str                 # https://<your-resource>.cognitiveservices.azure.com/
    AZURE_DI_KEY: str                      # Your API key from Azure portal

    # Azure Service Bus
    AZURE_SB_CONNECTION_STRING: str        # From Azure portal → Shared access policies
    AZURE_SB_QUEUE_NAME: str = "auction-documents"

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:4200"]


@lru_cache
def get_settings() -> Settings:
    return Settings()