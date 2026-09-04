# 企业 AI 智能办公系统 Java/Python 物理拆分实施方案

> 状态：Java/Python 分支拆分与仓库收尾已完成，情报聚合表 owner 收尾中
> 
> 更新日期：2026-09-04
> 
> 适用项目：
> - Java/前端项目：`E:\project\enterprise-ai-office-system-admin`
> - Python AI 项目：`E:\project\enterprise-ai-office-system-new`

## 一、决策结论

生产环境采用两个独立项目，而不是把 Java 和 Python 作为同一项目的源码模块：

1. Java 和 Python 共用同一 GitHub 远程仓库（`zhb0829/enterprise-ai-office-system`），以独立分支维护：`main` 承载 Java/前端，`python` 承载 Python AI 服务；两边互不引用对方分支源码，各自独立依赖、独立测试、独立镜像和独立回滚。
2. 两边使用独立依赖、独立测试、独立镜像、独立版本号和独立发布流程。
3. Java 对外提供统一 API；Python 只提供内网 AI 能力。
4. 两边通过版本化 HTTP API 和异步任务协议协作，不直接引用对方源码。
5. PostgreSQL、Redis、日志和监控平台可以共用，但业务数据和迁移脚本必须有唯一所有者。
6. 初期可以部署在同一台服务器或同一集群中，使用独立容器、网络策略和资源限制。

该方案同时满足语言职责清晰、独立扩容、独立回滚和统一运维的要求，避免为了代码隔离而增加两套完整基础设施。

## 二、项目职责

### Java/前端项目

路径：`E:\project\enterprise-ai-office-system-admin`

负责：

- Spring Boot API 网关
- JWT、用户、租户、角色和权限
- 管理业务、工作流和通知
- 对外 API、参数校验和审计
- 用户端与管理端前端
- Java 负责的数据迁移和业务表
- Java 对 Python 的任务派发和回调接收

不负责：

- LLM 供应商调用
- 文档解析、向量化和 AI Prompt 编排
- Python Worker 的内部任务实现

### Python AI 项目

路径：`E:\project\enterprise-ai-office-system-new`

负责：

- FastAPI AI 服务
- LLM、Embedding、视觉模型和 ASR 适配
- 草稿生成、润色、核查和政策检索
- 文档解析、文本切分和向量处理
- Celery Worker、Beat 和 AI 长任务
- Python 负责的 AI 任务、向量和解析中间结果
- Python 负责的数据迁移和 AI 表

不负责：

- 浏览器登录和权限判断
- 用户、租户和角色管理
- Java 业务表的直接写入
- 对公网开放 API

## 三、目标运行架构

```text
浏览器
   |
   v
Nginx / API Gateway
   |-- /              -> frontend
   |-- /admin/        -> frontend-admin
   |-- /api/**        -> admin-server:8080
   |                       `-> /internal/v1/** -> ai-service:8000
   `-- /static/**     -> 按文件所有权转发

admin-server:8080
   |-- 对外鉴权和业务 API
   |-- Java 数据库访问
   `-- Java -> Python 内网调用

ai-service:8000
   |-- 仅内网可达
   |-- AI API 和 Worker
   |-- Python 数据库访问
   `-- Python -> Java 内部回调

PostgreSQL / Redis / 文件存储 / Prometheus / Loki / Grafana
   `-- 基础设施可共用，数据和权限按服务隔离
```

Python 不应暴露宿主机公网端口。开发环境可以使用 `localhost:8000`，生产环境使用 Docker 网络中的
`http://ai-service:8000`。

## 四、接口协作规则

### 同步接口

- 浏览器只访问 Java 的 `/api/**`。
- Java 对需要 AI 能力的请求调用 Python `/internal/v1/**`。
- Python 内部接口统一携带 `X-Internal-Token`。
- 所有请求透传 `X-Trace-Id` 或生成新的 `traceId`。
- Java 设置连接超时、读取超时、有限重试和熔断。
- Python 不依赖浏览器传入的用户权限，用户身份由 Java 校验后以可信上下文传递。

### 异步任务

统一使用以下流程：

```text
Java 创建业务任务
  -> Java 调用 Python 启动任务
  -> Python 返回 taskId / accepted
  -> Python Worker 执行
  -> Python 回调 Java 进度、结果或失败
  -> Java 保存权威状态
  -> 前端查询 Java 的任务状态
```

任务协议至少包含：

- `taskId`
- `idempotencyKey`
- `status`
- `progress`
- `traceId`
- `errorCode`
- `errorMessage`
- `resultRef`

回调必须幂等。Java 收到重复回调时不得重复推进业务状态或重复发送通知。

### API 版本策略

采用 `/internal/v1/**` 作为稳定接口前缀。升级顺序：

1. Python 先增加兼容字段或新版本接口。
2. Python 发布。
3. Java 切换调用并完成验收。
4. 观察稳定后再删除旧接口。

Python 至少兼容当前版本和上一个版本的请求结构。破坏性变更不得直接覆盖旧字段含义。

## 五、数据库边界

### 总原则

可以共用一个 PostgreSQL 实例，但每张表必须满足：

- 一个项目负责建表和迁移。
- 一个项目负责业务写入。
- 另一个项目只能通过 API 访问。
- 不复制同一张表的 Flyway 和 Alembic 迁移。
- 不通过跨项目 SQL 查询绕过 API 边界。

### 初步所有权

Java 负责：

- `sys_*`
- 用户、租户、角色、刷新令牌和通知
- `opinion_*`
- `qual_*`
- `conference_*`
- 业务任务、审批和业务审计记录

Python 负责：

- 草稿生成相关表
- 素材解析和向量相关表
- 政策文档、政策条款和 AI 问答记录
- LLM 调用记录
- AI 解析中间结果

情报聚合表已裁定为 Java 权威：`source_config`、`collected_article`、`article_cluster`、`intelligence_report`、`collection_task_log` 由 Java Flyway `V1__baseline.sql` 建表与维护（来源配置、任务面板、报告生命周期位于 Java 侧）。Python 不保留这些表的 Alembic 迁移与 ORM 模型，采集、聚类和摘要结果改为通过 Java 新增的 internal API 回写。

### 迁移顺序

1. 列出 Java Flyway 和 Python Alembic 的全部表。
2. 为每张表登记 owner、读者、写者和迁移文件。
3. 删除非 owner 项目的重复迁移。
4. 把跨表查询改为内部 API。
5. 在测试数据库执行完整迁移。
6. 在生产数据库先备份，再执行迁移。
7. 观察一个完整发布周期后再拆分数据库实例。

## 六、文件和对象存储

文件按服务和业务域分配所有权：

```text
/data/storage/java/
/data/storage/ai/
/data/storage/meeting/
/data/storage/policy/
```

- Java 不直接删除 Python 生成文件。
- Python 不直接修改 Java 业务文件。
- 跨服务传递文件引用，不传递宿主机绝对路径。
- 生产扩容前切换到 S3/OSS/MinIO 等对象存储。
- 文件下载由 Java 做权限判断，再返回受控下载地址或代理下载。

## 七、配置和密钥

### Java 必需配置

```env
JWT_SECRET=<至少32位随机值>
AI_INTERNAL_TOKEN=<至少16位随机值>
OPINION_INTERNAL_TOKEN=<至少16位随机值>
MEETING_INTERNAL_TOKEN=<至少16位随机值>
AI_BASE_URL=http://ai-service:8000
```

### Python 必需配置

```env
DATABASE_URL=postgresql+psycopg://...
AI_INTERNAL_TOKEN=<与Java一致>
OPINION_INTERNAL_TOKEN=<按回调约定配置>
MEETING_INTERNAL_TOKEN=<按回调约定配置>
APP_ENV=production
```

真实 AI 能力配置：

```env
LLM_API_KEY=<LLM供应商密钥>
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL_GENERATION=deepseek-chat
EMBEDDING_API_KEY=<Embedding供应商密钥>
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
```

密钥要求：

- 不写入 Git、Dockerfile、镜像和前端代码。
- 通过部署平台 Secret、环境变量或密钥管理服务注入。
- 定期轮换服务间 Token。
- Token 轮换时短时间支持旧 Token 和新 Token，完成切换后撤销旧 Token。

未配置 `LLM_API_KEY` 时，Python 可以使用规则化降级实现，仅适合本地开发和离线验收。

## 八、发布和回滚

### 仓库和镜像

main 分支（Java/前端）构建：

```text
admin-server:<git-sha>
frontend:<git-sha>
frontend-admin:<git-sha>
gateway:<git-sha>
```

python 分支（Python AI）构建：

```text
ai-service:<git-sha>
```

main 与 python 分支各自独立 CI/CD、独立版本号、独立回滚。生产 Compose 只引用已发布镜像，不从 Java 仓库的相对路径构建 Python。

### 推荐发布顺序

1. Python 增加兼容接口或兼容字段。
2. 发布 Python 镜像。
3. 执行接口契约测试和健康检查。
4. 发布 Java 镜像。
5. 发布前端和网关。
6. 检查任务、日志、错误率和模型耗时。

### 回滚

- Java 故障：回滚 Java 镜像，不回滚 Python 数据迁移。
- Python 故障：回滚 Python 镜像，Java 保持兼容调用。
- 数据迁移故障：先停止写入，再按迁移脚本回滚或恢复数据库备份。
- 文件存储故障：保留旧 volume 或对象存储版本，禁止直接覆盖原文件。

## 九、监控与故障隔离

必须监控：

- Java 和 Python 的健康状态
- API P50/P95/P99 延迟
- 4xx/5xx 错误率
- Python Worker 积压、失败和重试次数
- LLM/Embedding 请求耗时和失败率
- 数据库连接池
- Redis 状态
- 文件存储容量
- `traceId` 关联日志

故障行为：

- Python 不可用时，Java 的登录、权限和非 AI 查询仍可用。
- 同步 AI 请求超时后返回明确错误，不无限重试。
- 异步任务进入失败或待重试状态，不阻塞 Java 主线程。
- LLM 供应商异常时保留任务记录和错误原因。
- Python 服务禁止被公网直接访问。

## 十、实施记录

已完成：

- [x] 确认 Java/Python 独立项目方案。
- [x] 将 `admin/ai-service` 的生产加固代码同步到独立 Python 项目。
- [x] 独立 Python 项目补充 Dockerfile、生产安全配置、可观测性和测试。
- [x] 独立 Python 项目增加自己的 GitHub Actions CI。
- [x] Java 项目移除 Python 源码副本。
- [x] Java CI 移除 Python 构建和测试任务。
- [x] 生产 Compose 移除 `build: ../ai-service`，改为只使用 Python 镜像。
- [x] 更新 Java、Python 和生产部署文档。
- [x] 独立 Python 测试通过：`74 passed`。
- [x] 建立单仓库双分支：`main`(Java)/`python`(Python)，删除冗余 `admin`、`archive/*` 远程分支。
- [x] 合并并推送独立 Python 项目的全部未提交同步变更（`d266322` → `origin/python`）。
- [x] Java 仓库提交移除 `ai-service` 源码与文档/CI/Compose 改动并推送（`2065052` → `origin/main`）；删除本地残留 `ai-service/.venv`。
- [x] 修复内部鉴权测试令牌注入（新增 `tests/conftest.py`），无需外部环境变量即可 `74 passed`。
- [x] 情报聚合重叠表 owner 落地为 Java 权威：Java 新增 `/internal/intelligence/**` 回写/查询 API（`183086b`）；Python 删除重叠表 Alembic/ORM 并改为 HTTP 回写（`6db1f7a`）。

待完成：

- [ ] 完成 OpenAPI/JSON Schema 契约文件和契约测试。
- [ ] 完成所有数据库表的 owner 登记。
- [ ] 将跨项目直接数据库读取改成内部 API。
- [ ] 明确静态文件下载的权限链路。
- [ ] 配置生产 Secret、镜像仓库和正式域名。
- [ ] 在 Linux + Docker 环境执行完整部署验收。

## 十一、验收清单

### 代码隔离

- [ ] Java 仓库不存在 Python 源码目录。
- [ ] Python 仓库可以脱离 Java 仓库独立安装、测试和构建镜像。
- [ ] 两边没有跨仓库源码 import。

### 接口隔离

- [ ] 浏览器不直接请求 Python。
- [ ] Python 内部接口有 Token 校验。
- [ ] 同步接口有超时、有限重试和错误映射。
- [ ] 异步回调幂等。

### 数据隔离

- [ ] 每张表只有一个迁移 owner。
- [ ] Java 和 Python 不同时写同一张表。
- [ ] 跨服务数据通过 API 访问。
- [ ] 数据库备份和恢复演练完成。

### 生产隔离

- [ ] Python 不暴露公网端口。
- [ ] Java、Python、Worker 有独立资源限制。
- [ ] 密钥不在仓库和镜像中。
- [ ] 监控、日志和 traceId 可用。
- [ ] Java 或 Python 可独立回滚。

## 十二、当前结论

本系统不采用 Java/Python 合并成一个源码项目的方案。采用“两个代码项目 + 一套可共用基础设施 + 清晰 API/数据边界”的生产形态。

拆分的成功标准不是目录被移走，而是：

1. 任意一边可以独立构建和发布。
2. 任意一边故障不会拖垮另一边的非相关能力。
3. 两边只通过稳定协议协作。
4. 每份数据和每个迁移脚本只有一个 owner。
5. 仓库中不再存在第二份 Python AI 源码。
