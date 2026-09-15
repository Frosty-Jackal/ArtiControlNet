"""QA 子 Agent：图像问答。图片 + 问题 → 文本回答。"""
import config
from errors import ImageTooLargeError, RouterError
from media import fetch_image_bytes, to_data_uri
from providers import qa


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

    data_uri = to_data_uri(image_bytes)

    text = await qa(data_uri, question, history_text=args.get("history_text") or "")
    return {"kind": "text", "text": text}
