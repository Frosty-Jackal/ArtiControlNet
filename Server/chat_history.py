"""对话历史业务层（Spec17 §5.2）：鉴权、落库编排、ThreadStore 回填。

分工：
- `db.py`      —— 纯 SQL（conversations / chat_messages 的 CRUD）。
- 本模块       —— 归属校验（越权与不存在同码 40407）、消息行 ↔ 路由上下文条目的
                  形态转换、助手结果的落库编排。
- `main.py`    —— HTTP 路由与 `ThreadStore`（内存路由上下文）。

**隐私**：消息正文一律不入日志（Spec17 §10），只记 id 与计数。
"""
import logging

import config
import db
from errors import ConversationNotFoundError

logger = logging.getLogger("chat_history")


# ---------- 鉴权 ----------

def require_owned(conv_id: str, user_id: int) -> dict:
    """取本人对话；不存在或不属于本人 → 40407（不泄露存在性）。"""
    conv = db.find_owned_conversation(conv_id, user_id)
    if conv is None:
        raise ConversationNotFoundError()
    return conv


# ---------- 路由上下文回填（Spec17 §5.2B） ----------

def to_thread_entry(row: dict) -> dict:
    """chat_messages 行 → ThreadStore 条目。

    形态对齐 `POST /api/chat` 里 `store.append` 的写法：
      user      → {"role","text","image_url"}
      assistant → {"role","text","images":[...]}
    图片地址用作品库引用，`media.fetch_image_bytes` 认得它（§5.2A）。
    这样 Supervisor 的 `_recent_images` / `_build_messages` / `_history_text`
    一行都不用改。
    """
    entry = {"role": row["role"], "text": row["text"] or ""}
    if row["image_id"]:
        ref = f"/api/gallery/{row['image_id']}/file"
        if row["role"] == "user":
            entry["image_url"] = ref
        else:
            entry["images"] = [ref]
    return entry


def load_recent_entries(conv_id: str, limit: int) -> list[dict]:
    """取某段对话最近 limit 条，转成路由上下文条目（时间正序）。"""
    return [to_thread_entry(r) for r in db.list_recent_chat_messages(conv_id, limit)]


# ---------- 落库编排（Spec17 §5.2B / §5.2C） ----------

def start_turn(conv_id: str, user_id: int, *, text: str,
               image_id: int | None) -> dict:
    """用户消息落库：确保 conversations 行存在 → 追加 user 消息。

    "消息驱动"的对话创建（§5.3）：新对话在这一步才真正建行，只有确保行存在
    且消息写进去之后才认为成功。
    """
    db.ensure_conversation(conv_id, user_id)
    return db.add_chat_message(conv_id, user_id, "user", text=text,
                               image_id=image_id, task_id=None, tool=None)


def record_assistant_reply(conv_id: str, user_id: int, result: dict,
                           task_id: int) -> dict | None:
    """把一次**成功**的助手结果落库为一条 assistant 消息（§5.2C）。

    失败 / 超时 / 排队被拒的结果**不落库**（§3.4）——失败气泡是瞬时 UI 状态，
    重试会产生新结果，落库只会让历史里堆满已无意义的错误。

    `image_ids` 可能为空（`save_gallery_image` 只在 user_id 非空时调用），
    故取首项带 `or [None]` 兜底——避免 IndexError 让一个本已成功的任务在落库
    这一步翻车（落库失败不该改变任务的成功/失败归属）。

    `task_id` 只在 `tool` 非空时写入：纯文本回复没有可反馈的对象，
    前端也不会为它渲染 👍/👎。

    对话已被用户删掉时直接返回 None：任务在飞的时候删对话是合法操作，
    此时补写会留下一条永远看不到的孤儿消息。
    """
    if db.get_conversation(conv_id) is None:
        return None

    if result.get("kind") == "text":
        return db.add_chat_message(conv_id, user_id, "assistant",
                                   text=result.get("text", ""),
                                   image_id=None, task_id=None, tool=None)

    tool = result.get("tool") or None
    image_id = (result.get("image_ids") or [None])[0]
    return db.add_chat_message(conv_id, user_id, "assistant", text=None,
                               image_id=image_id,
                               task_id=task_id if tool else None, tool=tool)


# ---------- 接口层用的读 / 删 ----------

def list_conversations(user_id: int) -> list[dict]:
    """本人对话列表（updated_at 倒序，上限 CONVERSATION_LIST_LIMIT，不分页）。

    只投影 `id` / `created_at` / `updated_at`（§6.3）——`user_id` 是查询条件不是
    返回内容，和 `get_conversation_messages` 里 `conversation` 的投影保持一致。
    """
    return [{"id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"]}
            for c in db.list_conversations(user_id, config.CONVERSATION_LIST_LIMIT)]


def get_conversation_messages(conv_id: str, user_id: int) -> dict:
    """`GET /api/conversations/{id}/messages` 的 data：对话元信息 + 全部消息。

    **不返回 vote**：Spec9 起"我在哪条结果上点过什么"只存在前端气泡上，
    `feedback` 表按类聚合。重新载入的历史气泡反馈按钮显示为未选
    （Spec17 §6.4），这是既有的口径，本 Spec 不改变它。
    """
    conv = require_owned(conv_id, user_id)
    return {
        "conversation": {
            "id": conv["id"],
            "created_at": conv["created_at"],
            "updated_at": conv["updated_at"],
        },
        "messages": db.list_chat_messages(conv_id),
    }


def delete_conversation(conv_id: str, user_id: int) -> dict:
    """删本人的一段对话及其全部消息；**不删任何图片**（§6.5）。

    不存在 / 不属于本人 → 40407（不是静默成功：前端只会拿到自己列表里的 id，
    触发即 bug）。
    """
    require_owned(conv_id, user_id)
    message_count = db.count_chat_messages(conv_id)
    db.delete_conversation(conv_id)
    return {"id": conv_id, "message_count": message_count}
