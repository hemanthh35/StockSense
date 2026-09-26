from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_KEYS = {"", "dev-secret", "change-me-to-a-long-random-string", "change-me"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"  # set to "production" to refuse insecure defaults at startup
    database_url: str = "postgresql+psycopg://stocksense:stocksense@localhost:5432/stocksense"
    secret_key: str = "dev-secret"
    access_token_minutes: int = 720
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"  # comma separated
    rate_limit_enabled: bool = True
    brevo_api_key: str = ""
    brevo_sender_email: str = ""
    brevo_sender_name: str = "StockSense"
    groq_api_key: str = ""  # enables the AI assistant (https://console.groq.com)
    groq_model: str = "openai/gpt-oss-120b"  # or openai/gpt-oss-20b for faster, cheaper answers
    groq_base_url: str = "https://api.groq.com/openai/v1"
    assistant_rate_per_minute: int = 20  # chat requests per person per minute
    digest_enabled: bool = True
    digest_hour_utc: int = 3  # 03:00 UTC = 08:30 IST

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def production(self) -> bool:
        return self.app_env.lower() in ("production", "prod")

    def check_secure(self) -> str | None:
        """None if the configuration is safe; otherwise what is wrong."""
        if self.secret_key in INSECURE_KEYS or len(self.secret_key) < 32:
            return "SECRET_KEY is missing, a placeholder, or shorter than 32 characters (try: openssl rand -base64 48)"
        return None


settings = Settings()
