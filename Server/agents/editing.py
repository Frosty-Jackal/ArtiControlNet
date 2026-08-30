"""Edit 子 Agent：线稿生图（图像编辑）。黑白线稿 + 文字 → 完整绘制图。

Spec5 增量：size（透传 TokenHub）；成功结果持久化到个人作品库（source='edit'）。
Spec6 增量：删除独立 style 参数；prompt 透传主 Agent 原文——API 发送保留 MAX_PROMPT_LEN
防御性截断，画廊入库存截断前完整原文（作品 prompt = 用户原话）。
"""
import re

import gallery
from errors import RouterError
from media import enforce_sketch_input, fetch_image_bytes, save_image
from providers import edit

MAX_PROMPT_LEN = 200

_SIZE_RE = re.compile(r"^(\d{3,4})x(\d{3,4})$")
_SIZE_MIN = 512
_SIZE_MAX = 2048
_SIZE_MAX_AREA = 1024 * 1024

# 预设比例（含短横式别名）→ 规范化像素尺寸（Spec7 §5.1）。
# 与 prompts.py 工具定义/系统提示词口径一致；主 Agent 传比例或像素都能通过。
_SIZE_PRESETS = {
    "1:1": "1024x1024",  "1x1": "1024x1024",
    "16:9": "1024x576",  "16x9": "1024x576",
    "9:16": "576x1024",  "9x16": "576x1024",
    "4:3": "1024x768",   "4x3": "1024x768",
    "3:4": "768x1024",   "3x4": "768x1024",
}


def validate_size(size: str) -> str | None:
    """校验并规范化 size：预设比例 → 像素；像素形式 `宽x高` 校验宽高 ∈ [512,2048] 且面积 ≤1024×1024。

    未指定 → None；非法值 → RouterError（61004，任务失败）。
    """
    size = (size or "").strip().lower()
    if not size:
        return None
    preset = _SIZE_PRESETS.get(size)        # 预设比例/别名 → 规范化像素（Spec7 §5.1）
    if preset:
        return preset
    m = _SIZE_RE.match(size)
    if not m:
        raise RouterError(f"size 参数非法: {size}"
                          f"（应为 1:1 / 16:9 / 9:16 / 4:3 / 3:4 或 宽x高，如 1024x576）")
    w, h = int(m.group(1)), int(m.group(2))
    if not (_SIZE_MIN <= w <= _SIZE_MAX and _SIZE_MIN <= h <= _SIZE_MAX):
        raise RouterError(f"size 参数非法: {size}（宽高需在 {_SIZE_MIN}~{_SIZE_MAX} 之间）")
    if w * h > _SIZE_MAX_AREA:
        raise RouterError(f"size 参数非法: {size}（面积超出 1024×1024 限制）")
    return f"{w}x{h}"


async def run(args: dict) -> dict:
    prompt = str(args.get("prompt") or "").strip()
    image_url = args.get("image_url") or ""
    if not prompt:
        raise RouterError("线稿生图缺少 prompt 参数")
    if not image_url:
        raise RouterError("线稿生图缺少 image_url 参数")
    size = validate_size(args.get("size"))
    # 透传主 Agent 的 prompt 原文（Spec6 §5.2）：仅 API 发送时防御性截断，
    # 画廊入库存截断前完整原文，作品 prompt = 用户原话。
    send_prompt = prompt[:MAX_PROMPT_LEN]

    # 取线稿 → 校验格式 → 按接口限制压缩（单边 ≤2000px，base64 ≤6MB）
    image_bytes = await fetch_image_bytes(image_url, args.get("public_base", ""))
    image_bytes = enforce_sketch_input(image_bytes)

    result = await edit(send_prompt, image_bytes, size or "")
    url = save_image(result, public_base=args.get("public_base", ""))
    user_id = args.get("user_id")
    if user_id is not None:
        gallery.save_gallery_image(result, user_id, "edit", prompt)
    return {"kind": "images", "images": [url]}
