# 生产发布清单：Secret / 镜像仓库 / 域名

> 面向 Linux + Docker 环境的真实发布准备（代码外的配置项）。
> 状态：模板已交付，真实值按本清单在生产/CI Secret 中填入。

## 1. Secret 清单与校验

运行时密钥统一放 `deploy/.env`（由 `deploy/.env.example` 复制，单一真源），不进 Git/镜像：

| 密钥 | 要求 | 用途 |
|---|---|---|
| JWT_SECRET | ≥32 位随机 | 登录态签名 |
| AI_INTERNAL_TOKEN | ≥16 位随机 | Java↔Python 情报/健康 internal |
| OPINION_INTERNAL_TOKEN | ≥16 位随机 | 舆情 Worker 回调 |
| MEETING_INTERNAL_TOKEN | ≥16 位随机 | 会议 Worker 回调 |
| POSTGRES_PASSWORD / GRAFANA_ADMIN_PASSWORD | ≥24 位随机 | 库/监控 |
| LLM_API_KEY / EMBEDDING_API_KEY | 真实供应商 Key | AI 能力 |

服务端双重校验已内置：Java `SecretProperties`、Python `Settings` 在生产环境拒绝默认/弱令牌（启动即失败）。
轮换：短时间新旧并存 → 全量切换 → 撤销旧值。

## 2. 镜像仓库（ACR/自建 Registry）

- 双分支各自 CI 推送：`main` 推 `admin-server / frontend / frontend-admin / gateway`，`python` 推 `ai-service`。
- CI Secrets：`ACR_REGISTRY / ACR_USERNAME / ACR_PASSWORD`（repo-level，双分支 workflow 均可用）。
- 生产 compose 为纯镜像模式（`deploy/docker-compose.yml` 无 build）；本地/离线构建用
  `docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build`。
- 部署机：`docker login <ACR_REGISTRY>` 后 `docker compose pull && docker compose up -d`。
- 回滚：改 `EAOS_IMAGE_TAG` 指回上一版本 `git-sha` 或重打 tag。

## 3. 正式域名与 TLS

- 域名（示意，正式值待定）：用户端 `office.example.com` → gateway:80；管理端 `admin.example.com` → 同 gateway 按路径分流即可（无独立子域亦可）。
- TLS 终止：云负载均衡/反向代理层（443 → 网关 80），网关容器不持有证书、不暴露 Python 公网端口。
- 生产网关仅保留：`/api/`（→ admin-server:8080）、`/admin/`、`/`（→ 前端）、`/api/files/**`（同样走 admin-server，经其代理取文件）。无 `/static`→Python 直连（已移除）。
- 域名证书与 DNS 由部署平台提供后填入 CORS_ALLOWED_ORIGINS 与文档。
- 健康检查：GET /api/health（Java）与内网 GET /internal/health（带令牌）。

## 4. 上线前 Checklist

- [ ] 生成 §1 全部密钥并注入 Secret，确认 Java/Python 生产校验通过（默认值会拒启）。
- [ ] ACR 四个镜像构建并推送成功，`deploy/docker-compose.yml` 只引用 `$ACR_REGISTRY/*:$EAOS_IMAGE_TAG`。
- [ ] 云 LB/DNS/证书就绪，CORS 填入正式域名。
- [ ] 网关镜像已含本清单 §3 转发规则（无 /static 直连）。
- [ ] 数据库全量迁移演练（Flyway V1~V3 + Python Alembic 空情报迁移）通过。
- [ ] 双端联通自检：Python 回写 /internal/intelligence、舆情/会议回调、受控文件下载 `/api/files/**`。
- [ ] 监控/日志/traceId 可查（Prometheus/Loki/Grafana 已编排）。
