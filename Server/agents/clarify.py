"""追问文案格式化（Spec6 §5.1）。

选项清单是确定性的：后端按 ask_clarification 的 missing 参数名，把每个缺失参数的
可选项（含「不指定/默认」项）拼成固定文案，LLM 不再自由写追问文案。口径与
prompts.py 的工具定义 / 系统提示词保持一致（Spec6 §3 决策记录）。
"""
from __future__ import annotations

# 画幅选项清单：固定清单 + 自定义范围说明（Spec6 §3「size 选项」决策）
_SIZE_OPTIONS_LINE = (
    "画幅想用哪种？可选：1:1（1024x1024）/ 16:9（1024x576）/ 9:16（576x1024）"
    "/ 4:3（1024x768）/ 3:4（768x1024）；也可以直接说「宽x高」自定义"
    "（宽高 512~2048、面积 ≤1024²）；或回复「随便」用默认画幅。"
)

# 每个缺失参数对应的固定追问文案。参数名全集：prompt / image_url / size / question。
_CLARIFY_TEXTS: dict[str, str] = {
    "prompt": "请描述你想要什么样的画面（主体 / 场景 / 配色等）。",
    "image_url": "请上传参考图（或给出已上传图片的说明）。",
    "size": _SIZE_OPTIONS_LINE,
    "question": (
        "想了解这张图的什么？比如：画面内容 / 构图 / 色彩 / 风格 / 光线。"
        "回复「看你」则自动描述画面内容。"
    ),
}

_DEFAULT_TEXT = "还需要补充哪些信息？请告诉我。"


def format_clarify(missing: list[str] | None) -> str:
    """按缺失参数名生成固定追问文案。

    missing 为空或含未知参数名时回退到默认文案；多项缺失时逐条列出。
    """
    parts = [_CLARIFY_TEXTS[k] for k in (missing or []) if k in _CLARIFY_TEXTS]
    if not parts:
        return _DEFAULT_TEXT
    if len(parts) == 1:
        return parts[0]
    return "我还需要知道以下几点：\n" + "\n".join(f"• {p}" for p in parts)
