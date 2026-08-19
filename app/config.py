"""应用配置：从 .env 读取环境变量。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 数据库
    database_url: str = "postgresql+psycopg://eaos:eaos_dev_password@localhost:5433/eaos"

    # LLM（DeepSeek，OpenAI 兼容）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model_generation: str = "deepseek-chat"
    llm_model_extraction: str = "deepseek-chat"
    llm_model_factcheck: str = "deepseek-chat"
    llm_temperature: float = 0.3
    llm_timeout: int = 120

    # 应用
    app_env: str = "dev"
    export_dir: str = "exports"
    upload_dir: str = "uploads"
    pdf_chinese_font: str = "Microsoft YaHei"
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def export_path(self) -> Path:
        p = BASE_DIR / self.export_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def upload_path(self) -> Path:
        p = BASE_DIR / self.upload_dir
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
