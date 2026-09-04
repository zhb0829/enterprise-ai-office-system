# 企业AI智能办公系统

面向企业的 AI 智能办公平台，当前完成 **P0 公告与新闻稿智能撰写**，并新增 **P0 行业政策法规智能问答 MVP**：公开政策文件解析、条款级切分、混合检索、引用溯源、条款解读与合规初步比对。

本目录是独立维护的 **Python AI/agent 服务项目**。Java 网关、用户端和管理端位于独立项目
`E:\project\enterprise-ai-office-system-admin`。

## 仓库结构

```
├── app/                  # Python FastAPI AI 服务（端口 8000）
│   ├── routers/          # drafts / templates / materials / policy / intelligence
│   ├── services/         # llm / extraction / generation / policy / revise / polish / factcheck / export / intelligence
│   ├── graphs/           # LangGraph 状态图编排
│   └── data/             # 种子模板与文风配置
├── alembic/              # Python 数据库迁移
├── tests/                # pytest 测试
└── requirements.txt      # Python 依赖
```

## 服务与端口

| 服务 | 端口 | 说明 |
|---|---|---|
| Python AI | 8000 | 生成/润色/核查/素材，API 文档 /docs |
| PostgreSQL | 5433 | eaos / eaos_dev_password / eaos |

Java 网关只对外提供统一 API；Python 服务仅通过内网 `/internal/**` 接口与 Java 协作。

## 启动

开发环境先在仓库根目录执行 `docker-compose up -d` 启动 PostgreSQL，再运行：

```powershell
cd E:\project\enterprise-ai-office-system-new
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

生产环境使用仓库根目录的 `deploy/docker-compose.yml`，复制 `deploy/.env.example` 为 `.env` 后填入密钥。

## 配置

- 本地配置：`.env`（不入库）；生产运行时配置由部署平台注入。
- Java 网关认证始终启用；Python 的 `/internal/**` 端点始终要求 `X-Internal-Token`。
- 生产环境必须设置 `AI_INTERNAL_TOKEN`、`OPINION_JAVA_TOKEN`、`OPINION_INTERNAL_TOKEN`、`MEETING_JAVA_TOKEN`、`MEETING_INTERNAL_TOKEN` 为至少 16 个字符的非默认随机值，否则服务拒绝启动。

## 测试基线

- 解释器：`Python 3.13.9`
- 虚拟环境：仅使用本目录的 `.venv`
- 依赖：`SQLAlchemy 2.0.52`

## 测试

```powershell
cd E:\project\enterprise-ai-office-system-new
.\.venv\Scripts\python.exe -m pytest tests -q
```

政策问答接口：

- `POST /api/policy/chat` 或 `POST /api/chat/policy`
- `POST /api/policy/interpret`
- `POST /api/policy/compliance/check` 或 `POST /api/compliance/check`
- `POST /api/policy/documents/upload`、`POST /api/policy/documents/from-url`
- `GET /api/policy/documents`、`GET /api/policy/search`

无 `LLM_API_KEY` 时使用离线检索与规则化降级实现；未命中现行有效条款时明确拒答，不生成无依据结论。

情报聚合接口：

- Java 管理端：`/api/sources`、`/api/intelligence/tasks`、`/api/reports/intelligence`、`/api/notification-channels`
- Python 业务接口：`/api/intelligence/items`、`/api/intelligence/clusters`、`/api/intelligence/summarize`
- Python 内网任务接口：`/internal/intelligence/sources/{id}/run`、`/internal/intelligence/tasks/{id}/retry`
- 默认 `CELERY_ENABLED=false` 时，手动采集使用 FastAPI 后台任务，便于离线开发；不会自动执行周期采集。
- 生产启用周期采集时，设置 `CELERY_ENABLED=true`、配置可访问的 `REDIS_URL`，并分别启动 Worker 与 Beat：

  ```powershell
  celery -A app.services.celery_app.celery_app worker --loglevel=info
  celery -A app.services.celery_app.celery_app beat --loglevel=info
  ```

  Worker 处理采集与失败重试，Beat 每小时扫描已启用来源并入队；来源级 `frequency` 由采集服务控制实际执行频率。

舆情本地验收：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_opinion_analysis.py tests/test_opinion_advanced.py tests/test_opinion_demo_dataset.py -q
.\.venv\Scripts\python.exe scripts/seed_opinion_demo.py
```

完整步骤见管理端仓库 `docs/舆情功能本地测试用例.md`。

## 真实 Embedding

默认未配置 `EMBEDDING_API_KEY` 时，系统使用离线哈希向量，便于本地开发；生产环境应配置一个 OpenAI 兼容的 Embedding 服务：

```env
EMBEDDING_API_KEY=你的_embedding_key
EMBEDDING_BASE_URL=https://你的_embedding_服务/v1
EMBEDDING_MODEL=你的_embedding_模型
EMBEDDING_DIMENSIONS=0
```

配置后，新上传的素材和政策文件会批量生成真实语义向量。已有数据可调用以下接口重建索引：

- `POST /api/policy/reindex`，可选查询参数 `document_id`
- `POST /api/materials/reindex`，可选查询参数 `material_id`

当真实 Embedding 已配置但服务不可用时，入库或重建会返回 `503`，避免把新哈希向量和已有语义向量混在同一索引中。

## 技术栈

- Python：FastAPI、SQLAlchemy 2.0、LangGraph、Alembic
- LLM：DeepSeek（OpenAI 兼容，可插拔）
- 数据库：PostgreSQL 16 + pgvector（Docker）
