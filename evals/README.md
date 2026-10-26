# Agent 评测与容量验证（P0 回归 + G2 四层口径 + G1 图谱增益 + G3 隔离压测 + G5 故障注入 + G4 路由对比 + G6 成本审计 + G7 治理验收 + G9 LTR 对比）

## 1. Golden Dataset

`synthetic-p0-v1` 为人工构造的工程回归集，不是政府政策准确率验收集：

- `policy_corpus.json`：可控政策条款，包括旧版本、未来生效、过期和未来发布。
- `policy_qa.json`：20 个问题，包含标准条款、答案片段、地区和历史日期过滤、拒答。
- `announcements.json`：10 个断言与事实来源，用于防止数字拼凑和无证据放行。
- `meetings.json`：8 个会议文本，检查卡片类型、责任人、时间和原文位置。

```powershell
.venv\Scripts\python.exe -m evals.run --mode offline --output evals/reports/offline.json
.venv\Scripts\python.exe -m pytest tests/test_p0_agents.py -q
```

报告包含 Recall@K、MRR、nDCG 和逐用例结果；任一用例失败时返回非零退出码。
GitHub Actions 会执行离线门禁并保留报告。测试使用独立 SQLite，不更新业务库。

离线运行强制关闭付费模型：Dense 使用原有 hash 向量，Rerank 使用词法降级。
`--mode offline` 会同时覆盖进程内 `settings` 的模型配置（不仅是环境变量），
保证库内调用（例如 pytest 直接调用 `evals.run.evaluate`）也不会误调付费模型。
这只能证明工程行为可回归，不能证明真实语义检索或公告生成质量。
`--mode live` 要求 LLM、Dense 和语义 Reranker 配置齐全；需单独审批调用预算。
真实上线前应补充有来源许可证的实际政策、人工双人标注、困难负例、Prompt 注入、
跨租户访问、公告完整工作流与人工抽检。合成样本不得替代真实质量验收。

## 2. 四层评测口径（G2）

一次运行同时产出四层指标，报告见 `report["layers"]`：

| 层 | 指标 | 判定依据 | 诚实边界 |
|---|---|---|---|
| 检索层 | `recall_at_k` / `mrr` / `ndcg_at_k` | 人工标注的期望条款 | 沿用 `evals/metrics.py`，与旧报告口径一致 |
| 生成层 | `answer_accuracy` / `answer_completeness` | 人工标注的 `answerContains` 字面命中 | 字面核对，不是语义质量评分 |
| 引用层 | `citation_precision` / `citation_traceability` / `refusal_rate` | 答案中的 `[引用N]` 是否落在真实条款内、条款是否带出处与正文 | 拒答与无条款记 null，不记 0；离线答案由检索兜底产出，该层**恒真**（`application=structural-regression-only`），只证明引用结构未被破坏 |
| 体验层 | `latency_p50_ms` / `latency_p95_ms` / `fallback_rate` | 逐用例墙钟延迟；`degraded` 标记来自 `answer_policy` | 仅覆盖政策问答；延迟不代表并发容量 |

各层同时输出 `samples`（每个指标的可用样本数）：`1.0` 与"只有 1 条样本"必须能区分，
缺样本一律为 `null`，不补零、不估算。

生成层与引用层自曝口径：离线写 `source=lexical-fallback` / `fallback-answer`、
`application=engineering-regression-only` / `structural-regression-only`，不得解释为真实
生成或引用质量；`--mode live` 才写 `source=llm`、`application=quality-acceptance`。

报告带两个数据集字段：`dataset_digest`（语料与用例的 sha256，防等量替换）与
`dataset_validation`（回流集标注校验结果）。

```powershell
# 合成回归集（CI 口径）
.venv\Scripts\python.exe -m evals.run --mode offline --output evals/reports/latest.json
# 真实模型 + 真实语料回流集
.venv\Scripts\python.exe -m evals.run --mode live --dataset reflow --output evals/reports/reflow.json
```

### 引用层线上汇总

离线引用层是"当次运行自算"，线上口径从已落库审计还原：读取
`agent_run.verification_result`（`passed` / `citation_ids` / `has_evidence` / `refused`）
与 `agent_run.final_answer`（`clauses` / `riskFlags` / `degraded`）。

```powershell
.venv\Scripts\python.exe -m evals.citation_audit --tenant default --since-days 7 `
    --output evals/reports/citation-online.json
# 也可附加到四层报告（需可访问业务库，CI 不使用）
.venv\Scripts\python.exe -m evals.run --mode offline --online-citation --output evals/reports/with-online.json
```

指标：`verification_pass_rate`、`citation_alignment_rate`（核验的 citation_ids 与实际返回
条款是否一致）、`evidence_rate`、`refusal_rate`、`degraded_rate`、`failed_run_rate`、
`citation_traceability`、延迟分位。没有样本时全部为 `null`，不得解读为质量已通过。

## 3. 指标劣化门禁

`evals.gate` 对照基线阻断劣化，CI 已接入（`.github/workflows/agent-evals.yml`）：

```powershell
.venv\Scripts\python.exe -m evals.run --mode offline --output evals/reports/ci.json
.venv\Scripts\python.exe -m evals.gate --report evals/reports/ci.json --baseline evals/baselines/offline.json
# 人工确认无误后刷新基线（需提交基线文件）；指标下调会被拒绝
.venv\Scripts\python.exe -m evals.gate --report evals/reports/ci.json --update-baseline `
    --approver 张三 --reason "切片策略 v3 上线，已复核全部用例"
```

门禁规则：

- 数据集摘要 `dataset_digest`、来源、模式与用例数必须与基线一致：等量替换用例同样被阻断，
  只防新增/删除是不够的。
- 通过率必须为 1。
- 单调门禁：`recall_at_k`、`mrr`、`ndcg_at_k`、`answer_accuracy`、`answer_completeness`、
  `citation_precision`、`citation_traceability` 不得下降；`fallback_rate` 不得上升。
- 基线有值而本次缺失（`null`）视为劣化：不允许"清空标注让指标消失"绕过门禁。
- 只报告不做方向门禁：`refusal_rate`（合规场景拒答不算劣化）、延迟（受机器与并发影响）。
- 基线或报告缺失直接失败，不静默放行。
- `--update-baseline` 拒绝任何指标下调或数据集变化，必须显式 `--force` 并填写
  `--approver` / `--reason`，痕迹写入基线 `note`；通过率不是 1 时拒绝刷新。

改动切片策略、嵌入模型或精排权重后，先跑全量回归再提 PR；基线只能由人工显式刷新。

## 4. 线上回流闭环

流程：线上点踩 → badcase 收集 → 人工标注 → 回流测试集。合成样本不得替代真实语料验收。

### 4.1 反馈落库

`POST /api/policy/feedback`（需 `policy:read`；只能反馈本租户记录，非本人记录以及无属主的
服务间记录均需 `agent:audit`）：

```json
{"qaLogId": 123, "rating": "dislike", "resolved": false, "reason": "引用条款不适用"}
```

`rating` 取值 `like` / `dislike` / `none`（`none` 撤销反馈）；`resolved` 未反馈为 `null`，
表示"未知"，不写 `false` 冒充"未解决"。落库字段：`qa_log.feedback`、`resolved`、
`feedback_reason`、`feedback_user_id`、`feedback_at`，并写治理审计 `policy.feedback`。

### 4.2 badcase 导出

```powershell
.venv\Scripts\python.exe -m evals.badcase --since-days 30 `
    --output evals/reports/badcases-2026-10-25.jsonl
```

来源与标签：`dislike`、`unresolved`（反馈类）；`run_failed`、`refused`、`no_citation`、
`degraded`（审计类）。同一 `runId` 会合并为一条。问答正文与引用正文默认按 PII/密钥规则
脱敏（`--no-mask` 仅限受控环境内部排查）；`tenantId` / `userId` / `runId` / `traceId`
保留原值用于定位，因此导出物本身仍是受控数据，不得进入公开报告。
`--tenant` 默认 `all-tenants`，输出中会显式标注实际范围。

### 4.3 回流测试集

```powershell
# 生成待标注集（可直接读业务库，或复用上一步的 badcase JSONL）
.venv\Scripts\python.exe -m evals.reflow draft --from-db --output evals/datasets/reflow/pending-2026-10-25.json
# 人工标注（建议双人复核，复核人写入 reviewedBy）：
#   labeled / labeledBy / labeledAt + expected|answerContains|refusal
#   需要时效或地区过滤时同时回填 asOf / region / policyName 等上下文
.venv\Scripts\python.exe -m evals.reflow validate evals/datasets/reflow/pending-2026-10-25.json
.venv\Scripts\python.exe -m evals.reflow promote evals/datasets/reflow/pending-2026-10-25.json `
    --output evals/datasets/reflow/real-2026-10-25.json
.venv\Scripts\python.exe -m evals.run --dataset reflow --output evals/reports/reflow.json
```

`validate` 除了要求标注字段齐全，还会试切语料确认 `expected` 的 `[key, articleNo]`
真的能被检索命中，避免"校验通过但评测必然失败"。

评测路径本身也会强制校验：`--dataset reflow` 会重新执行同一套 `validate`，并要求
`synthetic=false`、`state=labeled`；校验不通过直接抛错，缺少 `real-*.json` 时也直接失败，
不会退回合成集顶替。校验结果与数据集摘要写入报告 `dataset_validation` / `dataset_digest`。

## 5. 关系推理与图谱增益（G1）

图谱能否上线由增益决定，不由架构图好不好看决定。

```powershell
# 离线：合成关系推理语料，强制关闭付费模型（构图走规则化通道）
.\.venv\Scripts\python.exe -m evals.graph_gain --output evals/reports/graph-gain.json
# 上线门禁口径：无增益返回非零退出码
.\.venv\Scripts\python.exe -m evals.graph_gain --require-gain
```

三个受控口径，唯一变量是 RRF 的融合来源：

| 口径 | 融合来源 | 用途 |
|---|---|---|
| `dense_only` | Dense | “纯向量”基线 |
| `lexical_dense` | BM25 + Dense | 现有主链路参照 |
| `lexical_dense_graph` | BM25 + Dense + 图谱遍历 | 待验证的“向量 + 图” |

判定与边界：

- `promoted` 只在 `lexical_dense_graph` 相对 `dense_only` 取得 Recall@K 或 MRR 正向增益时为真；
  持平即 `false`。报告同时给出相对现有主链路的增益（可能为 0，如实记录）。
- 语料 `datasets/policy_graph_corpus.json`（6 份合成文件，含“依据《条例》制定”的引用链），
  用例 `datasets/policy_graph_qa.json`（8 个关系型问句：问“上位依据”，答案条款与问题词面基本不重叠）。
- 合成集只能证明工程行为与方向，不能证明真实语义检索质量；上线前应在真实语料回流集上以
  `--mode live` 复测（需模型预算审批），并通过 `KG_ENABLED=true` 显式开启。
- 最近一次离线结果（2026-10-25，合成集）：纯向量 Recall@K 0.00 / MRR 0.000 →
  向量+图 Recall@K 1.00 / MRR 0.425；相对现有主链路 Recall 持平、MRR +0.017。

## 6. HTTP 压测

```powershell
.venv\Scripts\python.exe -m evals.load_test
.venv\Scripts\python.exe -m evals.load_test --concurrency 500 --requests 500 --output evals/reports/load-500.json
```

脚本启动自己的 Uvicorn 单进程，使用临时 SQLite 和合成政策，自动清理自己的进程。
1、50、500 并发分别测试政策问答和公告生成。请求包含同步写库与 Agent 审计，
不是直接调用函数计时。报告包含客户端和服务端实际 in-flight、P50/P95/P99、
吞吐、HTTP 错误率、业务响应完整性，以及 2 秒/30 秒阈值。

压测客户端显式携带 `X-User-Permissions: policy:read,draft:write`：网关生产上按路由下发权限，
直连服务时缺权限一律 403。脚本以 `RATE_LIMIT_ENABLED=false` 启动服务并在报告里记
`tenant_rate_limit=disabled-for-capacity-test` —— 容量测试测的是系统极限，不是限流行为；
多租户隔离另见第 8 节。

当前 `passed` 定义为零错误且 P95 达标，同时单独报告所有请求是否达标；
这是工程测试口径，不擅自把需求的“响应时间”解释成最终验收的 P95。
500 请求同时发起不等于 500 个模型任务同时计算，应查看服务端实际峰值。
单次突发不代表持续稳态容量，更不能证明 99.9% 可用性。

默认不调用付费模型。真实模型压测需显式执行：

```powershell
.venv\Scripts\python.exe -m evals.load_test --mode live --allow-model-cost --concurrency 1 50 500 --requests 500 --output evals/reports/load-live.json
```

即使 live 模式也只覆盖 Python 直连服务，不包含 Java 网关、JWT、生产 PostgreSQL、
外部网络与真实知识库规模。上线验收需在隔离预生产环境对完整链路测试，
约定持续时间、错误预算、并发模型、限流和真实模型配额。
失败报告必须保留，不得据此写“已支持 500 并发”。

## 7. 审计与隐私

运行快照会保留业务文本，访问需用户本人或 `agent:audit`；不要将生产数据导入公开报告。
`evals/reports/` 下的评测报告、badcase 导出与回流草稿同样按此约束处理。
每个请求携带 `runId`，网关注入可信 `X-User-Id`、`X-Tenant-Id`、权限和 `X-Trace-Id`；
`qa_log.run_id` 把问答流水与运行审计关联，后续 trace 定位从这里开始。

两处已知边界，不要误解为已收敛：

- 中间件对缺失 `X-Tenant-Id` 的请求回退为 `default` 租户（`app/observability.py`），
  因此 Java 网关必须强制注入租户头；这是跨仓库契约风险，本仓库无法单方面关闭。
- `qa_log` 与 `agent_run` 不在 ORM 数据隔离（`install_data_isolation`）覆盖范围内，
  反馈接口与 `evals` 运维脚本各自手工做租户过滤，不存在第二道防线。

Token/cost 仅在模型返回 usage 时记录，未知成本为 null，不估算伪造；
按租户 / 业务功能 / 模型用途 / 模型核算的口径与查询端点见第 11 节。
可用以下命令先预览，再经审批执行保留期清理；公告证据和审核记录不在此清理范围：

```powershell
.venv\Scripts\python.exe -m app.agent.maintenance --days 30
.venv\Scripts\python.exe -m app.agent.maintenance --days 30 --apply
```

## 8. 多租户资源隔离压测（G3）

```powershell
.venv\Scripts\python.exe -m evals.tenant_load_test --output evals/reports/tenant-isolation-2026-10-25.json
```

脚本自建单 worker 服务（临时 SQLite + 合成语料），并起一个本地假模型服务（向量/精排，
可动态调延迟），两个受控阶段：

| 阶段 | 设置 | 判定 |
|---|---|---|
| `rate_limit_isolation` | `noisy` 租户配额压到 rps=2 / burst=4；`quiet` 用全局默认 | `noisy` 出现 429 且带 `Retry-After`；`quiet` 零 429、零错误、P95 ≤ 2s |
| `capacity_fast_fail` | Embedding 池 2 并发 + 2 排队、Rerank 池 1 并发 + 1 排队，假模型 600ms 慢响应 | 两租户各 20 并发全部 200（降级而非 5xx），出现容量快速失败计数与 `denseDisabled` 标记，最大耗时 ≤ 5s |

判定逐项写入报告 `checks`，任一不通过返回非零退出码。报告保留每租户状态码分布、
延迟分位、降级计数、容量池前后快照与 `Retry-After` 样本，便于复核判定依据。

两个阶段的语义必须分清：

- 租户限流保证"单租户打满不挤占其他租户"（`noisy` 被拒，`quiet` 不受影响）；
- 容量池是**全局**保护，保证"超限快速失败而不是无限排队"（慢租户不会把线程池占满）。

诚实的边界：只覆盖 Python AI 服务直连，**不含** Java 网关、JWT、生产 PostgreSQL、
外部网络与真实模型配额。`passed` 是工程隔离口径，不等于预生产完整链路验收
（与第 6 节容量口径同样的边界）。

## 9. 故障注入：运行时开关（G5）

```powershell
.venv\Scripts\python.exe -m evals.fault_injection --output evals/reports/fault-injection-2026-10-25.json
```

服务全程不重启，报告里比对进程身份 token 证明"只热切换、不重启"。模型指向本地假服务
（可注入 HTTP 500），逐项注入并断言"服务仍正常返回 + 明确标记降级"：

| 注入 | 期望 |
|---|---|
| 关闭 `remote_llm` | 200 + `degraded` + "运行时开关已关闭外部生成模型"，条款仍在；恢复后立刻回到未降级 |
| 关闭 `remote_embedding` | 200 + `denseBackend=disabled-by-flag`（不混用哈希向量顶替） |
| 关闭 `semantic_rerank` | 200 + `deterministic-lexical` + `runtime-flag-semantic-rerank-off` |
| 关闭 `kg` | 200 + `fusionSources` 不含 graph + 明确降级说明 |
| 关闭 `factcheck` | 200 + `factCheckReport` 每条 `degraded=true` + `degradeReason` |
| 远端精排真实返回 500 | 200 + 词法降级 + `reranker.degraded=true`（上游真的坏了，不是开关） |

基线场景要求"模型可用时不得声称降级"，否则 `degraded` 会被用成一个无意义的常量。
边界同上：只覆盖 Python AI 服务；真实网关与真实模型配额仍需预生产环境验收。

## 10. 模型分层路由对比（G4）

```powershell
.venv\Scripts\python.exe -m evals.routing_compare --output evals/reports/routing-compare-2026-10-26.json
```

服务自建（临时 SQLite + 合成语料），模型指向本地假服务：**轻量层 30ms、旗舰层 400ms，
两个模型返回完全相同的内容与 usage**。同一组问题（5 个简单 + 2 个复杂）跑两遍，
唯一变量是运行时开关 `model_routing`，进程不重启。

| 判定 | 口径 |
|---|---|
| `baseline_routing_disabled` | 基线不得偷偷路由，模型必须等于配置默认值 |
| `simple_questions_use_light_tier` / `complex_questions_use_flagship` | 分层真的按复杂度生效 |
| `decisions_are_auditable` | 每条决策带 tier / score / signals / reason |
| `decisions_persisted_in_agent_run` | `agent_run.routing` 落库，可按 run 回溯 |
| `retrieval_unchanged` / `retrieval_has_hits` | 两口径检索命中条款集合一致，且不是"零命中所以看不出差别" |
| `quality_not_regressed` | 答案非空率、引用合规率不下降，降级率不上升 |
| `latency_improved` | 开启后 P50 至少改善 20% |
| `cost_reduced` | 开启后按 G6 口径的总成本下降 |

最近一次（2026-10-26）：P50 441.5ms → 83.7ms（P95 2083ms → 460ms），
成本 0.000588 元 → 0.000233 元，10 项判定全通过（其中 `quality_not_regressed` 标
`informative=false`，见下）。

**边界**：假模型内容一致，因此本项证明的是"路由工程行为正确、链路未被破坏、延迟与账目口径正确"，
**不能**证明轻量模型在真实语料上的回答质量；真实质量需 `--mode live` 在预生产环境用真实模型复测。

## 11. 成本核算口径审计（G6）

```powershell
.venv\Scripts\python.exe -m evals.cost_audit --output evals/reports/cost-audit-2026-10-26.json
```

两个租户、两种功能（政策问答 / 条款解读）造流量；价格表**只收录旗舰模型**，轻量模型故意不收录，
用来验证"未知成本记 null 而不是 0"。旗舰模型每次调用固定 10 in / 8 out token，金额可精确复算。

| 判定 | 口径 |
|---|---|
| `cost_query_requires_audit` | 查成本需 `agent:audit`；跨租户 / 全平台口径需 `agent:admin` |
| `cost_grouped_by_tenant` / `by_intent` / `by_purpose` / `by_model` | 四个维度都能分组（intent = 业务功能，purpose = 模型用途） |
| `intent_filter_narrows_scope` | 按业务功能过滤时窗口真的收窄 |
| `tokens_match_provider_usage` | 明细 token 与供应商返回的 usage 一致 |
| `priced_cost_matches_tokens` | 金额 = Σ(tokens × 单价)，可复算 |
| `unpriced_model_is_null_not_zero` | 未定价模型 `cost=null`，token 与调用次数照记 |
| `partial_total_exposes_gap` | 总额只含已知部分，并自曝 `costComplete=false` + `unpricedModels` |
| `usage_persisted_with_model_and_purpose` | 明细真的落进 `agent_run.usage`（不是只在内存里算） |

最近一次（2026-10-26）：旗舰 2 次调用 → 0.000168 元（与 10in/8out × 单价精确一致），
轻量 4 次调用 token 照记、成本为 null，11 项判定全通过。

口径补充：`usage_complete` 表示"每次调用都拿回了 usage"，`tokens_complete` 更严——
要求输入与输出两侧都有值；缺一侧时**不按 0 计价**，只记 `cost=null` + `token-usage-missing`。

**边界**：价格表是配置口径而非供应商账单，本项只证明账目算法与数据链路正确，
真实账单核对需要供应商结算数据；空价格表（完全未知）由 `tests/test_g6_cost.py` 覆盖。

## 12. 三角色治理分工验收（G7）

G7 的验收入口是测试而非评测脚本（角色判定是确定性逻辑，不需要模型与统计口径）：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_g7_roles.py -q
```

三层强制点与用例映射：

| 强制点 | 代码位置 | 覆盖用例 |
|---|---|---|
| 网关第一跳 | `app/observability.py`（`harden_principal`） | 未知角色 403、缺租户身份 403、伪造权限头被收敛 |
| 路由级 | `require_route_permission` | member 打知识库 / 开关 / 成本 / 审计 / 租户治理全部 403；tenant_admin 打平台开关 403 |
| 检索末条 | `app/agent/knowledge.py`、`app/services/policy.py`（`filter_visible`） | 跨租户快照与检索为空、未知密级按不可读、拒绝条数入审计 |
| 职责映射本身 | `app/agent/access.py`（`responsibility_matrix()`） | 每条职责都有权限支撑，每条权限都有职责解释；三条硬边界在案 |
| 加固点（独立审查后补） | `app/observability.py`、`app/agent/routers.py` | 重复身份头 403、CORS 预检放行、`/internal/**` 不受角色治理、工具判权用收敛权限、`TENANT_ROLE_REQUIRED` 收口、公共域契约 |

口径与边界：

- **只收缩不放大**：有效权限 = 角色基线 ∩ 网关声明；`Principal.require` 还有一道角色上限（纵深防御），
  所以"伪造全量权限头 + 直接调用服务函数"同样越不了权。
- **过渡期不收紧**：网关未下发 `X-User-Role` 时保持既有口径；`TENANT_ROLE_GOVERNANCE_ENABLED=false`
  整体回退（含 `require` 的角色上限检查），回退不是"回退一半"。
- **跨租户只放行治理元数据**：`GET /api/agent/tenants` 只回命名空间 / 版本数 / 审计条数，
  用例显式断言响应里不含知识正文。
- **已知边界**：本仓库只覆盖 Python 侧判定。`X-User-Role` 的真实下发、租户头强制注入、
  客户端伪造头剥离都在 Java 网关（`AiGatewayIdentity` / `GatewayProxyController`），
  与第 7 节记录的跨仓库契约风险同源；预生产验收必须在完整链路上复测。
  当前部署是单租户账号模型（网关固定下发 `X-Tenant-Id: default`），
  跨租户隔离用例由 Python 侧合成多租户身份验证，真实多租户账号体系仍待补齐。

## 13. LTR 增益对比（G9）

```powershell
# 合成图谱语料（CI 口径，默认；强制关闭付费模型）
.venv\Scripts\python.exe -m evals.ltr_compare --output evals/reports/ltr-compare.json
# 真实回流标注集（上线依据，先跑第 4 节的回流闭环拿到 real-*.json）
.venv\Scripts\python.exe -m evals.ltr_compare --dataset-file evals/datasets/reflow/real-2026-10-25.json
# 门禁口径：增益与上线门禁任一不通过即非零退出码
.venv\Scripts\python.exe -m evals.ltr_compare --require-gain
```

三个受控口径，唯一变量是排序函数：

| 口径 | 排序依据 | 用途 |
|---|---|---|
| `rrf` | 现有 RRF 倒数排名融合 | 保底基线 |
| `ltr_shadow` | 仍按 RRF 排序，只记录影子排序差异 | 上线前影子观察 |
| `ltr_blend` | `(1-alpha)·RRF + alpha·LTR` | 待验证的渐进替换 |

判定与边界：

- **样本外口径**：按 case 做 5 折，折内 case 只用其他折训练出的模型排序，避免"自己考自己"；
  报告同时给出 `inSampleReference`，但它只作参考，不作为上线依据。
- **训练数据不足不训练**：样本数 < `LTR_MIN_SAMPLES` 或标签单一 → 报告 `trained=false` +
  `gate.promoted=false`，并指向 G2 回流闭环（第 4 节）。
- `promoted` 需要**同时**满足"样本外 Recall/MRR/nDCG 有正向增益"与"门禁通过
  （样本量 + 样本外 AUC ≥ `LTR_MIN_AUC`）"，任一不达标都是 `false`。
- **候选池口径**：单次检索 top-20（在线是整池），BM25 归一化在本批候选内完成；
  这个差异写进报告 `note`，不允许拿它当"等价线上"的证据。
- 最近一次离线结果（2026-10-26，合成图谱集，92 个候选样本 / 8 个正例 / 5 折全部训练）：
  `recall_gain 0.0` / `mrr_gain -0.021` / `ndcg_gain -0.017`，门禁通过
  （**按 case 分组折的折外 AUC 0.7842** ≥ 0.6）但**增益未达标** → `promoted=false`，
  即保持 RRF 保底（`LTR_MODE=off`）。这正是本项目要的口径：模型"能训出来"不等于"值得上线"。
- 折的划分单位决定 AUC 可信度：门禁与评测都按 **case / query 分组**切折（`foldUnit=group`），
  同一查询的候选整组进同一折；`train_model` 里按行取模的折（`foldUnit=row`）会偏乐观，报告如实标注。
- 指标口径：正例稀少（8/92）时 `accuracy` 会被"全猜负例"抬到 0.913，结论只看 **AUC**；
  `shadow_top_changed_avg` 度量的是前 K 名**集合**对称差（不是名次顺序差异）——
  本次为 0 但 MRR 仍下降，即"集合没变、名次变了"。
- 门禁与增益是两件事：门禁（`gate`）只回答"模型有没有区分度"，
  增益（`decision.outOfSampleGain`）回答"检索有没有变好"；两者都通过才 `promoted=true`。
- `gate.cvSource = "kfold-by-group-out-of-fold"`：门禁 AUC 来自按 case 分组折的折外预测汇总；
  同批全量打分只放在 `inSampleReference`，不作为上线依据。
- **训练与指标只由服务端产生**：线上入口是 `POST /api/agent/ltr/train`（样本进、指标出），
  没有"客户端自报 weights / cv_auc"的注册端点；模型落库默认 `shadow`，`save_model` 不允许直接写 `active`。
- **blend 会被精排采纳**：词法降级路径与排序键以 `blend_score` 为基准（缺失回落 RRF），
  所以 `blend` 会改变最终返回顺序；`off` / 模型缺失 / 异常（含 NaN）一律退回 RRF 原序。
- **force 不是后门**：`activate?force=true` 只允许回滚**曾激活过**的版本，从未上线的模型即使 force 也 409。
- **上线依据**必须是 G2 回流人工标注集上的样本外增益；合成集只能证明工程行为可回归。
  真开先走 `LTR_MODE=shadow`，再小步提高 `LTR_BLEND_ALPHA` 切 `blend`，不做一步到位的 replace。