"""知识图谱最小闭环（G1）：Schema 约束抽取 → 实体对齐去重 → 落图 → 多跳遍历 → 社区摘要。

模块边界：

- `schema`：受限 Schema 白名单，抽取结果的唯一准入判定。
- `extract`：按 Schema 抽取（LLM 通道 + 无 Key 的规则化通道）。
- `align`：实体对齐去重，避免"同一对象多种叫法"污染图。
- `store`：networkx 内存图 + 关系表持久化；租户与密级沿用现有治理口径。
- `traverse`：多跳遍历，产出可回溯的路径。
- `community`：社区检测与社区摘要（全局性问题的入口）。
- `retrieval`：图召回，供 `app/services/policy.py` 的 RRF 做第三路融合。
- `build`：构图入口与 CLI。

注意：本包不是 `app/graphs`（LangGraph 流程编排），命名取知识图谱（knowledge graph）含义。
"""

__all__ = ["schema", "extract", "align", "store", "traverse", "community", "retrieval", "build"]
