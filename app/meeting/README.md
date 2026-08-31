# 会议公开信息整理 Worker

## 模块职责

`app/meeting` 只负责公开会议资料的采集、解析、模型调用、要点提炼、纪要与卡片生成、向量索引和关联推荐。会议 CRUD、权限、状态机、业务表结构、通知与 Word 导出全部由 Java `admin-server` 负责。

前端不得直连本模块。长任务入口为 `POST /internal/meeting/conferences/{id}/reorganize`，回调 Java 的 `/internal/meeting/tasks/{taskId}/progress|result|failure`，统一携带 `X-Internal-Token`。

## 五步流程

1. `collect`：用户链接正文已在资料解析阶段抓取；本步骤按会议关键词过滤配置的 RSS。
2. `parse`：PDF、DOCX、PPTX、文本/转录、图片视觉模型、云 ASR。
3. `extract`：要点分类并绑定资料位置。
4. `generate`：生成 Markdown 纪要和知识卡片，缺失引用时降级为“待确认”。
5. `recommend`：政策和未归档历史会议各 top5，阈值 0.72。

每步最多执行三次（首次加两次重试），每次状态都回写 Java。资料解析结果随进度回调保存，失败任务重试时跳过已经解析成功的资料。

## Prompt 规范

Prompt 位于 `app/meeting/prompts/*.md`，随代码版本管理。模板使用 `{{name}}` 占位符，由代码注入经过长度控制的结构化上下文。禁止把 Prompt 存入业务数据库或提供热更新接口。

## 数据边界

- Java `schema.sql` 是 `conference*`、`knowledge_card`、`user_notification` 的唯一表结构来源。
- Python 可只读查询政策与历史会议候选用于 AI 检索，不实现业务 CRUD。
- `meeting_knowledge_index` 是 Python 独占的派生向量索引，不是业务事实来源。
- V1 不引入 Redis、MQ、ES、MinIO，不做竞品关联和情感分类。
