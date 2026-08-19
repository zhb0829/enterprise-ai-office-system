# enterprise-ai-office-system-ai（Python AI 服务）

企业 AI 智能办公系统的 **AI/agent 服务**（Python 独立项目）。负责一切 AI、文档处理、采集相关的"干活"逻辑：LLM 调用、Agent/Workflow 编排（LangGraph/LangChain）、RAG（解析/切分/向量化/检索/重排/引用校验）、采集爬虫、情感分类、ASR 转写等。

> 与 Java 后台管理系统（`enterprise-ai-office-system-admin`）完全分离，两个独立项目。Java 为对外唯一网关，本服务只暴露内网 `/internal/**` 接口供 Java 调用。

## 目录结构

```
├── app/               # FastAPI 应用
│   ├── routers/       # 接口路由（对外 /api/**，内网 /internal/**）
│   ├── services/      # llm / extraction / generation / revise / polish / factcheck / export 等
│   ├── graphs/        # LangGraph 状态图编排
│   └── data/          # 种子模板与文风配置
├── alembic/           # 数据库迁移
├── tests/             # pytest 测试
├── exports/ uploads/  # 运行时导出/上传目录（gitignore）
├── .env               # 本地配置（含 DeepSeek API Key，不入库）
└── requirements.txt
```

## 启动

```powershell
cd E:\project\enterprise-ai-office-system-new
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt   # 首次
uvicorn app.main:app --reload --port 8000
```

- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health

## 关键配置（.env）

- `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_*`：DeepSeek（OpenAI 兼容，可插拔）
- `DATABASE_URL`：PostgreSQL（默认 localhost:5433/eaos，由 Java 项目的 docker-compose 提供）
- `EXPORT_DIR=exports`、`UPLOAD_DIR=uploads`（相对仓库根）

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --basetemp=C:\Temp\opencode\pytest-basetemp
```

## 与 Java 项目协作

- Java 同步调用本服务 `/internal/**` 内网接口（如 `/internal/health`）。
- 异步任务：Java 写任务表 → 本服务 Celery Worker 消费 → 回写状态。
- 数据库共享同一套 PostgreSQL（Java 项目的 docker-compose 编排）。