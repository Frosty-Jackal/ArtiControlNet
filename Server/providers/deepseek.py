"""DeepSeek 提供方（OpenAI 兼容）。

- route_message：Supervisor 路由，带工具选择，返回工具调用或纯文本。
- chat_text：纯文本对话。
- qa_image：视觉问答（content 为块数组，图片只出现在 user 消息）。
调用方式见 Spec §7.1。内部为同步调用，对外统一 async（线程池）。
"""
import json
import logging
from typing import Optional

from openai import OpenAI

import config
from errors import AppError, MissingApiKeyError, UpstreamApiError, UpstreamTimeoutError
from providers import run_sync, with_retry

logger = logging.getLogger("providers")

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.OPENAI_BASE_URL,
            timeout=120.0,
            max_retries=1,
        )
    return _client


def _check_key() -> None:
    if not config.DEEPSEEK_API_KEY:
        raise MissingApiKeyError("DeepSeek")


def _map_error(exc: Exception) -> AppError:
    err = getattr(exc, "body", None)
    code = None
    if isinstance(err, dict):
        code = err.get("code")
    msg = str(exc) or "deepseek api error"
    if "timeout" in msg.lower() or isinstance(exc, TimeoutError):
        return UpstreamTimeoutError("deepseek", msg[:500])
    return UpstreamApiError("deepseek", msg[:500], upstream_code=str(code))


# ---- 同步实现 ----

def _route_sync(messages: list[dict], tools: list[dict]) -> dict:
    """返回 {"kind":"tool","name":...,"arguments":{...}} 或 {"kind":"text","text":...}。"""
    _check_key()
    try:
        resp = _get_client().chat.completions.create(
            model=config.MODEL_NAME,
            messages=messages,
            tools=tools or None,
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_error(exc) from exc
    msg = resp.choices[0].message
    if msg.tool_calls:
        tc = msg.tool_calls[0]
        try:
            arguments = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        return {"kind": "tool", "name": tc.function.name, "arguments": arguments}
    return {"kind": "text", "text": msg.content or ""}


def _chat_sync(messages: list[dict]) -> str:
    _check_key()
    try:
        resp = _get_client().chat.completions.create(
            model=config.MODEL_NAME, messages=messages, temperature=0.7,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_error(exc) from exc
    return resp.choices[0].message.content or ""


def _qa_sync(image_url: str, question: str, history_text: str = "") -> str:
    _check_key()
    content: list[dict] = [
        {"type": "text", "text": question},
    ]
    if image_url:
        content.append({"type": "image_url", "image_url": {"url": image_url}})
    messages: list[dict] = []
    if history_text:
        messages.append({
            "role": "system",
            "content": f"以下是此前对话背景，仅作参考：\n{history_text}",
        })
    messages.append({"role": "user", "content": content})
    try:
        resp = _get_client().chat.completions.create(
            model=config.VLM_MODEL, messages=messages, temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_error(exc) from exc
    return resp.choices[0].message.content or ""


# ---- 对外 async API ----

async def route_message(messages: list[dict], tools: list[dict]) -> dict:
    return await with_retry(
        lambda: run_sync(_route_sync, messages, tools),
        attempts=2, provider="deepseek",
    )


async def chat_text(messages: list[dict]) -> str:
    return await with_retry(
        lambda: run_sync(_chat_sync, messages),
        attempts=2, provider="deepseek",
    )


async def qa_image(image_url: str, question: str, history_text: str = "") -> str:
    return await with_retry(
        lambda: run_sync(_qa_sync, image_url, question, history_text),
        attempts=2, provider="deepseek",
    )
