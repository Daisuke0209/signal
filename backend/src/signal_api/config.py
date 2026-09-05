from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    seed_demo_password: SecretStr | None = None
    backend_cors_origins: str = "http://localhost:3000"
    document_storage_dir: Path = ROOT_ENV_FILE.parent / ".local" / "documents"
    document_max_size_bytes: int = 20 * 1024 * 1024
    document_max_count_per_organization: int = 100
    openai_api_key: SecretStr | None = None
    transcription_model: str = "gpt-live-transcribe"
    transcription_energy_threshold: float = Field(default=0.005, gt=0, le=1)

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url.startswith("postgres://"):
            return self.database_url.replace("postgres://", "postgresql+psycopg://", 1)
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace(
                "postgresql://", "postgresql+psycopg://", 1
            )
        return self.database_url

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.backend_cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
