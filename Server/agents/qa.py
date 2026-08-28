"""QA 子 Agent：图像问答。图片 + 问题 → 文本回答。"""
import base64

import config
from errors import ImageTooLargeError, RouterError
from media import detect_ext, fetch_image_bytes
from providers import qa

_MIME = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png",
         ".webp": "webp", ".gif": "gif"}


async def run(args: dict) -> dict:
    question = str(args.get("question") or "").strip()
    image_url = args.get("image_url") or ""
    if not question:
        raise RouterError("图像问答缺少 question 参数")
    if not image_url:
        raise RouterError("图像问答缺少 image_url 参数")

    image_bytes = await fetch_image_bytes(image_url, args.get("public_base", ""))
    if len(image_bytes) > config.QA_IMAGE_MAX_BYTES:
        raise ImageTooLargeError("图片超过 32MiB，无法用于图像问答")

    ext = detect_ext(image_bytes)
    mime = _MIME.get(ext, "jpeg")
    data_uri = f"data:image/{mime};base64,{base64.b64encode(image_bytes).decode()}"

    text = await qa(data_uri, question, history_text=args.get("history_text") or "")
    return {"kind": "text", "text": text}
