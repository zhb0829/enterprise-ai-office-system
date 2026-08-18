"""LLM 封装：OpenAI 兼容（DeepSeek）可插拔。

未配置 LLM_API_KEY 时进入 Mock 模式（各服务按 is_mock 走规则化实现），
保证无 Key 环境也能端到端跑通链路；填入 Key 后自动切换真实调用。
"""
import json
import logging
import re

from openai import OpenAI

from ..config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用异常。"""


class LLMClient:
    def __init__(self):
        self.is_mock = not bool(settings.llm_api_key)
        self._client = None
        if not self.is_mock:
            self._client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout,
            )

    def chat(self, messages: list[dict], model: str | None = None, temperature: float | None = None) -> str:
        if self.is_mock:
            raise LLMError("LLM 未配置 API Key，处于 Mock 模式，不可调用 chat()")
        model = model or settings.llm_model_generation
        temperature = settings.llm_temperature if temperature is None else temperature
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            logger.error("LLM 调用失败: %s", e)
            raise LLMError(str(e)) from e

    def chat_json(self, messages: list[dict], model: str | None = None, temperature: float | None = None) -> dict:
        """要求模型返回 JSON 并解析（容错剥离 ```json 代码块）。"""
        text = self.chat(messages, model=model, temperature=temperature)
        return parse_json_text(text)


def parse_json_text(text: str) -> dict:
    """从模型输出中解析 JSON 对象，容错处理代码块包裹与前后缀。"""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise LLMError(f"模型返回非 JSON 内容: {text[:200]}")