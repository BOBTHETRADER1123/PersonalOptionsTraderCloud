from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_secret: str = "local-development-only-change-me"
    app_password: str = "paper-only"
    app_password_hash: str = ""
    cookie_secure: bool = False
    database_url: str = "sqlite:///./data/options_trader.db"
    data_dir: str = "./OptionsTraderData"
    host: str = "127.0.0.1"
    port: int = 8000
    quote_stale_seconds: int = 5
    charge_per_order: float = 20.0
    slippage_points: float = 0.0
    live_trading_enabled: bool = False
    cors_origins: str = ""

    @property
    def allowed_origins(self) -> list[str]:
        local = ["http://localhost:5173", "http://127.0.0.1:5173"]
        configured = [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]
        return list(dict.fromkeys([*local, *configured]))

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).resolve()


settings = Settings()
