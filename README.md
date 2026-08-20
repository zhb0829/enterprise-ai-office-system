# 企业AI智能办公系统

面向企业的 AI 智能办公平台，当前完成 **P0 公告与新闻稿智能撰写**，并新增 **P0 行业政策法规智能问答 MVP**：公开政策文件解析、条款级切分、混合检索、引用溯源、条款解读与合规初步比对。

本项目为 **Python AI/agent 服务**。Java 后台管理系统已独立迁移至
`E:\project\enterprise-ai-office-system-admin`，不再位于本项目目录中。

## 仓库结构

```
├── app/                  # Python FastAPI AI 服务（端口 8000）
│   ├── routers/          # drafts / templates / materials / policy
│   ├── services/         # llm / extraction / generation / policy / revise / polish / factcheck / export
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

后台管理系统的 Java 网关、用户端和管理端端口及启动方式，见
`E:\project\enterprise-ai-office-system-admin\README.md`。

## 启动

一键启动（部署编排，含 DB + Python 及独立后台管理系统）：

```cmd
E:\project\eaos-deploy\start.bat
E:\project\eaos-deploy\stop.bat
```

手动启动见各子目录 README。

## 配置

- 统一外部配置：`E:\project\eaos-deploy\.env`（DB / 端口 / JWT / LLM Key，不入库）
- 认证开关：`SECURITY_ENABLED=true`（Java 网关）开启 JWT；默认关闭（开发）
- 生产环境：替换 `JWT_SECRET`、`LLM_API_KEY`、DB 密码

## 测试

```powershell
cd E:\project\enterprise-ai-office-system-new
.\.venv\Scripts\python.exe -m pytest tests -q --basetemp=C:\Temp\opencode\pytest-basetemp
```

政策问答接口：

- `POST /api/policy/chat` 或 `POST /api/chat/policy`
- `POST /api/policy/interpret`
- `POST /api/policy/compliance/check` 或 `POST /api/compliance/check`
- `POST /api/policy/documents/upload`、`POST /api/policy/documents/from-url`
- `GET /api/policy/documents`、`GET /api/policy/search`

无 `LLM_API_KEY` 时使用离线检索与规则化降级实现；未命中现行有效条款时明确拒答，不生成无依据结论。

## 技术栈

- Java：Spring Boot 3.4.5、MyBatis-Plus、Spring Security + JWT、JDK21
- Python：FastAPI、SQLAlchemy 2.0、LangGraph、Alembic
- 前端：Vue3 + Vite + vue-router
- LLM：DeepSeek（OpenAI 兼容，可插拔）
- 数据库：PostgreSQL 16 + pgvector（Docker）
