请从以下证据中提炼会议要点，并只输出 JSON：

```json
{
  "insights": [
    {
      "cardType": "核心观点|决策事项|行动项|专家观点|关键数据",
      "title": "简短标题",
      "content": "不超出证据的完整表述",
      "actor": "行为主体或发言人，可空",
      "expectedTime": "时间要求，可空",
      "sourceRef": [{"materialId": 1, "location": "PPT第2页", "quote": "原文短引"}]
    }
  ]
}
```

要求：
- 每条 insight 至少包含一个与输入完全一致的 materialId 和 location。
- 不推测未公开的决策，不做情感分类。
- 重复观点合并；无法确认的内容不输出为确定事实。

证据：
{{evidence}}
