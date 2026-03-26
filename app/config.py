from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Groq API
    groq_api_key: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://localhost:5432/podcast_assistant"

    # Azure Blob Storage
    azure_blob_connection_string: str = ""
    azure_blob_container_name: str = "podcast-audio"

    # Scheduler
    poll_interval_hours: int = 6

    # Feeds file path
    feeds_file: str = "feeds.yaml"


settings = Settings()
