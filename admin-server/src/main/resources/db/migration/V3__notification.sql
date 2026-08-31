-- 消息中心与通知渠道（P1，Q19）

CREATE TABLE IF NOT EXISTS sys_notification_channel (
    id         BIGSERIAL PRIMARY KEY,
    name       VARCHAR(128) NOT NULL,
    type       VARCHAR(32)  NOT NULL,
    config     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    enabled    BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE sys_notification_channel IS '通知渠道配置（webhook/email 等）';
