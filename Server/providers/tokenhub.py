"""TokenHub 统一生图提供方（hy-image-v3，Spec §7.2 / §7.3）。

文生图与线稿生图（图生图）都走同一个 OpenAI 风格同步接口：
    POST {TOKENHUB_API_URL}
    Authorization: Bearer {TOKENHUB_API_KEY}
- 文生图：{model, prompt, size}
- 图生图：在文生图基础上加 images=[data URI 或 URL]（0~3 张，png/jpeg/jpg，每张 ≤10MB）

响应同步返回 data[0].url（仅 12h 有效）→ 立即下载字节转存本地（Spec §7.3 注意事项 1）。
内部为同步 httpx 调用，对外统一 async（线程池）。
"""
import base64
import logging

import httpx

import config
from errors import (AppError, MissingApiKeyError, UpstreamApiError,
                    UpstreamTimeoutError)
from providers import run_sync, with_retry

logger = logging.getLogger("providers")

PROVIDER = "hunyuan-image"


def _data_uri(image_bytes: bytes) -> str:
    """把图片字节转成 data URI（按魔数识别 mime）。"""
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif image_bytes.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif image_bytes.startswith(b"GIF8"):
        mime = "image/gif"
    elif image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/png"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _raise_upstream(resp: httpx.Response) -> None:
    """把非 200 的 HTTP 响应映射为 UpstreamApiError（上游错误码透传）。"""
    try:
        err = (resp.json() or {}).get("error") or {}
    except ValueError:
        err = {}
    msg = err.get("message") or err.get("message_zh") or resp.text[:300]
    code = err.get("code") or f"HTTP_{resp.status_code}"
    raise UpstreamApiError(PROVIDER, f"{code}: {msg}", upstream_code=str(code))


def _sync_generate(prompt: str, images: list[str] | None, size: str) -> bytes:
    if not config.TOKENHUB_API_KEY:
        raise MissingApiKeyError("TokenHub")
    payload: dict = {"model": config.HUNYUAN_IMAGE_MODEL, "prompt": prompt}
    if images:
        payload["images"] = images
    if size:
        payload["size"] = size
    headers = {"Authorization": f"Bearer {config.TOKENHUB_API_KEY}"}
    try:
        with httpx.Client(timeout=config.TOKENHUB_TIMEOUT_SECONDS,
                          follow_redirects=True) as client:
            resp = client.post(config.TOKENHUB_API_URL, json=payload,
                               headers=headers)
            if resp.status_code != 200:
                _raise_upstream(resp)
            data = (resp.json() or {}).get("data") or []
            img_url = data[0].get("url") if data else None
            if not img_url:
                raise UpstreamApiError(PROVIDER, "响应缺少生成图片 URL",
                                       upstream_code="no_image_url")
            # 生成图 URL 仅 12h 有效 → 立即下载字节，交给上层转存 storage/
            img = client.get(img_url)
            img.raise_for_status()
            return img.content
    except AppError:
        raise
    except httpx.TimeoutException as exc:
        raise UpstreamTimeoutError(PROVIDER, "上游生成超时") from exc
    except httpx.HTTPError as exc:
        raise UpstreamApiError(PROVIDER, f"网络错误: {exc}",
                               upstream_code="http_error") from exc


# ---- 对外 async API ----

async def generate_image(prompt: str, size: str | None = None) -> bytes:
    return await with_retry(
        lambda: run_sync(_sync_generate, prompt, None,
                         size or config.HUNYUAN_IMAGE_SIZE),
        attempts=2, provider=PROVIDER,
    )


async def sketch_to_image(prompt: str, input_image: bytes,
                          size: str | None = None) -> bytes:
    data_uri = _data_uri(input_image)
    return await with_retry(
        lambda: run_sync(_sync_generate, prompt, [data_uri],
                         size or config.HUNYUAN_IMAGE_SIZE),
        attempts=2, provider=PROVIDER,
    )
