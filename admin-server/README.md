# admin-server — 后台管理系统（Java / Spring Boot 3）

企业AI智能办公系统后台管理系统，作为对外唯一 API 网关：负责认证鉴权、业务/管理型 CRUD、列表/看板/报表查询、配置管理、通知通道、任务调度面板，并将 AI/文档/采集类请求转发给独立 Python agent 服务（`E:\project\enterprise-ai-office-system-new`）。

## 技术栈

- Spring Boot 3.4 + Spring Security + JWT
- MyBatis-Plus + PostgreSQL（与 Python 共享同一数据库）
- springdoc-openapi（Swagger UI）

## 启动

1. 确保 PostgreSQL 已启动（`docker-compose up -d`，见仓库根目录）。
2. 编译运行：

   ```bash
   cd E:\project\enterprise-ai-office-system-admin\admin-server
   mvn spring-boot:run
   ```

3. 默认端口 `8080`，Swagger：`http://localhost:8080/swagger-ui.html`。
4. 首次启动自动建表并初始化管理员账号 `admin / admin123`（仅供开发，生产务必修改）。

## 关键配置（application.yml，支持环境变量覆盖）

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DB_HOST` / `DB_PORT` / `DB_NAME` | localhost / 5433 / eaos | PostgreSQL |
| `DB_USER` / `DB_PASSWORD` | eaos / eaos_dev_password | 数据库账号 |
| `JWT_SECRET` | 开发用密钥 | 生产必须通过环境变量替换 |
| `AI_BASE_URL` | http://localhost:8000 | Python agent 服务地址（本地源码位于 `E:\project\enterprise-ai-office-system-new`） |

## 目录结构

```
src/main/java/com/eaos/admin/
├── AdminServerApplication.java   # 启动类
├── common/                       # 统一返回 R / 异常处理
├── config/                       # Security / RestTemplate / 属性配置
├── security/                     # JWT 认证体系
├── controller/                   # 业务与管理 API
├── service/                      # 业务逻辑（含 Python AI 服务调用）
├── dto/ entity/ mapper/          # 数据层
src/main/resources/
├── application.yml
└── schema.sql                    # 建表脚本（幂等）
```

## 与 Python 服务协作

- 同步请求：通过 `AiService`（RestTemplate）调用 Python 的 `/internal/**` 内网接口。
- 异步任务：Java 写任务表 → Python Celery Worker 消费 → 回写状态。
