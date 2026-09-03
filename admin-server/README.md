# admin-server — 后台管理系统（Java / Spring Boot 3）

企业AI智能办公系统后台管理服务，作为对外唯一 API 网关：负责认证鉴权、业务/管理型 CRUD、列表/看板/报表查询、配置管理、通知通道、任务调度面板，并将 AI/文档/采集类请求转发给同仓 `../ai-service`。

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
4. 首次启动自动建表并创建管理员账号 `admin`。随机初始密码仅输出到服务日志，首次登录必须修改密码；历史 `admin123` 会被标记为必须修改。

## 测试运行建议

- 推荐运行位置：`Linux` CI（`ubuntu-latest`）或带 Docker 的 Linux 主机。
- 推荐原因：`AuthFlowIntegrationTest` 依赖 Testcontainers，当前在 Windows 本机容易被 Docker 探测链路干扰。
- Windows 本机默认跳过 `AuthFlowIntegrationTest`；该测试应在 Linux CI 或带 Docker 的 Linux 主机运行。
- CI 已固定 `Java 21`，并在 `admin-server` 任务里执行 `mvn -B spotless:check verify`。

## 关键配置（application.yml，支持环境变量覆盖）

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DB_HOST` / `DB_PORT` / `DB_NAME` | localhost / 5433 / eaos | PostgreSQL |
| `DB_USER` / `DB_PASSWORD` | eaos / eaos_dev_password | 数据库账号 |
| `JWT_SECRET` | 无 | 必填，至少 32 个字符且不可使用默认占位值 |
| `AI_INTERNAL_TOKEN` | 无 | 必填，Java 调用 Python 内网接口的服务间令牌，至少 16 个字符 |
| `OPINION_INTERNAL_TOKEN` | 无 | 必填，舆情 Worker 回调服务间令牌，至少 16 个字符 |
| `MEETING_INTERNAL_TOKEN` | 无 | 必填，会议 Worker 回调服务间令牌，至少 16 个字符 |
| `AI_BASE_URL` | http://localhost:8000 | 同仓 Python 服务地址 |

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
