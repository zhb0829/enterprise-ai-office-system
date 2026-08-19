"""润色服务：语法纠错、逻辑优化、表达提升、冗余删减、语气统一。

输出润色稿 + 逐条修改说明（original/revised/reason），供前端逐条接受/拒绝。
"""
import logging
from datetime import datetime, timezone

from ..config import settings
from .llm import LLMClient, LLMError

logger = logging.getLogger(__name__)

POLISH_SYSTEM_PROMPT = (
    "你是一名资深中文文字编辑。对给定文稿进行润色，处理方向：语法纠错、逻辑结构优化、表达提升、冗余删减、语气统一。\n"
    "必须遵守：\n"
    "1. 保持原意不变，不得增删任何事实信息（数据、金额、日期、人名、头衔、机构、地名）。\n"
    "2. 输出完整润色稿与逐条修改说明，说明粒度到句子/短语级，每条附理由。\n"
    '只输出 JSON 对象：{"polished":"润色后全文","changes":[{"original":"原文片段","revised":"修改后片段","reason":"修改理由"}]}'
)


def polish_text(text: str, llm: LLMClient) -> tuple[str, list[dict]]:
    """润色文本，返回 (润色稿, [{"original","revised","reason"}])。"""
    if llm.is_mock:
        return (
            text + "\n\n（润色稿：配置 LLM_API_KEY 后切换真实润色，将逐条输出修改说明。）\n",
            [],
        )
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": POLISH_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            model=settings.llm_model_generation,
            temperature=0.2,
        )
        polished = data.get("polished", "")
        changes = data.get("changes") or []
        valid = [
            {
                "original": str(c.get("original", "")),
                "revised": str(c.get("revised", "")),
                "reason": str(c.get("reason", "")),
            }
            for c in changes
            if isinstance(c, dict) and c.get("original") and c.get("revised")
        ]
        if not polished:
            raise LLMError("润色结果为空")
        return polished, valid
    except (LLMError, ValueError, AttributeError) as exc:
        logger.warning("润色失败，退回原文: %s", exc)
        return text, []


def utcnow() -> datetime:
    return datetime.now(timezone.utc)