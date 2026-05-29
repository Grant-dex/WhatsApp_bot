import os
import sys
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, model_validator


def get_bundle_dir() -> Path:
    """Return the directory containing bundled data files.

    When running from PyInstaller, uses sys._MEIPASS (the _internal directory).
    When running from source, uses the project root (parent of src/).
    """
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """Return the data directory, either from env var or current working dir."""
    data_dir = os.getenv("WHATSAPP_BOT_DATA_DIR", "")
    if data_dir:
        return Path(data_dir)
    return Path.cwd()


def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ.
    Existing environment variables take precedence (never overwritten).
    If path is relative and WHATSAPP_BOT_DATA_DIR is set, look there first."""
    env_path = Path(path)
    if not env_path.is_absolute():
        data_dir = get_data_dir()
        data_env = data_dir / path
        if data_env.exists():
            env_path = data_env
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def get_api_key() -> str:
    val = os.getenv("LLM_API_KEY", "").strip()
    if not val:
        raise RuntimeError(
            "LLM_API_KEY is not set. Export LLM_API_KEY=... or create a .env file "
            "(see .env.example)."
        )
    return val


class AppConfig(BaseModel):
    name: str = "WhatsApp Business Bot"
    timezone: str = "Asia/Shanghai"


class BusinessConfig(BaseModel):
    owner_name: str = "Grant"
    company_name: str = "Tide Power"
    quiet_hours_start: int = 21
    quiet_hours_end: int = 8
    max_auto_replies_per_hour: int = 30
    min_delay_between_messages_seconds: int = 60


class AIConfig(BaseModel):
    provider: str = "openai_compatible"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    max_context_messages: int = 20
    reply_max_length: int = 150
    reply_cooldown_minutes: int = 10

    @model_validator(mode="after")
    def apply_env_overrides(self) -> "AIConfig":
        if os.getenv("LLM_BASE_URL"):
            self.base_url = os.getenv("LLM_BASE_URL")
        if os.getenv("LLM_MODEL"):
            self.model = os.getenv("LLM_MODEL")
        return self


class SchedulerConfig(BaseModel):
    followup_check_interval_minutes: int = 5
    default_followup_days: int = 7


class DatabaseConfig(BaseModel):
    path: str = "./data/customers.db"


class BridgeConfig(BaseModel):
    port: int = 3001
    host: str = "127.0.0.1"
    proxy: str = ""

    @model_validator(mode="after")
    def apply_env_overrides(self) -> "BridgeConfig":
        if os.getenv("BRIDGE_HOST"):
            self.host = os.getenv("BRIDGE_HOST")
        if os.getenv("BRIDGE_PORT"):
            self.port = int(os.getenv("BRIDGE_PORT"))
        return self


class APIConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000

    @model_validator(mode="after")
    def apply_env_overrides(self) -> "APIConfig":
        if os.getenv("API_HOST"):
            self.host = os.getenv("API_HOST")
        if os.getenv("API_PORT"):
            self.port = int(os.getenv("API_PORT"))
        return self


class Config(BaseModel):
    app: AppConfig = AppConfig()
    business: BusinessConfig = BusinessConfig()
    ai: AIConfig = AIConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    database: DatabaseConfig = DatabaseConfig()
    bridge: BridgeConfig = BridgeConfig()
    api: APIConfig = APIConfig()

    @model_validator(mode="after")
    def resolve_paths(self) -> "Config":
        db_path = Path(self.database.path)
        if not db_path.is_absolute():
            data_dir = get_data_dir()
            self.database.path = str(data_dir / db_path)
        return self


_config: Optional[Config] = None


def load_config(config_path: str = "config.yaml") -> Config:
    global _config
    path = Path(config_path)
    if not path.is_absolute():
        data_dir = get_data_dir()
        data_config = data_dir / config_path
        if data_config.exists():
            path = data_config
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(path) as f:
        raw = yaml.safe_load(f)
    _config = Config(**raw)
    return _config


def get_config() -> Config:
    if _config is None:
        raise RuntimeError("Config not loaded. Call load_config() first.")
    return _config
