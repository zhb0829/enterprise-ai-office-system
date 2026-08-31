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

    # Embedding（OpenAI 兼容接口；DeepSeek 对话模型不承担向量化）
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 0
    embedding_timeout: int = 60
    embedding_batch_size: int = 64

    # 应用
    app_env: str = "dev"
    export_dir: str = "exports"
    upload_dir: str = "uploads"
    pdf_chinese_font: str = "C:/Windows/Fonts/msyh.ttc"
    cors_origins: str = "http://localhost:5173"
    ai_internal_token: str = "eaos-internal-token-change-me"
    qual_java_base_url: str = "http://localhost:8080"

    # 情报聚合 / Celery。权限由 Java 网关统一负责。
    redis_url: str = "redis://localhost:6379/0"
    celery_enabled: bool = False
    collection_user_agent: str = "EAOS-IntelligenceCollector/0.1 (+internal)"
    collection_timeout: int = 20
    collection_max_items: int = 50
    collection_failure_pause_after: int = 3

    # 舆情分析（P1）：Python 是纯 Worker，业务数据全部经由 Java 内部接口读写，
    # 本服务仅在自己的 AI 记录表中保存任务运行/模型调用记录。
    opinion_java_base_url: str = "http://localhost:8080"
    opinion_java_token: str = "eaos-opinion-internal-dev-token"
    opinion_internal_token: str = "eaos-opinion-internal-dev-token"
    opinion_max_articles_per_source: int = 200
    opinion_analysis_budget_per_job: int = 50
    opinion_asr_service_url: str = ""

    # 会议公开信息整理（P2）：Java 保存业务数据，Python 只运行解析与 AI 流程。
    meeting_java_base_url: str = "http://localhost:8080"
    meeting_java_token: str = "eaos-meeting-internal-dev-token"
    meeting_internal_token: str = "eaos-meeting-internal-dev-token"
    meeting_rss_urls: str = ""
    meeting_report_model: str = "deepseek-chat"
    meeting_card_model: str = "deepseek-chat"
    meeting_vision_model: str = ""
    meeting_vision_api_key: str = ""
    meeting_vision_base_url: str = ""
    meeting_asr_api_key: str = ""
    meeting_asr_base_url: str = "https://api.openai.com/v1"
    meeting_asr_model: str = "whisper-1"

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

    @property
    def meeting_rss_url_list(self) -> list[str]:
        return [url.strip() for url in self.meeting_rss_urls.split(",") if url.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
