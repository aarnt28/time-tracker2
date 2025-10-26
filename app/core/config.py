from functools import lru_cache
from typing import List, Sequence

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore[import-not-found]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = Field(default="Tracker2", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=9444, alias="PORT")
    external_url: str | None = Field(default=None, alias="EXTERNAL_URL")
    api_token: str = Field(default="", alias="API_TOKEN")
    db_url: str = Field(default="sqlite:///./data/data.db", alias="DB_URL")
    allowed_hosts: List[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"], alias="ALLOWED_HOSTS"
    )
    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:9444"], alias="CORS_ORIGINS"
    )

    @field_validator("allowed_hosts", "cors_origins", mode="before")
    @classmethod
    def _split_str(cls, value: Sequence[str] | str | None) -> List[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(v).strip() for v in value if str(v).strip()]
        return [item.strip() for item in str(value).split(",") if item.strip()]


@lru_cache()
def get_settings() -> Settings:
    return Settings()
