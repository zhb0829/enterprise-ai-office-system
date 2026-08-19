# 企业AI智能办公系统

面向企业的 AI 智能办公平台，当前完成 **P0 公告与新闻稿智能撰写** 模块：模板化生成、风格适配、内容润色、事实核查、多轮修改、版本历史、导出（MD/DOCX）。

统一仓库，包含 **Java 后台管理端** 与 **Python AI/agent 服务** 两个独立项目。

## 仓库结构

```
├── admin/                # Java 后台管理系统（Spring Boot + Vue3）
│   ├── admin-server/     # Spring Boot 3.4.5（JDK21 / 端口 8080）：网关 + JWT 认证 + 反向代理
│   ├── frontend/         # 用户端 Vue3 + Vite（端口 5173）：撰写工作台
│   ├── frontend-admin/   # 管理端 Vue3 + Vite（端口 5174）：模板/文风/素材管理
│   └── docker-compose.yml# PostgreSQL 16 + pgvector（端口 5433）
├── app/                  # Python FastAPI AI 服务（端口 8000）
│   ├── routers/          # drafts / templates / materials
│   ├── services/         # llm / extraction / generation / revise / polish / factcheck / export
│   ├── graphs/           # LangGraph 状态图编排
│   └── data/             # 种子模板与文风配置
├── alembic/              # Python 数据库迁移
├── tests/                # pytest 测试
└── requirements.txt      # Python 依赖
```

## 服务与端口

| 服务 | 端口 | 说明 |
|---|---|---|
| 用户端（撰写工作台） | 5173 | http://localhost:5173 |
| 管理端（后台管理） | 5174 | http://localhost:5174/admin/templates |
| Java 网关 | 8080 | JWT 认证（可开关）、反向代理到 Python |
| Python AI | 8000 | 生成/润色/核查/素材，API 文档 /docs |
| PostgreSQL | 5433 | eaos / eaos_dev_password / eaos |

## 启动

一键启动（部署编排，含 DB + Python + Java + 用户端 + 管理端）：

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

## 技术栈

- Java：Spring Boot 3.4.5、MyBatis-Plus、Spring Security + JWT、JDK21
- Python：FastAPI、SQLAlchemy 2.0、LangGraph、Alembic
- 前端：Vue3 + Vite + vue-router
- LLM：DeepSeek（OpenAI 兼容，可插拔）
- 数据库：PostgreSQL 16 + pgvector（Docker）
