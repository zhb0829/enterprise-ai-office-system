"""行业政策法规问答服务。

生产环境可以把这里的哈希向量检索替换为 pgvector + Elasticsearch；当前实现保留
相同的召回、引用和降级契约，保证没有外部模型或搜索服务时也不会编造答案。
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..models import ComplianceReport, PolicyClause, PolicyDocument, QALog
from .llm import LLMClient, LLMError
from .materials import embed_text, parse_material, split_text

DISCLAIMER = "本结果为基于公开信息的初步比对，不构成法律意见；请结合完整材料咨询专业人士。"
AI_DISCLAIMER = "AI 生成，仅供参考，不构成法律意见。"
CURRENT_STATUSES = {"现行有效", "有效"}
ARTICLE_RE = re.compile(r"(?m)(?<!\S)(第[一二三四五六七八九十百千万零〇\d]+条)")
TERM_RE = re.compile(r"[\u4e00-\u9fa5]{2,}|[A-Za-z0-9_.%\-]+")


class _VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth and data.strip():
            self.parts.append(data.strip())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _terms(text: str) -> list[str]:
    terms: list[str] = []
    for token in TERM_RE.findall((text or "").lower()):
        terms.append(token)
        if re.fullmatch(r"[\u4e00-\u9fa5]+", token) and len(token) > 2:
            terms.extend(token[index : index + 2] for index in range(len(token) - 1))
    return list(dict.fromkeys(terms))


def _safe_title(filename: str) -> str:
    name = Path(filename).stem.strip()
    return name or "未命名政策文件"


def split_policy_clauses(text: str) -> list[dict]:
    """优先按“第 X 条”切分，无法识别条款时按语义窗口切分。"""
    normalized = re.sub(r"\r\n?", "\n", text or "").strip()
    if not normalized:
        return []
    matches = list(ARTICLE_RE.finditer(normalized))
    if not matches:
        return [
            {"article_no": "", "chapter_path": "", "content": part, "page": 0}
            for part in split_text(normalized, chunk_size=800, overlap=80)
        ]

    clauses: list[dict] = []
    prefix = normalized[: matches[0].start()].strip()
    chapter = _last_heading(prefix)
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        content = normalized[start:end].strip()
        if not content:
            continue
        chapter = _last_heading(normalized[max(0, start - 180) : start]) or chapter
        clauses.append(
            {
                "article_no": match.group(1),
                "chapter_path": chapter,
                "content": content,
                "page": max(1, normalized[:start].count("\f") + 1),
            }
        )
    return clauses or [{"article_no": "", "chapter_path": "", "content": normalized, "page": 0}]


def _last_heading(text: str) -> str:
    headings = re.findall(r"(?:第[一二三四五六七八九十百千万零〇\d]+章[^\n]{0,80}|[一二三四五六七八九十百千万零〇\d]+、[^\n]{0,80})", text)
    return headings[-1].strip() if headings else ""


def create_policy_document(
    db: Session,
    *,
    title: str,
    content: str,
    doc_number: str = "",
    issuing_authority: str = "",
    level: str = "其他",
    status: str = "现行有效",
    industry_tags: list[str] | None = None,
    source_url: str = "",
    file_path: str = "",
) -> PolicyDocument:
    document = PolicyDocument(
        title=title,
        doc_number=doc_number,
        issuing_authority=issuing_authority,
        level=level,
        status=status,
        industry_tags=industry_tags or [],
        source_url=source_url,
        file_path=file_path,
        text_content=content,
        parse_status="解析中",
    )
    db.add(document)
    db.flush()
    for clause in split_policy_clauses(content):
        db.add(
            PolicyClause(
                doc_id=document.id,
                article_no=clause["article_no"],
                chapter_path=clause["chapter_path"],
                content=clause["content"],
                page=clause["page"],
                embedding=embed_text(clause["content"]),
                meta={"source": "公开文件" if source_url else "用户上传"},
            )
        )
    document.parse_status = "已完成"
    db.commit()
    db.refresh(document)
    return document


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = sum(v * v for v in left) ** 0.5
    right_norm = sum(v * v for v in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def search_policy_clauses(
    db: Session,
    query: str,
    *,
    industry: str = "",
    level: str = "",
    authority: str = "",
    limit: int = 6,
) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    terms = _terms(query)
    q_vec = embed_text(query)
    rows = (
        db.query(PolicyClause)
        .options(joinedload(PolicyClause.document))
        .join(PolicyDocument)
        .filter(PolicyDocument.status.in_(CURRENT_STATUSES), PolicyDocument.parse_status == "已完成")
        .all()
    )
    ranked: list[dict] = []
    for clause in rows:
        document = clause.document
        tags = [str(item).lower() for item in (document.industry_tags or [])]
        if industry and tags and industry.lower() not in tags:
            continue
        if level and document.level != level:
            continue
        if authority and authority.lower() not in (document.issuing_authority or "").lower():
            continue
        haystack = " ".join(
            [document.title, document.doc_number, document.issuing_authority, clause.article_no, clause.content]
        ).lower()
        keyword_hits = sum(1 for term in terms if term in haystack)
        title_hits = sum(1 for term in terms if term in (document.title or "").lower())
        cosine = _cosine(q_vec, clause.embedding or [])
        score = keyword_hits * 2.0 + title_hits * 1.0 + max(0.0, cosine)
        if score <= 0:
            continue
        ranked.append(
            {
                "clause": clause,
                "document": document,
                "score": round(float(score), 4),
                "keyword_hits": keyword_hits,
            }
        )
    ranked.sort(key=lambda row: row["score"], reverse=True)
    return ranked[: max(1, min(limit, 20))]


def citation_for(row: dict | PolicyClause) -> dict:
    if isinstance(row, dict):
        clause = row["clause"]
        document = row["document"]
    else:
        clause = row
        document = row.document
    return {
        "id": clause.id,
        "docTitle": document.title,
        "articleNo": clause.article_no,
        "excerpt": clause.content[:1200],
        "sourceUrl": document.source_url,
        "page": clause.page or 0,
        "status": document.status,
    }


def _intent(question: str) -> str:
    if any(word in question for word in ("合规", "是否符合", "风险", "比对", "要求我司")):
        return "比对"
    if any(word in question for word in ("解读", "什么意思", "怎么理解", "白话")):
        return "解读"
    return "检索"


def _fallback_answer(citations: list[dict]) -> str:
    if not citations:
        return "未检索到现行有效且有明确出处的相关政策条款，暂不生成结论。请补充行业、地区、法规名称或上传公开文件后重试。"
    lines = ["检索到以下相关政策条款，建议以原文和最新发布版本为准："]
    for index, citation in enumerate(citations, 1):
        label = f"《{citation['docTitle']}》{citation['articleNo']}".strip()
        lines.append(f"[引用{index}] {label}：{citation['excerpt'][:260]}")
    return "\n".join(lines)


def _llm_answer(question: str, citations: list[dict], llm: LLMClient) -> tuple[str, list[str]]:
    if llm.is_mock or not citations:
        return _fallback_answer(citations), []
    context = "\n\n".join(
        f"[{index}] {item['docTitle']} {item['articleNo']}\n{item['excerpt']}"
        for index, item in enumerate(citations, 1)
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是政策法规检索助手。只能基于用户提供的条款回答，不能补充常识或外推。"
                "每一个可验证结论必须带 [引用N]，条款没有明确规定时必须说未检索到明确规定。"
                '只输出 JSON：{"answer":"...","usedCitations":[1,2]}。'
            ),
        },
        {"role": "user", "content": f"问题：{question}\n\n条款：\n{context}"},
    ]
    try:
        data = llm.chat_json(messages, model=settings.llm_model_generation, temperature=0)
        answer = str(data.get("answer") or "").strip()
        used = [int(index) for index in data.get("usedCitations", []) if str(index).isdigit()]
        used = [index for index in used if 1 <= index <= len(citations)]
        if answer and used and all(f"[引用{index}]" in answer for index in used):
            return answer, []
    except (LLMError, ValueError, TypeError) as exc:
        return _fallback_answer(citations), [f"模型生成失败，已降级为检索结果：{exc}"]
    return _fallback_answer(citations), ["模型未返回可验证引用，已降级为检索结果。"]


def answer_policy(db: Session, request, llm: LLMClient | None = None) -> dict:
    started = time.perf_counter()
    llm = llm or LLMClient()
    hits = search_policy_clauses(
        db,
        request.question,
        industry=request.industry,
        level=request.level,
        authority=request.authority,
        limit=request.limit,
    )
    citations = [citation_for(hit) for hit in hits]
    answer, risk_flags = _llm_answer(request.question, citations, llm)
    if not hits:
        risk_flags = [*risk_flags, "未检索到相关现行有效条款"]
    confidence = "high" if hits and hits[0]["keyword_hits"] >= 2 else ("medium" if hits else "none")
    response = {
        "answer": answer,
        "clauses": citations,
        "sources": citations,
        "confidence": confidence,
        "generatedAt": _now(),
        "model": settings.llm_model_generation if not llm.is_mock else "offline-policy-retrieval",
        "riskFlags": risk_flags,
        "intent": _intent(request.question),
        "queryTerms": _terms(request.question),
    }
    db.add(
        QALog(
            session_id=request.sessionId or "",
            question=request.question,
            answer=answer,
            citations=citations,
            model=response["model"],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    )
    db.commit()
    return response


def _interpret_fallback(text: str) -> dict:
    clean = re.sub(r"^第[^条]{1,20}条", "", text).strip(" ：:，,。")
    obligations = [clean[:180]] if any(word in clean for word in ("应当", "必须", "需", "应在")) else []
    prohibitions = [clean[:180]] if any(word in clean for word in ("不得", "禁止", "严禁")) else []
    consequences = [part.strip() for part in re.split(r"[。；]", clean) if any(word in part for word in ("处罚", "罚款", "责任", "追究"))]
    return {
        "plainSummary": f"这段条文主要规定：{clean[:260]}",
        "applicableObjects": ["需要结合条文上下文和配套文件进一步确认"],
        "obligations": obligations or ["条文未能直接识别出明确义务，请核对完整原文"],
        "prohibitions": prohibitions,
        "consequences": consequences,
    }


def interpret_clause(db: Session, request, llm: LLMClient | None = None) -> dict:
    llm = llm or LLMClient()
    clause = db.get(PolicyClause, request.clauseId) if request.clauseId else None
    text = clause.content if clause else (request.clauseText or "").strip()
    if not text:
        raise ValueError("clauseId 或 clauseText 至少提供一项")
    base_citation = citation_for(clause) if clause else {
        "id": None,
        "docTitle": request.docTitle or "用户提供条文",
        "articleNo": request.articleNo,
        "excerpt": text[:1200],
        "sourceUrl": request.sourceUrl,
        "page": 0,
        "status": "待核实",
    }
    result = _interpret_fallback(text)
    risk_flags: list[str] = []
    if not clause:
        risk_flags.append("用户提供的条文未绑定知识库出处")
    if not llm.is_mock:
        messages = [
            {"role": "system", "content": "你是政策条款解读助手，只能解释给定原文，不得添加原文没有的法律结论。只输出 JSON，字段为 plainSummary、applicableObjects、obligations、prohibitions、consequences。"},
            {"role": "user", "content": text},
        ]
        try:
            candidate = llm.chat_json(messages, model=settings.llm_model_generation, temperature=0)
            for key in result:
                if candidate.get(key):
                    result[key] = candidate[key]
        except (LLMError, ValueError, TypeError) as exc:
            risk_flags.append(f"模型解读失败，已使用规则化摘要：{exc}")
    related = []
    if clause:
        related_rows = (
            db.query(PolicyClause)
            .filter(PolicyClause.doc_id == clause.doc_id, PolicyClause.id != clause.id)
            .order_by(PolicyClause.id)
            .limit(3)
            .all()
        )
        for item in related_rows:
            item.document = clause.document
            related.append(citation_for(item))
    return {
        **result,
        "relatedClauses": related,
        "citations": [base_citation],
        "disclaimer": AI_DISCLAIMER,
        "generatedAt": _now(),
        "model": settings.llm_model_generation if not llm.is_mock else "offline-policy-interpretation",
        "riskFlags": risk_flags,
    }


def check_compliance(db: Session, request, llm: LLMClient | None = None) -> dict:
    llm = llm or LLMClient()
    hits = search_policy_clauses(db, request.businessDesc, industry=request.industry, limit=request.limit)
    items = []
    for hit in hits:
        citation = citation_for(hit)
        items.append(
            {
                "requirement": citation["excerpt"],
                "citation": citation,
                "enterpriseMatch": "仅凭当前公开业务描述无法确认是否满足，需人工核实完整材料。",
                "riskLevel": "待人工核实",
                "suggestion": "核对该条款适用范围、资质证照、流程记录及最新配套规定，并保留核验凭证。",
            }
        )
    risk_flags = [] if hits else ["未检索到可用于比对的现行有效条款"]
    model = settings.llm_model_generation if not llm.is_mock else "offline-compliance-screening"
    response = {
        "items": items,
        "disclaimer": DISCLAIMER,
        "generatedAt": _now(),
        "model": model,
        "riskFlags": risk_flags,
    }
    db.add(
        ComplianceReport(
            business_desc=request.businessDesc,
            industry=request.industry,
            items=items,
            model=model,
        )
    )
    db.commit()
    return response


def document_out(document: PolicyDocument) -> dict:
    return {
        "id": document.id,
        "title": document.title,
        "doc_number": document.doc_number,
        "issuing_authority": document.issuing_authority,
        "level": document.level,
        "publish_date": document.publish_date,
        "effective_date": document.effective_date,
        "status": document.status,
        "industry_tags": document.industry_tags or [],
        "source_url": document.source_url,
        "file_path": document.file_path,
        "parse_status": document.parse_status,
        "clause_count": len(document.clauses),
        "created_at": document.created_at,
    }


def fetch_public_source(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("仅支持 http/https 公开链接")
    with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "EAOS-PolicyBot/0.1"}) as client:
        response = client.get(url)
        response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type or response.text.lstrip().startswith("<"):
        parser = _VisibleTextParser()
        parser.feed(response.text)
        text = "\n".join(parser.parts)
    else:
        text = response.text
    text = html.unescape(re.sub(r"\n{3,}", "\n\n", text)).strip()
    if len(text) < 20:
        raise ValueError("公开链接未提取到足够正文，请改为上传 PDF/Word/TXT 文件")
    return text


def policy_document_by_id(db: Session, document_id: int) -> PolicyDocument | None:
    return (
        db.query(PolicyDocument)
        .options(joinedload(PolicyDocument.clauses))
        .filter(PolicyDocument.id == document_id)
        .first()
    )
