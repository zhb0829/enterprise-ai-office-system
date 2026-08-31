# 会议公开信息整理模块约定

## 分工边界

| 能力 | Java `admin-server` | Python `app/meeting` |
|---|---|---|
| 会议、资料、纪要版本、任务、通知业务数据 | 唯一写入口，负责 CRUD、权限、状态机与文件存储 | 不提供业务 CRUD，不修改表结构 |
| 文档、图片、音频、链接解析 | 禁止实现 | 负责解析、ASR、视觉模型与正文抽取 |
| 要点、纪要、卡片、关联推荐 | 只校验与持久化回调结果 | 负责生成、引用校验、检索与推荐 |
| 对前端接口 | `/api/meeting/**` | 禁止前端直连 |
| 服务协作 | 派发任务并接收回调 | 仅暴露 `/internal/meeting/**` |

## 接口契约

- Java 派发：`POST /internal/meeting/conferences/{conferenceId}/reorganize`
- Python 回调进度：`POST /internal/meeting/tasks/{taskId}/progress`
- Python 回调结果：`POST /internal/meeting/tasks/{taskId}/result`
- Python 回调失败：`POST /internal/meeting/tasks/{taskId}/failure`
- 服务间请求统一携带 `X-Internal-Token`。
- 进度由 `collect / parse / extract / generate / recommend` 五步组成。
- 结果中的每张知识卡片必须包含非空 `sourceRef`；Java 对缺失引用的卡片追加“待确认”兜底标记。

## 表结构

业务表唯一事实来源为 `admin-server/src/main/resources/schema.sql`：

`conference`、`conference_material`、`conference_report`、`knowledge_card`、
`conference_task`、`conference_media`、`user_notification`。

V1 不引入 Redis、MQ、ES、MinIO，也不实现竞品关联与情感分类。
