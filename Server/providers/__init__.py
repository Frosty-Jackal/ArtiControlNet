"""提供方统一工厂（Spec §12）：按用途暴露 generate / edit / qa / route。

所有外部调用是同步 SDK，此处统一包成 async（asyncio.to_thread），
并带轻量退避重试与 provider.retry JSON 日志。
"""
import asyncio
import logging

from errors import AppError, UpstreamApiError, UpstreamTimeoutError

logger = logging.getLogger("providers")

__all__ = ["generate", "edit", "qa", "route", "run_sync", "with_retry"]


async def run_sync(fn, *args, **kwargs):
    """把阻塞的外部调用放进线程池，避免卡住事件循环。"""
    return await asyncio.to_thread(fn, *args, **kwargs)


async def with_retry(fn, *, attempts: int = 2, base_delay: float = 1.0,
                     provider: str = "upstream") -> object:
    """对可重试的上游错误做退避重试，并打 provider.retry 日志。

    fn 为返回 coroutine 的工厂（如 lambda: run_sync(_sync_call, ...)）。
    不可重试的错误直接抛出。
    """
    last: AppError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except (UpstreamTimeoutError, UpstreamApiError) as exc:
            last = exc
            if attempt >= attempts or not _is_retryable(exc):
                raise
            logger.warning(
                f"上游异常，第 {attempt} 次重试",
                extra={"event": "provider.retry", "provider": provider},
            )
            await asyncio.sleep(base_delay * attempt)
    raise last  # pragma: no cover


def _is_retryable(exc: AppError) -> bool:
    if isinstance(exc, UpstreamTimeoutError):
        return True
    code = (exc.upstream_code or "").lower()
    return any(k in code for k in (
        "requestlimitexceeded", "internalservererror", "timeout", "gatewaytimeout",
    ))


# ---- 按用途暴露 ----

async def generate(prompt: str, size: str = "") -> bytes:
    from providers import tokenhub
    return await tokenhub.generate_image(prompt, size or None)


async def edit(prompt: str, input_image: bytes, size: str = "") -> bytes:
    from providers import tokenhub
    return await tokenhub.sketch_to_image(prompt, input_image, size or None)


async def qa(image_url: str, question: str, history_text: str = "") -> str:
    from providers import deepseek
    return await deepseek.qa_image(image_url, question, history_text)


async def route(messages: list[dict], tools: list[dict]) -> dict:
    from providers import deepseek
    return await deepseek.route_message(messages, tools)
