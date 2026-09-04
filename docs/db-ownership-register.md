# 数据库表 Owner 登记

> 目的：落实《Java/Python 物理拆分实施方案》第五节的数据库边界 —— 每张表只有一个迁移
> owner、一个业务写者，跨服务数据一律走内部 API。
>
> 更新日期：2026-09-04
>
> 数据库实例可共用，本登记不涉及实例拆分；`sys_*`、`opinion_*` 等前缀分组仅用于归类。

## 一、总则

- 建表/迁移唯一 owner：表中“owner”列。
- 其它项目只允许：①通过该域内部 API 读写；②不直接 SELECT/UPDATE/INSERT 该表。
- 业务写入唯一责任：表中“写者”列（可为 owner 内部多个模块）。
- 若未来出现跨项目新表，先登记本表再写迁移。

## 二、Java 权威表（owner：admin-server / Flyway `V1~V3__*.sql`）

> 表结构迁移来源：`admin-server/src/main/resources/db/migration/V1__baseline.sql`（业务基线）、
> `V2__auth.sql`、`V3__notification.sql`。

### 系统与认证（读者：admin-server 及各服务经 API）

| 表 | owner | 写者 | 迁移 |
|---|---|---|---|
| sys_user | Java | Java | V1/V2 |
| sys_tenant | Java | Java | V2 |
| sys_role / sys_user_role | Java | Java | V2 |
| sys_refresh_token / sys_password_reset | Java | Java | V2 |
| sys_notification_channel / user_notification | Java | Java | V1/V3 |

### 舆情分析（opinion_*）

| 表 | owner | 写者 | 迁移 |
|---|---|---|---|
| opinion_monitor / opinion_source / opinion_source_task | Java | Java | V1 |
| opinion_article / opinion_analysis_task / opinion_analysis | Java | Java(分析结果)/ Python(经 /internal/opinion 回写采集与分析) | V1 |
| opinion_event / opinion_review / opinion_audit_log | Java | Java | V1 |
| opinion_alert_rule / opinion_alert_event / opinion_notification | Java | Java | V1 |
| opinion_report / opinion_response_case / opinion_spread_edge / opinion_suggestion | Java | Java（AI 内容经 Python /internal/opinion 回写） | V1 |

说明：Python 是舆情 Worker，**不建表**，正文/分析/事件均经 Java `OpinionInternalController`（`/internal/opinion`）读写；Python 仅拥有下方 `opinion_ai_*` 运行记录。

### 资质合规（qual_*）

| 表 | owner | 写者 | 迁移 |
|---|---|---|---|
| qual_guide_schema / qual_material / qual_task / qual_task_event | Java | Java（AI 解析经 Python `/internal/qual` 回写） | V1 |
| qual_document / qual_document_version / qual_validation_rule / qual_validation_report | Java | Java | V1 |

### 会议（conference_* / knowledge_card）

| 表 | owner | 写者 | 迁移 |
|---|---|---|---|
| conference / conference_task / conference_material / conference_media / conference_report / knowledge_card | Java | Java（AI 纪要经 Python `/internal/meeting` 回写） | V1 |

### 行业情报（Java 权威，2026-09-04 裁定落地）

| 表 | owner | 写者 | 迁移 |
|---|---|---|---|
| source_config | Java | Java（CRUD）；Python 仅经 `/internal/intelligence/sources/*/run-state` 更新运行态 | V1 |
| collected_article | Java | Python 经 `/internal/intelligence/articles/batch` 回写 | V1 |
| article_cluster | Java | Python 经 `/internal/intelligence/clusters/replace` 全量重建 | V1 |
| intelligence_report | Java | Python 经 `/internal/intelligence/reports` 回写 | V1 |
| collection_task_log | Java | Java 建任务；Python 经 `/internal/intelligence/tasks/*` 更新状态 | V1 |

> 注：早期由 Python Alembic `4c1_intelligence_aggregation` 创建/迁移同一批表，迁移已改为 no-op；
> Python `models.py` 中相关 ORM 已移除，彻底避免双重 owner。

## 三、Python 权威表（owner：ai-service）

> 迁移来源：`alembic/versions/*`（草稿/模板/素材/政策域）+ 启动时 `Base.metadata.create_all`
> （各域 AI 运行记录）。Java 一律不直连这些表，经 `GatewayProxyController` 或对应 internal 接口访问。

### 起草域（模板/草稿/素材/导出）

| 表 | owner | 写者 | 迁移 |
|---|---|---|---|
| template | Python | Python | alembic init |
| style_config | Python | Python | alembic init / 种子 |
| draft / draft_element / fact_check | Python | Python | alembic init |
| export_log | Python | Python | alembic init |
| reference_material / material_chunk | Python | Python | alembic 9b7a_material_chunks |

### 政策与合规域

| 表 | owner | 写者 | 迁移 |
|---|---|---|---|
| policy_document / policy_clause / qa_log | Python | Python | alembic 2a4f_policy_qa |
| compliance_report | Python | Python | alembic 2a4f_policy_qa |

### 舆情/会议 AI 运行记录（Python 私有中间结果）

| 表 | owner | 写者 | 迁移 |
|---|---|---|---|
| opinion_ai_run / opinion_ai_model_call / opinion_case_chunk | Python | Python | create_all（`app/opinion/models_ai.py`） |
| meeting_knowledge_index | Python | Python | create_all（`app/meeting/models_ai.py`） |

## 四、重叠与豁免清单

- 历史重叠表：`source_config` / `collected_article` / `article_cluster` / `intelligence_report` /
  `collection_task_log` —— **已裁定 Java 权威并落地**（见上）。
- 暂存（观察后处理）：无。`opinion_ai_run` 等 Python 记录 Java 不读；Java 业务表 Python 不直连（舆情/会议/资质已改经 internal API）。
- 文件/对象存储、Redis、监控基础设施可共用，不参与本登记。

## 五、验收口径

- [x] 每张表只有一个迁移 owner（Flyway 或 Alembic/create_all）。
- [x] Java 与 Python 不存在对同一张表的直接写入。
- [x] 跨服务数据经 `/internal/**` 访问（舆情/会议/资质/情报均已切换）。
- [ ] 备份与恢复演练（生产验收项，非代码项）。
