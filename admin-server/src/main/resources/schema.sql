CREATE TABLE IF NOT EXISTS sys_user (
    id          BIGSERIAL PRIMARY KEY,
    username    VARCHAR(64)  NOT NULL UNIQUE,
    password    VARCHAR(128) NOT NULL,
    nickname    VARCHAR(64),
    role        VARCHAR(32)  NOT NULL DEFAULT 'USER',
    enabled     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE sys_user IS '系统用户（后台管理系统）';

CREATE TABLE IF NOT EXISTS source_config (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    type VARCHAR(16) NOT NULL,
    url VARCHAR(2048) NOT NULL UNIQUE,
    keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
    competitors JSONB NOT NULL DEFAULT '[]'::jsonb,
    frequency VARCHAR(32) NOT NULL DEFAULT 'daily',
    status VARCHAR(32) NOT NULL DEFAULT 'enabled',
    health_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_run_at TIMESTAMP,
    last_success_at TIMESTAMP,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_source_config_status ON source_config(status);

CREATE TABLE IF NOT EXISTS collected_article (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES source_config(id),
    title VARCHAR(512) NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    url VARCHAR(2048) NOT NULL DEFAULT '',
    author VARCHAR(256) NOT NULL DEFAULT '',
    publish_time TIMESTAMP,
    collected_at TIMESTAMP NOT NULL DEFAULT NOW(),
    content_hash VARCHAR(64) NOT NULL UNIQUE,
    title_hash VARCHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'new',
    embedding JSONB NOT NULL DEFAULT '[]'::jsonb,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_collected_article_source_time ON collected_article(source_id, collected_at DESC);

CREATE TABLE IF NOT EXISTS article_cluster (
    id BIGSERIAL PRIMARY KEY,
    topic VARCHAR(256) NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    article_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    report_count INTEGER NOT NULL DEFAULT 0,
    time_start TIMESTAMP,
    time_end TIMESTAMP,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_article_cluster_topic ON article_cluster(topic);

CREATE TABLE IF NOT EXISTS intelligence_report (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(256) NOT NULL,
    period VARCHAR(64) NOT NULL,
    topic_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    trend JSONB NOT NULL DEFAULT '{}'::jsonb,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    generated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    model VARCHAR(128) NOT NULL DEFAULT '',
    risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS collection_task_log (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES source_config(id),
    celery_task_id VARCHAR(128) NOT NULL DEFAULT '',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    error TEXT NOT NULL DEFAULT '',
    items_count INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_collection_task_log_created ON collection_task_log(created_at DESC);

-- Earlier Python-only deployments created these columns as JSON.  MyBatis sends
-- structured values as PostgreSQL JSONB, so normalize existing installations
-- before the admin service starts writing source and report configuration.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'source_config' AND column_name = 'keywords' AND data_type = 'json') THEN
        ALTER TABLE source_config ALTER COLUMN keywords TYPE JSONB USING keywords::jsonb;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'source_config' AND column_name = 'competitors' AND data_type = 'json') THEN
        ALTER TABLE source_config ALTER COLUMN competitors TYPE JSONB USING competitors::jsonb;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'collected_article' AND column_name = 'embedding' AND data_type = 'json') THEN
        ALTER TABLE collected_article ALTER COLUMN embedding TYPE JSONB USING embedding::jsonb;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'collected_article' AND column_name = 'meta' AND data_type = 'json') THEN
        ALTER TABLE collected_article ALTER COLUMN meta TYPE JSONB USING meta::jsonb;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'article_cluster' AND column_name = 'article_ids' AND data_type = 'json') THEN
        ALTER TABLE article_cluster ALTER COLUMN article_ids TYPE JSONB USING article_ids::jsonb;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'article_cluster' AND column_name = 'sources' AND data_type = 'json') THEN
        ALTER TABLE article_cluster ALTER COLUMN sources TYPE JSONB USING sources::jsonb;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'article_cluster' AND column_name = 'meta' AND data_type = 'json') THEN
        ALTER TABLE article_cluster ALTER COLUMN meta TYPE JSONB USING meta::jsonb;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'intelligence_report' AND column_name = 'topic_tags' AND data_type = 'json') THEN
        ALTER TABLE intelligence_report ALTER COLUMN topic_tags TYPE JSONB USING topic_tags::jsonb;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'intelligence_report' AND column_name = 'items' AND data_type = 'json') THEN
        ALTER TABLE intelligence_report ALTER COLUMN items TYPE JSONB USING items::jsonb;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'intelligence_report' AND column_name = 'trend' AND data_type = 'json') THEN
        ALTER TABLE intelligence_report ALTER COLUMN trend TYPE JSONB USING trend::jsonb;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'intelligence_report' AND column_name = 'sources' AND data_type = 'json') THEN
        ALTER TABLE intelligence_report ALTER COLUMN sources TYPE JSONB USING sources::jsonb;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'intelligence_report' AND column_name = 'risk_flags' AND data_type = 'json') THEN
        ALTER TABLE intelligence_report ALTER COLUMN risk_flags TYPE JSONB USING risk_flags::jsonb;
    END IF;
END $$;

-- ============================================================================
-- P1 舆情分析模块（独立于行业情报，业务数据全部由 Java 服务独占）
-- ============================================================================

CREATE TABLE IF NOT EXISTS opinion_monitor (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT       REFERENCES sys_user(id),
    name             VARCHAR(128) NOT NULL,
    enterprise_name  VARCHAR(128) NOT NULL DEFAULT '',
    brand_words      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    competitor_words JSONB        NOT NULL DEFAULT '[]'::jsonb,
    executive_names  JSONB        NOT NULL DEFAULT '[]'::jsonb,
    exclude_words    JSONB        NOT NULL DEFAULT '[]'::jsonb,
    match_mode       VARCHAR(16)  NOT NULL DEFAULT 'any',
    time_window_days INTEGER      NOT NULL DEFAULT 7,
    status           VARCHAR(16)  NOT NULL DEFAULT 'enabled',
    created_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE opinion_monitor IS '舆情监控任务与词库（品牌词/竞品词/高管词/排除词）';
CREATE INDEX IF NOT EXISTS idx_opinion_monitor_user ON opinion_monitor(user_id);

CREATE TABLE IF NOT EXISTS opinion_source (
    id               BIGSERIAL PRIMARY KEY,
    name             VARCHAR(128) NOT NULL,
    source_type      VARCHAR(16)  NOT NULL,
    platform         VARCHAR(64)  NOT NULL DEFAULT '',
    homepage         VARCHAR(2048) NOT NULL DEFAULT '',
    auth_subject     VARCHAR(128) NOT NULL DEFAULT '',
    auth_scope       VARCHAR(256) NOT NULL DEFAULT '',
    auth_start       TIMESTAMP,
    auth_expire      TIMESTAMP,
    collect_method   VARCHAR(32)  NOT NULL DEFAULT 'http',
    frequency        VARCHAR(32)  NOT NULL DEFAULT 'daily',
    rate_limit       VARCHAR(128) NOT NULL DEFAULT '',
    priority         INTEGER      NOT NULL DEFAULT 0,
    adapter_version  VARCHAR(64)  NOT NULL DEFAULT 'v1',
    status           VARCHAR(16)  NOT NULL DEFAULT 'disabled',
    health_status    VARCHAR(16)  NOT NULL DEFAULT 'unknown',
    failure_count    INTEGER      NOT NULL DEFAULT 0,
    last_collect_at  TIMESTAMP,
    last_success_at  TIMESTAMP,
    last_error       TEXT         NOT NULL DEFAULT '',
    audit_status     VARCHAR(16)  NOT NULL DEFAULT 'pending',
    audit_by         VARCHAR(64)  NOT NULL DEFAULT '',
    audit_at         TIMESTAMP,
    audit_note       TEXT         NOT NULL DEFAULT '',
    created_by       VARCHAR(64)  NOT NULL DEFAULT '',
    created_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_opinion_source_homepage UNIQUE (homepage)
);

COMMENT ON TABLE opinion_source IS '公开采集源及授权审核信息';
CREATE INDEX IF NOT EXISTS idx_opinion_source_audit ON opinion_source(audit_status, status);

CREATE TABLE IF NOT EXISTS opinion_source_task (
    id              BIGSERIAL PRIMARY KEY,
    source_id       BIGINT       NOT NULL REFERENCES opinion_source(id),
    monitor_id      BIGINT,
    task_type       VARCHAR(16)  NOT NULL DEFAULT 'collect',
    status          VARCHAR(16)  NOT NULL DEFAULT 'queued',
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    payload         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    items_sent      INTEGER      NOT NULL DEFAULT 0,
    items_ingested  INTEGER      NOT NULL DEFAULT 0,
    retry_count     INTEGER      NOT NULL DEFAULT 0,
    worker          VARCHAR(64)  NOT NULL DEFAULT '',
    error           TEXT         NOT NULL DEFAULT '',
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE opinion_source_task IS '舆情采集任务执行日志（Java 侧）';
CREATE INDEX IF NOT EXISTS idx_opinion_source_task_created ON opinion_source_task(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_opinion_source_task_status ON opinion_source_task(status);

CREATE TABLE IF NOT EXISTS opinion_article (
    id               BIGSERIAL PRIMARY KEY,
    source_id        BIGINT       REFERENCES opinion_source(id),
    monitor_id       BIGINT       REFERENCES opinion_monitor(id),
    title            VARCHAR(512) NOT NULL DEFAULT '',
    content          TEXT         NOT NULL DEFAULT '',
    url              VARCHAR(2048) NOT NULL DEFAULT '',
    url_hash         VARCHAR(64)  NOT NULL DEFAULT '',
    content_hash     VARCHAR(64)  NOT NULL UNIQUE,
    author           VARCHAR(256) NOT NULL DEFAULT '',
    publish_time     TIMESTAMP,
    collected_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    matched_keywords JSONB        NOT NULL DEFAULT '[]'::jsonb,
    status           VARCHAR(16)  NOT NULL DEFAULT 'analysis_pending',
    object_key       VARCHAR(512) NOT NULL DEFAULT '',
    created_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE opinion_article IS '舆情文章元数据（原文由对象存储保存，此处仅元数据）';
CREATE INDEX IF NOT EXISTS idx_opinion_article_monitor ON opinion_article(monitor_id);
CREATE INDEX IF NOT EXISTS idx_opinion_article_source ON opinion_article(source_id);
CREATE INDEX IF NOT EXISTS idx_opinion_article_status ON opinion_article(status);
CREATE INDEX IF NOT EXISTS idx_opinion_article_collected ON opinion_article(collected_at DESC);

CREATE TABLE IF NOT EXISTS opinion_analysis_task (
    id             BIGSERIAL PRIMARY KEY,
    article_id     BIGINT       NOT NULL REFERENCES opinion_article(id),
    monitor_id     BIGINT,
    status         VARCHAR(16)  NOT NULL DEFAULT 'queued',
    retry_count    INTEGER      NOT NULL DEFAULT 0,
    next_retry_at  TIMESTAMP,
    worker         VARCHAR(64)  NOT NULL DEFAULT '',
    claimed_at     TIMESTAMP,
    last_error     TEXT         NOT NULL DEFAULT '',
    created_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_opinion_analysis_task_article UNIQUE (article_id, monitor_id)
);

COMMENT ON TABLE opinion_analysis_task IS '舆情文章待分析任务（幂等，由 Java 创建并派发给 Python Worker）';
CREATE INDEX IF NOT EXISTS idx_opinion_analysis_task_status ON opinion_analysis_task(status);
CREATE INDEX IF NOT EXISTS idx_opinion_analysis_task_claim ON opinion_analysis_task(status, next_retry_at);
ALTER TABLE opinion_analysis_task ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_opinion_analysis_task_recovery
    ON opinion_analysis_task(status, claimed_at);

CREATE TABLE IF NOT EXISTS opinion_analysis (
    id             BIGSERIAL PRIMARY KEY,
    article_id     BIGINT       NOT NULL REFERENCES opinion_article(id),
    monitor_id     BIGINT       REFERENCES opinion_monitor(id),
    sentiment      VARCHAR(16)  NOT NULL DEFAULT 'neutral',
    confidence     NUMERIC(5,4) NOT NULL DEFAULT 0,
    emotion_tags   JSONB        NOT NULL DEFAULT '[]'::jsonb,
    reason         TEXT         NOT NULL DEFAULT '',
    evidence_ids   JSONB        NOT NULL DEFAULT '[]'::jsonb,
    risk_factors   JSONB        NOT NULL DEFAULT '[]'::jsonb,
    risk_score     INTEGER      NOT NULL DEFAULT 0,
    topic          VARCHAR(256) NOT NULL DEFAULT '',
    keywords       JSONB        NOT NULL DEFAULT '[]'::jsonb,
    model          VARCHAR(128) NOT NULL DEFAULT '',
    prompt_version VARCHAR(64)  NOT NULL DEFAULT '',
    ai_run_id      VARCHAR(64)  NOT NULL DEFAULT '',
    status         VARCHAR(16)  NOT NULL DEFAULT 'pending',
    version        INTEGER      NOT NULL DEFAULT 1,
    source         VARCHAR(16)  NOT NULL DEFAULT 'ai',
    audited_by     VARCHAR(64)  NOT NULL DEFAULT '',
    created_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_opinion_analysis_article UNIQUE (article_id, monitor_id)
);

COMMENT ON TABLE opinion_analysis IS '舆情文章情感/事件/风险分析结果（AI 结果不可覆盖，人工修正走新版本）';
CREATE INDEX IF NOT EXISTS idx_opinion_analysis_article ON opinion_analysis(article_id);
CREATE INDEX IF NOT EXISTS idx_opinion_analysis_sentiment ON opinion_analysis(sentiment);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_opinion_analysis_article'
          AND conrelid = 'opinion_analysis'::regclass
    ) THEN
        ALTER TABLE opinion_analysis DROP CONSTRAINT uq_opinion_analysis_article;
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_opinion_analysis_version
    ON opinion_analysis(article_id, monitor_id, version);

CREATE TABLE IF NOT EXISTS opinion_event (
    id              BIGSERIAL PRIMARY KEY,
    monitor_id      BIGINT       REFERENCES opinion_monitor(id),
    title           VARCHAR(256) NOT NULL,
    summary         TEXT         NOT NULL DEFAULT '',
    article_ids     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    sentiment_dist  JSONB        NOT NULL DEFAULT '{}'::jsonb,
    risk_level      VARCHAR(16)  NOT NULL DEFAULT '关注',
    time_start      TIMESTAMP,
    time_end        TIMESTAMP,
    source_weight   NUMERIC(8,2) NOT NULL DEFAULT 0,
    spread_speed    INTEGER      NOT NULL DEFAULT 0,
    report_count    INTEGER      NOT NULL DEFAULT 0,
    keywords        JSONB        NOT NULL DEFAULT '[]'::jsonb,
    status          VARCHAR(16)  NOT NULL DEFAULT 'active',
    version         INTEGER      NOT NULL DEFAULT 1,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE opinion_event IS '舆情热点事件聚类与生命周期';
CREATE INDEX IF NOT EXISTS idx_opinion_event_monitor ON opinion_event(monitor_id);
CREATE INDEX IF NOT EXISTS idx_opinion_event_risk ON opinion_event(risk_level);

CREATE TABLE IF NOT EXISTS opinion_review (
    id           BIGSERIAL PRIMARY KEY,
    target_type  VARCHAR(32)  NOT NULL,
    target_id    BIGINT       NOT NULL,
    field        VARCHAR(64)  NOT NULL DEFAULT '',
    old_value    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    new_value    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    reason       TEXT         NOT NULL DEFAULT '',
    reviewed_by  VARCHAR(64)  NOT NULL DEFAULT '',
    reviewed_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE opinion_review IS '舆情人工复核/修正记录';
CREATE INDEX IF NOT EXISTS idx_opinion_review_target ON opinion_review(target_type, target_id);

CREATE TABLE IF NOT EXISTS opinion_audit_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT,
    action      VARCHAR(64)  NOT NULL,
    target_type VARCHAR(32)  NOT NULL DEFAULT '',
    target_id   BIGINT,
    detail      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    trace_id    VARCHAR(64)  NOT NULL DEFAULT '',
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE opinion_audit_log IS '舆情操作与模型审计日志';
CREATE INDEX IF NOT EXISTS idx_opinion_audit_log_created ON opinion_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_opinion_audit_log_user ON opinion_audit_log(user_id);

-- ============================================================================
-- P1 舆情分析（阶段四：告警闭环）
-- ============================================================================

CREATE TABLE IF NOT EXISTS opinion_alert_rule (
    id              BIGSERIAL PRIMARY KEY,
    monitor_id      BIGINT       REFERENCES opinion_monitor(id),
    name            VARCHAR(128) NOT NULL,
    risk_level      VARCHAR(16)  NOT NULL DEFAULT '关注',
    trigger         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    cooldown_minutes INTEGER     NOT NULL DEFAULT 60,
    escalate        JSONB        NOT NULL DEFAULT '{}'::jsonb,
    status          VARCHAR(16)  NOT NULL DEFAULT 'enabled',
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE opinion_alert_rule IS '舆情告警规则（数量/比例/增长率/时间窗口/来源权重）';
CREATE INDEX IF NOT EXISTS idx_opinion_alert_rule_monitor ON opinion_alert_rule(monitor_id);

CREATE TABLE IF NOT EXISTS opinion_alert_event (
    id                BIGSERIAL PRIMARY KEY,
    monitor_id        BIGINT       REFERENCES opinion_monitor(id),
    rule_id           BIGINT       REFERENCES opinion_alert_rule(id),
    event_id          BIGINT,
    risk_level        VARCHAR(16)  NOT NULL DEFAULT '关注',
    state             VARCHAR(16)  NOT NULL DEFAULT 'triggered',
    trigger_stats     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    trigger_count     INTEGER      NOT NULL DEFAULT 1,
    first_triggered_at TIMESTAMP   NOT NULL DEFAULT NOW(),
    last_triggered_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    resolved_at       TIMESTAMP,
    owner             VARCHAR(64)  NOT NULL DEFAULT '',
    handle_note       TEXT         NOT NULL DEFAULT '',
    created_at        TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE opinion_alert_event IS '舆情告警事件与处置状态（triggered/acknowledged/processing/resolved/closed）';
CREATE INDEX IF NOT EXISTS idx_opinion_alert_event_monitor ON opinion_alert_event(monitor_id, state);
CREATE INDEX IF NOT EXISTS idx_opinion_alert_event_last ON opinion_alert_event(last_triggered_at DESC);

CREATE TABLE IF NOT EXISTS opinion_notification (
    id          BIGSERIAL PRIMARY KEY,
    alert_id    BIGINT       REFERENCES opinion_alert_event(id),
    channel     VARCHAR(16)  NOT NULL DEFAULT '站内',
    target      VARCHAR(256) NOT NULL DEFAULT '',
    content     TEXT         NOT NULL DEFAULT '',
    status      VARCHAR(16)  NOT NULL DEFAULT 'pending',
    retry_count INTEGER      NOT NULL DEFAULT 0,
    error       TEXT         NOT NULL DEFAULT '',
    sent_at     TIMESTAMP,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE opinion_notification IS '舆情通知记录（站内/邮件/Webhook，失败可重试）';
CREATE INDEX IF NOT EXISTS idx_opinion_notification_alert ON opinion_notification(alert_id);
ALTER TABLE opinion_notification ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_opinion_notification_retry
    ON opinion_notification(status, next_retry_at);

-- ============================================================================
-- P1 舆情分析（阶段五：报告能力）
-- ============================================================================

CREATE TABLE IF NOT EXISTS opinion_report (
    id            BIGSERIAL PRIMARY KEY,
    monitor_id    BIGINT       REFERENCES opinion_monitor(id),
    period        VARCHAR(16)  NOT NULL DEFAULT 'daily',
    period_start  TIMESTAMP,
    period_end    TIMESTAMP,
    title         VARCHAR(256) NOT NULL DEFAULT '',
    summary       TEXT         NOT NULL DEFAULT '',
    content_html  TEXT         NOT NULL DEFAULT '',
    status        VARCHAR(16)  NOT NULL DEFAULT 'draft',
    version       INTEGER      NOT NULL DEFAULT 1,
    model         VARCHAR(128) NOT NULL DEFAULT '',
    prompt_version VARCHAR(64) NOT NULL DEFAULT '',
    data_scope    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    evidence      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    published_by  VARCHAR(64)  NOT NULL DEFAULT '',
    published_at  TIMESTAMP,
    created_at    TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE opinion_report IS '舆情日报/周报（不可覆盖，重新生成产生新版本，发布需人工确认）';
CREATE INDEX IF NOT EXISTS idx_opinion_report_monitor ON opinion_report(monitor_id, period);
CREATE INDEX IF NOT EXISTS idx_opinion_report_created ON opinion_report(created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_opinion_report_version
    ON opinion_report(monitor_id, period, version);

-- ============================================================================
-- P1 舆情分析（阶段六：高级 AI）
-- ============================================================================

CREATE TABLE IF NOT EXISTS opinion_response_case (
    id          BIGSERIAL PRIMARY KEY,
    title       VARCHAR(256) NOT NULL,
    event_type  VARCHAR(128) NOT NULL DEFAULT '',
    risk_level  VARCHAR(16)  NOT NULL DEFAULT '关注',
    strategy    TEXT         NOT NULL DEFAULT '',
    content     TEXT         NOT NULL DEFAULT '',
    effect      TEXT         NOT NULL DEFAULT '',
    tags        JSONB        NOT NULL DEFAULT '[]'::jsonb,
    source      VARCHAR(64)  NOT NULL DEFAULT '',
    created_by  VARCHAR(64)  NOT NULL DEFAULT '',
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE opinion_response_case IS '历史应对案例（供 RAG 检索与应对建议生成）';
CREATE INDEX IF NOT EXISTS idx_opinion_response_case_type ON opinion_response_case(event_type, risk_level);

CREATE TABLE IF NOT EXISTS opinion_spread_edge (
    id              BIGSERIAL PRIMARY KEY,
    monitor_id      BIGINT       REFERENCES opinion_monitor(id),
    from_article_id BIGINT       REFERENCES opinion_article(id),
    to_article_id   BIGINT       REFERENCES opinion_article(id),
    relation_type   VARCHAR(16)  NOT NULL DEFAULT '相似',
    verified        BOOLEAN      NOT NULL DEFAULT FALSE,
    evidence        TEXT         NOT NULL DEFAULT '',
    confidence      NUMERIC(5,4) NOT NULL DEFAULT 0,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_opinion_spread_edge UNIQUE (from_article_id, to_article_id, relation_type)
);

COMMENT ON TABLE opinion_spread_edge IS '传播关系（已验证：页面明确转载/引用/转发证据；推测：时间/相似度推断，不可作为正式事实）';
CREATE INDEX IF NOT EXISTS idx_opinion_spread_edge_monitor ON opinion_spread_edge(monitor_id);

CREATE TABLE IF NOT EXISTS opinion_suggestion (
    id             BIGSERIAL PRIMARY KEY,
    target_type    VARCHAR(16)  NOT NULL DEFAULT 'alert',
    target_id      BIGINT       NOT NULL,
    monitor_id     BIGINT       REFERENCES opinion_monitor(id),
    content        TEXT         NOT NULL DEFAULT '',
    citations      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    model          VARCHAR(128) NOT NULL DEFAULT '',
    prompt_version VARCHAR(64)  NOT NULL DEFAULT '',
    status         VARCHAR(16)  NOT NULL DEFAULT 'pending',
    feedback       TEXT         NOT NULL DEFAULT '',
    created_by     VARCHAR(64)  NOT NULL DEFAULT '',
    created_at     TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE opinion_suggestion IS '应对建议（基于历史案例 RAG，默认需人工确认）';
CREATE INDEX IF NOT EXISTS idx_opinion_suggestion_target ON opinion_suggestion(target_type, target_id);

CREATE TABLE IF NOT EXISTS qual_guide_schema (
    id VARCHAR(64) PRIMARY KEY,
    owner_enterprise_id VARCHAR(64) NOT NULL,
    qualification_type VARCHAR(128) NOT NULL,
    guide_name VARCHAR(256) NOT NULL,
    version VARCHAR(64) NOT NULL,
    effective_from DATE,
    effective_to DATE,
    source_file_name VARCHAR(256) NOT NULL DEFAULT '',
    source_file_path VARCHAR(512) NOT NULL DEFAULT '',
    source_url VARCHAR(1024) NOT NULL DEFAULT '',
    schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    material_checklist_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qual_guide_owner_type ON qual_guide_schema(owner_enterprise_id, qualification_type);

CREATE TABLE IF NOT EXISTS qual_material (
    id VARCHAR(64) PRIMARY KEY,
    owner_enterprise_id VARCHAR(64) NOT NULL,
    category VARCHAR(64) NOT NULL DEFAULT 'QUALIFICATION_ARCHIVE',
    file_name VARCHAR(256) NOT NULL,
    file_path VARCHAR(512) NOT NULL DEFAULT '',
    text_content TEXT NOT NULL DEFAULT '',
    parse_status VARCHAR(32) NOT NULL DEFAULT 'READY',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qual_material_owner_category ON qual_material(owner_enterprise_id, category);

CREATE TABLE IF NOT EXISTS qual_task (
    id VARCHAR(64) PRIMARY KEY,
    owner_enterprise_id VARCHAR(64) NOT NULL,
    qualification_type VARCHAR(128) NOT NULL,
    guide_schema_id VARCHAR(64) NOT NULL REFERENCES qual_guide_schema(id),
    document_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    progress_message VARCHAR(512) NOT NULL DEFAULT '',
    idempotency_key VARCHAR(128) NOT NULL,
    material_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    format_requirements_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    worker_result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    failure_reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(owner_enterprise_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_qual_task_owner_created ON qual_task(owner_enterprise_id, created_at DESC);

CREATE TABLE IF NOT EXISTS qual_document (
    id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES qual_task(id),
    owner_enterprise_id VARCHAR(64) NOT NULL,
    title VARCHAR(256) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    content_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    sources_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_flags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    current_version INTEGER NOT NULL DEFAULT 1,
    review_comment TEXT NOT NULL DEFAULT '',
    generated_at TIMESTAMP,
    model VARCHAR(128) NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qual_document_owner_task ON qual_document(owner_enterprise_id, task_id);

CREATE TABLE IF NOT EXISTS qual_document_version (
    id VARCHAR(64) PRIMARY KEY,
    document_id VARCHAR(64) NOT NULL REFERENCES qual_document(id),
    owner_enterprise_id VARCHAR(64) NOT NULL,
    version_no INTEGER NOT NULL,
    content_json JSONB NOT NULL,
    diff_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    change_note VARCHAR(512) NOT NULL DEFAULT '',
    created_by VARCHAR(64) NOT NULL DEFAULT 'system',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, version_no)
);

CREATE TABLE IF NOT EXISTS qual_validation_rule (
    id VARCHAR(64) PRIMARY KEY,
    owner_enterprise_id VARCHAR(64) NOT NULL DEFAULT 'system',
    code VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    rule_type VARCHAR(32) NOT NULL,
    rule_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(owner_enterprise_id, code)
);

CREATE TABLE IF NOT EXISTS qual_validation_report (
    id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES qual_task(id),
    document_id VARCHAR(64) NOT NULL REFERENCES qual_document(id),
    owner_enterprise_id VARCHAR(64) NOT NULL,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    items_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qual_task_event (
    id BIGSERIAL PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES qual_task(id),
    owner_enterprise_id VARCHAR(64) NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qual_task_event_task_id ON qual_task_event(task_id, id);
