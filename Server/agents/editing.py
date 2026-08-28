"""Edit 子 Agent：线稿生图（图像编辑）。黑白线稿 + 文字 → 完整绘制图。"""
from errors import RouterError
from media import enforce_sketch_input, fetch_image_bytes, save_image
from providers import edit

MAX_PROMPT_LEN = 200


async def run(args: dict) -> dict:
    prompt = str(args.get("prompt") or "").strip()
    image_url = args.get("image_url") or ""
    if not prompt:
        raise RouterError("线稿生图缺少 prompt 参数")
    if not image_url:
        raise RouterError("线稿生图缺少 image_url 参数")
    prompt = prompt[:MAX_PROMPT_LEN]

    # 取线稿 → 校验格式 → 按接口限制压缩（单边 ≤2000px，base64 ≤6MB）
    image_bytes = await fetch_image_bytes(image_url, args.get("public_base", ""))
    image_bytes = enforce_sketch_input(image_bytes)

    result = await edit(prompt, image_bytes)
    url = save_image(result, public_base=args.get("public_base", ""))
    return {"kind": "images", "images": [url]}
