from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://stocksense:stocksense@localhost:5432/stocksense"
    secret_key: str = "dev-secret"
    access_token_minutes: int = 720
    brevo_api_key: str = ""
    brevo_sender_email: str = ""
    brevo_sender_name: str = "StockSense"


settings = Settings()
