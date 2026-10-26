# Agent G4/G6 交付与验收：模型分层路由与成本核算

日期：2026-10-26。
依据：`D:\我的知识库\企业AI智能办公助手实现方案\架构对标与补齐计划-基于RAG-GraphRAG多租户知识中台.md`
的 G4、G6 条目（落地节奏第四步：`G4 模型分层路由 + G6 成本核算`，完成标志"延迟/成本可见，质量不降"）。

本次只做 G4 与 G6，未触碰 G7 三角色治理、G8 多云编排、G9 LTR 排序。改动全部在 Python AI 服务内：

- 新增 `app/services/model_router.py`（分层路由）、`app/services/cost.py`（成本核算）、
  `app/agent/cost_routers.py`（两个只读运维端点）；
- `agent_run` 表新增 `routing` 列（迁移 `9f7_model_routing`），`usage` 明细扩展为按模型 × 用途分桶；
- `LLMClient` 新增 `purpose` / `routing_text` 参数（既有位置参数与 `model` 显式覆盖语义保持不变）；
- 新增一个运行时开关 `model_routing`（复用 G5 开关中心），不新增任何对外写契约。

## 1. 验收结论

| 缺口 | 完成标志 | 验收命令 | 本次结果 |
|---|---|---|---|
| G4 | 延迟/成本可见，质量不降 | `python -m evals.routing_compare` | `passed=true`，10 项判定全通过；P50 441.5ms → 83.7ms，成本 0.000588 元 → 0.000233 元 |
| G6 | 成本可按租户/功能/模型核算 | `python -m evals.cost_audit` | `passed=true`，11 项判定全通过；已定价金额与"10in/8out × 单价"精确一致 |

判定不是"看报告颜色"：两个脚本把每个判定项的名称、布尔结果与实测明细写进报告 `checks`，
任一不通过即返回非零退出码（可直接进 CI）。

## 2. G4 模型分层路由

### 2.1 三层与判定口径

| 层 | 触发条件 | 模型来源 |
|---|---|---|
| `light` | 复杂度分值 ≤ `LLM_ROUTING_LIGHT_MAX_SCORE`（默认 0） | `LLM_MODEL_TIER_LIGHT` |
| `standard` | 中间区间 | `LLM_MODEL_TIER_STANDARD`（留空则复用 `LLM_MODEL_GENERATION`） |
| `reasoning` | 分值 ≥ `LLM_ROUTING_REASONING_MIN_SCORE`（默认 3） | `LLM_MODEL_TIER_REASONING` |

阈值在配置加载时校验"旗舰下界必须大于轻量上界"，区间重叠直接拒绝启动（否则路由结果不可预期）。

复杂度打分是**可解释启发式**，不是学习模型：不需要训练数据，可回归、可复算（LTR 才需要标注数据，
见 G9）。每条决策都会写明分值与命中的信号：

| 信号 | 权重 | 依据 |
|---|---|---|
| 问题长度 ≥ 40 / ≥ 120 字 | +1 / +2 | 长问句通常带多个约束 |
| 问号数 ≥ 2 | +1 | 一次问了多件事 |
| 比较 / 因果 / 条件词（对比、差异、为什么、冲突、优先级、如果…） | +1 ~ +2（去重后按命中数，上限 2） | 需要跨条款推理 |
| 多跳词（依据、上位、引用、配套…） | +1 | 需要沿引用链遍历 |
| 命中条款 ≥ 6 / ≥ 10 条 | +1 / +2 | 需要跨条款综合 |
| 检索上下文 ≥ 3000 / ≥ 8000 字符 | +1 / +2 | 材料规模大 |
| 用途加成（`draft.generate`） | +1 | 长文生成天生更重 |
| 短问句命中查表词（是什么、哪些、多少…且长度 < 40） | −1 | 单点事实查询 |
| 无任何信号 | 0 | 记为 `no-complexity-signal`：简单结论来自"无加分项"，也要能说清 |

命中词做了去重：`是否冲突` 命中时不再重复计一次 `冲突`，避免同一个语言现象被计两次。

### 2.2 四条纪律（缺任一条即"不路由"，且必须说清为什么）

1. **用途可分层**：只有"任务复杂度随用户输入变化"的生成类用途参与分层。
2. **目标层模型已配置**：轻量层 / 旗舰层未配置时回落标准层，决策里写 `source=tier-model-unset`
   ——不允许"以为路由了，其实一直走同一个模型"。
3. **路由开关打开**：`LLM_ROUTING_ENABLED` 只是默认值，运行时开关 `model_routing` 可热切换。
4. **显式模型优先**：调用方显式传 `model`（抽取 / 核查 / 视觉等专用模型）时路由不覆盖，
   但仍留一条 `explicit-model` 决策用于回溯与成本归集。专用用途（`DESIGNATED_PURPOSES`）
   即使**没传** `model`（专用配置被运维置空）也不会被分层接管，决策写 `source=designated-purpose`
   ——"抽取用哪个模型"是配置事实，不是复杂度决定的。

**默认关闭**：与 G1 图谱同口径——先用 `evals.routing_compare` 跑出"延迟/成本改善且质量不降"
的证据，再显式开启。未配置任何分层模型时开启也是 no-op（行为与"没有路由"完全一致）。

### 2.3 各链路的接入口径

| 用途（purpose） | 链路 | 参与分层 | 说明 |
|---|---|---|---|
| `policy.answer` | 政策问答生成 | 是 | 判定文本取**用户问句**，并带上引用条款数与上下文规模 |
| `policy.interpret` | 条款解读 | 是 | 判定文本取条文 |
| `draft.generate` | 公告/新闻稿起草（含流式、修改建议） | 是 | 判定文本取事件描述，避免超长模板把分数带偏 |
| `draft.revise` | 多轮修改 | 是 | 判定文本取修改指令 |
| `draft.polish` | 润色 | 否 | 文本处理任务，走标准层，只按用途记成本 |
| `extraction` | 事件要素抽取、会议要点抽取 | 否 | 专用 `LLM_MODEL_EXTRACTION` |
| `factcheck` | 事实核查 / 交叉验证 | 否 | 专用 `LLM_MODEL_FACTCHECK` |
| `kg.extract` / `kg.community` | 图谱抽取与社区摘要 | 否 | `KG_MODEL` 或 `LLM_MODEL_EXTRACTION` |
| `opinion.*` / `intelligence.analysis` | 舆情分析、情报摘要 | 否 | 任务形态固定，用配置模型 |
| `meeting.report` / `meeting.card` | 会议纪要 / 卡片 | 否 | 专用 `MEETING_REPORT_MODEL` 等 |
| `qualification.draft` | 资质材料初稿 | 否 | 暂不纳入（后续按需加） |
| `embedding` | 向量化 | 否 | 专用 `EMBEDDING_MODEL`，用量进成本口径 |
| `rerank.policy` | 远端精排 | 否 | 不回 token usage：只记调用次数，成本记 null |

"判定文本"与"提示词正文"是两件事：路由只看用户侧的意图文本，否则检索到的条款越多、
模板越长，分数越高，提问本身的复杂度差异会被上下文长度淹没。

### 2.4 审计留痕

| 位置 | 内容 |
|---|---|
| `agent_run.steps[]` 的 `model.route` 步骤 | purpose / complexity / score / signals / tier / model / source / reason |
| `agent_run.routing`（新列） | `enabled`、`routedCalls`、`tiers` 分布、`models` 分布、`sources` 分布、最近 50 条决策明细 |
| 政策问答 / 解读响应体 `routing` 字段 | 同一条决策（tier / model / score / signals / reason），便于前端与排查直接对照 |
| `GET /api/agent/model-routing` | 开关现状、阈值、三层模型是否已配置（需 `agent:audit`） |

决策明细上限 50 条：一次运行里同一用途可能被调用上千次（例如批量审校），
审计不允许被无限撑大。

## 3. G6 成本核算

### 3.1 三条纪律

1. **单价只来自配置**：`LLM_PRICE_TABLE`（JSON，元 / 百万 token，仅 CNY）是唯一价格来源。
   代码里不内置任何单价——内置单价会随供应商调价静默过期，比没有单价更危险。
2. **未知即 null**：模型未收录、或供应商没返回 usage，成本记 `null`，不用 0 顶替、不估算。
3. **部分已知必须自曝缺口**：`cost` 只累加已定价部分，同时给出 `cost_complete` /
   `unpriced_models` / `unpriced_reasons`；调用方不得把 `cost` 当完整账单。

价格表条目在解析期做校验，不合规条目**被拒绝并记录原因**而不是被猜一个值：

| 被拒绝的情况 | 原因码 |
|---|---|
| 不是 JSON 对象 / 条目不是对象 | `error` / `entry-not-object` |
| 缺 input 或 output 单价 | `missing-input-price` / `missing-output-price`（缺 output ≠ 输出免费） |
| 负数或非数字 | `invalid-input-price` / `invalid-output-price` |
| 非 CNY 币种 | `currency-not-supported:USD`（混币种相加会得出"看似精确但错误"的总额） |
| 非 per-million-token 单位 | `unit-not-supported:per_1k_tokens` |

与"不估算"同源的一条纪律：**只在输入与输出 token 都有值时计价**。供应商只回
`total_tokens`、或某一侧缺失时，按缺失侧 = 0 计价会静默低报，因此记 `cost=null` +
`token-usage-missing`。

- `usage_complete`：每次调用都拿回了 usage；
- `tokens_complete`：每次调用的**输入与输出两侧都有值**（更严，`null` 表示 token 也不完整）。

token 未知同样**不可逆**：某模型一旦出现过"拿不到"，该模型的 token 合计此后报 `null`，
后续已知调用不会把它"复原"成看起来完整的数字（已知部分照常计价）。

### 3.2 记账结构与落库

明细随 AgentRun **一次性**落库（`agent_run.usage`），不新建"每次调用一行"的流水表——
那会把写放大压到被保护的业务库上（与 G3"高频拒绝默认不落库"同一条纪律）。

```json
{
  "input_tokens": 10, "output_tokens": 8,
  "cost": 0.000084, "cost_complete": true, "currency": "CNY", "price_unit": "per_million_tokens",
  "usage_complete": true, "tokens_complete": true, "unpriced_models": [],
  "by_model": {
    "deepseek-chat": {
      "input_tokens": 10, "output_tokens": 8, "calls": 1,
      "cost": 0.000084, "cost_complete": true, "tokens_complete": true, "unpriced_reasons": [],
      "purposes": {"policy.answer": {"input_tokens": 10, "output_tokens": 8, "calls": 1,
                                     "cost": 0.000084, "cost_complete": true}}
    }
  }
}
```

- `by_model` 是唯一权威明细，顶层字段是它的汇总视图（历史消费方读 `input_tokens` / `cost` 不受影响）。
- token 未知不可逆：某模型只要有一次调用拿不到 usage，该节点的 token 此后记 `null`，
  不用 0 冒充"没有消耗"。
- 向量化（embedding）用量走同一条链路；远端精排不回 usage，只记调用次数 + `token-usage-missing`。

### 3.3 查询、权限与聚合口径

```powershell
# 当前租户最近 7 天，按模型/用途/功能/租户分组（需 agent:audit）
curl.exe -s -H "X-Internal-Token: $env:AI_INTERNAL_TOKEN" -H "X-User-Id: ops" `
  -H "X-Tenant-Id: default" -H "X-User-Permissions: agent:audit" `
  "http://localhost:8000/api/agent/costs?days=7&groupBy=model,purpose,intent,tenant"
# 全平台口径（需 agent:admin）
curl.exe -s -H "..." -H "X-User-Permissions: agent:audit,agent:admin" `
  "http://localhost:8000/api/agent/costs?tenant=all-tenants&groupBy=tenant"
```

| 维度 | 含义 | 举例 |
|---|---|---|
| `tenant` | 租户 | `default` / `tenant-a` |
| `intent` | 业务功能（`agent_run.intent`） | `policy_qa` / `policy_interpretation` |
| `purpose` | 模型调用用途（usage 明细的 key） | `policy.answer` / `factcheck` |
| `model` | 模型名 | `deepseek-chat` |

`intent` 与 `purpose` 是两层口径，必须分别给出：一次"政策问答"（intent）里可能既有生成
（`policy.answer`）又有核查（`factcheck`），混成一个维度会让"按功能核算"不可解释。

其他口径：`costKnownOnly=true`（金额只含已定价部分）、`unpricedModels` / `unpricedReasons`
列出缺口、`zeroUsageRuns` 单独统计"没有产生模型用量的运行"（离线/规则化链路不算成本缺口，
否则 `costComplete` 会永远是 false）、`attributedRuns` 之外还有 `unattributedRuns` 表示历史行
只有总量、无法归属到模型、`truncated` + `truncateNote` 提示行数上限截断。

### 3.4 可观测

| 指标 | 含义 |
|---|---|
| `eaos_model_tokens_total{model,purpose,kind}` | input / output token 计数 |
| `eaos_model_cost_cny_total{model,purpose}` | 仅已定价模型的成本累加（元） |
| `eaos_model_unpriced_calls_total{model,reason}` | 成本未知的调用计数（`model-not-priced` / `token-usage-missing`） |

## 4. 验收怎么跑、怎么判

### 4.1 分层前后对比（G4）

```powershell
.\.venv\Scripts\python.exe -m evals.routing_compare `
    --output evals/reports/routing-compare-2026-10-26.json
```

服务自建（临时 SQLite + 合成语料），模型指向本地假服务：**轻量层 30ms、旗舰层 400ms，
两个模型返回完全相同的内容与 usage**。同一组问题（5 简单 + 2 复杂）跑两遍，
唯一变量是运行时开关 `model_routing`，进程不重启。

| 判定 | 本次实测 |
|---|---|
| `baseline_routing_disabled` | 基线 7 次调用全部为旗舰模型，决策 `source=routing-disabled` |
| `simple_questions_use_light_tier` | 5 个简单问题全部 `tier=light` + 轻量模型 |
| `complex_questions_use_flagship` | 2 个复杂问题全部 `tier=reasoning` + 旗舰模型 |
| `decisions_are_auditable` | 每条决策带 tier / score / signals / reason |
| `decisions_persisted_in_agent_run` | 7 条运行审计全部落库 `routing.decisions` |
| `retrieval_unchanged` / `retrieval_has_hits` | 两口径命中条款集合完全一致，且不是零命中 |
| `quality_not_regressed` | 答案非空率 1.0、引用合规率 1.0、降级率 0.0（前后一致）；报告把它标 `informative=false`——两个假模型内容相同，该判定只能证明"链路未被路由破坏"，不能当质量门禁读 |
| `latency_improved` | P50 441.5ms → 83.7ms；P95 2083ms → 460ms（阈值：P50 至少改善 20%） |
| `cost_reduced` | 0.000588 元 → 0.000233 元（按 G6 口径的已定价部分） |

### 4.2 成本核算口径审计（G6）

```powershell
.\.venv\Scripts\python.exe -m evals.cost_audit `
    --output evals/reports/cost-audit-2026-10-26.json
```

两个租户、两种功能（政策问答 / 条款解读）造流量；价格表**只收录旗舰模型**，轻量模型故意不收录。
旗舰模型每次调用固定 10 in / 8 out token，金额可精确复算。

| 判定 | 本次实测 |
|---|---|
| `cost_query_requires_audit` | `policy:read` → 403；`agent:admin` 全平台 → 200 |
| `cost_grouped_by_tenant` | `tenant-a` / `tenant-b` |
| `cost_grouped_by_intent` | `policy_qa` / `policy_interpretation` |
| `cost_grouped_by_purpose` | `policy.answer` / `policy.interpret` |
| `cost_grouped_by_model` | 旗舰 / 轻量两个模型 |
| `intent_filter_narrows_scope` | `intent=policy_interpretation` → 2 次运行、仅轻量模型 |
| `tokens_match_provider_usage` | 旗舰 2 次调用 → 20 in / 16 out（与供应商 usage 一致） |
| `priced_cost_matches_tokens` | 0.000168 元 = 2 × (10/1e6×2 + 8/1e6×8) |
| `unpriced_model_is_null_not_zero` | 轻量 4 次调用 token 照记，`cost=null`、`costComplete=false` |
| `partial_total_exposes_gap` | 总额只含已知部分 0.000168 元 + `unpricedModels=[轻量模型]` |
| `usage_persisted_with_model_and_purpose` | 6 条运行全部含"模型 × 用途"明细 |

## 5. 回归与门禁

| 项 | 命令 | 本次结果 |
|---|---|---|
| 单元测试 | `python -m pytest -q` | 259 passed, 1 skipped |
| 离线评测 | `python -m evals.run --mode offline` | 38/38 通过；Recall@K 1.00 / MRR 0.933 / nDCG 0.951 |
| 指标劣化门禁 | `python -m evals.gate --baseline evals/baselines/offline.json` | `passed=true` |
| 图谱增益门禁 | `python -m evals.graph_gain --require-gain` | `promoted=true`（Recall 1.00 / MRR 0.425） |
| G4 验收 | `python -m evals.routing_compare` | `passed=true`，10/10 |
| G6 验收 | `python -m evals.cost_audit` | `passed=true`，11/11 |

新增测试：`tests/test_g4_routing.py`（打分与阈值 / 层选择 / 回落与不路由原因 / 显式模型不被覆盖 /
运行时开关覆盖 / 端到端响应与审计落库 / 决策明细上限 / 运维端点权限）、
`tests/test_g6_cost.py`（价格表校验与拒绝 / 未知成本记 null / 部分定价自曝缺口 / 四维聚合 /
历史行未归属 / 零用量不算缺口 / 端点权限与窗口上限 / 端到端 usage 落库）。

顺带修掉一处既有测试替身与新调用契约不符：`tests/test_materials_generation_export.py`
的假 `Llm.chat` 签名缺 `purpose`（现在会显式断言修订链路带 `purpose="draft.revise"`）。

## 6. 边界与未覆盖

- **合成假模型不能证明真实质量**：路由对比脚本的两个模型返回相同内容，它证明的是
  "路由工程行为正确、链路未被破坏、延迟与账目口径正确"；真实质量必须用真实模型 + 真实语料
  在预生产复测（`--mode live` 口径），本报告不作为质量验收结论。
- **价格表不是账单**：`LLM_PRICE_TABLE` 是配置口径；真实结算可能与配置不同步，
  需要与供应商账单定期核对；本项目不内置单价，也不为未知模型估算价格。
- **只支持 CNY / per-million-token**：其他币种与单位在解析期被拒绝（混币种相加会得出错误总额）。
- **价格表改动静默生效在下次重建缓存**：`cost.reload_price_table()` 供程序内调用，
  当前没有热更新端点；生产改价需要重启进程（或后续补一个 `agent:admin` 端点）。
- **无 AgentRun 的批处理不进租户账目**：例如 `POST /api/materials/reindex` 的向量化、
  Celery 后台采集，只有 Prometheus 指标与日志，没有租户维度的账目。这是已知缺口，
  补法是引入"批次级用量记录"（同样要避免每次调用落库）。
- **视觉 / ASR 不进成本账目**：`app/meeting/parsers.py` 的图片识别与语音转写走独立第三方客户端
  （`MEETING_VISION_*` / `MEETING_ASR_*`），既不参与分层，也不记 token 与成本。
- **流式中断按"用量未知"入账**：SSE 中途断开时拿不到 usage，只记一次调用（成本 null，
  `token-usage-missing`），不假装这次调用没发生。
- **历史行无法按模型归属**：老数据只有总量（`unattributedRuns`），金额按 null 记账，
  不会被分摊到任何模型。
- **预生产完整链路未验**：两个验收脚本都只覆盖 Python AI 服务直连，不含 Java 网关、JWT、
  生产 PostgreSQL、外部网络与真实模型配额。
- **开关与价格表缓存都在进程内**：多副本部署需逐副本下发（与 G5 相同边界）。
- **路由默认关闭**：本次交付的是"能力 + 证据"，是否开启（以及轻量/旗舰模型选型）
  由业务按 `evals/routing_compare` 的报告决策。

## 7. 后续

- **G7 三角色治理**：`agent:audit`（看账）/ `agent:admin`（跨租户、全平台）已用于成本与路由端点，
  可与"平台管理员 / 租户管理员 / 普通用户"的职责映射复用同一套权限词汇。
- **G9 LTR**：当前打分是可解释启发式；等 G2 的线上回流积累到标注规模后，
  可把"模型选择"从规则升级为学习排序（RRF/LTR 的演进口径同理：规则保底、模型渐进替换）。
- **租户成本预算**：账目已经可按租户统计，下一步可加"预算上限 + 超限告警/降级"
  （参考 `OPINION_ANALYSIS_BUDGET_PER_JOB` 的配额思路），把成本从"可见"推进到"可控"。
- **批处理账目**：把 reindex / Celery 链路的用量按批次汇总落一条记录，补齐第 6 节的第一处缺口。