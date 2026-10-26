# Agent G9 交付与验收：LTR 学习排序演进

日期：2026-10-26。
依据：`D:\我的知识库\企业AI智能办公助手实现方案\架构对标与补齐计划-基于RAG-GraphRAG多租户知识中台.md`
的 G9 条目（"特征取向量相似度、图路径长度、文本匹配分，训排序模型后渐进替换 RRF；
生产姿势是 RRF 保底、LTR 渐进替换，不一步到位"，前置条件为 G2 线上回流闭环）。

本次只做 G9；G7 见 `docs/Agent-G7-三角色治理分工.md`。改动全部在 Python AI 服务内：

- 新增 `app/agent/ltr.py`（特征 / 训练 / 门禁 / 三档排序 / 模型落库）、`app/agent/ltr_routers.py`（运维端点）、
  `evals/ltr_compare.py`（增益对比）；
- `app/agent/platform_models.py` 新增 `ranking_model` 表（迁移 `alembic/versions/9g8_ranking_model.py`），
  不动任何既有业务表结构；
- 新增运行时开关 `ltr`（复用 G5 开关中心）与配置项 `LTR_*`；
- `app/services/policy.py` 在 RRF 融合之后接入 LTR，不改变 `off` 口径下的候选池与顺序语义。

## 1. 验收结论

| 缺口 | 完成标志 | 验收命令 | 本次结果 |
|---|---|---|---|
| G9 特征 | 三特征可解释、可复算 | `pytest tests/test_g9_ltr.py -q` | `9 passed`：路径长度倒数、批内归一化、未命中记 0 全部有断言 |
| G9 渐进替换 | RRF 保底，LTR 只在 shadow / blend 生效 | 同上 | `off` / 模型缺失 / 模型抛异常 / 开关关闭四种情况顺序与基线完全一致 |
| G9 门禁 | 没有标注数据不训练、不达标不激活 | 同上 + `GET /api/agent/ltr` | 样本不足 / 单类标签拒绝训练；`activate` 门禁不达标返回 409 |
| G9 增益 | 相对 RRF 有正向增益才上线 | `python -m evals.ltr_compare` | **`promoted=false`**：`recall_gain 0.0 / mrr_gain -0.0208 / ndcg_gain -0.0173`（合成集，如实记录无增益） |

**结论：本次交付"能力 + 证据 + 门禁"，不交付"上线"**。合成图谱集上 LTR 没有取得正向增益，
因此 `LTR_MODE` 保持 `off`（RRF 保底），这与文档第 5 节"无增益不上线""不要照搬生产上就上 LTR"一致。

## 2. 三档模式与两条纪律

| 模式 | 排序依据 | 用途 | 线上语义 |
|---|---|---|---|
| `off`（默认） | RRF 倒数排名融合 | 保底口径 | 与改动前完全一致（除检索诊断里多出的 `ltr` 字段） |
| `shadow` | **仍按 RRF 排序**，另算 LTR 分与影子对比 | 上线前影子观察 | 不改顺序；`retrieval.ltr.shadowTopChanged` 记录"如果启用会变几名" |
| `blend` | `(1-alpha)·RRF + alpha·LTR`（池内重排） | 渐进替换 | `LTR_BLEND_ALPHA` 小步提高，每一步要有增益证据 |

两条纪律：

1. **RRF 保底**：候选池由 RRF 产生，RRF 分始终保留在 `rrf_score` / `retrieval.rrf`；
   `off`、模型缺失（`no-active-model`）、模型异常（`degraded=true` + 异常类名）、运行时开关关闭
   （`runtime-flag-ltr-off`）四种情况都必须退回 RRF 原序，绝不让检索失败、返回空或静默降级。
2. **不一步到位**：代码里**没有** `replace` 档；`blend` 的 RRF 权重永远是 `1-alpha`。
   想进一步替换只能提高 alpha，而 alpha 每个值都要有 `evals/ltr_compare` 的样本外增益作依据。

## 3. 特征口径（文档点名的三个）

| 特征 | 定义 | 边界口径 |
|---|---|---|
| `dense_similarity` | Dense 路 cosine 相似度 | 负值记 0，再 clamp 到 [0,1] |
| `graph_proximity` | 图路径长度 `1/(1+hops)` | 图未命中（`hops` 为 None/0/非法）记 **0**，不把"没有图信号"当成最优路径 |
| `text_match` | BM25 分，**本批候选内** min-max 归一化 | 跨查询的 BM25 绝对值不可比，所以只在本批内归一化；这是口径的一部分，不是实现细节 |

`off` 时不做任何特征计算；`shadow`/`blend` 时逐行写入 `retrieval.ltrFeatures`，可直接复算。

## 4. 训练与上线门禁

- **训练**：逻辑回归（梯度下降 + L2），纯 Python 实现，不引入新依赖，权重可解释、可复算。
- **拒绝训练**：样本数 < `LTR_MIN_SAMPLES`（默认 50）或标签单一 → `ValueError`，
  不返回"凑合能用"的模型；报告里写 `trained=false` 并指向 G2 回流闭环。
- **样本外评估**：`train_model` 内部做 k 折（默认 5 折），每折用其余样本训练、预测本折，
  汇总出 `metrics.cv_auc`（折外 AUC）。折的划分单位可指定：传 `groups`（如 case id）时按分组切折
  （`foldUnit=group`，推荐），否则按行取模（`foldUnit=row`，同一查询的候选会跨折、AUC 偏乐观）；
  评测脚本的 `gate.cvSource` 因此是 `kfold-by-group-out-of-fold`。
  同一份数据上全量训练后的打分放在 `inSampleReference`，只作参考、**不作为上线依据**。
- **上线门禁**：`should_promote` 要求"样本量达标 + 折外 AUC ≥ `LTR_MIN_AUC`"；
  `POST /api/agent/ltr/models/{version}/activate` 在激活前强制跑一次，不达标返回 409。
  `force=true` 只允许回滚**曾激活过**的版本（`activated_at` 非空），从未上线的模型即使 force 也 409，
  且把 `forced=true` 写进审计。
- **门禁 ≠ 增益**：门禁回答"模型有没有区分度"，增益回答"检索有没有变好"；
  两者都不通过就不上线，只有一个通过也不上线（本次就是这种情况：门禁 true、增益 false）。

## 5. 检索接入与可观测

接入点在 `app/services/policy.py`：RRF 融合 → 构造候选池 → （可选）LTR 重排 → 取 `candidate_limit`
→ 精排（CrossEncoder）→ 末条 filter。因此 LTR 影响的是"谁进候选池、以什么顺序进"，
精排仍是独立的第二段排序（两段职责不混）。

检索诊断新增：

| 字段 | 含义 |
|---|---|
| `retrieval.ltr.mode` | 本次实际生效模式（`off` / `shadow` / `blend`） |
| `retrieval.ltr.modelVersion` | 生效模型版本 |
| `retrieval.ltr.alpha` | 本次混合权重 |
| `retrieval.ltr.shadowTopChanged` | 影子排序相对 RRF 的前 K 名**集合**对称差 / 2（不是名次顺序差异） |
| `retrieval.ltr.degraded` / `reason` | 退化原因（`no-active-model` / `runtime-flag-ltr-off` / 异常类名） |
| `retrieval.ltrScore` / `ltrFeatures` / `blendScore` | 行级分数与特征，便于复算与评测 |
| `runtimeFlags` | 含 `ltr` 表示"配置里开了、被运行时开关显式关闭" |

`answer_policy` 的 `degradationReasons` 同步补充："LTR 排序已启用但没有激活模型，本次已退回 RRF 保底顺序"。

## 6. 模型生命周期与运维端点

| 动作 | 入口 | 权限 | 说明 |
|---|---|---|---|
| 查看现状 | `GET /api/agent/ltr` | `agent:audit` | 模式、alpha、门禁阈值、三特征说明、激活模型、历史版本 |
| 训练模型 | `POST /api/agent/ltr/train` | `agent:admin` | 服务端算权重与指标（**不接受自报 `weights` / `cv_auc`**）；先落 `shadow`，`activate=true` 时仍要过门禁 |
| 激活 | `POST /api/agent/ltr/models/{version}/activate` | `agent:admin` | 门禁不通过 409；激活新模型自动退役旧的；写 `ltr.activate` 审计 |
| 退役 | `POST /api/agent/ltr/models/{version}/retire` | `agent:admin` | 写 `ltr.retire` 审计；退役后 `load_active` 立即变 null |

模型落库字段：版本号（权重 + 样本数 + 数据集摘要的摘要）、特征列表、权重、bias、样本数、正例数、
指标（auc / accuracy / logloss / cv_auc / folds / epochs…）、数据集摘要、备注、训练与激活时间。
激活状态在进程内缓存，激活 / 退役 / 保存时失效，避免每行查询都打库。

## 7. 验收怎么跑、怎么判

```powershell
cd E:\project\enterprise-ai-office-system-new
.\.venv\Scripts\python.exe -m pytest tests/test_g9_ltr.py -q
.\.venv\Scripts\python.exe -m evals.ltr_compare --output evals/reports/ltr-compare.json
.\.venv\Scripts\python.exe -m evals.ltr_compare --require-gain   # 门禁口径：未通过返回非零退出码
```

本次实测（2026-10-26，合成图谱集 `policy_graph_*`，离线口径，92 个候选样本 / 8 个正例）：

| 口径 | Recall@6 | MRR | nDCG@6 |
|---|---|---|---|
| `rrf`（基线） | 1.000 | 0.4792 | 0.6077 |
| `ltr_shadow` | 1.000 | 0.4792 | 0.6077 |
| `ltr_blend` | 1.000 | **0.4583** | **0.5903** |

- 折外 AUC：**按 case 分组折 0.7842**（5 折全部训练、无跳折），门禁通过；学到的权重
  `graph_proximity 1.683 / text_match 1.011 / dense_similarity -0.074`（合成集里 dense 基本无区分度）。
- 检索增益：`recall_gain 0.0`、`mrr_gain -0.0208`、`ndcg_gain -0.0173` → `outOfSampleGain=false`，
  因此 `decision.promoted=false`，`--require-gain` 返回 1（已在 CI 里**不**用该参数，只留报告）。
- `shadow_top_changed_avg = 0`：说明影子排序没有改变前 6 名的集合（但改变了名次，所以 MRR 下降）。
  该字段度量的是集合变化，不要当成"排序完全没变"。

口径警示（写在报告里）：正例稀少（8/92）时 `accuracy` 会被"全猜负例"抬到 0.913，**结论只看 AUC**；
8 个正例的信息量本就不足以支撑"检索增益"，这正是 G2 回流标注规模要先行的原因。

## 8. 回归与门禁

- 全量测试：`293 passed, 1 skipped`（本次新增 G7 21 例 + G9 13 例）。
- `LTR_MODE=off`（默认）时检索结果与改动前一致：候选池、顺序、精排输入都不变，
  仅 `retrieval` 多出 `ltr` / `ltrScore` / `ltrFeatures` / `blendScore` 只读字段。
- `evals.ltr_compare --require-gain` 已具备门禁语义（本次返回非零），CI 只跑不打门禁的那条。
- **迁移已在真实 PostgreSQL 16 上验证**（一次性临时库，用完即删）：
  `upgrade head` → 表与 4 个索引（`domain` / `tenant_id` / `status` / `domain+tenant_id+status`）齐全 →
  `downgrade 9f7_model_routing` 表消失 → 再 `upgrade head` 表回来。回退对称，无残留。

## 9. 边界与未覆盖

- **没有真实回流标注集**：本次训练/评测用的是合成图谱集（8 个 case），只能证明工程行为可回归。
  上线依据必须是 `evals/datasets/reflow/real-*.json`（G2 人工标注集）上的**样本外**增益；
  当前仓库里 `evals/datasets/reflow/` 只有 README，尚无 `real-*.json`。
- **候选池口径差异**：评测按单次检索 top-20 收集候选，在线是整池（`max(20, min(limit*4, 80))`）；
  BM25 归一化在各自批内完成。两者不完全等价，报告 `note` 已声明，不能拿评测数字当线上承诺。
- **特征只用三个**：没有加"点击率""历史偏好"等特征——那些要么没有数据，要么无法解释；
  特征扩展需要先有 G2 的反馈数据，并同步更新门禁口径。
- **图路径长度只在图开启时有值**：`KG_ENABLED=false` 时 `graph_proximity` 恒为 0，
  此时模型退化为"向量 + 文本"两特征（权重不变，`bias` 也仍在），不会报错但也不会有图带来的增益。
- **模型只有线性逻辑回归**：没有上 GBDT / 神经排序；样本量在千级以下时线性模型更稳，
  也更容易解释与复算；升级要先证明收益。
- **进程内缓存与单 worker**：激活状态缓存在进程内（激活 / 退役会失效），多副本部署需逐副本下发
  （与 G5 开关同一边界）。
- **只覆盖政策检索**：`domain="policy"`；素材检索（`search_knowledge`）仍用 BM25 + cosine 简单相加，
  未接入 LTR——那需要单独的模型与数据集。
- **`force` 是回滚通道**：它绕过门禁，所以只给 `agent:admin`，且代码强制"仅曾激活过的版本"可用，
  并强制写审计；生产上仍应只对已验证过的版本使用。
- **未做 A/B 线上实验**：`shadow` 模式提供了对照分，但没有线上并行分流与统计显著性检验；
  真实上线前建议先用 shadow 观察一到两周。

## 10. 后续

- 先把 G2 回流做起来（真实 badcase → 人工标注 → `real-*.json`），再回来重跑 `evals.ltr_compare`；
  只有样本外增益为正、且门禁通过时，才按 `shadow → blend(alpha=0.2) → blend(alpha=0.4)…` 逐步推进。
- 特征扩展候选：图社区归属、条款时效权重、引用链长度（都要求可解释 + 有数据）。
- 模型管理可考虑"按租户独立模型"（`ranking_model.tenant_id` 已预留），但先要有租户级标注量。
- 线上分流实验（shadow 分数落库 + 离线复算）是"从影子到替换"之间缺的最后一段证据链。
## 11. 独立审查后的加固（同日）

一次只读独立审查（含攻击性探针）在 G9 上发现了若干问题，均已修复并补测试：

| 发现 | 性质 | 修法 |
|---|---|---|
| 注册端点接受调用方自报 `weights` / `cv_auc`：权重全 0 + 自报 `cv_auc=0.99` 也能激活 | 门禁自证漏洞 | 移除自报注册端点，改为 `POST /api/agent/ltr/train` 由服务端训练并算指标；`save_model` 不允许直接写 `active` |
| 同一 `version` 重复落库会静默覆写权重并把状态打回 `shadow`（线上无声退回 RRF） | 篡改漏洞 | 同版本重复落库必须内容一致，否则 409；`status` 不再被 `save_model` 覆盖 |
| `force=true` 可让从未验证过的模型上线 | 门禁后门 | 代码强制：仅 `activated_at` 非空的版本允许 force |
| `blend` 重排后紧接的精排排序键不含混合分，LTR 顺序被还原为纯 RRF | 能力与表述不符 | `app/agent/retrieval.py` 的词法降级评分与排序键改用 `blend_score`（缺失回落 RRF） |
| 门禁 AUC 是行级折（同一 query 的候选跨折） | 口径夸大 | `train_model` 支持 `groups` 分组切折；评测与门禁改用 case 级折外 AUC（`foldUnit=group`） |
| NaN 分数会写进响应 | 健壮性 | `rank` 校验有限性并退回 RRF；训练拒绝非有限特征；`save_model` 拒绝非有限权重 |
| `retire` 不校验 domain / tenant（与 activate 不对称） | 防护不对称 | 退役同样校验归属 |
| 文档"min-max 归一化"、`gate.cvSource` 取值与代码不一致 | 口径不精确 | 改为"批内最大值归一化"，`cvSource` / `foldUnit` 与实际一致 |

审查同时确认：`off` / 模型缺失 / 模型异常 / 运行时开关关闭 / 空池 / 单候选六种边界下顺序与基线一致，
异常不留半写字段；报告数字与文档逐位一致，未把合成集包装成"质量达标"。

**仍存在的边界**（未修复、需业务决策）：除 `force` 限制外没有审批流；模型是平台级共享资源
（`ranking_model.tenant_id` 已预留，线上只用默认作用域），任何 `agent:admin` 改动影响所有租户；
没有真实回流标注集，因此"上线依据"目前仍为空（这正是 G2 先行、G9 后置的原因）。