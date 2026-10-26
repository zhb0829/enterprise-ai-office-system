"""Schema 约束抽取（G1）：LLM 通道 + 规则化通道，两条通道共用同一套白名单校验。

- **LLM 通道**：提示词里直接嵌白名单，`temperature=0`，只输出 JSON；模型自由发挥的部分
  由 `schema.validate_extraction` 裁掉，不看模型自觉。
- **规则化通道**：没有抽取模型（离线评测、未配 Key）时，从条款文本与文档元数据构造
  实体与关系，保证最小链路在无付费模型的环境里也能端到端跑通并可回归。
- **骨架优先**：LLM 结果若漏掉 Policy/Authority/Region/Industry/Clause 这些结构化锚点，
  由规则化结果补齐——语义靠模型，骨架靠元数据，避免图稀疏到无法遍历。

预算：`kg_extract_budget_per_job` 是构图任务的硬上限，超出的条款由 `build` 层跳过并计数。
"""
from __future__ import annotations

import re

from ..agent.runtime import traced
from ..config import settings
from ..services.llm import LLMClient, LLMError
from .align import canonical_key
from .schema import schema_block, validate_extraction

_SENTENCE_RE = re.compile(r"[。；;\n]+")
_OBLIGATION_MARKERS = ("应当", "必须", "须", "不得", "禁止", "严禁", "应于", "应在")
_CONCEPT_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,10}(?:台账|报告|制度|审计|培训|记录|审批|证明|材料|清单|标准|流程|许可证|备案)"
)
_REQUIREMENT_MAX = 64
_CONCEPTS_PER_SENTENCE = 3


def _clause_label(context: dict, clause_key: str) -> str:
    title = str(context.get("title") or "").strip()
    article = str(context.get("article_no") or "").strip()
    if title and article:
        return f"{title}{article}"
    return title or clause_key


def rule_extraction(text: str, context: dict) -> dict:
    """从条款与文档元数据构造骨架图；完全确定性，可离线回归。"""
    context = dict(context or {})
    entities: list[dict] = []
    relations: list[dict] = []
    policy_name = str(context.get("title") or "").strip()
    if not policy_name:
        return {"entities": entities, "relations": relations}

    entities.append({"name": policy_name, "type": "Policy"})
    authority = str(context.get("authority") or "").strip()
    if authority:
        entities.append({"name": authority, "type": "Authority"})
        relations.append({
            "head": authority, "tail": policy_name, "type": "issues",
            "evidence": f"发文机关：{authority}",
        })
        for industry in context.get("industry") or []:
            label = str(industry or "").strip()
            if label:
                entities.append({"name": label, "type": "Industry"})
                relations.append({
                    "head": authority, "tail": label, "type": "governs",
                    "evidence": f"{authority}监管{label}领域",
                })
    region = str(context.get("region") or "").strip()
    if region:
        entities.append({"name": region, "type": "Region"})
        relations.append({
            "head": policy_name, "tail": region, "type": "covers",
            "evidence": f"适用范围：{region}",
        })
    for industry in context.get("industry") or []:
        label = str(industry or "").strip()
        if not label:
            continue
        entities.append({"name": label, "type": "Industry"})
        relations.append({
            "head": policy_name, "tail": label, "type": "appliesTo",
            "evidence": f"适用行业：{label}",
        })

    clause_name = _clause_label(context, str(context.get("clause_key") or ""))
    if clause_name:
        entities.append({"name": clause_name, "type": "Clause"})
        relations.append({
            "head": policy_name, "tail": clause_name, "type": "contains",
            "evidence": clause_name,
        })
        for sentence in _SENTENCE_RE.split(str(text or "")):
            statement = re.sub(r"\s+", " ", sentence).strip()
            if not statement or len(statement) > 400:
                continue
            if not any(marker in statement for marker in _OBLIGATION_MARKERS):
                continue
            requirement = statement[:_REQUIREMENT_MAX]
            entities.append({"name": requirement, "type": "Requirement"})
            relations.append({
                "head": clause_name, "tail": requirement, "type": "requires",
                "evidence": statement[:200],
            })
            concepts = list(dict.fromkeys(_CONCEPT_RE.findall(statement)))[:_CONCEPTS_PER_SENTENCE]
            for concept in concepts:
                entities.append({"name": concept, "type": "Concept"})
                relations.append({
                    "head": clause_name, "tail": concept, "type": "mentions",
                    "evidence": statement[:200],
                })
    # 引用型关系：条文点名了另一份文件时抽出 basedOn / supersedes。
    # 这是"关系推理"问句唯一的落点——问"上位依据是什么"时，问题与被引用条款几乎不共享词面。
    references: list[tuple[str, str, str]] = []
    for pattern, relation_type, label in (
        (re.compile(r"(?:替代|取代|废止)\s*《([^》]{2,60})》"), "supersedes", "替代"),
        (re.compile(r"(?:依据|根据|按照|遵照|参照)\s*《([^》]{2,60})》"), "basedOn", "依据"),
    ):
        for name in dict.fromkeys(pattern.findall(str(text or ""))):
            references.append((name.strip(), relation_type, label))
    for reference, relation_type, label in references:
        entities.append({"name": reference, "type": "Policy"})
        relations.append({
            "head": policy_name, "tail": reference, "type": relation_type,
            "evidence": f"{label}《{reference}》",
        })
    return {"entities": entities, "relations": relations}


def merge_payloads(primary: dict, fallback: dict) -> dict:
    """合并两份抽取结果：同名同类型只保留一份，关系按头/尾/类型去重。"""
    merged_entities: list[dict] = []
    seen_entities: set[tuple[str, str]] = set()
    for source in (primary, fallback):
        for row in (source or {}).get("entities") or []:
            if not isinstance(row, dict):
                continue
            name, entity_type = str(row.get("name") or ""), str(row.get("type") or "")
            key = (entity_type, canonical_key(name))
            if not key[1] or key in seen_entities:
                continue
            seen_entities.add(key)
            merged_entities.append(row)
    merged_relations: list[dict] = []
    seen_relations: set[tuple[str, str, str]] = set()
    for source in (primary, fallback):
        for row in (source or {}).get("relations") or []:
            if not isinstance(row, dict):
                continue
            signature = (
                canonical_key(str(row.get("head") or "")),
                str(row.get("type") or ""),
                canonical_key(str(row.get("tail") or "")),
            )
            if not all(signature) or signature in seen_relations:
                continue
            seen_relations.add(signature)
            merged_relations.append(row)
    return {"entities": merged_entities, "relations": merged_relations}


def llm_extraction(text: str, context: dict, llm: LLMClient, model: str) -> dict:
    """把条款交给抽取模型；提示词与校验共用同一份白名单定义。"""
    system = (
        "你是企业政策知识图谱抽取器。只允许使用给定白名单中的实体类型与关系类型，"
        "禁止自造类型，禁止输出白名单外的自由文本标签。\n"
        f"{schema_block()}\n"
        '只输出 JSON：{"entities":[{"name":"","type":"","aliases":[]}],'
        '"relations":[{"head":"","tail":"","type":"","evidence":""}]}。\n'
        "约束：relations 的 head/tail 必须出现在 entities 的 name 中；evidence 必须是原文里的短句；"
        "没有把握就不要输出，宁可少输出也不要编造。"
    )
    user = (
        f"文件：{context.get('title', '')}\n发文机关：{context.get('authority', '')}\n"
        f"地区：{context.get('region', '')}\n行业：{'、'.join(str(item) for item in (context.get('industry') or []))}\n"
        f"条款号：{context.get('article_no', '')}\n条文：{text}"
    )
    return llm.chat_json(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=model, temperature=0, purpose="kg.extract",
    )


@traced("kg.extract", prompt_version="kg-extract-v1")
def extract_clause(
    text: str, *, context: dict, clause_key: str, llm: LLMClient | None = None, allow_llm: bool = True,
) -> dict:
    """抽取单个条款并按 Schema 校验；任何失败都退回规则化通道，不抛出到主链路。

    `allow_llm=False` 用于预算耗尽或要求纯规则化回归的场景：连一次模型都不调用。
    """
    context = dict(context or {})
    context.setdefault("clause_key", clause_key)
    source_ref = {
        "clauseKey": clause_key,
        "clauseId": context.get("clause_id"),
        "docId": context.get("doc_id"),
        "articleNo": context.get("article_no"),
        "parentKey": context.get("parent_key"),
    }
    rules = rule_extraction(text, context)
    payload, backend = rules, "rule"
    llm = llm if llm is not None else LLMClient()
    if allow_llm and not llm.is_mock:
        model = settings.kg_model or settings.llm_model_extraction
        try:
            payload = merge_payloads(llm_extraction(text, context, llm, model), rules)
            backend = "llm"
        except (LLMError, ValueError, TypeError, KeyError, AttributeError):
            payload, backend = rules, "rule-fallback"
    result = validate_extraction(payload, source_ref=source_ref)
    result.update({"backend": backend, "clauseKey": clause_key})
    return result
