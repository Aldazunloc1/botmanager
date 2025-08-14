from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    # Bot configuration
    bot_token: str = Field(..., env="BOT_TOKEN")
    imei_checker_api_key: str = Field(..., env="IMEI_CHECKER_API_KEY")  # Nombre corregido
    imei_api_url: str = Field("https://alpha.imeicheck.com/api/php-api/create", env="IMEI_API_URL")
    
    # FastAPI configuration
    host: str = Field("0.0.0.0", env="HOST")
    port: int = Field(8000, env="PORT")
    debug: bool = Field(False, env="DEBUG")
    
    # Webhook configuration
    webhook_url: str = Field("", env="WEBHOOK_URL")
    webhook_path: str = Field("/webhook", env="WEBHOOK_PATH")
    webhook_secret: str = Field("", env="WEBHOOK_SECRET")
    
    # Bot settings
    owner_id: int = Field(7655366089, env="OWNER_ID")
    users_db_path: str = Field("users.json", env="USERS_DB_PATH")
    services_db_path: str = Field("services.json", env="SERVICES_DB_PATH")
    request_timeout: int = Field(15, env="REQUEST_TIMEOUT")
    max_retries: int = Field(3, env="MAX_RETRIES")
    
    # AutoPinger settings
    autopinger_enabled: bool = Field(True, env="AUTOPINGER_ENABLED")
    autopinger_interval: int = Field(300, env="AUTOPINGER_INTERVAL")
    autopinger_url: str = Field("", env="AUTOPINGER_URL")
    
    # Admin configuration for API endpoints
    admin_key: str = Field("your_secure_admin_key_change_this", env="ADMIN_KEY")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Permite campos extra sin error


settings = Settings()