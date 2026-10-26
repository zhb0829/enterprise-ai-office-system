# Agent G2 交付与验收：评测四层口径与线上回流

日期：2026-10-25。
依据：`D:\我的知识库\企业AI智能办公助手实现方案\架构对标与补齐计划-基于RAG-GraphRAG多租户知识中台.md` 的 G2 条目。

本次只做 G2（评测四层口径 + 线上回流闭环），未触碰 G1 图谱、G3 限流、G4 路由等其他缺口。
改动限于 Python AI 服务仓库；Java 网关与用户端未改，反馈身份继续走既有可信头。
交付前做过一次独立对抗式复审，下述加固均为复审后补齐。

## 1. 四层口径

`evals/run.py` 一次运行产出 `report["layers"]`，`evals/metrics.py` 提供口径实现：

| 层 | 指标 | 判定 | 缺样本时 |
|---|---|---|---|
| 检索 | `recall_at_k`、`mrr`、`ndcg_at_k` | 标注 `expected` 条款 | `null` |
| 生成 | `answer_accuracy`、`answer_completeness` | 标注 `answerContains` 字面命中 | `null` |
| 引用 | `citation_precision`、`citation_traceability`、`refusal_rate` | `[引用N]` 是否落在真实条款内；条款是否带出处与正文 | `null` |
| 体验 | `latency_p50_ms`、`latency_p95_ms`、`fallback_rate` | 逐用例墙钟延迟；`answer_policy` 的 `degraded` | `null` |

口径纪律：

- 生成层是字面核对，不是语义质量评分；离线自曝 `source=lexical-fallback`、
  `application=engineering-regression-only`，只有 `--mode live` 写 `source=llm`、
  `application=quality-acceptance`。
- 引用层同样自曝：离线为 `source=fallback-answer`、
  `application=structural-regression-only`。离线答案由检索兜底产出，引用标记与出处由管道
  结构保证，该层**恒真**，只证明引用结构未被破坏，不代表引用质量。
- 拒答与无条款记 `null`，不记 0；各层输出 `samples`（每指标可用样本数），
  避免把"只有 1 条样本"读成 `1.0` 满覆盖。本应拒答却作答的用例不再被抹成 `null`。
- 报告新增 `dataset_digest`（语料与用例 sha256）与 `dataset_validation`（回流标注校验结果）。
- `answer_policy` 新增 `degraded` 与 `degradationReasons`（无检索结果、未配置生成模型、
  模型输出不可验证而降级），`PolicyAnswer` 同步声明，前端可据此展示降级状态。
- 离线强制关模型的做法同步加固：`settings` 是进程单例，只改环境变量对库内调用无效，
  `evaluate()` 用 `patch.object` 覆盖模型配置，并用 `patch.dict` 覆盖环境变量，退出即恢复。

## 2. 引用层线上汇总

`evals/citation_audit.py` 从已落库审计还原线上引用口径，不重新生成答案：

- 输入：`agent_run.verification_result`（`passed` / `citation_ids` / `has_evidence` / `refused`）
  与 `agent_run.final_answer`（`clauses` / `riskFlags` / `degraded`）。
- 输出：`verification_pass_rate`、`citation_alignment_rate`、`evidence_rate`、`refusal_rate`、
  `degraded_rate`、`failed_run_rate`、`citation_traceability`、延迟分位与 `tenantScope`。
- 无样本时全部 `null`；`--tenant` / `--since-days` / `--limit` 控制范围，
  也可用 `evals.run --online-citation` 附加到四层报告。

## 3. 线上反馈落库

`POST /api/policy/feedback`（`app/routers/policy.py`），需 `policy:read`：

```json
{"qaLogId": 123, "rating": "dislike", "resolved": false, "reason": "引用条款不适用"}
```

- `rating`：`like` / `dislike` / `none`（`none` 撤销反馈）。
- `resolved`：未反馈为 `null`（未知），不写 `false` 冒充"未解决"。
- 关联：`qaLogId` 或 `runId` 至少一个。
- 授权：只能反馈本租户记录；非本人记录需 `agent:audit`；**无属主**（服务间/后台写入，
  `user_id` 为空）的记录同样只允许 `agent:audit`，避免同租户任意只读用户改写流水、
  污染回流数据。跨租户一律 404，不泄露存在性。
- 落库：`qa_log.feedback` / `resolved` / `feedback_reason` / `feedback_user_id` / `feedback_at`，
  另写治理审计 `policy.feedback`。
- 归属：`qa_log` 增加 `tenant_id` / `user_id` / `run_id`；`answer_policy` 写入时从
  可信身份与 `AgentRun` 取值，`run_id` 打通问答流水与运行审计。

迁移 `alembic/versions/9d5_eval_feedback.py`（`down_revision=9c4_run_classification`）
新增 7 个字段与 4 个索引，回滚脚本对称，`tests/test_p1_migrations.py` 已补列存在与移除断言
（该用例需一次性 PostgreSQL，默认 skip，CI 未设置该变量）。

## 4. badcase 导出

`evals/badcase.py` 合并两类来源并按 `runId` 去重合并标签：

- 反馈类：`dislike`、`unresolved`（`qa_log`）。
- 审计类：`run_failed`、`refused`、`no_citation`、`degraded`（`agent_run`）。

导出 JSONL：问答正文与引用正文按既有 PII/密钥规则脱敏（`--no-mask` 仅限受控排查）；
`tenantId` / `userId` / `runId` / `traceId` 保留原值用于定位，导出物整体按受控数据处理，
不得进入公开文档。`--tenant` 默认 `all-tenants`，输出显式标注实际范围。

## 5. 回流测试集

`evals/reflow.py` 固定三步，未标注内容不能晋级：

1. `draft`：由 badcase（或直接读业务库）生成待标注集，带 `corpus`（真实条款正文）与
   每条 `candidateClauses` 便于标注；没有问题文本的条目丢弃并计入 `intake`。
2. `validate`：要求 `labeled`、`labeledBy`、`labeledAt` 齐全，且
   `expected` / `answerContains` / `refusal` 至少一项有效；拒答与期望条款互斥；
   `expected` 引用的语料 key 必须存在，且 `[key, articleNo]` 必须能从语料切分出来
   （避免"校验通过但评测必然失败"）。
3. `promote`：校验通过才产出 `real-<日期>.json`（`synthetic: false`，
   `dataset_version=production-reflow-*`），并保留标注者回填的检索上下文
   （`asOf` / `region` / `policyName` / `industry` / `authority`），
   使时效、地区类回流样本在评测中不失真。

`evals.run --dataset reflow` 读取 `evals/datasets/reflow/real-*.json`，并且**评测路径本身**
会重新执行同一套 `validate`，额外要求 `synthetic=false`、`state=labeled`、
corpus key 唯一、用例 id 齐备；任何一条不满足直接抛错。目录为空时同样直接失败，
不会退回合成集顶替真实语料验收。

## 6. 门禁与基线

`evals/gate.py` 对照 `evals/baselines/offline.json` 阻断劣化，已接入
`.github/workflows/agent-evals.yml`（pytest → evals.run → evals.gate，产物全部上传）：

- 数据集摘要 `dataset_digest`、来源、`synthetic`、模式与用例数必须与基线一致；
  摘要覆盖语料与用例内容，"等量替换用例"同样被阻断。
- 通过率必须为 1。
- 单调门禁：检索层三项、生成层两项、引用层两项不得下降，`fallback_rate` 不得上升。
- 基线有值而本次为 `null` 视为劣化：不允许"清空标注让指标消失"绕过门禁。
- `refusal_rate` 与延迟只报告：合规场景拒答不算劣化，延迟受机器与并发影响。
- 基线或报告缺失直接失败。
- `--update-baseline` 拒绝任何指标下调或数据集变化；必须显式 `--force` 并填写
  `--approver` / `--reason`，痕迹写入基线 `note`；通过率不是 1 时拒绝刷新。

## 7. 本机验收证据（2026-10-25）

| 项目 | 结果 |
|---|---|
| 全量单元/集成测试 | 190 passed, 1 skipped（迁移用例需 `P1_TEST_DATABASE_URL`，本地跳过） |
| `evals.run --mode offline` | 38/38 通过，exit 0 |
| 检索层 | recall@k 1.0，MRR 0.9333，nDCG 0.9508 |
| 生成层（lexical-fallback） | answer_accuracy 1.0，answer_completeness 1.0 |
| 引用层（fallback-answer） | citation_precision 1.0，citation_traceability 1.0，refusal_rate 0.25 |
| 体验层 | p50 3.99 ms，p95 5.61 ms，fallback_rate 1.0 |
| `evals.gate` | passed=true，exit 0（`evals/reports/g2-gate-2026-10-25.json`） |
| 等量替换阻断实测 | 临时副本清空 1 条 `answerContains`：用例数不变、检索指标不变、`digest_changed=true`、`gate_passed=false`（failures=`dataset_digest`） |
| 未标注回流集拒绝 | `synthetic=true` / `state=pending-labeling` / `labeled=false` 三种形态均被 `load_reflow` 拒绝 |
| 回流端到端 | 临时目录 draft → validate → promote → `--dataset reflow` 评测通过，`synthetic=false`、`dataset_validation.passed=true` |
| 反馈闭环 | 接口落库、租户隔离、他人记录与无属主记录拒绝、治理审计写入均有测试覆盖 |
| badcase/回流 | 导出、脱敏、合并标签、草稿、校验拒绝、试切校验、上下文保留、晋级、BOM 兼容均有测试覆盖 |

延迟与兜底率来自本机离线环境，`fallback_rate=1.0` 是"离线无模型"的必然结果，
不构成质量结论；延迟逐次运行会波动，仅作管道行为回归证据。

## 8. 边界与未验收项

- **回流集目前为空**：`evals/datasets/reflow/` 尚无 `real-*.json`，需真实线上点踩数据与
  人工标注（建议双人复核，复核人写入 `reviewedBy`）后才能跑 `--dataset reflow`。
  合成集不作为真实质量证据。
- **live 模式未执行**：需付费模型预算与审批，本次未跑，四层口径在真实模型下的数值未验收。
- **数据库迁移未在生产执行**：`9d5_eval_feedback` 仅在本地/CI 语义验证；含列存在与移除
  断言的迁移用例需要一次性 PostgreSQL，CI 暂未提供，业务库升级需单独授权。
- **租户头是跨仓库契约**：中间件对缺失 `X-Tenant-Id` 的请求回退为 `default`
  （`app/observability.py`），网关不注入租户头就会让多租户折叠，反馈接口的租户比较随之失效。
  本仓库未单方面改身份解析（会影响全部路由），需要与 Java 网关一起收紧为"缺失即 403"。
- **反馈与审计表无第二道防线**：`qa_log` / `agent_run` 不在 ORM 数据隔离
  （`install_data_isolation`）覆盖范围内，接口与运维脚本各自手工做租户过滤。
- **反馈来源单一**：只覆盖政策问答；公告、会议、情报等场景的反馈未接入。
- **Java 侧未改**：用户端反馈入口需在 admin 仓库对接本接口，本次未实现前端。
- **延迟无门禁**：并发与延迟需在预生产完整链路验证（见 `evals/README.md` 压测章节），
  不能据此声明容量结论。