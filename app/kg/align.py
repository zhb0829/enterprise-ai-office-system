"""实体对齐去重（G1）：别名归一 + 相似度合并。

同一个对象在政策语料里常有多种叫法（"测试科技局" 与 "测试科技局（以下简称科技局）"、
"市监局" 与 "市场监督管理局"）。不归一就会把图污染成一堆孤立近义节点，多跳遍历随即失效。

两步走，全部确定性可复现：

1. **归一**：NFKC 全角转半角 → 去掉括号补充说明 → 去掉书名号与标点空白 → 统一小写，
   再查内置别名组得到规范写法。
2. **合并**：同类型实体做 2-gram Jaccard 相似度（含包含比修正），达到阈值即判为同一实体，
   保留先出现的规范名，并把别名与合并来源记进实体，便于人工回溯合并是否合理。

阈值由 `kg_alignment_threshold` 控制，合并依据（相似度分数）随实体落库，不静默处理。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# 内置别名组：每组第一个是规范写法，其余是等价叫法。
# 只放"人工确认过等价"的官方简称，不做同义词猜测——猜错会把不同机关并成一个节点。
ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("市场监督管理局", "市监局", "市场监督局", "市场监管局"),
    ("发展和改革委员会", "发改委", "发改局"),
    ("应急管理局", "应急局", "安全生产监督管理局", "安监局"),
    ("人力资源和社会保障局", "人社局"),
    ("科学技术局", "科技局"),
    ("商务局", "商务主管部门"),
    ("数据局", "大数据管理局", "政务服务数据管理局"),
    ("全国", "国家", "全国范围"),
)

_BRACKET_RE = re.compile(r"[（(【\[][^）)】\]]*[）)】\]]")
_PUNCT_RE = re.compile(r"[\s\u3000·・,，。;；:：、/\\|—\-_'\"]+")
_TITLE_RE = re.compile(r"^《(.*)》$")


def normalize_name(name: str) -> str:
    """实体名归一：去全角/括号/标点/书名号并统一小写。空名返回空串。"""
    text = unicodedata.normalize("NFKC", str(name or "")).strip()
    text = _BRACKET_RE.sub("", text).strip()
    match = _TITLE_RE.match(text)
    if match:
        text = match.group(1).strip()
    text = _PUNCT_RE.sub("", text)
    return text.lower()


def _canonical_table() -> dict[str, str]:
    table: dict[str, str] = {}
    for group in ALIAS_GROUPS:
        canonical = normalize_name(group[0])
        for alias in group:
            normalized = normalize_name(alias)
            if normalized:
                table[normalized] = canonical
    return table


ALIAS_CANONICAL: dict[str, str] = _canonical_table()


def canonical_key(name: str) -> str:
    """归一 + 别名归并后的键。相同键即判为同一实体。"""
    normalized = normalize_name(name)
    return ALIAS_CANONICAL.get(normalized, normalized)


def _bigrams(text: str) -> set[str]:
    if len(text) <= 2:
        return {text} if text else set()
    return {text[index : index + 2] for index in range(len(text) - 1)}


def name_similarity(left: str, right: str) -> float:
    """实体名相似度：2-gram Jaccard 与包含比取较大值，范围 [0, 1]。

    包含比让"科技局"与"测试科技局"得 3/5=0.6，低于默认阈值 0.86，
    即"不因短名被长名吞掉"；只有真正的同源写法才会越线合并。
    """
    first, second = canonical_key(left), canonical_key(right)
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    left_grams, right_grams = _bigrams(first), _bigrams(second)
    union = left_grams | right_grams
    jaccard = len(left_grams & right_grams) / len(union) if union else 0.0
    containment = 0.0
    if first in second or second in first:
        containment = min(len(first), len(second)) / max(len(first), len(second))
    return max(jaccard, containment)


@dataclass
class AlignedEntity:
    """对齐结果：规范名 + 归一键 + 合并依据。"""

    name: str
    norm_key: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)
    merged_from: list[str] = field(default_factory=list)
    reason: str = "new"
    similarity: float = 1.0


class EntityAligner:
    """按实体类型分别维护归一索引，同类型内才允许相似度合并。"""

    def __init__(self, threshold: float, known: dict[str, dict[str, str]] | None = None):
        self.threshold = float(threshold)
        # entity_type -> norm_key -> 规范名
        self._index: dict[str, dict[str, str]] = {
            entity_type: dict(entries) for entity_type, entries in (known or {}).items()
        }

    @classmethod
    def from_entities(cls, entities, threshold: float) -> "EntityAligner":
        index: dict[str, dict[str, str]] = {}
        for row in entities or []:
            entity_type = str(_field(row, "entity_type") or "")
            name = str(_field(row, "name") or "")
            key = canonical_key(name)
            if not entity_type or not key:
                continue
            index.setdefault(entity_type, {}).setdefault(key, name)
        return cls(threshold, index)

    def resolve(self, entity_type: str, name: str, aliases=()) -> AlignedEntity:
        """把一条抽取实体解析到规范实体；找不到就登记为新实体。"""
        raw = str(name or "").strip()
        key = canonical_key(raw)
        if not entity_type or not key:
            raise ValueError("实体名或类型为空，无法对齐")
        alias_list = [str(item).strip() for item in (aliases or []) if str(item).strip()]
        known = self._index.setdefault(entity_type, {})
        if key in known:
            return AlignedEntity(
                name=known[key], norm_key=key, entity_type=entity_type,
                aliases=alias_list, reason="exact",
            )
        best_key, best_name, best_score = "", "", 0.0
        for known_key, canonical in known.items():
            score = name_similarity(key, known_key)
            if score >= self.threshold and score > best_score:
                best_key, best_name, best_score = known_key, canonical, score
        if best_key:
            return AlignedEntity(
                name=best_name, norm_key=best_key, entity_type=entity_type, aliases=alias_list,
                merged_from=[raw], reason=f"similarity:{best_score:.3f}", similarity=best_score,
            )
        known[key] = raw
        return AlignedEntity(name=raw, norm_key=key, entity_type=entity_type, aliases=alias_list)


def _field(row, name: str):
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)
