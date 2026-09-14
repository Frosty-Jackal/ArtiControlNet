"""个人作品风格 Wiki（Spec12 §5.2）：把散落的作品 prompt 沉淀成一段风格自述。

职责边界（与 gallery / community / shares 同为"拿到 user_id 就干活"的业务模块）：
- 提取：只取**从未参与过合并**的生成/绘图作品（images.wiki_used = 0），单条截断 +
  总量封顶（WIKI_PROMPT_ITEM_MAX / WIKI_PROMPT_TOTAL_MAX），触顶被丢弃的作品不标记；
- 组提示词：wiki.style 非空走「合并」提示词，为空走「首次生成」提示词（Spec12 §2）；
- 调 LLM：复用既有 DeepSeek 纯文本通道（providers.deepseek.chat_text），不新增 provider；
- 清洗 + 落库：单事务写 wiki 并标记作品（db.commit_style_update），失败则不落任何状态。

本模块不直接写日志：`wiki.style_updated` / `wiki.refresh_skipped` 由 main.py 在路由层记
（需要 request_id，且不该把风格全文写进日志）。
"""
import config
import db
from agents.prompts import WIKI_INIT_SYSTEM_PROMPT, WIKI_MERGE_SYSTEM_PROMPT
from errors import UpstreamApiError, WikiContentError
from providers import deepseek


# ---------- 读 / 手动编辑 ----------

def get_wiki(user_id: int) -> dict:
    """读本人 Wiki；行不存在返回全空默认值（不建行）。"""
    return _style_out(db.get_wiki(user_id))


def update_style_manually(user_id: int, text: str) -> dict:
    """手动覆盖风格（Spec12 §5.2C）：校验 → 单事务写库（旧风格进 prev_style）。

    不触碰 images.wiki_used —— 手动改风格是覆盖式动作，不消费任何作品。
    非法内容（strip 后为空 / 超长）→ WikiContentError(40014)。
    """
    style = (text or "").strip()
    if not style or len(style) > config.WIKI_STYLE_MAX:
        raise WikiContentError(f"风格内容需为 1~{config.WIKI_STYLE_MAX} 字")
    return _style_out(db.commit_style_update(user_id, style))


# ---------- 基于新作品更新 ----------

async def refresh_style(user_id: int) -> dict:
    """基于未纳入过的作品更新风格（Spec12 §5.2B，同步等 LLM）。

    返回 {updated, reason, style, prev_style, style_updated_at, used_count, pending_count}。
    没有待考虑作品时 → updated=False / reason="nothing_new"，**不调 LLM、不写库、不改标记**。
    上游失败按既有 UpstreamApiError(61001) / UpstreamTimeoutError(61002) 抛出，库保持原样。
    """
    pending = db.list_pending_style_images(user_id)
    if not pending:
        return {**_style_out(db.get_wiki(user_id)), "updated": False,
                "reason": "nothing_new", "used_count": 0, "pending_count": 0}

    refs, used_ids = _collect_references(pending)
    current_style = db.get_wiki(user_id)["style"]
    raw = await deepseek.chat_text(_build_messages(current_style, refs))
    style = _clean(raw)[:config.WIKI_STYLE_MAX]
    if not style:
        raise UpstreamApiError("deepseek", "风格生成返回为空")

    record = db.commit_style_update(user_id, style, used_image_ids=used_ids)
    # 触顶截断时仍有剩余待考虑作品 → pending_count > 0，下次点按钮继续增量纳入
    pending_after = len(db.list_pending_style_images(user_id))
    return {**_style_out(record), "updated": True, "reason": None,
            "used_count": len(used_ids), "pending_count": pending_after}


def _style_out(record: dict) -> dict:
    """wiki 记录 → 响应字段（user_id 不外露）。"""
    return {
        "style": record["style"],
        "prev_style": record["prev_style"],
        "style_updated_at": record["style_updated_at"],
        "updated_at": record["updated_at"],
    }


def _collect_references(pending: list[dict]) -> tuple[list[str], list[int]]:
    """按时间倒序（新 → 旧）提取参考文字，返回 (参考文字列表, 被纳入的作品 id 列表)。

    - 单条截断到 WIKI_PROMPT_ITEM_MAX；prompt 为空的记录跳过（不计入、不标记）。
    - 总长累计不超过 WIKI_PROMPT_TOTAL_MAX：装不下的这条**本次丢弃且不标记**，
      保持 wiki_used = 0（不 break —— 后面的短条目仍可把余量用完），
      下次点按钮继续算，增量语义自洽（Spec12 §5.2）。
    """
    refs: list[str] = []
    used_ids: list[int] = []
    total = 0
    for item in pending:
        text = (item.get("prompt") or "").strip()[:config.WIKI_PROMPT_ITEM_MAX]
        if not text:
            continue
        if total + len(text) > config.WIKI_PROMPT_TOTAL_MAX:
            continue
        refs.append(text)
        used_ids.append(item["id"])
        total += len(text)
    return refs, used_ids


def _build_messages(current_style: str, refs: list[str]) -> list[dict]:
    """组提示词（Spec12 §5.2B 第 3 步）：首次分支只给参考文字，不出现空的「个人作品风格：」。"""
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(refs, start=1))
    if current_style.strip():
        system = WIKI_MERGE_SYSTEM_PROMPT
        user = (f"个人作品风格：\n{current_style.strip()}\n\n"
                f"新提取的作品风格参考文字：\n{numbered}")
    else:
        system = WIKI_INIT_SYSTEM_PROMPT
        user = f"新提取的作品风格参考文字：\n{numbered}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _clean(raw: str) -> str:
    """清洗 LLM 返回值：strip → 剥 ``` 包裹 → 再 strip（Spec12 §5.2B 第 4 步）。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text[3:]
        if "\n" in text:
            text = text.split("\n", 1)[1]   # 丢掉 ```lang 那一行
        text = text.rstrip()
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
