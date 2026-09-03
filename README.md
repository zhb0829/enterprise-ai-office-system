# 企业 AI 智能办公系统

企业 AI 智能办公系统单仓。Java 负责统一 API 网关、认证授权和管理型业务，Python AI 服务负责生成、文档解析、采集与 AI 工作流；服务通过共享 PostgreSQL 和内网 HTTP 协作。

## 目录结构

```
├── admin-server/      # Spring Boot 3：统一网关、认证、管理型业务 API
├── ai-service/        # FastAPI：AI/文档/采集服务（端口 8000）
├── frontend/          # Vue3 用户工作台（端口 5173）
├── frontend-admin/    # Vue3 管理端（端口 5174）
└── docker-compose.yml # PostgreSQL + pgvector（宿主机端口 5433）
```

## 快速启动

1. 启动数据库：

   ```bash
   cd E:\project\enterprise-ai-office-system-admin
   docker-compose up -d
   ```

2. 启动 Python AI 服务：

   ```powershell
   cd E:\project\enterprise-ai-office-system-admin\ai-service
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
   ```

   - 首次安装依赖：`py -3.13 -m venv .venv`，然后 `.\.venv\Scripts\pip.exe install -r requirements.txt`
   - API 文档：`http://localhost:8000/docs`

3. 启动 Java 网关（需 JDK 21，Temurin 位于 D:\JDK21\jdk-21.0.12+8）：

   ```powershell
   cd E:\project\enterprise-ai-office-system-admin\admin-server
   $env:JAVA_HOME="D:\JDK21\jdk-21.0.12+8"
   mvn spring-boot:run
   ```

   - 默认端口 8080，Swagger：http://localhost:8080/swagger-ui.html
   - 首次启动自动创建管理员账号 `admin`，随机初始密码仅打印在服务日志中，首次登录必须修改密码。

4. 启动用户端：

   ```powershell
   cd E:\project\enterprise-ai-office-system-admin\frontend
   npm install
   npm run dev
   ```

5. 启动管理端：

   ```powershell
   cd E:\project\enterprise-ai-office-system-admin\frontend-admin
   npm install
   npm run dev
   ```

## 关键配置

- 数据库（admin-server/src/main/resources/application.yml，环境变量可覆盖）：默认 `localhost:5433/eaos`，账号 `eaos/eaos_dev_password`
- `AI_BASE_URL`：Python AI 服务地址（默认 `http://localhost:8000`）。
- `JWT_SECRET`：必须设置至少 32 个字符的非默认值。
- `AI_INTERNAL_TOKEN`、`OPINION_INTERNAL_TOKEN`、`MEETING_INTERNAL_TOKEN`：必须设置至少 16 个字符的非默认随机值；生产环境 Python 与 Java 都会在启动时校验。

政策法规模块：

- 用户端：`http://localhost:5173/workspace/policy`
- 管理端：`http://localhost:5174/admin/policy-documents`
- Java 网关转发 `/api/policy/**`、`/api/chat/**`、`/api/compliance/**` 到 Python AI 服务
- 合规结果仅作公开信息初步比对和风险提示，前端与接口均附免责声明

行业动态与竞品情报聚合：

- 管理端页面：`http://localhost:5174/admin/intelligence`
- Java 管理接口：来源配置 `/api/sources`，任务面板 `/api/intelligence/tasks`，简报查询/生成 `/api/reports/intelligence`，通知通道 `/api/notification-channels`
- Python 负责采集、正文抽取、SimHash 去重、向量辅助聚类、摘要与趋势生成；Java 仅做统一鉴权、配置管理、面板查询和内网任务触发。

## 服务协作

- 同步请求：Java 网关转发用户端请求至 Python AI 服务
- 异步任务：Python 负责解析、向量化和采集，结果回写共享数据库
- 数据库同一套 PostgreSQL（本仓库 docker-compose 提供）
- Python 不对公网暴露；Java 网关负责公网 JWT 鉴权，Python `/internal/**` 端点额外校验服务间令牌。
