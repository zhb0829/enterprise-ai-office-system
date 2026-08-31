-- 认证与权限体系（P0）
-- 多企业租户数据模型 V1 就位：先落表结构，角色配置 UI 后补（Q2/Q11）

CREATE TABLE IF NOT EXISTS sys_tenant (
    id          BIGSERIAL PRIMARY KEY,
    code        VARCHAR(64)  NOT NULL UNIQUE,
    name        VARCHAR(128) NOT NULL,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE sys_tenant IS '企业租户';

INSERT INTO sys_tenant (code, name)
SELECT 'demo-enterprise', '演示企业'
WHERE NOT EXISTS (SELECT 1 FROM sys_tenant WHERE code = 'demo-enterprise');

ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS tenant_id BIGINT;
ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS sys_role (
    id         BIGSERIAL PRIMARY KEY,
    code       VARCHAR(64)  NOT NULL UNIQUE,
    name       VARCHAR(128) NOT NULL,
    created_at TIMESTAMP    NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE sys_role IS '系统角色（V1 先落表，角色配置 UI 后补）';

INSERT INTO sys_role (code, name)
SELECT 'ADMIN', '系统管理员'
WHERE NOT EXISTS (SELECT 1 FROM sys_role WHERE code = 'ADMIN');

INSERT INTO sys_role (code, name)
SELECT 'USER', '普通用户'
WHERE NOT EXISTS (SELECT 1 FROM sys_role WHERE code = 'USER');

CREATE TABLE IF NOT EXISTS sys_user_role (
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    PRIMARY KEY (user_id, role_id)
);

COMMENT ON TABLE sys_user_role IS '用户-角色关联';

CREATE TABLE IF NOT EXISTS sys_refresh_token (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT       NOT NULL,
    token_hash VARCHAR(128) NOT NULL UNIQUE,
    expires_at TIMESTAMP    NOT NULL,
    revoked_at TIMESTAMP,
    created_at TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_refresh_token_user ON sys_refresh_token (user_id);

COMMENT ON TABLE sys_refresh_token IS '刷新令牌（服务端 SHA-256 哈希存储，可吊销）';

CREATE TABLE IF NOT EXISTS sys_password_reset (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT    NOT NULL,
    reset_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE sys_password_reset IS '密码重置记录（含首登强制改密标记）';
