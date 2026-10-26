"""受限 Schema：实体类型 / 关系类型白名单（G1）。

"拒绝自由文本"的落点在这张白名单，而不是靠提示词自觉：抽取结果先过
`validate_extraction`，类型不在白名单、关系端点类型不符、端点不是本次抽取到的实体
（悬空边）一律丢弃并计入 `rejected`，绝不写进图。

每条被拒记录都带原因，评测与审计能看到"拒了多少、为什么拒"，而不是图里悄悄混进
一堆自由文本节点后才发现检索变脏。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .align import canonical_key

SCHEMA_VERSION = "kg-schema-v1"

ENTITY_TYPES: dict[str, str] = {
    "Policy": "政策法规文件",
    "Authority": "发文或监管机关",
    "Industry": "行业领域",
    "Region": "地区",
    "Clause": "条款条文",
    "Requirement": "义务或要求",
    "Enterprise": "企业或其他主体",
    "Concept": "业务概念",
}


@dataclass(frozen=True)
class RelationSpec:
    """一条白名单关系：允许的头/尾实体类型与中文标签。"""

    head: tuple[str, ...]
    tail: tuple[str, ...]
    label: str


RELATION_TYPES: dict[str, RelationSpec] = {
    "issues": RelationSpec(("Authority",), ("Policy",), "发布"),
    "governs": RelationSpec(("Authority",), ("Industry", "Enterprise"), "监管"),
    "appliesTo": RelationSpec(("Policy", "Clause"), ("Industry", "Enterprise", "Region"), "适用于"),
    "covers": RelationSpec(("Policy",), ("Region",), "覆盖地区"),
    "contains": RelationSpec(("Policy",), ("Clause",), "包含条款"),
    "requires": RelationSpec(("Policy", "Clause"), ("Requirement",), "提出要求"),
    "supersedes": RelationSpec(("Policy",), ("Policy",), "替代"),
    "basedOn": RelationSpec(("Policy", "Clause"), ("Policy", "Clause"), "依据"),
    "mentions": RelationSpec(
        ("Policy", "Clause", "Requirement"), ("Concept", "Enterprise", "Industry", "Region"), "提及",
    ),
    "responsibleFor": RelationSpec(("Enterprise",), ("Requirement",), "承担"),
}

MAX_NAME_LENGTH = 128
MAX_TYPE_LENGTH = 64
MAX_ALIASES_PER_ENTITY = 8
MAX_ENTITIES_PER_CHUNK = 40
MAX_RELATIONS_PER_CHUNK = 60
EVIDENCE_MAX_LENGTH = 300


def entity_type_names() -> tuple[str, ...]:
    return tuple(ENTITY_TYPES)


def relation_type_names() -> tuple[str, ...]:
    return tuple(RELATION_TYPES)


def schema_block() -> str:
    """给抽取提示词用的白名单说明；与校验共用同一份定义，不会漂移。"""
    entities = "、".join(f"{name}({label})" for name, label in ENTITY_TYPES.items())
    relations = "；".join(
        f"{name}({spec.label}: {'/'.join(spec.head)}→{'/'.join(spec.tail)})"
        for name, spec in RELATION_TYPES.items()
    )
    return (
        f"实体类型白名单：{entities}。\n"
        f"关系类型白名单：{relations}。\n"
        "类型必须取自白名单，白名单外的类型一律不要输出。"
    )


def _text(value, limit: int) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        return ""
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _confidence(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 1.0


def _source_ref(value, default) -> dict:
    merged: dict = dict(default or {})
    if isinstance(value, dict):
        for key, item in list(value.items())[:12]:
            if isinstance(item, (int, float, bool, str)) or item is None:
                merged[str(key)[:64]] = item
            else:
                merged[str(key)[:64]] = str(item)[:200]
    return merged


def _reject(rejected: list, kind: str, value: str, reason: str) -> None:
    rejected.append({"kind": kind, "value": value[:MAX_NAME_LENGTH], "reason": reason})


def validate_extraction(payload, *, source_ref=None) -> dict:
    """把抽取结果裁进白名单。

    返回 `{"schemaVersion", "entities", "relations", "rejected"}`；图只接受通过白名单的
    节点与边。同一批内重名实体合并别名并记 `duplicate_name_merged`，不做静默丢弃。
    """
    payload = payload if isinstance(payload, dict) else {}
    rejected: list[dict] = []
    entities: list[dict] = []
    by_key: dict[str, dict] = {}

    raw_entities = payload.get("entities")
    for raw in raw_entities if isinstance(raw_entities, list) else []:
        if not isinstance(raw, dict):
            _reject(rejected, "entity", _text(raw, MAX_NAME_LENGTH), "not_an_object")
            continue
        name = _text(raw.get("name"), MAX_NAME_LENGTH)
        entity_type = _text(raw.get("type") or raw.get("entityType"), MAX_TYPE_LENGTH)
        if not name:
            _reject(rejected, "entity", "", "empty_name")
            continue
        if entity_type not in ENTITY_TYPES:
            _reject(rejected, "entity", name, "entity_type_not_in_schema")
            continue
        key = canonical_key(name)
        if not key:
            _reject(rejected, "entity", name, "name_normalizes_to_empty")
            continue
        raw_aliases = raw.get("aliases")
        aliases = [
            alias for alias in (
                _text(item, MAX_NAME_LENGTH) for item in (raw_aliases if isinstance(raw_aliases, list) else [])
            ) if alias
        ]
        if key in by_key:
            existing = by_key[key]
            existing["aliases"] = list(dict.fromkeys([*existing["aliases"], *aliases]))[:MAX_ALIASES_PER_ENTITY]
            _reject(rejected, "entity", name, "duplicate_name_merged")
            continue
        if len(entities) >= MAX_ENTITIES_PER_CHUNK:
            _reject(rejected, "entity", name, "over_chunk_entity_limit")
            continue
        row = {
            "name": name,
            "type": entity_type,
            "aliases": list(dict.fromkeys(aliases))[:MAX_ALIASES_PER_ENTITY],
            "source_ref": _source_ref(raw.get("source_ref"), source_ref),
            "confidence": _confidence(raw.get("confidence")),
        }
        entities.append(row)
        by_key[key] = row

    relations: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    raw_relations = payload.get("relations")
    for raw in raw_relations if isinstance(raw_relations, list) else []:
        if not isinstance(raw, dict):
            _reject(rejected, "relation", _text(raw, MAX_NAME_LENGTH), "not_an_object")
            continue
        relation_type = _text(raw.get("type") or raw.get("relation"), MAX_TYPE_LENGTH)
        head = _text(raw.get("head") or raw.get("source"), MAX_NAME_LENGTH)
        tail = _text(raw.get("tail") or raw.get("target"), MAX_NAME_LENGTH)
        if relation_type not in RELATION_TYPES:
            _reject(rejected, "relation", f"{head}-{relation_type}->{tail}", "relation_type_not_in_schema")
            continue
        if not head or not tail:
            _reject(rejected, "relation", f"{head}-{relation_type}->{tail}", "empty_endpoint")
            continue
        head_entity, tail_entity = by_key.get(canonical_key(head)), by_key.get(canonical_key(tail))
        if head_entity is None or tail_entity is None:
            # 端点必须是本批已通过的实体：引用外部自由文本的边一律拒绝。
            _reject(rejected, "relation", f"{head}-{relation_type}->{tail}", "dangling_endpoint")
            continue
        spec = RELATION_TYPES[relation_type]
        if head_entity["type"] not in spec.head or tail_entity["type"] not in spec.tail:
            _reject(rejected, "relation", f"{head}-{relation_type}->{tail}", "endpoint_type_mismatch")
            continue
        signature = (head_entity["name"], relation_type, tail_entity["name"])
        if signature in seen:
            _reject(rejected, "relation", f"{head}-{relation_type}->{tail}", "duplicate_relation")
            continue
        if len(relations) >= MAX_RELATIONS_PER_CHUNK:
            _reject(rejected, "relation", f"{head}-{relation_type}->{tail}", "over_chunk_relation_limit")
            continue
        seen.add(signature)
        relations.append({
            "head": head_entity["name"],
            "headType": head_entity["type"],
            "tail": tail_entity["name"],
            "tailType": tail_entity["type"],
            "type": relation_type,
            "evidence": _text(raw.get("evidence"), EVIDENCE_MAX_LENGTH),
            "source_ref": _source_ref(raw.get("source_ref"), source_ref),
            "confidence": _confidence(raw.get("confidence")),
        })

    return {
        "schemaVersion": SCHEMA_VERSION,
        "entities": entities,
        "relations": relations,
        "rejected": rejected,
    }
