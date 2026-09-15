"""个人作品风格 Wiki（Spec15 §5.2）：把散落的作品沉淀成两段风格自述。

职责边界（与 gallery / community / shares 同为"拿到 user_id 就干活"的业务模块）：
- 提取：只取**从未参与过合并**的作品（images.wiki_used = 0），并按来源分两路——
  上传作品逐张走视觉 QA（并发 WIKI_UPLOAD_QA_CONCURRENCY 路、单轮最多 WIKI_UPLOAD_QA_MAX 张），
  生成/绘图作品直接取其 prompt（单条截断 WIKI_PROMPT_ITEM_MAX + 总量封顶 WIKI_PROMPT_TOTAL_MAX）；
- 组提示词：**三段带标题**（历史风格 / 上传作品分析 / 生成作品描述），无材料的段整段略去（Spec15 §5.3b）；
- 调 LLM：复用既有 DeepSeek 纯文本通道（providers.deepseek.chat_text），不新增 provider；
- 清洗 + 落库：单事务写 wiki 并标记**真正被纳入**的作品（db.commit_style_update），失败则不落任何状态。

本模块只记 `wiki.upload_analysis_failed`（逐张失败需要 image_id，只有这里知道）；
`wiki.style_updated` / `wiki.refresh_skipped` 由 main.py 在路由层记（需要 request_id，
且不该把风格全文写进日志）。

Spec18：本模块是 `style` 类别计数的**唯一埋点处**——两次 `db.record_call(user_id, "style")`
分别在视觉调用与文本合成**发出之前**（§5.2B）。粒度与四类任务不同（按实际发出的上游
调用数，不是按任务），别顺手改成"成功后才记"。
"""
import asyncio
import logging

import config
import db
import gallery
import media
from agents.prompts import WIKI_STYLE_SYSTEM_PROMPT, WIKI_UPLOAD_QA_PROMPT
from errors import AppError, UpstreamApiError, WikiContentError
from providers import deepseek, qa

logger = logging.getLogger("wiki")


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
    """基于未纳入过的作品更新风格（Spec15 §5.2B，同步等 LLM）。

    返回 {updated, reason, style, prev_style, style_updated_at, used_count,
    pending_count, upload_analyzed, upload_failed}。

    - 没有待考虑作品 → updated=False / reason="nothing_new"，**不调 LLM、不写库、不改标记**；
    - 上传图分析全失败且没有可用的生成作品 → updated=False / reason="analysis_failed"（同上）。
    上游失败按既有 UpstreamApiError(61001) / UpstreamTimeoutError(61002) 抛出，库保持原样——
    **本轮已分析成功的上传图也不标记**，下次点按钮会重新分析（Spec15 §3 已知限制 1）。
    """
    pending = db.list_pending_style_images(user_id)
    if not pending:
        return _skip(user_id, "nothing_new", 0)

    # 上传段在前、生成段在后（Spec15 §2）；上传图受单轮张数上限约束，
    # 超上限的保持 wiki_used=0，下次点按钮继续 —— 与 Spec12 触顶截断的增量口径同构。
    uploads = [it for it in pending if it["source"] == "upload"][:config.WIKI_UPLOAD_QA_MAX]
    others = [it for it in pending if it["source"] != "upload"]

    analyses, failed = await _analyze_uploads(user_id, uploads)
    refs, prompt_ids = _collect_prompt_refs(others)
    used_ids = [a["id"] for a in analyses] + prompt_ids

    if not analyses and not refs:
        # 本次材料全部不可用：点了但没有可用材料的正常业务状态，不占错误码
        return _skip(user_id, "analysis_failed", len(pending), upload_failed=len(failed))

    history = db.get_wiki(user_id)["style"]
    # Spec18 §5.2B：风格合成也是一次真实调用；nothing_new / analysis_failed 两条
    # 跳过路径都到不了这里，所以它们天然是 0。
    db.record_call(user_id, "style")
    raw = await deepseek.chat_text(_build_messages(history, analyses, refs))
    style = _clean(raw)[:config.WIKI_STYLE_MAX]
    if not style:
        raise UpstreamApiError("deepseek", "风格生成返回为空")

    record = db.commit_style_update(user_id, style, used_image_ids=used_ids)
    # 触顶截断 / 超过上传分析上限时仍有剩余待考虑作品 → pending_count > 0，下次继续增量纳入
    pending_after = len(db.list_pending_style_images(user_id))
    return {**_style_out(record), "updated": True, "reason": None,
            "used_count": len(used_ids), "pending_count": pending_after,
            "upload_analyzed": len(analyses), "upload_failed": len(failed)}


def _skip(user_id: int, reason: str, pending_count: int, upload_failed: int = 0) -> dict:
    """「点了但没有可用材料」的响应（Spec15 §6.1b/c）：wiki 与 images.wiki_used 全不变。"""
    return {**_style_out(db.get_wiki(user_id)), "updated": False, "reason": reason,
            "used_count": 0, "pending_count": pending_count,
            "upload_analyzed": 0, "upload_failed": upload_failed}


def _style_out(record: dict) -> dict:
    """wiki 记录 → 响应字段（user_id 不外露）。"""
    return {
        "style": record["style"],
        "prev_style": record["prev_style"],
        "style_updated_at": record["style_updated_at"],
        "updated_at": record["updated_at"],
    }


async def _analyze_uploads(user_id: int, uploads: list[dict]) -> tuple[list[dict], list[dict]]:
    """逐张分析上传作品的风格（Spec15 §5.2B 第 A 步），返回 (成功列表, 失败列表)。

    并发 WIKI_UPLOAD_QA_CONCURRENCY 路；结果顺序与入参一致（= 时间倒序）。
    单张失败**跳过且不标记**（wiki_used 保持 0，下次点按钮自动重试）：整次失败会把已经
    花掉的视觉调用全部作废，永久标记则等于那张图再也不会被分析（Spec15 §2）。

    失败分类（Spec15 §5.4）：AppError 子类（61001/61002/61003/40403…）与清洗后为空；
    其它未预期异常**不吞**，整次刷新抛出（保持既有"失败即无痕"的边界清晰）。
    """
    if not uploads:
        return [], []
    sem = asyncio.Semaphore(max(1, config.WIKI_UPLOAD_QA_CONCURRENCY))

    async def one(item: dict) -> dict:
        async with sem:
            # 归属校验在 gallery 内兜底：即使 list_pending_style_images 出错也读不到别人的图
            _, image_bytes = gallery.read_gallery_file(item["id"], user_id)
            data_uri = media.to_data_uri(image_bytes, max_side=config.WIKI_UPLOAD_QA_MAX_SIDE)
            # Spec18 §5.2B：调用即将发出即记账（不是"成功后记"）。放在 read_gallery_file /
            # to_data_uri 之后，保证"图已被删"这类**根本没发出调用**的情况不被计费。
            db.record_call(user_id, "style")
            text = (await qa(data_uri, WIKI_UPLOAD_QA_PROMPT)).strip()
        if not text:
            raise UpstreamApiError("deepseek", "上传图风格分析返回为空")
        return {"id": item["id"], "created_at": item["created_at"],
                "text": text[:config.WIKI_UPLOAD_ANSWER_MAX]}

    results = await asyncio.gather(*(one(it) for it in uploads), return_exceptions=True)

    analyses: list[dict] = []
    failed: list[dict] = []
    for item, res in zip(uploads, results):
        if not isinstance(res, BaseException):
            analyses.append(res)
            continue
        if not isinstance(res, AppError):
            raise res
        reason = str(res)[:200]
        failed.append({"id": item["id"], "reason": reason})
        # 逐张都要有痕迹：否则用户只看到一个数字，排障无从下手（Spec15 §10）
        logger.warning("上传作品风格分析失败", extra={
            "event": "wiki.upload_analysis_failed",
            "user_id": user_id, "image_id": item["id"], "reason": reason,
        })
    return analyses, failed


def _collect_prompt_refs(pending: list[dict]) -> tuple[list[str], list[int]]:
    """生成/绘图作品按时间倒序（新 → 旧）提取 prompt，返回 (描述列表, 被纳入的作品 id 列表)。

    - 单条截断到 WIKI_PROMPT_ITEM_MAX；prompt 为空的记录跳过（不计入、不标记）。
    - 总长累计不超过 WIKI_PROMPT_TOTAL_MAX：装不下的这条**本次丢弃且不标记**，
      保持 wiki_used = 0（不 break —— 后面的短条目仍可把余量用完），
      下次点按钮继续算，增量语义自洽（Spec12 §5.2）。
    - 上传作品**不参与**触顶丢弃：视觉调用已经花掉了，再因为额度丢掉等于白烧一次调用；
      它们全部分析成功的都纳入（Spec15 §2），本函数的入参只含生成/绘图作品。
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


def _build_messages(history: str, analyses: list[dict], refs: list[str]) -> list[dict]:
    """组提示词（Spec15 §5.3b）：三段材料按需出现，**无材料的段整段略去**。

    留空标签会诱发"原有风格为空，我为你归纳"之类元话语（Spec12 §2 的既有教训）。
    「输出要求」恒定出现 —— 它不是材料段，是贴在材料上的即时语感要求。
    """
    parts: list[str] = []
    if history.strip():
        parts.append(f"【我的历史风格，这是我之前的作品风格】\n{history.strip()}")
    if analyses:
        body = "\n".join(f"{i}. {a['text']}" for i, a in enumerate(analyses, start=1))
        parts.append(f"【上传作品的风格分析】\n{body}")
    if refs:
        body = "\n".join(f"{i}. {t}" for i, t in enumerate(refs, start=1))
        parts.append(f"【生成作品的画面描述】\n{body}")
    parts.append(
        "【输出要求】无废话，简洁清楚自然有力，用简洁的语言描述清楚风格，"
        "不要说并不存在的风格。"
    )
    return [
        {"role": "system", "content": WIKI_STYLE_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
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
