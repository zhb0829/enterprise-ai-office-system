# Agent G3/G5 交付与验收：租户资源隔离与运行时降级开关

日期：2026-10-25。
依据：`D:\我的知识库\企业AI智能办公助手实现方案\架构对标与补齐计划-基于RAG-GraphRAG多租户知识中台.md`
的 G3、G5 条目（落地节奏第三步：`G3 资源隔离限流 + G5 运行时开关`，完成标志"故障注入与多租户压测通过"）。

本次只做 G3 与 G5，未触碰 G4 模型分层路由、G6 成本核算、G7 三角色治理。
改动跨两个仓库：Python AI 服务（服务侧限流兜底 + 耗时链路容量池 + 运行时开关）
与 Java 网关（第一道租户限流）。两处改动都保持既有降级话术与审计口径，不新增对外契约。

## 1. 验收结论

| 缺口 | 完成标志 | 验收命令 | 本次结果 |
|---|---|---|---|
| G3 | 多租户压测通过 | `python -m evals.tenant_load_test` | `passed=true`，10 项判定全通过 |
| G5 | 故障注入通过 | `python -m evals.fault_injection` | `passed=true`，18 项判定全通过 |

判定不是"看报告颜色"：两个脚本把每个判定项的名称、布尔结果与实测明细写进报告 `checks`，
任一不通过即返回非零退出码（可直接进 CI）。

## 2. G3 租户资源隔离与限流

### 2.1 两层防线 + 一条容量边界

| 层 | 位置 | 手段 | 超限表现 |
|---|---|---|---|
| 网关（第一道） | `admin-server` `TenantRateLimitFilter` | 按认证租户的令牌桶（`eaos.rate-limit.rps/burst`）+ 并发配额（租户 / 全局） | 429 + `Retry-After` |
| AI 服务（第二道） | `app/resource_guard.py` | 同一套限额，按可信身份解析出的 `tenant_id` 分桶 | 429 + `Retry-After` + `X-RateLimit-*` |
| 耗时链路 | `app/services/capacity.py` | LLM / Embedding / Rerank 各自线程池 + 有界队列 | 池满立即失败并走既有降级路径 |

三层职责不同，不能混为一谈：

- 租户限流回答"**谁**占用太多"——保证单租户打满不挤占其他租户；
- 容量池回答"**全局**有多少并发在耗资源"——保证超限快速失败，而不是无限排队把线程拖垮；
- 网关与 AI 服务是**两级**而不是二选一：网关负责对外统一入口，AI 服务的限流在网关漏配、
  内部直连或 worker 绕过时仍是兜底（`evals` 与脚本都是直连 AI 服务）。

### 2.2 关键取舍

1. **租户键只取可信身份**。网关取 JWT 认证出的 `LoginUser.tenantId`；AI 服务取可信身份头
   解析出的 `Principal.tenant_id`。客户端自报的租户头不参与配额计算，否则限流可被伪造请求绕过。
2. **限流在鉴权之后执行**。AI 服务的限流中间件注册在可观测性中间件之前（更内层），
   因此未认证 / 越权请求先被 403 拦掉，不会被伪装成"限流"；网关过滤器用
   `@Order(LOWEST_PRECEDENCE)` 排在 Spring Security 之后，同理。
3. **高频拒绝默认不落库**。`RATE_LIMIT_AUDIT_ENABLED=false`：把每一次拒绝写治理审计表，
   会与被保护的服务抢数据库连接，反而放大故障。日志与 Prometheus 指标始终记录，
   需要留痕时显式打开。
4. **容量池满不等于 5xx，但降级路径随链路而不同**。Embedding 池满 → 检索跳过 Dense 路并标
   `denseDisabled`（**拒绝以哈希向量顶替真实向量**，避免相似度口径失真）；Rerank 池满 →
   确定性词法重排；LLM 池满 → 政策问答用检索兜底，公告生成按文风降级为规则化草稿并把
   "因模型容量不足已降级"写进 `riskFlags`（`LLMCapacityError` 与上游故障 `LLMError` 分开，
   只有前者走这条降级）。三类降级都保留 `degraded` 语义，不静默产出低置信度结果。
   唯一的例外是公告流式端点：SSE 已经开始输出，无法中途换成规则化草稿，池满走既有错误事件通道。
5. **池内任务继承审计上下文**。容量池提交任务时用 `copy_context()`，否则池线程里
   `step()` / `current_run` 会丢失，AgentRun 的模型步骤会静默变空。
6. **未认证请求不进租户配额**。它们会被鉴权层直接拒绝，既不该占用某个租户的额度，
   也不该把 403 掩盖成 429。匿名流量的防刷由网关第一道防线负责（Spring Security 在限流前返回 401）。

### 2.3 可观测

| 指标 | 含义 |
|---|---|
| `eaos_gateway_tenant_throttled_total` / `eaos_gateway_tenant_passed_total` | 网关放行与拒绝计数 |
| `eaos_tenant_throttled_total{tenant,reason}` | 服务侧拒绝计数（`tenant_rate` / `tenant_concurrency` / `global_concurrency`） |
| `eaos_tenant_inflight{tenant}` | 租户在飞请求 |
| `eaos_capacity_rejected_total{pool}` | 容量池快速失败计数 |
| `eaos_capacity_pool_inflight{pool}` | 池内占用（运行 + 排队） |

拒绝响应统一带 `Retry-After`（精确到令牌补满所需秒数）与 `X-RateLimit-*`。

## 3. G5 运行时降级开关

### 3.1 开关清单

实现：`app/agent/runtime_flags.py`；管理端点：`app/agent/flag_routers.py`。

| 开关 | 关闭后的回退路径 | 默认值来源 | 留痕位置 |
|---|---|---|---|
| `kg` | 不走图路，退化为 BM25 + Dense 两路 RRF + 精排 | `KG_ENABLED` | `fusionSources`、`graph.enabled`、`degradationReasons` |
| `semantic_rerank` | 跳过语义精排，改确定性词法重排 | `RERANK_URL` / `RERANK_LOCAL_MODEL` | `retrieval[].reranker.reason=runtime-flag-semantic-rerank-off` |
| `remote_llm` | 不调外部对话 / 抽取模型，走规则化兜底 | `LLM_API_KEY` | `model=offline-policy-retrieval`、`degradationReasons` |
| `remote_embedding` | 检索跳过 Dense 路，不混用哈希向量 | `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` | `denseBackend=disabled-by-flag`、`denseDisabledReason` |
| `factcheck` | 模型核查退化为规则化核查 | 默认开启 | `factCheckReport[].degraded` + `degradeReason`，AgentRun `verification.factcheck` |

### 3.2 两条纪律

1. **环境变量仍是默认值口径，运行时开关只做覆盖**。`PUT .../flags/{name}` 传 `enabled=null`
   即恢复环境变量默认，避免出现两套互相打架的配置；`describe()` 明确给出
   `configDefault` 与 `source=configuration|runtime-override`。
2. **"配置里本来就没启用"不算运行时降级**。`disabled()` 只在"存在运行时覆盖且值为假"时为真；
   否则未配置精排 / 未配置向量的离线环境会被误报成故障注入结果，也会把离线评测基线一起改掉
   （`fallback_rate` 口径）。

### 3.3 管理端点权限与边界

- `GET /api/agent/flags` 需 `agent:audit`（运维可见当前降级状态）；
- `PUT /api/agent/flags/{name}` 需 `agent:admin`（平台管理员），每次切换写治理审计 `flag.update`，
  含 `enabled` / `previous` / `source` / `reason`；
- **开关状态在进程内**，当前部署为单 worker。多副本部署需逐副本下发或引入外部配置中心，
  本模块不假装是分布式配置中心——这一点写进了端点返回与文档。

## 4. 验收怎么跑、怎么判

### 4.1 多租户隔离压测（G3）

```powershell
.\.venv\Scripts\python.exe -m evals.tenant_load_test `
    --output evals/reports/tenant-isolation-2026-10-25.json
```

脚本自建单 worker 服务（临时 SQLite + 合成语料）并起本地假模型服务（可动态调延迟），两阶段：

| 阶段 | 自变量 | 判定 |
|---|---|---|
| `rate_limit_isolation` | `noisy` 租户 rps=2 / burst=4，`quiet` 用全局默认 rps=100 | `noisy` 429 ≥ 6 且带 `Retry-After`；`quiet` 零 429、零错误、P95 ≤ 2s |
| `capacity_fast_fail` | Embedding 池 2+2、Rerank 池 1+1，假模型 600ms | 两租户各 20 并发全部 200（无 5xx）；容量快速失败计数 > 0；出现 `denseDisabled`；最大耗时 ≤ 5s |

第二条判定针对的正是"无限排队"：若无界排队，40 个请求按 2 并发 × 0.6s 需要约 12s，
实测最大耗时被压在数秒内，说明超限确实快速失败了。

### 4.2 故障注入（G5）

```powershell
.\.venv\Scripts\python.exe -m evals.fault_injection `
    --output evals/reports/fault-injection-2026-10-25.json
```

服务全程不重启：报告里比对 `/benchmark/identity` 的进程 token，前后一致才通过。
共 18 项判定，覆盖基线（模型可用时**不得**声称降级）、五个开关的关闭与回切、
以及"远端精排真实返回 500"这条非开关故障路径。

## 5. 回归与门禁

| 项 | 命令 | 本次结果 |
|---|---|---|
| 单元测试 | `python -m pytest -q` | 219 passed, 1 skipped |
| 离线评测门禁 | `python -m evals.run --mode offline` + `python -m evals.gate` | `passed=true`，指标与基线一致 |
| 图谱增益门禁 | `python -m evals.graph_gain --require-gain` | `promoted=true`（Recall 1.00 / MRR 0.425） |
| HTTP 容量压测 | `python -m evals.load_test --concurrency 1 50` | 1 与 50 并发零错误 |
| 网关限流单测 | `mvn -o test -Dtest=TenantRateLimitFilterTest` | 6/6 通过 |

顺带修掉一个既有缺陷：`evals/load_test.py` 的压测客户端没有携带 `X-User-Permissions`，
在网关权限收紧后会**全部 403**（报告 `passed=false`）。现已补齐权限头，并在该脚本中
显式关闭租户限流（容量测试测的是系统极限，不是限流行为），报告新增
`tenant_rate_limit=disabled-for-capacity-test` 字段避免误读。

新增测试：`tests/test_g3_limits.py`（令牌桶 / 并发配额 / 配额覆盖 / 容量池 / 中间件 429）、
`tests/test_g5_flags.py`（开关状态机 / 端点权限 / 五种降级路径）。

## 6. 边界与未覆盖

- **预生产完整链路未验**：两个验收脚本都只覆盖 Python AI 服务直连，**不含** Java 网关、
  JWT、生产 PostgreSQL、外部网络与真实模型配额。G3 文档原本就要求"本项验收必须在预生产环境
  做完整链路"，本次给的是可重复的工程口径与判定依据，不等于最终生产验收。
- **多副本未验**：运行时开关是进程内状态，多副本需逐副本下发；限流器同样是进程内的，
  多副本部署时每副本各有一份配额，若需要全局配额需引入 Redis 等共享计数（当前部署为单 worker）。
- **网关多租户身份未启用**：`AiGatewayIdentity` 仍固定下发 `X-Tenant-Id=default`
  （账户模型尚未多租户化）。网关限流已按 `LoginUser.tenantId` 维度工作，待账户模型落地即可生效，
  不需要再改本类；在此之前不会改变既有数据隔离契约。
- **真实模型配额未验**：容量池的上限是工程保护值，不是模型供应商的真实配额；生产需要按
  实际配额调整 `*_POOL_WORKERS` / `*_POOL_QUEUE`。

## 7. 后续

- G4 模型分层路由：路由决策要落进 AgentRun 审计（G5 的开关与 `runtimeFlags` 已预留同一处留痕位）。
  **已完成**（2026-10-26）：见同目录 `Agent-G4G6-模型分层路由与成本核算.md`，`model_routing`
  已注册进本模块的开关清单。
- G7 三角色治理：`agent:admin` / `agent:audit` 已用于开关管理，可与"平台管理员 / 租户管理员 /
  普通用户"的职责映射复用同一套权限词汇。
- 若部署改为多副本，优先补两件事：开关的统一下发、限流计数的共享存储。