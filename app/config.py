"""应用配置：从 .env 读取环境变量。"""
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
_NON_PRODUCTION_ENVS = {"dev", "development", "test", "testing"}
_DEFAULT_INTERNAL_TOKENS = {
    "eaos-internal-token-change-me",
    "eaos-opinion-internal-dev-token",
    "eaos-meeting-internal-dev-token",
}


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
    chunk_semantic_enabled: bool = True
    chunk_semantic_trigger_size: int = Field(default=1200, ge=600)
    chunk_min_size: int = Field(default=320, ge=1)
    chunk_semantic_similarity_threshold: float = Field(default=0.42, ge=-1, le=1)
    rerank_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_timeout: int = 10
    rerank_local_model: str = ""
    agent_trace_retention_days: int = 30

    # 知识图谱最小闭环（G1）。默认关闭：必须先用 evals.graph_gain 跑出
    # "向量 + 图" 相对 "纯向量" 的正向增益，再人工开启（无增益不上线）。
    kg_enabled: bool = False
    kg_model: str = ""  # 空则复用 llm_model_extraction，避免额外的模型配置面
    kg_max_hops: int = Field(default=2, ge=1, le=4)
    kg_seed_limit: int = Field(default=8, ge=1, le=50)
    kg_clause_limit: int = Field(default=30, ge=1, le=200)
    kg_alignment_threshold: float = Field(default=0.86, ge=0.5, le=1.0)
    kg_extract_budget_per_job: int = Field(default=50, ge=1, le=1000)
    kg_community_min_size: int = Field(default=3, ge=2, le=100)
    kg_max_nodes: int = Field(default=5000, ge=100)

    # ===== G3 租户资源隔离与限流 =====
    # 第一道防线在 Java 网关（admin-server 的 TenantRateLimitFilter）；
    # 这里是 AI 服务自身的兜底，见 app/resource_guard.py。超限返回 429，不排队。
    rate_limit_enabled: bool = True
    rate_limit_rps: float = Field(default=50, gt=0)
    rate_limit_burst: int = Field(default=100, ge=1)
    # 0 表示不限制该维度
    rate_limit_max_concurrency: int = Field(default=32, ge=0)
    rate_limit_global_concurrency: int = Field(default=128, ge=0)
    rate_limit_exempt_paths: str = "/api/health,/internal/health,/metrics,/static/,/api/agent/flags"
    # 说明：运行时开关是"带外管理通道"，不能被自身限流挡住（需 agent:audit/agent:admin，且不耗资源）。
    # 形如 {"tenant-a": {"rps": 5, "burst": 10, "concurrency": 4}}；缺省项回落全局默认
    rate_limit_tenant_overrides: str = ""
    # 高频拒绝默认不落库（落库会反噬被保护的服务），需要留痕时显式打开
    rate_limit_audit_enabled: bool = False

    # 耗时链路容量池（G3）：workers=0 表示关闭池直通；超限快速失败而非无限排队。
    llm_pool_workers: int = Field(default=4, ge=0, le=256)
    llm_pool_queue: int = Field(default=8, ge=0, le=4096)
    embedding_pool_workers: int = Field(default=4, ge=0, le=256)
    embedding_pool_queue: int = Field(default=8, ge=0, le=4096)
    rerank_pool_workers: int = Field(default=2, ge=0, le=256)
    rerank_pool_queue: int = Field(default=8, ge=0, le=4096)

    # ===== G5 运行时降级开关 =====
    # 启动时覆盖一组运行时开关（JSON 对象）；运行中经 /api/agent/flags 热切换。
    # 环境变量仍是默认值口径，运行时开关只做覆盖，见 app/agent/runtime_flags.py。
    runtime_flag_overrides: str = ""

    # ===== G4 模型分层路由 =====
    # 默认关闭，与 G1 图谱同口径：先跑 `evals.routing_compare` 拿到"延迟/成本改善且质量不降"
    # 的证据，再显式开启；运行中可经运行时开关 `model_routing` 热切换（见 app/agent/runtime_flags.py）。
    # 未配置任何分层模型时本项为 no-op —— 行为与"没有路由"完全一致。
    llm_routing_enabled: bool = False
    # 三层模型：留空表示该层未配置（回落标准层）；标准层留空则复用 LLM_MODEL_GENERATION。
    llm_model_tier_light: str = ""
    llm_model_tier_standard: str = ""
    llm_model_tier_reasoning: str = ""
    # 复杂度打分阈值（分值为整数，打分信号见 app/services/model_router.py）：
    # score <= light_max 走轻量层，score >= reasoning_min 走旗舰层，其余走标准层。
    llm_routing_light_max_score: int = Field(default=0, ge=-10, le=10)
    llm_routing_reasoning_min_score: int = Field(default=3, ge=-10, le=10)

    # ===== G6 成本核算 =====
    # 价格表，JSON：{"<model>": {"input": 元/百万token, "output": 元/百万token}}。
    # 口径：仅 CNY、仅 per-million-token；未收录的模型成本记 null（不估算、不用 0 顶替）。
    llm_price_table: str = ""
    cost_query_max_days: int = Field(default=90, ge=1, le=3650)
    cost_query_max_runs: int = Field(default=20000, ge=1, le=1000000)

    # ===== G7 三角色租户治理分工 =====
    # 角色由 Java 网关下发 X-User-Role（platform_admin / tenant_admin / member）；
    # Python 侧只做"收缩"：有效权限 = 角色基线 ∩ 网关声明的权限集合，见 app/agent/access.py。
    # 网关尚未下发角色头时本开关无影响（role 为空即过渡期口径）；
    # 置 false 可整体回退到"权限集合即事实"的过渡期口径。
    tenant_role_governance_enabled: bool = True
    # 过渡期纪律（默认保持兼容，网关全量下发角色头后按需收紧）：
    # - TENANT_ROLE_REQUIRED=true：无 X-User-Role 的 /api 请求直接 403（fail-closed 收口）；
    # - TENANT_ROLE_EMPTY_PERMISSIONS_FALLBACK=true：角色头有、权限头为空时回落到角色基线
    #   （默认 false，即按"没有权限"处理，避免网关漏发权限头变成放大授权）。
    tenant_role_required: bool = False
    tenant_role_empty_permissions_fallback: bool = False

    # ===== G9 LTR 学习排序（依赖 G2 标注数据）=====
    # 生产姿势是 RRF 保底、LTR 渐进替换：off（保底）→ shadow（影子，只算分不改序）→
    # blend（(1-alpha)·RRF + alpha·LTR）。alpha 小步提高，每一步都要有 evals.ltr_compare
    # 的样本外增益作依据；未达 LTR_MIN_AUC 的模型不允许激活（见 app/agent/ltr.py）。
    ltr_mode: str = "off"
    ltr_blend_alpha: float = Field(default=0.3, ge=0, le=1)
    # 训练样本不足直接拒绝训练；阈值是"有没有资格训模型"，不是"模型好不好"。
    ltr_min_samples: int = Field(default=50, ge=4)
    ltr_min_auc: float = Field(default=0.6, ge=0.5, le=1)
    ltr_train_epochs: int = Field(default=400, ge=1, le=5000)
    ltr_learning_rate: float = Field(default=0.5, gt=0, le=10)

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
    # 情报权威数据（source_config 等）全部由 Java 管理，Python 经 Java internal API 读写。
    intelligence_java_base_url: str = "http://localhost:8080"
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

    @model_validator(mode="after")
    def validate_routing_thresholds(self) -> "Settings":
        if self.llm_routing_reasoning_min_score <= self.llm_routing_light_max_score:
            raise ValueError(
                "LLM_ROUTING_REASONING_MIN_SCORE 必须大于 LLM_ROUTING_LIGHT_MAX_SCORE，"
                "否则轻量层与旗舰层区间重叠，路由结果不可预期"
            )
        return self

    @model_validator(mode="after")
    def validate_ltr_mode(self) -> "Settings":
        mode = (self.ltr_mode or "").strip().lower()
        if mode not in {"off", "shadow", "blend"}:
            raise ValueError("LTR_MODE 只能是 off / shadow / blend")
        return self

    @model_validator(mode="after")
    def reject_insecure_production_tokens(self) -> "Settings":
        if self.app_env.strip().lower() in _NON_PRODUCTION_ENVS:
            return self

        internal_tokens = {
            "AI_INTERNAL_TOKEN": self.ai_internal_token,
            "OPINION_JAVA_TOKEN": self.opinion_java_token,
            "OPINION_INTERNAL_TOKEN": self.opinion_internal_token,
            "MEETING_JAVA_TOKEN": self.meeting_java_token,
            "MEETING_INTERNAL_TOKEN": self.meeting_internal_token,
        }
        invalid_names = [
            name
            for name, token in internal_tokens.items()
            if len(token.strip()) < 16
            or token.strip().lower() in _DEFAULT_INTERNAL_TOKENS
            or "change-me" in token.strip().lower()
        ]
        if invalid_names:
            raise ValueError(
                "生产环境必须为服务间令牌配置至少 16 个字符的非默认随机值: "
                + ", ".join(invalid_names)
            )
        return self

    @property
    def effective_rerank_api_key(self) -> str:
        if self.rerank_api_key:
            return self.rerank_api_key
        embedding = urlsplit(self.embedding_base_url)
        rerank = urlsplit(self.rerank_url)
        if (
            embedding.scheme == rerank.scheme == "https"
            and embedding.hostname
            and embedding.hostname == rerank.hostname
            and (embedding.port or 443) == (rerank.port or 443)
            and not rerank.username
            and not rerank.password
        ):
            return self.embedding_api_key
        return ""

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
