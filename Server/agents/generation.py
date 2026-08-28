"""Generation 子 Agent：文生图。prompt → 图片 URL 列表（纯图片，无文本包裹）。"""
from errors import RouterError
from media import save_image
from providers import generate

MAX_PROMPT_LEN = 256


async def run(args: dict) -> dict:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise RouterError("文生图缺少 prompt 参数")
    prompt = prompt[:MAX_PROMPT_LEN]

    image_bytes = await generate(prompt)
    url = save_image(image_bytes, public_base=args.get("public_base", ""))
    return {"kind": "images", "images": [url]}
