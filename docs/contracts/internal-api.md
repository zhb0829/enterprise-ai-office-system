# 服务内部接口契约（Java ⇄ Python）

> 目标：把 Java 与 Python 之间的 `/internal/**` 调用固化为稳定契约，双方不引用对方源码，
> 任何破坏性变更必须先行新增兼容层。
>
> 更新日期：2026-09-04

## 1. 范围

本契约覆盖三部分：

1. Java → Python 的能力触发（同步/异步派发）。
2. Python → Java 的业务数据回写与查询。
3. 异步任务统一信封（回调协议）。

公网只暴露 Java `/api/**`；Python 仅内网可达。以下路径在 **当前 main/python 分支语义下为 v1 兼容面**，
未来升级按 §4 增加 `/internal/v2/**` 或兼容字段，不得改写旧字段含义。

## 2. 传输与鉴权

- Header：`X-Internal-Token: <共享服务间令牌>`，长度 ≥ 16，由环境变量注入、轮换时新旧并行。
- Header：`X-Trace-Id`（可选）透传；缺失时接收方生成。
- Content-Type：`application/json`；文件上传使用 multipart（仅资质/会议解析入口）。
- 超时：Java 侧同步调用设连接/读取超时；Python 同步处理长任务由调用方按场景放宽读超时。
- Python 回调必须幂等：Java 重复收到同一 `taskId` 的终态回调时不得重复推进状态/通知。

## 3. 端点清单（v1 兼容面）

### 3.1 Java → Python（Python 侧入口）

| 方法 | 路径 | 语义 |
|---|---|---|
| GET | /internal/health | 存活（需令牌） |
| POST | /internal/intelligence/tasks/{id}/dispatch | 情报采集任务派发（202，后台执行） |
| POST | /internal/intelligence/reports/generate?period= | 情报简报生成（同步返回已落库简报） |
| POST | /internal/opinion/... | 舆情分析/报告/事件触发（模块内部面） |
| POST | /internal/meeting/... | 会议纪要/AI 处理（模块内部面） |
| POST | /internal/qual/parse-guide 等 | 资质解析/校验（模块内部面） |
| POST | /internal/meeting/... | 会议模块内部面 |
| POST | /internal/qual/... | 资质模块内部面 |

### 3.2 Python → Java（Java 侧入口）

| 方法 | 路径 | 语义 |
|---|---|---|
| GET | /internal/intelligence/sources[?status=&limit=] | 情报来源列表 |
| GET | /internal/intelligence/sources/{id} | 来源详情 |
| POST | /internal/intelligence/sources/{id}/run-state | 回写来源运行状态 |
| POST | /internal/intelligence/articles/batch | 去重入库采集文章 |
| GET | /internal/intelligence/articles[?sinceDays=&keyword=&sourceId=&page=&pageSize=] | 文章分页查询 |
| GET | /internal/intelligence/articles/by-ids?ids= | 按 id 批量读取 |
| POST | /internal/intelligence/clusters/replace | 全量重建聚类 |
| GET | /internal/intelligence/clusters[?sinceDays=&topic=&limit=] / /clusters/{id} | 聚类查询 |
| POST | /internal/intelligence/tasks | 建采集任务（Beat 用） |
| GET | /internal/intelligence/tasks/{id} | 任务详情 |
| POST | /internal/intelligence/tasks/{id}/start / result / failure | 任务状态回写 |
| POST | /internal/intelligence/reports | 保存简报 |
| GET | /internal/intelligence/reports[?period=&limit=] | 简报查询 |
| GET | /internal/opinion/ping、/articles/ingest、/analysis/*、/spread/ingest、/cases/all | 舆情 Worker 数据面 |
| GET/POST | /internal/meeting/tasks/{id}/progress、/result、/failure | 会议 Worker 数据面 |
| POST | /internal/qual/progress、/result、/failure | 资质 Worker 数据面 |

> 完整字段级定义见各端点实现与下述任务信封；字段命名统一 camelCase。

## 4. 版本策略

- 稳定前缀目标为 `/internal/v1/**`；现有 `/internal/{module}` 路由视为 v1 兼容实现，不承诺重构重命名以免大回归。
- 升级顺序：Python 先加兼容字段或新接口 → 发布 → Java 切换并验收 → 稳定后删旧接口。
- Python 至少兼容当前与上一版本的请求结构；破坏性变更必须新增版本路径。

## 5. 异步任务信封（回调幂等）

所有 Python Worker 长任务在 Java 侧的状态推进使用如下最小字段（Java `collection_task_log`、
`opinion_*_task`、`conference_task` 等权威行的视图即据此序列化）：

| 字段 | 类型 | 说明 |
|---|---|---|
| taskId | int | Java 权威任务行 id |
| idempotencyKey | string(可选) | 调用方去重键 |
| status | string | queued/running/success/failed |
| progress | number(可选) | 0-100 |
| traceId | string(可选) | 全链路追踪 |
| errorCode | string(可选) | 稳定错误码 |
| errorMessage | string | 人类可读原因 |
| resultRef | string(可选) | 结果文件/资源引用 |

终态（success/failed）以 taskId 为准且只推进一次；重复回执直接返回当前权威状态。

## 6. 错误约定

- Java 收 Python 回调返回 `2xx` 即确认；非 2xx 由 Worker 有限重试/进入 failed。
- Python 处理超时返回 502 与稳定 JSON 错误体，不无限重试。
- 服务间错误消息截断 4000 字符入库。

## 7. 契约守护

- `contracts/task-envelope.schema.json`：异步任务信封的 JSON Schema。
- Python `tests/test_contract_paths.py`：锁定上表稳定内部路径与令牌/状态码，防止误改（回归即失败）。
