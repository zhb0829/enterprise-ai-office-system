# Agent G7 交付与验收：三角色租户治理分工

日期：2026-10-26。
依据：`D:\我的知识库\企业AI智能办公助手实现方案\架构对标与补齐计划-基于RAG-GraphRAG多租户知识中台.md`
的 G7 条目（"在现有密级 + 权限集合之上，补平台管理员 / 租户管理员 / 普通用户的职责映射，
从网关第一跳校验到检索末条 filter 全程贯通"）。

本次只做 G7；G9 见 `docs/Agent-G9-LTR学习排序.md`。改动跨两个仓库：

- Python AI 服务：新增 `app/agent/access.py`（职责映射与判定）、`app/agent/tenant_routers.py`（治理端点）；
  `Principal` 增 `role` 字段；`require` 增角色基线上限；`require_route_permission` 补 agent 管理面；
  知识检索与政策检索补末条 filter；配置新增 `TENANT_ROLE_GOVERNANCE_ENABLED`。
- Java 网关（`enterprise-ai-office-system-admin/admin-server`）：`AiGatewayIdentity` 下发 `X-User-Role`；
  `GatewayProxyController` 把 `x-user-role` / `x-target-tenant` 纳入客户端头剥离白名单；
  `DataInitializer` 补播 `TENANT_ADMIN` 角色。

## 1. 验收结论

| 缺口 | 完成标志 | 验收命令 | 本次结果 |
|---|---|---|---|
| G7 | 三角色职责映射贯通"网关第一跳 → 路由级 → 调用点" | `.venv\Scripts\python.exe -m pytest tests/test_g7_roles.py -q` | `21 passed`：跨租户 / 伪造身份 / 越权访问 / 头走私 / 预检 / 工具判权 / 收口开关 / 公共域契约 / 末条 filter / 审计留痕全覆盖 |
| G7 | 职责映射自身可核对 | `python -c "from app.agent.access import responsibility_matrix; ..."` | 每条职责都有权限支撑、每条权限都有职责解释（用例逐条校验） |
| 回归 | 不破坏既有授权与隔离 | `.venv\Scripts\python.exe -m pytest tests -q` | `293 passed, 1 skipped`（其中既有 `tests/test_p1_platform.py` 全绿） |
| 跨仓库 | 网关按角色下发身份 | `mvn -o test`（admin-server） | `BUILD SUCCESS`，`Tests run: 56, Failures: 0, Errors: 0` |

## 2. 角色与职责映射

### 2.1 三个角色

| 角色 | 租户范围 | 职责（可读的职责名） | 权限边界 |
|---|---|---|---|
| `platform_admin` 平台管理员 | `platform` | 管租户：`tenant.provision` / `tenant.audit` / `flag.operate` + 租户管理员全部职责 | 租户管理员能力 ∪ `agent:admin`；**跨租户仍读不到内容** |
| `tenant_admin` 租户管理员 | `tenant` | 管知识库：`knowledge.stage` / `knowledge.publish` / `materials.manage` / `draft.review` / `audit.read` / `memory.share.*` | 无 `agent:admin`：碰不到运行时开关、成本全平台口径、跨租户治理 |
| `member` 普通用户 | `self` | 只提问：`policy.ask` / `materials.search` / `meeting.read` / `memory.self(.write)` | 无任何写 / 发布 / 审计权限 |

三条硬边界（测试逐条断言）：

1. 普通用户不能写 / 发布 / 审计 —— 只能只读检索与自己的记忆；
2. 租户管理员不能操作 `agent:admin`（平台开关、跨租户治理）；
3. **任何角色都不能跨租户读内容**：跨租户只放行治理元数据，内容级永远再过 `Principal.can_read`。

### 2.2 只收缩，不放大（三条防线）

| 防线 | 位置 | 效果 |
|---|---|---|
| 网关剥离伪造头 | Java `GatewayProxyController` 的剥离白名单 | 客户端自己塞的 `X-User-Role` / `X-User-Permissions` 不会传到 AI 服务 |
| 第一跳权限收敛 | `app/observability.py` → `access.harden_principal` | 有效权限 = 角色基线 ∩ 网关声明；未知角色 / 缺租户身份直接 403 |
| 角色基线硬上限 | `Principal.require` | 绕过前面两道直接构造 `Principal` 的调用方，仍拿不到角色职责外的能力 |

`TENANT_ROLE_GOVERNANCE_ENABLED=false` 会让上述三处角色判定整体停用（含 `require` 的角色上限），
即**完整回退**到"权限集合即事实"的过渡期口径——回退不允许只回退一半。

### 2.3 职责自洽性怎么保证

`CAPABILITY_PERMISSIONS` 把"职责名 → 说明 → 需要的权限"写死成一张表，`responsibility_matrix()` 对外导出；
`tests/test_g7_roles.py::test_responsibility_matrix_is_consistent_and_complete` 双向校验：

- 每条职责映射到的权限必须真的在该角色基线里（不允许"职责写了没有权限支撑"）；
- 角色基线里每条权限都必须被至少一条职责解释（不允许"给了权限没职责"）。

## 3. 三层强制点

| 阶段 | 代码位置 | 判定 |
|---|---|---|
| 网关第一跳 | `app/observability.py` 中间件 | 读受信网关下发的 `X-User-Role`；未知角色 / 缺 user 或 tenant → 403；权限按角色基线收敛 |
| 路由级 | `app/agent/governance.py::require_route_permission` | `/api/agent/{flags,costs,model-routing,governance}` 读需 `agent:audit`、写需 `agent:admin`；`/api/agent/tenants` 恒需 `agent:admin`；`/api/agent/knowledge` 读需 `knowledge:read`、写需 `knowledge:write` |
| 检索末条 | `app/agent/knowledge.py::search_knowledge`、`app/services/policy.py::search_policy_clauses` | 结果出站前用 `access.filter_visible` 逐条复核密级 / 租户 / 部门 / 属主，未知密级按不可读处理，拒绝条数写进审计与检索诊断 |

末条 filter 的口径：`public` 对任何身份可见（含匿名，与既有行为一致）；
非 public 必须同时满足"密级 ≤ clearance、租户一致、部门一致（若条目限部门）、属主一致（若条目限属主）"。
`search_knowledge` 的审计里带 `filtered` 与 `access.role`，policy 检索把同样的诊断写进 `retrieval.access`。

## 4. 治理端点

| 端点 | 权限 | 返回 |
|---|---|---|
| `GET /api/agent/roles` | 受信身份即可读 | 三角色职责映射 + 当前身份落在哪个角色、当前权限集合 |
| `GET /api/agent/tenants` | `agent:admin` | 租户治理概览：命名空间、版本数、审计条数；**只回元数据，永不回知识正文** |

`GET /api/agent/tenants` 的范围参数：留空=本租户，`?target=<tenant>` / `X-Target-Tenant: <tenant>`=指名租户，
`?target=all`=全平台（仅平台管理员；`require_tenant_scope` 会拒掉其他角色的跨租户请求）。

## 5. 验收怎么跑、怎么判

```powershell
cd E:\project\enterprise-ai-office-system-new
.\.venv\Scripts\python.exe -m pytest tests/test_g7_roles.py -q     # G7 专项
.\.venv\Scripts\python.exe -m pytest tests -q                       # 全量回归
.\.venv\Scripts\python.exe -c "import json; from app.agent.access import responsibility_matrix; print(json.dumps(responsibility_matrix(), ensure_ascii=False, indent=2))"
```

用例覆盖矩阵：

| 用例 | 断言 |
|---|---|
| `test_responsibility_matrix_is_consistent_and_complete` | 职责 ↔ 权限双向自洽，三条硬边界在案 |
| `test_unknown_role_is_rejected_and_permissions_only_shrink` | 未知角色 403；成员带 `knowledge:publish` 头只剩 `policy:read`；过渡期不收敛 |
| `test_gateway_first_hop_hardens_or_rejects` | 收敛产出新对象；未知角色 / 缺租户 403 |
| `test_tenant_scope_rules` | 成员跨租户 403；平台管理员可指名租户与 `all` |
| `test_role_baseline_is_a_hard_ceiling_for_direct_callers` | 绕过收敛的 `Principal` 仍被 `require` 挡住 |
| `test_filter_visible_rejects_cross_tenant_and_unknown_classification` | 跨租户 / 超密级 / 未知密级被拒并计数 |
| `test_cross_tenant_knowledge_snapshot_and_search_are_empty_for_every_role` | 快照与检索对租户管理员（他租户）、平台管理员（他租户）、异部门成员均为空 |
| `test_search_audit_records_role_and_filtered_count` | `knowledge.search` 审计含 `filtered` 与 `access.role` |
| `test_policy_retrieval_carries_access_diagnostics` | 普通用户检索不被误伤，诊断带角色 |
| `test_member_cannot_escalate_with_full_permission_header` | 伪造全量权限头下：知识发布 / 开关 / 成本 / 审计 / 租户治理全部 403，记忆与职责表可用 |
| `test_tenant_admin_manages_own_knowledge_but_not_platform` | 本租户知识库 201；平台开关与租户治理 403；成员连快照都 403 |
| `test_platform_admin_sees_governance_metadata_only` | 元数据可见、正文不可见（`assert 正文 not in response.text`） |
| `test_forged_or_unknown_identity_is_rejected_at_the_first_hop` | 未知角色、缺租户、无内部令牌三种伪造身份 403，且审计 `role` 留痕 |
| `test_legacy_identity_and_governance_switch` | 无角色头不收紧；开关置 false 后带角色也放行；复位后立刻 403 |

## 6. 回归与门禁

- 全量测试：`293 passed, 1 skipped`（本次新增 G7 21 例 + G9 13 例）。
- Java：`mvn -o test` → `Tests run: 56, Failures: 0, Errors: 0, Skipped: 3`，`BUILD SUCCESS`。
- CI：`.github/workflows/agent-evals.yml` 增加一步职责映射快照输出（便于评审时直接核对口径），
  角色判定本身由 pytest 门禁覆盖。
- 路由级拦截的新增映射只覆盖 `/api/agent/**` 管理面；业务面（`/api/policy`、`/api/drafts`…）
  沿用既有映射不变，避免"顺手改权限词汇"引发回归。

## 7. 边界与未覆盖

- **过渡期是风险窗口**：网关未下发 `X-User-Role` 时不收紧。这是为了"先贯通、后收紧"，
  必须随 Java 网关一并发版；在那之前角色治理对线上不生效（可通过 `/api/agent/roles` 的
  `current.role == legacy` 直接看出来）。
- **Java 当前仍是单租户账号模型**：`AiGatewayIdentity` 固定下发 `X-Tenant-Id: default`
  （与 `evals/README.md` 第 7 节记录的跨仓库契约风险同源）。本仓库的跨租户用例用合成多租户身份验证，
  真实多租户需要 `SysTenant` 接入登录态后复测。
- **网关侧有集成断言，但没有真实联调**：`GatewayProxyControllerIntegrationTest` 已断言
  客户端伪造的 `X-User-Role` / `X-Target-Tenant` 被剥离、ADMIN 账号下发 `platform_admin`、
  匿名请求不下发任何角色头；但**没有**跑真实网关 + Python AI 服务的端到端联调
  （真实 JWT、真实下游、真实租户头）。预生产验收必须补这一段。
- **角色不改变密级**：角色只映射权限与租户范围，`clearance` 仍由网关下发（`X-Data-Clearance`），
  两者不互相推导——不允许"平台管理员所以能读 restricted"。
- **内部 worker 不受角色治理约束**：`principal_var` 为空（采集、Celery、迁移）时既有的
  "无交互身份"分支照旧，角色判定不介入；这与既有 ORM 隔离口径一致。
- **职责表是代码常量**：改角色要改代码 + 发版（换来的是可评审、可审计）；DB 化配置留作后续。
- **审计保留 90 天**：`governance_audit` 的越权留痕按既有保留期清理，长期取证需另行归档。

## 8. 后续

- 把角色下发接到真实多租户账号体系（`SysTenant` + `SysUser.role`），并补"网关剥离 `X-User-Role`"的 Java 集成断言。
- 职责表配置化（DB + 审计），支持按租户自定义知识库管理员。
- 与 G3 限流的租户标识打通：限流按 `X-Tenant-Id`，治理按角色，二者共用同一租户视图（`/api/agent/tenants` 已是候选入口）。
## 9. 独立审查后的加固（同日）

一次只读独立审查（含攻击性探针）在 G7 上发现了若干收敛缺口与口径问题，均已修复并补测试：

| 发现 | 性质 | 修法 |
|---|---|---|
| 工具调用按**原始请求头**判权：`X-User-Role: member` 收敛后仍能调用 `draft:verify` 工具 | 越权通道 | `app/agent/routers.py` 改用 `Principal.permissions`；`/api/agent/registry` 也要求受信身份 + 只读权限 |
| 同一身份头出现两次时取首个值，客户端可自选角色 | 头走私 | 中间件检测重复的 `X-User-Role` / `X-User-Permissions` / `X-User-Id` / `X-Tenant-Id` → 403 |
| 角色头有、权限头为空时回落到"角色全集" | fail-open | 默认按"没有权限"处理；`TENANT_ROLE_EMPTY_PERMISSIONS_FALLBACK=true` 才回落 |
| 第一跳对所有路径生效，`/internal/health` 带角色头但无租户身份会被打成 403 | 潜在误伤 | 角色治理只对 `/api` 与 `/static` 生效（服务间调用不受影响） |
| CORS `OPTIONS` 预检被权限校验拦成 403 | 可用性 | `OPTIONS` 直接让路给内层 CORSMiddleware |
| 过渡期里持有 `agent:admin` 的 legacy 身份反而用不了新的治理端点 | 口径矛盾 | `require_tenant_scope` 同时认 `agent:admin` 权限 |
| 租户管理员能只读平台开关 / 路由 / 排序模型现状，但职责表没有对应条目 | 语义扩张 | 新增职责 `platform.status.read` → `agent:audit`，并在文档与职责矩阵里显式披露 |
| `materials/reindex` 路由级要 `knowledge:write`，与"素材管理"职责不一致；发布类动作档位偏低 | 档位不一致 | reindex 改 `materials:write`；`publish` / `cancel` / `rollback` 路由级改 `knowledge:publish` |
| 知识快照遇未知密级抛 `KeyError` → 500 | 健壮性 | 快照与检索共用 `filter_visible`（未知密级按不可读处理） |
| 政策域"公共库"与职责文案"只在本租户域内"冲突 | 口径与实现不符 | 明确为设计边界（政策域 = 全局公共法规库）写进 `responsibility_matrix().knownDesignBoundaries`，并用用例固定 |

审查同时确认：三条硬边界在"伪造全量权限头 / 直接构造 `Principal` / 借工具越权"下均未被绕过；
`TENANT_ROLE_GOVERNANCE_ENABLED=false` 的回退是完整的（`harden_principal`、`effective_permissions`、
`require` 的角色上限三处同时停用）；末条 filter 在第一道失效时有效并落审计。

**仍存在的边界（上线前提）**：所有既有业务 API 都依赖 Java 网关注入受信身份头
（`X-User-Id` / `X-Tenant-Id` / `X-User-Permissions` 至少覆盖 `policy:read`、`materials:read`、
`draft:write|review|verify`、`templates:write`），网关未覆盖到位时这些接口会 403 —— 必须在预生产联调确认；
真实多租户账号体系尚未接入（网关固定 `X-Tenant-Id: default`）。