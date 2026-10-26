# 回流测试集目录

本目录存放**线上回流 + 人工标注**的真实语料测试集（`real-*.json`），
由 `python -m evals.run --dataset reflow` 评测。

## 规则

- 只放真实语料：来自线上 badcase（`evals.badcase` 导出）并经人工双人复核标注，
  不得放入合成样本，也不得把 `evals/datasets/policy_*.json` 复制过来充数。
- `pending-*.json` 是待标注草稿，已加入 `.gitignore`：含业务文本，不要提交。
- 晋级必须经 `python -m evals.reflow validate` 通过；校验不通过的条目不得进入 `real-*.json`。
- `real-*.json` 的 `synthetic` 必须为 `false`，`labeled_by` / `labeled_at` 必填，
  `expected` 引用的语料 key 必须在本文件 `corpus` 中存在。

## 当前状态

截至 2026-10-25，本目录尚无 `real-*.json`：回流闭环的代码、校验与晋级流程已具备，
但真实线上点踩样本与人工标注尚未产生。本目录为空时 `--dataset reflow` 直接失败，
不会退回合成集顶替真实语料验收。