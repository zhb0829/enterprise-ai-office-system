"""舆情情感/事件/风险分析。

两阶段：轻量规则模型处理常规情感分类；低置信度、复杂语义或高风险内容
交由 DeepSeek 复核。所有结论均带置信度、证据片段、模型版本与运行记录。
结构化输出；无法解析的自由文本不作为业务结果。
"""
from __future__ import annotations

import hashlib
import logging
import re
import time

from ..db import SessionLocal
from ..config import settings
from ..services.llm import LLMClient, LLMError, parse_json_text
from .models_ai import OpinionAiModelCall

logger = logging.getLogger(__name__)

NEGATIVE_CUES = [
    "投诉", "曝光", "质量问题", "退货", "召回", "安全事故", "事故", "违规", "违法",
    "起诉", "诉讼", "亏损", "裁员", "倒闭", "破产", "造假", "欺诈", "骗", "被罚",
    "处罚", "监管", "泄漏", "泄密", "隐私", "质疑", "批评", "不满", "抗议", "危机",
    "泡水", "爆炸", "起火", "中毒", "死亡", "污染", "虚假宣传", "价格欺诈",
]

POSITIVE_CUES = [
    "增长", "突破", "创新", "合作", "签约", "获奖", "好评", "涨停", "盈利", "上调",
    "领先", "突破", "点赞", "认可", "里程碑", "战略合作", "上市", "增资", "稳中向好",
]

HIGH_RISK_CUES = ["违法", "起诉", "诉讼", "事故", "死亡", "倒闭", "破产", "造假", "召回",
                   "被罚", "监管", "泄密", "曝光", "危机", "欺诈", "安全事故", "污染", "中毒"]

EMOTION_MAP = {
    "投诉": "投诉", "虚假宣传": "批评", "价格欺诈": "质疑", "欺诈": "质疑", "骗": "谣言",
    "事故": "风险", "危机": "风险", "曝光": "质疑", "监管": "风险",
}

PROMPT_VERSION = "opinion-analysis-v1"


def _random_run_id() -> str:
    import uuid

    return uuid.uuid4().hex[:16]


def rule_classify(title: str, content: str, matched: list[str]) -> dict:
    text = (title + " " + content).lower()
    neg = [w for w in NEGATIVE_CUES if w.lower() in text]
    pos = [w for w in POSITIVE_CUES if w in text]
    risk = [w for w in HIGH_RISK_CUES if w in text]

    if neg and not pos:
        sentiment = "negative"
    elif pos and not neg:
        sentiment = "positive"
    elif neg and pos:
        sentiment = "negative" if len(neg) > len(pos) else ("positive" if len(pos) > len(neg) else "neutral")
    else:
        sentiment = "neutral"

    cues = neg or pos
    confidence = min(0.95, 0.4 + 0.1 * len(cues) + (0.15 if risk else 0))
    if not cues and not risk:
        confidence = 0.3

    emotion_tags = list({EMOTION_MAP.get(w, "风险") for w in risk} | {EMOTION_MAP.get(w, "批评") for w in neg})
    if sentiment == "positive":
        emotion_tags = ["感谢" if "好评" in pos else "利好"]
    if not emotion_tags:
        emotion_tags = ["讨论"]

    evidence = [s for s in _sentences(content + " " + title) if any(c.lower() in s.lower() for c in risk or neg)][:3]
    if not evidence:
        evidence = [title][:1]

    risk_score = _risk_score(neg, risk)
    topic = _pick_topic(title, matched)
    keywords = list(dict.fromkeys((matched or []) + (neg[:5])))[:12]

    return {
        "sentiment": sentiment,
        "confidence": round(confidence, 4),
        "emotion_tags": emotion_tags,
        "reason": f"命中{'、'.join(cues[:5]) if cues else ''} 关键词（共 {len(cues)} 个），高风险线索 {'、'.join(risk[:3]) if risk else '无'}。",
        "evidence": evidence,
        "risk_factors": risk,
        "risk_score": risk_score,
        "topic": topic,
        "keywords": keywords,
        "model": "rule-based",
        "prompt_version": PROMPT_VERSION,
    }


def _risk_score(neg: list[str], risk: list[str]) -> int:
    score = 10 + len(neg) * 12
    score += len(risk) * 18
    if len(risk) >= 3:
        score = max(score, 70)
    return min(100, score)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?；;\n]+", text)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) >= 4]


def _pick_topic(title: str, matched: list[str]) -> str:
    if title and len(title.strip()) > 2:
        return title.strip()[:256]
    if matched:
        return matched[0][:256]
    return "未命名主题"


def _should_deepseek(result: dict) -> bool:
    if result["sentiment"] == "neutral" and result["confidence"] < 0.5:
        return True
    if result["risk_score"] >= 60:
        return True
    return len(result["emotion_tags"]) == 1 and result["emotion_tags"][0] in {"讨论", "福利"} and result["confidence"] < 0.55


def deepseek_review(result: dict, title: str, content: str, matched: list[str]) -> dict:
    llm = LLMClient()
    context = f"标题：{title}\n正文摘要：{content[:4000]}\n匹配关键词：{'、'.join(matched[:10])}"
    messages = [
        {"role": "system", "content": (
            "你是企业舆情分析员。仅根据输入材料，输出 JSON 对象，不得补造事实。"
            "格式：{sentiment:positive|neutral|negative, confidence:0~1 数字, emotion_tags:string[], "
            "reason:string, evidence:string[], risk_factors:string[], risk_score:0~100 整数, "
            "topic:string, keywords:string[]}。讽刺、反讽、辟谣情形请结合上下文判断。"
        )},
        {"role": "user", "content": context},
    ]
    start = time.time()
    raw = llm.chat_json(messages, model=settings.llm_model_extraction)
    latency = int((time.time() - start) * 1000)
    parsed = _sanitize(raw, result, title, matched)
    parsed["model"] = settings.llm_model_extraction
    parsed["prompt_version"] = PROMPT_VERSION
    _record_model_call("deepseek_review", settings.llm_model_extraction, "deepseek",
                       context, raw, latency, True)
    return parsed


def _sanitize(raw: dict, fallback: dict, title: str, matched: list[str]) -> dict:
    sentiment = raw.get("sentiment", fallback["sentiment"])
    if sentiment not in ("positive", "neutral", "negative"):
        sentiment = fallback["sentiment"]
    try:
        confidence = float(raw.get("confidence", fallback["confidence"]))
    except (TypeError, ValueError):
        confidence = fallback["confidence"]
    confidence = min(1.0, max(0.0, confidence))
    try:
        risk_score = int(raw.get("risk_score", fallback["risk_score"]))
    except (TypeError, ValueError):
        risk_score = fallback["risk_score"]
    return {
        "sentiment": sentiment,
        "confidence": round(confidence, 4),
        "emotion_tags": [str(t) for t in raw.get("emotion_tags", []) or fallback["emotion_tags"]][:12],
        "reason": str(raw.get("reason", fallback["reason"]))[:2000],
        "evidence": [str(e) for e in raw.get("evidence", []) or fallback["evidence"]][:3],
        "risk_factors": [str(e) for e in raw.get("risk_factors", []) or fallback["risk_factors"]][:10],
        "risk_score": min(100, max(0, risk_score)),
        "topic": str(raw.get("topic", fallback["topic"]))[:256],
        "keywords": [str(k) for k in raw.get("keywords", []) or fallback["keywords"]][:12],
    }


def analyze_article(task: dict) -> dict:
    """分析一篇文章。返回结构化结果，并记录 AI 运行/模型调用。"""
    title = task.get("title") or ""
    content = task.get("content") or ""
    matched = task.get("matchedKeywords") or []
    run_id = _random_run_id()

    start = time.time()
    result = rule_classify(title, content, matched)
    if _should_deepseek(result):
        try:
            result = deepseek_review(result, title, content, matched)
        except (LLMError, ValueError, AttributeError) as exc:
            logger.warning("DeepSeek 复核失败，保留规则结果: %s", exc)
            _record_model_call("deepseek_review_retry", settings.llm_model_extraction,
                               "deepseek", title + " " + content[:1000], str(exc), 0, False)
    latency = int((time.time() - start) * 1000)

    _record_model_call("rule_classify", "rule-based", "rule",
                       title + " " + content[:1000], str(result.get("reason")), latency, True)

    return {
        "taskId": task.get("taskId"),
        "articleId": task.get("articleId"),
        "monitorId": task.get("monitorId"),
        "sentiment": result["sentiment"],
        "confidence": result["confidence"],
        "emotionTags": result["emotion_tags"],
        "reason": result["reason"],
        "evidenceIds": result["evidence"],
        "riskFactors": result["risk_factors"],
        "riskScore": result["risk_score"],
        "topic": result["topic"],
        "keywords": result["keywords"],
        "model": result["model"],
        "promptVersion": result["prompt_version"],
        "aiRunId": run_id,
    }


def _record_model_call(stage: str, model: str, provider: str, sent_text: str,
                       output_text: str, latency_ms: int, success: bool) -> None:
    db = SessionLocal()
    try:
        call = OpinionAiModelCall(
            stage=stage,
            model=model,
            provider=provider,
            prompt_version=PROMPT_VERSION,
            input_chars=len(sent_text or ""),
            output_chars=len(str(output_text) or ""),
            latency_ms=latency_ms,
            success=success,
            sent_hash=hashlib.sha256((sent_text or "").encode("utf-8")).hexdigest(),
        )
        db.add(call)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("记录模型调用失败: %s", exc)
    finally:
        db.close()


def sanitize_sensitive(text: str) -> str:
    """发送 DeepSeek 前的敏感信息脱敏。"""
    pattern_map = [
        (r"1[3-9]\d{9}", "<手机号>"),
        (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<邮箱>"),
        (r"\d{17}[\dXx]", "<身份证>"),
        (r"\d{16,19}", "<卡号>"),
    ]
    for pattern, repl in pattern_map:
        text = re.sub(pattern, repl, text or "")
    return text
