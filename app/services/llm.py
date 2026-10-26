"""LLM 封装：OpenAI 兼容（DeepSeek）可插拔。

未配置 LLM_API_KEY 时进入 Mock 模式（各服务按 is_mock 走规则化实现），
保证无 Key 环境也能端到端跑通链路；填入 Key 后自动切换真实调用。

- **G4 分层路由**：调用点传 `purpose`（用途）后，由 `app/services/model_router.py`
  按用途与问题复杂度选层（简单走轻量层、复杂走旗舰层）。显式传 `model` 表示专用模型
  （抽取 / 核查 / 视觉等），路由不覆盖它，但仍留一条 `explicit-model` 决策用于回溯与成本归集。
- **G6 成本核算**：每次调用的 token（与命中价格表时的成本）经 `app/services/cost.py`
  按"模型 + 用途"累加进当前 AgentRun 的 usage；价格或 usage 缺失一律记 null，不估算。
"""
import json
import logging
import re

from openai import OpenAI

from ..config import settings
from ..agent.runtime import digest, step
from ..agent.runtime_flags import enabled as flag_enabled
from ..observability import observe_llm
from ..agent.governance import model_messages
from . import capacity, cost, model_router

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用异常。"""


class LLMCapacityError(LLMError):
    """LLM 容量池已满：可归因的过载错误。

    调用方应据此走既有降级路径（政策问答退化为检索兜底、公告生成退化为规则化草稿），
    而不是把它当成上游故障抛 5xx。
    """


def _routing_text(messages: list[dict]) -> str:
    """路由只看用户侧文本。

    系统提示词里是我们自己的模板文字（含"对比""如果"等词），用它打分会把复杂度信号带偏，
    因此只在没有显式 `routing_text` 时回落到最后一条 user 消息。
    """
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content
            return json.dumps(content, ensure_ascii=False)[:4000]
    return ""


def _record_usage(model: str, purpose: str, usage) -> dict:
    """按模型 + 用途登记用量，返回写进 step 审计的账目片段。"""
    entry = cost.record_usage(
        model=model, purpose=purpose or "unspecified",
        input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        tokens_available=usage is not None,
    )
    return {
        "input_tokens": entry["inputTokens"], "output_tokens": entry["outputTokens"],
        "cost": entry["cost"], "currency": cost.CURRENCY,
        "priced": entry["priced"], "unpriced_reason": entry["unpricedReason"],
    }


class LLMClient:
    def __init__(self):
        self._configured = bool(settings.llm_api_key)
        self._client = None
        if self._configured:
            self._client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout,
            )

    @property
    def is_mock(self) -> bool:
        """未配置 Key，或运行时开关 `remote_llm` 被关闭，都进入 Mock 模式。

        关闭开关后各链路自动走既有规则化兜底并标记 degraded，无需逐个调用点判断，
        因此"秒级回退主链路"不需要重启进程（见 app/agent/runtime_flags.py）。
        """
        return not (self._configured and flag_enabled("remote_llm"))

    def _resolve_model(
        self, messages: list[dict], model: str | None, *, purpose: str, routing_text: str,
        citation_count: int, context_chars: int,
    ) -> str:
        """定模型：有用途就走路由（含显式模型的留痕），无用途则沿用既有默认。"""
        if purpose:
            decision = model_router.resolve(
                purpose=purpose, text=routing_text or _routing_text(messages), model=model or "",
                citation_count=citation_count, context_chars=context_chars,
            )
            return decision.model
        return model or settings.llm_model_generation

    def _completion(self, model: str, messages: list[dict], temperature: float):
        """真正的外部调用：放进 LLM 容量池，池满快速失败而不是无限排队。"""
        return capacity.run(
            "llm",
            self._client.chat.completions.create,
            model=model, messages=messages, temperature=temperature,
        )

    def chat(
        self, messages: list[dict], model: str | None = None, temperature: float | None = None,
        *, purpose: str = "", routing_text: str = "", citation_count: int = 0,
        context_chars: int = 0,
    ) -> str:
        if self.is_mock:
            raise LLMError("LLM 未配置 API Key 或已被运行时开关关闭，不可调用 chat()")
        messages = model_messages(messages)
        model = self._resolve_model(
            messages, model, purpose=purpose, routing_text=routing_text,
            citation_count=citation_count, context_chars=context_chars,
        )
        temperature = settings.llm_temperature if temperature is None else temperature
        try:
            with step("model.chat", inputs={"messages": messages}, model=model,
                      prompt_version=digest([m.get("content") for m in messages if m.get("role") == "system"])[:16]) as audit:
                with observe_llm(model):
                    resp = self._completion(model, messages, temperature)
                audit["usage"] = _record_usage(model, purpose, resp.usage)
                content = resp.choices[0].message.content or ""
                audit["output"] = content
                return content
        except capacity.CapacityError as exc:
            logger.error("LLM 容量池已满，已快速失败: %s", exc)
            raise LLMCapacityError(str(exc)) from exc
        except Exception as e:  # noqa: BLE001
            logger.error("LLM 调用失败: %s", e)
            raise LLMError(str(e)) from e

    def chat_json(
        self, messages: list[dict], model: str | None = None, temperature: float | None = None,
        *, purpose: str = "", routing_text: str = "", citation_count: int = 0,
        context_chars: int = 0,
    ) -> dict:
        """要求模型返回 JSON 并解析（容错剥离 ```json 代码块）。"""
        text = self.chat(
            messages, model=model, temperature=temperature, purpose=purpose,
            routing_text=routing_text, citation_count=citation_count, context_chars=context_chars,
        )
        try:
            return parse_json_text(text)
        except (json.JSONDecodeError, LLMError) as exc:
            raise LLMError(f"模型 JSON 输出解析失败: {exc}") from exc

    def chat_stream(
        self, messages: list[dict], model: str | None = None, temperature: float | None = None,
        *, purpose: str = "", routing_text: str = "", citation_count: int = 0,
        context_chars: int = 0,
    ):
        """流式生成，逐块 yield 文本片段（SSE 实时输出用）。

        流式响应无法跨线程搬运，因此用 `capacity.slot("llm")` 只占配额不换线程。
        """
        if self.is_mock:
            raise LLMError("LLM 未配置 API Key 或已被运行时开关关闭，不可调用 chat_stream()")
        messages = model_messages(messages)
        model = self._resolve_model(
            messages, model, purpose=purpose, routing_text=routing_text,
            citation_count=citation_count, context_chars=context_chars,
        )
        temperature = settings.llm_temperature if temperature is None else temperature
        try:
            with capacity.slot("llm"):
                with step("model.stream", model=model,
                          prompt_version=digest([m.get("content") for m in messages if m.get("role") == "system"])[:16]) as audit:
                    with observe_llm(model):
                        resp = self._client.chat.completions.create(
                            model=model, messages=messages, temperature=temperature, stream=True,
                            stream_options={"include_usage": True},
                        )
                        usage = None
                        try:
                            for chunk in resp:
                                usage = getattr(chunk, "usage", None) or usage
                                if chunk.choices and chunk.choices[0].delta.content:
                                    yield chunk.choices[0].delta.content
                        finally:
                            # 客户端断开（SSE 中断）也要入账：否则这次调用在账面上完全消失，
                            # 落库 usage 反而看起来"完整"。拿不到 usage 就按"用量未知"记 null。
                            audit["usage"] = _record_usage(model, purpose, usage)
        except capacity.CapacityError as exc:
            logger.error("LLM 容量池已满，已快速失败: %s", exc)
            raise LLMCapacityError(str(exc)) from exc
        except Exception as e:  # noqa: BLE001
            logger.error("LLM 流式调用失败: %s", e)
            raise LLMError(str(e)) from e


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