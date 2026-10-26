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

## 混合切分

普通素材先识别章节与段落，再递归细分；政策优先保留完整条款，
仅超过 `CHUNK_SEMANTIC_TRIGGER_SIZE`（默认 1200 字）的父段落/条款进行语义边界检测。
表格、列表和代码块保留整体，不做语义打散。只有最终子块建立向量索引，
父级原文及切分方式保存于 `meta`，检索按父级去重，生成和政策引用使用父级原文。

- `CHUNK_SEMANTIC_ENABLED=false` 可关闭语义检测；未配置真实 Embedding 时使用结构/递归切分。
- 语义边界检测失败时回退递归切分；最终索引向量生成失败仍返回 `503`，不混入哈希向量。
- `CHUNK_MIN_SIZE` 默认 320 字，限制语义边界两侧最小长度；
  `CHUNK_SEMANTIC_SIMILARITY_THRESHOLD` 默认 0.42，需结合实际语料评估调整。
- 现有 `/api/materials/reindex` 和 `/api/policy/reindex` 默认仍只更新向量。
  加上 `rechunk=true` 才会按新策略重新切分并发布知识快照，
  可分别通过 `material_id` / `document_id` 限定范围。
  重新切分会更新切片 ID，旧知识快照仍保留，使用中的引用需重新检索。

## 知识图谱与关系召回（G1）

图谱是政策域的派生物，跑通 `Schema 约束抽取 → 实体对齐去重 → networkx 落图 → 多跳遍历`，
社区摘要用于全局性问题。它**默认关闭**（`KG_ENABLED=false`），必须先跑出
“向量 + 图”相对“纯向量”的正向增益才开启——无增益不上线。

### 构图

```powershell
# 为 default 租户下全部已完成政策文档构图，并生成社区摘要
.\.venv\Scripts\python.exe -m app.kg.build --tenant default
# 限定文档 / 限制条款数 / 不写社区摘要
.\.venv\Scripts\python.exe -m app.kg.build --document-id 12 --limit 50 --no-communities
```

- 幂等：节点按「类型 + 归一键」合并；同一来源重构图按 `source_key` 覆盖旧边，不累积两套边。
- 预算：一次任务最多调用 `KG_EXTRACT_BUDGET_PER_JOB`（默认 50）次抽取模型，超出自动改用
  规则化通道并在统计里记 `llmBudgetExhausted`，不做无限重试。
- 准入：抽取必须落在白名单内（`app/kg/schema.py`）。类型不在白名单、关系端点类型不符、
  端点不是本批抽取到的实体，一律丢弃并计入 `rejected`，不写进图。
- 对齐：别名归一（全角/括号/官方简称）+ 同类型相似度合并（`KG_ALIGNMENT_THRESHOLD`，默认 0.86），
  合并依据随节点落库，可回溯。

### 检索接入

`search_policy_clauses` 在 BM25 + Dense 之外增加图谱遍历第三路，三路一起进现有 RRF：

- 图命中不受词面/向量门槛限制，因此能召回“关系可达但字面不可达”的条款；
- 图路失败只标记 `degraded`，主链路照常返回；
- 每条结果带路径（经过哪些实体、哪些关系、几跳），写入检索审计，可解释召回来源。

### 治理与边界

- 图数据带 `tenant_id` + `classification`；加载与命中都按 `Principal.can_read` 过滤。
  `install_data_isolation` 不覆盖图数据，因此这道过滤是显式的，不假设第二道防线。
- 起步用 networkx + 关系表（`kg_entity` / `kg_relation` / `kg_community`）；图规模上来再换 Neo4j，
  只需替换 `app/kg/store.py` 与 `app/kg/traverse.py`，抽取与对齐不受影响。
- 增益评测与上线门禁见 `evals/README.md` 第 5 节。

```env
KG_ENABLED=false
KG_MODEL=
KG_MAX_HOPS=2
KG_SEED_LIMIT=8
KG_CLAUSE_LIMIT=30
KG_ALIGNMENT_THRESHOLD=0.86
KG_EXTRACT_BUDGET_PER_JOB=50
KG_COMMUNITY_MIN_SIZE=3
KG_MAX_NODES=5000
```

## 资源隔离与运行时开关（G3 / G5）

### G3 租户资源隔离与限流

隔离分两层，两层都"超限快速失败"，不做无限排队：

| 层 | 位置 | 手段 | 超限表现 |
|---|---|---|---|
| 网关（第一道） | Java `admin-server` `TenantRateLimitFilter` | 按认证租户的令牌桶（`rps`/`burst`）+ 并发配额（租户/全局） | 429 + `Retry-After` |
| AI 服务（第二道） | `app/resource_guard.py` | 同上，按可信身份头解析出的 `tenant_id` 分桶 | 429 + `Retry-After` + `X-RateLimit-*` |
| 耗时链路 | `app/services/capacity.py` | LLM / Embedding / Rerank 各自独立线程池 + 有界队列 | 池满立即失败，走既有降级路径（见下） |

- 网关租户键取自 JWT 认证出的 `LoginUser.tenantId`，客户端自报的组织头不参与配额计算；
  AI 服务侧的租户键取自可信身份头解析结果，**未认证请求不进任何租户配额**
  （没有共享的匿名桶：匿名流量由网关第一道防线在认证阶段挡掉）。
- 429 只影响超配额的那个租户：同机其他租户的请求、延迟与错误率不受挤占；
  未认证请求不进租户配额（它们会被鉴权层直接拒绝，不该把 403 掩盖成 429）。
- 运行时开关端点（`/api/agent/flags`）默认在免限流名单内：它是"带外管理通道"，
  不能被自身限流挡住（仍需 `agent:audit` / `agent:admin` 权限）。
- 容量池满时：LLM → 政策问答走检索兜底、公告生成按文风降级为规则化草稿并写进 `riskFlags`
  （`LLMCapacityError` 与上游故障分开）；Embedding → 跳过 Dense 路，**不混用哈希向量**；
  Rerank → 确定性词法重排。三者都带 `degraded` 标记。
- 指标：网关 `eaos_gateway_tenant_throttled_total`；服务侧 `eaos_tenant_throttled_total`、
  `eaos_tenant_inflight`、`eaos_capacity_rejected_total`、`eaos_capacity_pool_inflight`。
- 验收：`evals/tenant_load_test.py`（多租户隔离压测），见 `evals/README.md` 第 8 节。

```env
RATE_LIMIT_ENABLED=true
RATE_LIMIT_RPS=50
RATE_LIMIT_BURST=100
RATE_LIMIT_MAX_CONCURRENCY=32
RATE_LIMIT_GLOBAL_CONCURRENCY=128
RATE_LIMIT_TENANT_OVERRIDES=
RATE_LIMIT_AUDIT_ENABLED=false
LLM_POOL_WORKERS=4
LLM_POOL_QUEUE=8
EMBEDDING_POOL_WORKERS=4
EMBEDDING_POOL_QUEUE=8
RERANK_POOL_WORKERS=2
RERANK_POOL_QUEUE=8
```

### G5 运行时降级开关

降级能力原本依赖环境变量重启，现在升级为**运行时热开关**：单点故障可在秒级回退主链路 + 兜底话术。

| 开关 | 关闭后的回退路径 | 默认值来源 |
|---|---|---|
| `kg` | 退化为 BM25 + Dense 两路融合，不再进入图路 | `KG_ENABLED` |
| `semantic_rerank` | 跳过语义精排，改用确定性词法重排并标记 `degraded` | `RERANK_URL` / `RERANK_LOCAL_MODEL` |
| `remote_llm` | 不调用外部对话/抽取模型，走既有规则化兜底并标记 `degraded` | `LLM_API_KEY` |
| `remote_embedding` | 检索跳过 Dense 路（拒绝以哈希向量顶替真实向量） | `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` |
| `factcheck` | 模型核查退化为规则化核查，每条结论带 `degraded` + `degradeReason` | 默认开启 |

```powershell
# 查看当前开关、默认值来源与关闭后的回退路径（需 agent:audit）
curl.exe -s -H "X-Internal-Token: $env:AI_INTERNAL_TOKEN" -H "X-User-Id: ops" -H "X-User-Permissions: agent:audit" `
  http://localhost:8000/api/agent/flags
# 关闭语义精排（需 agent:admin）；enabled=null 表示恢复环境变量默认
curl.exe -s -X PUT -H "X-Internal-Token: $env:AI_INTERNAL_TOKEN" -H "X-User-Id: ops" -H "X-User-Permissions: agent:admin" `
  -H "Content-Type: application/json" -d "{\"enabled\": false, \"reason\": \"精排服务 502\"}" `
  http://localhost:8000/api/agent/flags/semantic_rerank
```

- **默认值仍来自环境变量**：运行时开关只做覆盖，`enabled=null` 即恢复，避免两套配置互相打架。
- **关闭必须能说清降级行为**：被关闭的原因会写进 `degradationReasons`、检索诊断
  （`denseBackend=disabled-by-flag`、`reranker.reason=runtime-flag-*`、`runtimeFlags`）
  与 AgentRun 审计，不允许"静默关掉还在报成功"。
- **切换留痕**：每次切换写治理审计 `flag.update`，并暴露 `eaos_runtime_flag` 指标。
- **边界**：开关状态在进程内，当前部署为单 worker；多副本部署需逐副本下发，
  本模块不假装是分布式配置中心。
- 验收：`evals/fault_injection.py`（故障注入），见 `evals/README.md` 第 9 节。

## 模型分层路由与成本核算（G4 / G6）

### G4 模型分层路由

生成类调用按"用途 + 问题复杂度"选层：简单问句走轻量模型、复杂推理走旗舰模型。
抽取 / 事实核查 / Embedding / Rerank 仍用各自的专用模型——那属于"用对模型"，不参与分层。

| 层 | 判定 | 默认模型来源 |
|---|---|---|
| `light` | 复杂度分值 ≤ `LLM_ROUTING_LIGHT_MAX_SCORE` | `LLM_MODEL_TIER_LIGHT` |
| `standard` | 中间区间 | `LLM_MODEL_TIER_STANDARD`（空则复用 `LLM_MODEL_GENERATION`） |
| `reasoning` | 分值 ≥ `LLM_ROUTING_REASONING_MIN_SCORE` | `LLM_MODEL_TIER_REASONING` |

- **默认关闭**（`LLM_ROUTING_ENABLED=false`），与 G1 图谱同口径：先跑 `evals/routing_compare.py`
  拿到"延迟/成本改善且质量不降"的证据再显式开启；运行中可经运行时开关 `model_routing` 热切换。
- **未配置轻量层 / 旗舰层时开启也是 no-op**：回落标准层，决策写明 `source=tier-model-unset`；
  用途不在可分层清单（或调用方显式传了专用模型）时同样如实标注，不假装路由过。
- 复杂度打分是**可解释启发式**：长度、多问句、比较/因果/条件词、多跳词、引用条款数、上下文规模；
  分值与命中信号一起写进决策，便于回归与回溯（不需要训练数据，LTR 另见 G9）。
- 决策两条留痕：`agent_run.steps` 的 `model.route` 步骤 + `agent_run.routing` 汇总列；
  政策问答 / 解读响应体带 `routing` 字段（tier / model / score / signals / reason）。
- 运维查看：`GET /api/agent/model-routing`（需 `agent:audit`）。
- 验收：`evals/routing_compare.py`，见 `evals/README.md` 第 10 节。

```env
LLM_ROUTING_ENABLED=false
LLM_MODEL_TIER_LIGHT=
LLM_MODEL_TIER_STANDARD=
LLM_MODEL_TIER_REASONING=
LLM_ROUTING_LIGHT_MAX_SCORE=0
LLM_ROUTING_REASONING_MIN_SCORE=3
```

### G6 成本核算

Token 用量按"租户 / 业务功能（intent）/ 模型用途（purpose）/ 模型"记账，成本只在价格表命中时计算。

- **价格表是唯一价格来源**：`LLM_PRICE_TABLE`（JSON，元 / 百万 token，仅 CNY）。
  代码里不内置任何单价——内置单价会随供应商调价静默过期，比没有单价更危险。
- **未知即 null**：模型未收录、或供应商没返回 usage，成本记 `null`，不用 0 顶替、不估算；
  部分已定价时 `cost` 只含已知部分，同时用 `costComplete=false` + `unpricedModels` 自曝缺口。
- **明细随 AgentRun 一次性落库**（`agent_run.usage.by_model`：模型 → 用途 → tokens/cost），
  不新建"每次调用一行"的流水表——那会把写放大压到被保护的业务库上（与 G3 同一条纪律）。
- **查询**：`GET /api/agent/costs?days=7&intent=&groupBy=model,purpose,intent,tenant`
  （需 `agent:audit`；`tenant=all-tenants` 与跨租户查询需 `agent:admin`）。
  窗口上限由 `COST_QUERY_MAX_DAYS` / `COST_QUERY_MAX_RUNS` 控制，超限显式截断并标记 `truncated`。
- 指标：`eaos_model_tokens_total`、`eaos_model_cost_cny_total`、`eaos_model_unpriced_calls_total`。
- 验收：`evals/cost_audit.py`，见 `evals/README.md` 第 11 节。

```env
LLM_PRICE_TABLE={"deepseek-chat":{"input":2,"output":8},"text-embedding-3-small":{"input":0.02,"output":0}}
COST_QUERY_MAX_DAYS=90
COST_QUERY_MAX_RUNS=20000
```

## 三角色治理分工（G7）

在既有密级（`DataLevel`）+ 细粒度权限集合 + 部门 + 属主之上，补一层**租户治理职责映射**，
从网关第一跳校验一直贯通到检索末条 filter。事实来源是 `app/agent/access.py`，
可通过 `GET /api/agent/roles`（受信身份即可读）导出同一份 `responsibility_matrix()`。

| 角色 | 职责 | 权限边界 |
|---|---|---|
| 平台管理员 `platform_admin` | 管租户：租户治理元数据、跨租户审计、运行时开关 | 租户管理员能力 ∪ `agent:admin`；**跨租户仍读不到内容** |
| 租户管理员 `tenant_admin` | 管知识库：本租户知识发布 / 回滚、素材、稿件复核、本租户审计 | 无 `agent:admin`（碰不到平台开关与跨租户治理） |
| 普通用户 `member` | 只提问：只读检索 + 自己的偏好与会话记忆 | 无任何写 / 发布 / 审计权限 |

- **只收缩，不放大**：声明角色后有效权限 = 角色基线 ∩ 网关声明的权限集合；
  声明了角色但权限头为空按"没有权限"处理（fail-closed，只有打开 `TENANT_ROLE_EMPTY_PERMISSIONS_FALLBACK` 才回落到基线）；
  即使绕过网关收敛直接构造 `Principal`，`Principal.require` 也会用角色基线上限再拦一次（纵深防御）。
- **头走私防护**：同一个受信身份头出现两次（`X-User-Role` / `X-User-Permissions` / `X-User-Id` / `X-Tenant-Id`）
  直接 403 —— 网关必须**覆盖**而不是追加客户端同名头（Java 集成测试也断言了伪造头被剥离）。
- **未下发角色不收紧**：Java 网关尚未下发 `X-User-Role` 时保持既有"权限集合即事实"口径（过渡期）；
  `TENANT_ROLE_GOVERNANCE_ENABLED=false` 可整体回退（含 `require` 的角色上限检查）；
  `TENANT_ROLE_REQUIRED=true` 则反过来 fail-closed：无角色头的 `/api` 请求直接 403（网关全量下发角色头后打开）。
- **三层强制点**：
  1. 网关第一跳 `app/observability.py`：未知角色 / 缺租户身份直接 403，权限按角色基线收敛；
     只对 `/api` 与 `/static` 生效（`/internal/**` 服务间调用不受角色治理影响），`OPTIONS` 预检让路给 CORS；
  2. 路由级 `require_route_permission`：`/api/agent/{flags,costs,model-routing,governance,tenants,ltr,knowledge}` 在进业务前按角色权限拦下；知识发布 / 取消 / 回滚按 `knowledge:publish` 档位、素材重建索引按 `materials:write`（与职责映射一致）；
  3. 调用点：工具判权用**收敛后**的 `Principal.permissions`（不回读原始请求头，否则能借 `/api/agent/tools/*` 绕过角色）；
     `/api/agent/registry` 需受信身份 + 只读权限；知识快照与检索末条共用 `filter_visible`
     （未知密级按不可读处理，不再 500；拒绝条数写审计）。
- **跨租户只放行元数据**：`GET /api/agent/tenants`（需 `agent:admin`）只回命名空间、版本数、审计条数，
  永不回知识正文；指名租户用 `X-Target-Tenant` 或 `?target=`，`target=all` 表示全平台地毯。
- **职责与权限双向闭合**：`CAPABILITY_PERMISSIONS` 每条职责都有权限支撑、角色基线每条权限都有职责解释，
  其中"平台配置只读"（`platform.status.read` → `agent:audit`）让租户管理员也能只读开关 / 路由 / 排序模型现状 —— 这是显式披露的口径，若业务要求隔离需拆出独立权限。
- **Java 侧配套**：`AiGatewayIdentity` 下发 `X-User-Role`（ADMIN→platform_admin、TENANT_ADMIN→tenant_admin、
  其余→member），`GatewayProxyController` 把 `x-user-role` / `x-target-tenant` 加入客户端头剥离白名单。
- **已知设计边界**：政策域（`public:policy`）是**全局公共法规库**，不参与租户隔离（租户私有内容必须走素材域 / 知识域）；
  路由级权限要求意味着所有既有业务 API 都依赖网关注入受信身份头（见 `evals/README.md` 第 7 节的跨仓库契约风险）。
- **验收**：`tests/test_g7_roles.py` 21 例（职责映射一致性、跨租户、伪造身份、越权访问、头走私、CORS 预检、工具判权、收口开关、公共域契约、末条 filter、审计留痕）。

## LTR 学习排序（G9）

**生产姿势是 RRF 保底、LTR 渐进替换，不一步到位。** 三档模式由 `LTR_MODE` 控制：

| 模式 | 行为 | 用途 |
|---|---|---|
| `off`（默认） | 完全走 RRF 顺序 | 保底口径；模型缺失 / 异常也自动退回这里 |
| `shadow` | 算 LTR 分并记录影子排序差异，**线上顺序仍是 RRF** | 上线前的影子观察 |
| `blend` | `(1-alpha)·RRF + alpha·LTR` 在候选池内重排 | 小步提高 `LTR_BLEND_ALPHA` 逐步替换 RRF |

- **特征只有三个**（对应文档口径）：向量相似度（Dense cosine，负值记 0）、
  图路径长度（`1/(1+hops)`，图未命中记 0，不把"没有图信号"当成最优路径）、
  文本匹配分（BM25，**本批候选内**按最大值归一化——跨查询绝对值不可比）。
- **没有标注数据就不训练**：样本数 < `LTR_MIN_SAMPLES`、标签单一、特征含 NaN / Inf → 直接拒绝；
  交叉验证默认按 **query / case 分组**切折（`foldUnit=group`），避免"同一查询的候选跨折"把 AUC 考虚高；
  **折外 AUC** 是唯一上线依据。
- **训练与指标由服务端产生**：`POST /api/agent/ltr/train`（需 `agent:admin`）接收标注样本、由服务端算权重与指标并落 `shadow`；
  既不接受调用方自报 `weights` / `cv_auc`（否则门禁会退化成填表），也不允许 `save_model` 直接写 `active`。
- **门禁在代码里**：`POST /api/agent/ltr/models/{version}/activate` 会先跑 `should_promote`，
  不达标返回 409；`force=true` 只允许回滚**曾激活过**的版本（从未上线的模型即使 force 也拒绝），且写进审计。
- **blend 真的会影响最终顺序**：精排词法降级路径与排序键都以 `blend_score` 为基准（缺失时回落 RRF），
  否则"渐进替换 RRF"会被精排整段抹掉；`off` / 模型缺失 / 模型异常（含 NaN）一律退回 RRF 原序并标记 `degraded`。
- **模型可追溯**：权重、样本数、指标、数据集摘要落库 `ranking_model`；同版本重复落库必须同内容（否则 409），
  激活新模型自动退役旧模型，`ltr.train` / `ltr.activate` / `ltr.retire` 写治理审计，`GET /api/agent/ltr` 看现状与历史版本。
- **验收**：`evals/ltr_compare.py`（`rrf` / `ltr_shadow` / `ltr_blend` 三口径，按 case 5 折做样本外评测，
  `--require-gain` 为门禁）。实测示例（合成图谱集 `policy_graph_*`，92 候选 / 8 正例）：
  折外 AUC（按 case 分组折）`0.784` ≥ 0.6、门禁通过，但 `recall_gain 0.0 / mrr_gain -0.02 / ndcg_gain -0.02`
  → `promoted=false`，即**当前合成集上没有增益，保持 RRF 保底**；真实上线必须在 G2 回流人工标注集上复测出样本外增益。
- **测试**：`tests/test_g9_ltr.py` 13 例（特征口径、训练与 NaN 拒绝、三档模式与退化、生命周期与同版本篡改、端点权限、精排基准、检索集成）。

```env
TENANT_ROLE_GOVERNANCE_ENABLED=true
TENANT_ROLE_REQUIRED=false
TENANT_ROLE_EMPTY_PERMISSIONS_FALLBACK=false
LTR_MODE=off
LTR_BLEND_ALPHA=0.3
LTR_MIN_SAMPLES=50
LTR_MIN_AUC=0.6
```

## 技术栈

- Python：FastAPI、SQLAlchemy 2.0、LangGraph、Alembic、networkx
- LLM：DeepSeek（OpenAI 兼容，可插拔）
- 数据库：PostgreSQL 16 + pgvector（Docker）
