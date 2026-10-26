# Agent P1 交付与验收

日期：2026-10-11。
依据：`D:\我的知识库\企业AI智能办公助手实现方案\Agent项目优化建议-基于需求与简历能力框架.md`。

本次实现用户指定的五组平台能力，不包含飞书/钉钉集成、强化学习或自主多智能体。
Java 与 Python 两个仓库均有配套修改；未覆盖或撤销原有 P0 与前端工作区修改。
最初交付时未对业务数据库执行迁移。用户后续授权后，本地 `localhost:5433/eaos`
已升级至 Alembic `9c4_run_classification` 和 Java Flyway V4；
备份恢复、原有数据及结构核验通过，详见 [业务数据库升级记录](业务数据库升级记录-2026-10-11.md)。
下文保留最初交付时的验收边界，真实模型和生产全链路仍未验收。

## 1. 四角色与业务接入

`app/agent/roles.py` 定义四个抽象接口和 `TaskContext`、`ExecutionPlan`、`AgentPipeline`。

| 角色 | 职责 | 默认适配 |
|---|---|---|
| Planner | 校验必填输入与权限，形成可追踪执行计划 | WorkflowPlanner |
| Retriever | 读取资料、记忆和知识证据，不产生事实结论 | FunctionRetriever |
| Actor | 执行已有业务工作流、工具或模型调用 | FunctionActor |
| Verifier | 校验权限、结构、引用和业务条件；失败不返回 Actor 结果 | EvidenceVerifier |

政策问答、公告同步生成、SSE 生成、会议整理和舆情文章分析已接入。
保留原有 LangGraph 业务节点，不把每个角色伪装成独立大模型。
SSE 增量为尚未完成核验的预览；完整结果以 `done` 为准。

`AgentRun` 保存计划、角色与子步骤、trace/user/session、模型、证据、usage、结果和失败状态。
仅成功且完整的会话响应进入短期记忆，失败或客户端取消的流不会写入半成品。
Run 继承处理过的最高数据等级，包括线程工具与临时分类上下文；
结束落库至少为 `internal`，运行详情需同时满足租户、部门和 clearance 条件。
可信的单租户后台作业归属 `default`，无交互用户时标记 `service-worker`，不因此获得 HTTP 权限。

接口：`GET /api/agent/runs`、`GET /api/agent/runs/{run_id}`。
审计员可读取权限范围内运行，本人可读取自己的运行详情；`public_only` 不可读取内部运行。

## 2. 记忆

`app/agent/memory.py` 使用持久化 `agent_memory`，而非仅在进程中保存 sessionId。

| 类型 | 内容 | 默认保留 |
|---|---|---|
| short | 当前会话最近 6 轮问答 | 24 小时 |
| summary | 超出窗口的问答片段抽取摘要，最多 8000 字符 | 7 天 |
| long | 写作风格、组织信息等显式偏好 | 30 天 |

摘要方法为 `extractive-v1`，不是大模型语义总结，不补造事实。
长期偏好按租户、部门、用户依次合并，用户值覆盖共享值。
短期与摘要必须有用户级 sessionId，不允许部门或租户共享会话正文。
自动上下文接入政策问答和公告生成；记忆用于行文与上下文，不作为政策或公告的事实证据。

记录含 classification、revision、expires_at；读取过期或超权限记录时不返回正文。
写入使用 revision CAS，创建 `expectedRevision=0`，后续更新需传当前 revision。
冲突返回 409，不采用最后写入覆盖。单条 value 上限 32 KiB，TTL 范围 1 秒至 365 天。
读取敏感记忆会提升当前任务数据等级；restricted 记忆不能转发外部模型。
公开任务不能消费、写入或删除企业记忆。管理清理只覆盖当前租户、部门与 clearance 范围。

| 接口 | 用途 | 权限 |
|---|---|---|
| GET /api/agent/memory?sessionId=...&scope=user | 读取有效记忆 | memory:read |
| PUT /api/agent/memory | 创建或 CAS 更新 | memory:read 与 memory:write |
| DELETE /api/agent/memory/{id} | 删除单条 | memory:write，共享记录额外需对应 scope 写权限 |
| DELETE /api/agent/memory/session/{session_id} | 删除本会话短期记忆及摘要 | memory:read 与 memory:write |
| POST /api/agent/memory/purge | 清理过期记录 | agent:admin |

共享写入另需 `memory:department:write` 或 `memory:tenant:write`。

```json
{
  "key": "style",
  "value": {"style": "concise"},
  "kind": "long",
  "scope": "user",
  "ttlSeconds": 2592000,
  "expectedRevision": 0
}
```

## 3. 知识生命周期

`KnowledgeHead`、`KnowledgeRelease`、`KnowledgeEntry` 分别保存 generation、不可变版本和文档快照。
命名空间为 `public:{domain}` 或 `tenant:{tenant_id}:{domain}`，domain 支持
`policy`、`materials`、`opinion`、`meeting`。

- 内容与元数据哈希去重；变化文档重新向量化，未变化文档复用已有 chunks 和 embedding。
- 增量列表不代表全量替换；删除必须显式传 `deletedKeys`。
- release 和 document 都有生效、失效时间，失效时间是排他上界，时区统一到 UTC。
- staged 版本不可检索；发布使用数据库 generation CAS，冲突返回 409。
- 已存在未来发布时拒绝直接追加发布，需先取消或回滚，避免计划版本覆盖之后的新内容。
- rollback 发布新版本恢复旧快照，不修改历史记录，并取消尚未生效的计划发布。
- 每次读取检查数据库当前有效版本及 generation；各 worker 按不可变版本缓存，发布提交后下一次读取热加载。
- 快照深拷贝，调用方不能修改缓存。正在执行的任务允许继续使用已取得的旧快照。
- 正常同步 no-op 不留下 staged release，也不重新向量化；预留版本号允许存在间隙。

政策条款检索与解读使用当前版本正文，而非回退到已被替换的 ORM 正文。
素材首次同步保留同租户历史 owner 的资料，读取时仍执行 owner 隔离。
舆情案例从 Java 权威接口全量同步后生成增量发布；缺失案例被删除。
会议按 conference 同步知识卡片，空卡片删除；推荐排除归档和未完成会议。
没有有效案例引用的模型建议回退到真实检索片段。

接口基址：`/api/agent/knowledge/{domain}`。

| 方法与路径 | 用途 |
|---|---|
| POST /releases | documents + deletedKeys 创建待发布版本，expectedGeneration 为当前 generation |
| POST /releases/{id}/publish | 发布或安排未来生效 |
| POST /releases/{id}/cancel | 取消 staged 或未来已发布版本 |
| POST /releases/{id}/rollback | 发布恢复快照的新版本 |
| GET /releases | 版本元数据 |
| GET /snapshot?asOf=... | 当前或指定时间的授权快照 |
| GET /search?q=... | 返回版本号、releaseId、文档 key、片段与分数 |

读取需 `knowledge:read`，staging 需 `knowledge:write`，发布/取消/回滚需 `knowledge:publish`。
公开命名空间在创建时传 `public=true`，后续接口通过查询参数 `public=true` 选择同一命名空间。
公开任务只能访问公开命名空间，内部文档不能放入公开命名空间。
全租户回滚若会触及另一 owner 私有文档，普通身份会被保守拒绝，不以管理员角色绕过正文权限。
这类恢复应经审批由受控运维任务执行，不能给浏览器伪造服务身份。

## 4. 治理

`Principal` 统一 user、tenant、department、permissions、clearance、public_only。
Java `AiGatewayIdentity` 只从服务器登录上下文生成身份头，不相信浏览器的身份/权限/分级头。
Python 仅在正确 `AI_INTERNAL_TOKEN` 下接受这些可信头；仅有自填 `X-User-Id` 不能访问接口。
该 Token 是服务身份凭证，应视作最高敏感秘密，Python 必须仅对可信网关/Worker 开放。

等级：`public < internal < confidential < restricted`。
素材与草稿、草稿证据/审核/核查/导出等子表有 ORM 查询隔离；
`Session.get` 命中 identity map 时也显式重查权限。
记忆、知识快照和运行详情有各自 scope 过滤。
公开资料可跨租户读取，私有资料要求租户匹配、部门匹配、clearance 足够；私有素材还需 owner 匹配。
等级不会随派生草稿、记忆或运行记录自动降低。

模型文本、远端 embedding、远端 rerank、审计详情、运行快照及 Python 日志共用脱敏逻辑，
覆盖常见秘密键、Bearer Token、手机号、邮箱、身份证和长账号数字。
restricted 内容禁止发送外部模型，不因模型服务在内网地址就自动放行。
图片/音频无法通过文本规则完成预上传脱敏，外部解析仅允许声明为 public 的内容；
显式 internal/confidential/restricted 会在读取文件和上传前拒绝。
会议链路默认处理公开资料，上传前的公开属性与版权/个人信息审核仍由业务流程负责。
规则脱敏不等于全面 DLP，也不会自动证明 `public` 标注正确。

HTTP 拒绝、业务动作、版本发布、记忆读写和失败均留治理审计，500 也写入失败状态；
HTTP 审计只记录动作、路径、权限、状态，不复制请求/响应正文。
`GET /api/agent/governance/audit` 要求 `agent:audit`，按租户、部门过滤，公开任务不可读取。
审计记录默认 90 天有效，到期不再返回；物理删除与备份保留需由运维作业配置。
Run 默认 30 天保留，沿用 `python -m app.agent.maintenance --days 30` 的 dry run/审批删除。

文件下载：

- 普通素材/稿件导出验证 ORM 归属，知道文件名不等于有权下载。
- 舆情文件使用 `opinion-report_{id}.pdf/html`，Java 先检查报告权限，
  再签发可信资源断言；浏览器同名头不能直接授权。
- Java 下载代理拒绝目录、路径穿越、二次编码、CRLF 和上游重定向。
- 旧名称的舆情 PDF/HTML 应通过报告导出重新生成，不建议开放匿名兼容下载。

## 5. 舆情事件、趋势和风险

Python 输出 sentiment、confidence、来源原文 evidence、subjects、eventType、
riskScore、riskModelVersion 和模型版本；模型证据必须能定位于原文，否则回退规则结果。
主体为原文中命中的监测关键词，不宣称实现通用实体识别或实体消歧。

Java 按 `monitor + 首个排序主体 + eventType + 周一开始的周窗口` 形成稳定事件 key。
未知主体按 articleId 隔离，不把所有未知文章合并。读取最新分析版本，最新版本 rejected 的文章不再计入事件。
失效分组标记 superseded。监测锁和文章锁串行化聚合及分析版本更新。
人工 review 追加新版本、保存 old/new 与审计，并重算事件和告警。

趋势以最近 24 小时和前一个 24 小时等长窗口比较，未来时间文章不参与趋势。
基线为 0 时 growthRate 为 null，新增报道为 emerging，而非伪造无限增长。
增长率 > 20% 为 rising，< -20% 为 falling，其余 stable。
保存小时 timeline、来源数量、负面比例、当前报道速度和 growthRate。

风险模型 `opinion-risk-v1`：

```text
severity = 事件文章最高风险分
negativeContribution = round(负面比例 * 10)
sourceContribution = min(10, max(0, 来源数 - 1) * 2)
trendContribution = rising ? 10 : 0
eventRiskScore = min(100, severity + 上述三个贡献)
```

0-39 为关注，40-69 为预警，70-100 为危机。
事件 >=40 分、缺少证据或 confidence <0.6 时标记 reviewRequired。
来源多样性不是来源权威性评分，模型为可解释筛查，不等于违法事实判断或已校准的风险概率。

## 6. 部署与恢复

先备份、停写，在预生产验证后发布。现有 `create_all` 不能补充已存在表的列。
两个服务共享 PostgreSQL 时先完成 Java Flyway，再完成 Python Alembic，再启动新版本服务。

Java 在 `admin-server` 使用现有 Spring Boot/Flyway 配置执行至 `V4__agent_opinion_event_models.sql`，
包括 analysis 主体/类型、event 趋势/风险字段和唯一事件 key。
Flyway 已校验的旧迁移不得随意修改；已有环境继续沿用项目既有 baseline 方案。

Python：

```powershell
cd E:\project\enterprise-ai-office-system-new
.venv\Scripts\python.exe -m alembic current
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic current
```

P1 迁移依次为 `9a2_agent_p1`、`9b3_ai_derived`、`9c4_run_classification`。
head 为 `9c4_run_classification`，包含记忆、知识、治理表、派生 AI 表和 Run 数据分级。
旧 Run 没有可靠的数据等级，迁移保守标记 restricted；需授权复核后再调整，不默认开放给 internal 审计员。
旧素材默认租户为 default、部门/owner 为空、等级 internal，需要按真实历史归属做额外回填。
仅靠升级迁移不能推断历史 owner。
已有 create_all 环境必须先核对实际结构与 Alembic version，不能不核对就 stamp head。

回退 P1 会删除记忆、治理审计、知识历史和派生 AI 索引/模型记录，包括升级前已存在的派生表。
**必须先备份，不建议直接在业务库尝试 downgrade。**
恢复旧应用需同步恢复兼容 schema；优先前向修复，而非把数据损失当成普通回滚。
Python 的旧 `7e4_remove_opinion_feature` 不再删除 Java-owned opinion_monitor；
真实迁移测试通过 sentinel 验证 Java 权威表不被 Python 删除。

## 7. 验证与限制

2026-10-11 最终验收结果：

| 检查 | 结果 | 报告 |
|---|---|---|
| Python 全量回归（含真实 PostgreSQL 迁移） | 128 passed，51.88 秒，无失败 | `evals/reports/p1-tests-2026-10-11.xml` |
| Java Maven 全量测试 | 共 59 项，57 通过、2 跳过，无失败或错误 | `admin-server/target/surefire-reports/TEST-*.xml` |
| 独立离线 Golden CLI | 38/38 合成用例通过 | `evals/reports/p1-offline-2026-10-11.json` |
| Python 编译与两仓 diff 检查 | compileall 与 git diff --check 通过 | 无独立报告 |

Java 跳过项为 Windows 环境下已有的 `AuthFlowIntegrationTest` 两项，不计入已通过验证。
Python 有 4 条 Alembic `path_separator` 配置弃用警告，不影响本次迁移结果。
真实数据库覆盖 Python upgrade、重复 upgrade、downgrade 至 P0 后重新 upgrade，
并验证 Java-owned sentinel 表不被删除；Java 覆盖 Flyway V1–V4 与再次执行无新增迁移。
本轮修复离线评测初始化未注册平台模型的问题，并新增独立子进程 CLI 回归，
避免 pytest 导入顺序掩盖独立启动时的缺表错误。
Golden 数据为工程合成集，不代表真实政策准确率或生产验收结果。

真实数据库测试使用独立 `pgvector/pg16` 临时容器，不使用业务 `eaos-db:5433`。
Python 迁移测试要求新建空库，通过 `P1_TEST_DATABASE_URL` 显式启用；
Java 迁移测试通过 `P1_TEST_JDBC_URL`、`P1_TEST_DB_USER`、`P1_TEST_DB_PASSWORD` 显式启用。
这些环境变量不能指向已有业务库。

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m evals.run --mode offline --output evals/reports/p1-offline-2026-10-11.json
cd E:\project\enterprise-ai-office-system-admin\admin-server
mvn -q test
```

验证覆盖四角色记录、无证据核验失败、记忆隔离/TTL/CAS/摘要/删除、
知识增量/no-op/时效/发布冲突/取消/真实回滚读取、
身份伪造、identity-map 与子表越权、公开模式、restricted 外发拦截、
报告下载、SSE 完成/失败/取消、500 审计及舆情趋势/风险/人工版本重算。

生产边界：

- Java 当前账号仍是 default 单租户、空部门、internal clearance；没有完整 Java 多租户账号管理。
  Python 支持可信租户/部门/clearance，不允许通过浏览器自填头开启多租户。
- 会议信息归档过滤沿用同库读取 Java 权威 conference 状态。
  Java/Python 物理分库部署需要改为权威内部 API，不支持开箱即用分库推荐。
- 会议知识索引失败会记录日志，主业务结果不失败；没有新增自动 outbox/重试补偿队列。
- ORM 隔离不是任意 raw SQL 的自动行级安全；后台服务、备份和数据库账号仍需最小权限管理。
- 规则分组、规则摘要与风险评分尚未用真实标注集校准，不宣称语义准确率。
- Run 在结束落库，强制杀进程不保证完整日志；知识缓存全量 manifest 与候选评分仍需真实规模验证。
- 本次没有付费模型调用、真实 JWT/Java/Python/LLM 全链路 E2E、持续容量或高可用验收。
  不以本次测试宣称 500 并发、99.9% 可用性或满足生产延迟指标。

## 8. 原始需求完成核对

本节按用户指定的五组需求核对当前代码和测试证据，不把原方案中的飞书/钉钉、
强化学习、完整多租户账号管理或生产性能验收扩写为本轮已完成内容。

| 用户需求 | 实现与业务接入 | 核验依据 |
|---|---|---|
| 抽象 Planner、Retriever、Actor、Verifier | `app/agent/roles.py` 四个 ABC 与 `AgentPipeline`；政策、公告同步/SSE、会议、舆情工作流接入 | `test_policy_actual_pipeline_captures_roles_version_memory_and_summary` 验证真实链路四阶段；`test_verifier_failure_never_returns_an_actor_result` 验证核验失败不返回结果；P0 公告同步/SSE 回归 |
| 短期记忆、长期记忆、会话摘要 | `MemoryRecord` 与 `MemoryStore` 持久化三类记忆；成功会话写入、政策与公告读取；租户/部门/用户 scope、TTL、CAS、删除 | `test_memory_isolated_expiring_conflict_redacted_and_deleted`、`test_shared_memory_scope_and_session_summary`、`test_policy_model_consumes_memory_without_treating_it_as_evidence`、`test_stream_completed_failed_and_cancelled_memory` |
| 知识库版本、生效时间、增量更新、热加载 | `KnowledgeHead/Release/Entry` 与 `KnowledgeStore`；四类知识源同步；不可变快照、generation CAS、时间过滤、发布/取消/回滚、按有效版本缓存 | `test_incremental_index_reuses_vectors_and_hot_loads`、`test_scheduled_validity_and_publish_conflict`、政策真实回滚检索、素材/舆情/会议增量与删除测试 |
| 统一权限、脱敏、审计、数据分级、公开信息隔离 | Java `AiGatewayIdentity` 服务端身份；Python `Principal`、HTTP/工具权限、共享脱敏、治理审计、ORM/记忆/知识/Run 隔离、外部模型限制 | 可信身份伪造、跨租户/部门/owner、identity-map/子表、restricted 记忆/Embedding、多模态外发、公开任务、500 审计、日志脱敏及报告下载测试；Java 网关与下载控制器测试 |
| 舆情事件、趋势、风险等级模型 | Python 原文证据/主体/类型/评分；Java `OpinionEventService`、`OpinionTrendModel`、`OpinionRiskModel`；人工分析追加版本并重算事件/告警 | `OpinionEventServiceTest` 验证分组、未知主体隔离和拒绝旧版本；`OpinionModelsTest` 验证趋势边界、零基线、未来时间排除、风险阈值和复核；`OpinionAnalysisServiceTest` 验证人工版本重算 |

完成审计时额外重跑 Python 平台、独立 CLI、舆情和 Embedding 相关测试：
**48 passed，35.63 秒**，报告为 `evals/reports/p1-completion-audit-2026-10-11.xml`。
该复核未更改业务代码，原全量 128 项及真实迁移报告仍保留。
数据库迁移文件和部署步骤已交付并在独立数据库验证；用户后续授权后，
本地业务库 `localhost:5433/eaos` 已完成 Flyway V4 与 Alembic `9c4_run_classification` 升级。
最终只读复核确认 69 张表、24 张 Python ORM 表可读取，原有 59 张业务表的 30 行数据
全部旧字段内容哈希不变，数据库默认只读为 off，无遗留数据库级设置。
后端服务保持未启动状态；本地数据库升级不代表远程生产部署或真实全链路验收完成。
备份、迁移演练和恢复边界见 [业务数据库升级记录](业务数据库升级记录-2026-10-11.md)。
