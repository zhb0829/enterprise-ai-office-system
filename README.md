# enterprise-ai-office-system-admin（Java 后台管理系统）

企业 AI 智能办公系统的 **后台管理系统**（Java 独立项目）。作为对外唯一 API 网关：负责认证鉴权、业务/管理型 CRUD、列表/看板/报表查询、配置管理、通知通道、任务调度面板，并将 AI/文档/采集类请求转发给 Python AI 服务（`enterprise-ai-office-system-new`）。

> 与 Python AI 服务完全分离，两个独立项目。本仓库自带前端与数据库编排。

## 目录结构

```
├── admin-server/      # Spring Boot 3 后端（含安全/JWT/网关/业务接口）
├── frontend/          # Vue3 + Vite 用户工作台（撰写 / 政策问答）
├── frontend-admin/    # Vue3 + Vite 管理端（模板 / 素材 / 政策知识库）
└── docker-compose.yml # 数据库编排（PostgreSQL + pgvector，端口 5433）
```

## 快速启动

1. 启动数据库：

   ```bash
   cd E:\project\enterprise-ai-office-system-admin
   docker-compose up -d
   ```

2. 启动后端（需 JDK 21，Temurin 位于 D:\JDK21\jdk-21.0.12+8）：

   ```powershell
   cd E:\project\enterprise-ai-office-system-admin\admin-server
   $env:JAVA_HOME="D:\JDK21\jdk-21.0.12+8"
   mvn spring-boot:run
   ```

   - 默认端口 8080，Swagger：http://localhost:8080/swagger-ui.html
   - 首次启动自动建表并初始化管理员 `admin / admin123`（生产必改）

3. 启动前端：

   ```powershell
   cd E:\project\enterprise-ai-office-system-admin\frontend
   npm install
   npm run dev
   ```

## 关键配置

- 数据库（admin-server/src/main/resources/application.yml，环境变量可覆盖）：默认 `localhost:5433/eaos`，账号 `eaos/eaos_dev_password`
- `AI_BASE_URL`：Python AI 服务地址（默认 `http://localhost:8000`）
- `JWT_SECRET`：生产必须通过环境变量替换

政策法规模块：

- 用户端：`http://localhost:5173/workspace/policy`
- 管理端：`http://localhost:5174/admin/policy-documents`
- Java 网关转发 `/api/policy/**`、`/api/chat/**`、`/api/compliance/**` 到 Python AI 服务
- 合规结果仅作公开信息初步比对和风险提示，前端与接口均附免责声明

## 与 Python 项目协作

- 同步请求：Java 经 `AiService`（RestTemplate）调用 Python 的 `/internal/**` 内网接口
- 异步任务：Java 写任务表 → Python Celery Worker 消费 → 回写状态
- 数据库同一套 PostgreSQL（本仓库 docker-compose 提供）
