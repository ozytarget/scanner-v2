from pydantic import Field
from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    # App
    APP_NAME: str = "SCANNER v2"
    DEBUG: bool = False
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production-please")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # APIs
    TRADIER_API_KEY: str = os.getenv("TRADIER_API_KEY", "")
    FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")
    FINVIZ_API_TOKEN: str = os.getenv("FINVIZ_API_TOKEN", "")
    POLYGON_API_KEY: str = os.getenv("POLYGON_API_KEY", "")
    KRAKEN_API_KEY: str = os.getenv("KRAKEN_API_KEY", "")
    KRAKEN_PRIVATE_KEY: str = os.getenv("KRAKEN_PRIVATE_KEY", "")

    # DB – v2 uses its own URL to avoid conflicts with legacy Streamlit DB.
    # Set V2_DATABASE_URL in env for PostgreSQL on Railway.
    # Falls back to async SQLite for local dev.
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./scanner_v2.db",
        validation_alias="V2_DATABASE_URL",
    )

    # CORS – comma-separated origins
    CORS_ORIGINS: str = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:3001"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
