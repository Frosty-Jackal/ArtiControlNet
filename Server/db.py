"""SQLite 账号库封装（Spec2 §5.2 / §5.3）。

- 零新依赖：Python 标准库 `sqlite3`，单文件 Server/artcn.db。
- 持久化：与 storage/ 临时目录无关，后端重启不清库。
- 线程安全：每次操作开新连接；启用 WAL 提升并发读写。
- 首次启动（users 表为空）时按 .env 的 ADMIN_USERNAME/ADMIN_PASSWORD 自动创建初始管理员，
  避免"建号需要管理员但还没有管理员"的死锁。
"""
import logging
import sqlite3
from datetime import datetime, timezone

import config
from errors import DuplicateUsernameError

logger = logging.getLogger("db")

AUTH_DB_PATH = config.AUTH_DB_PATH

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
)
"""

# 4 类调用计数表（Spec4 §5.4）：每用户一行，任务成功完成后 +1。
_CREATE_USAGE_TABLE = """
CREATE TABLE IF NOT EXISTS usage (
    user_id    INTEGER PRIMARY KEY,
    chat       INTEGER NOT NULL DEFAULT 0,
    generate   INTEGER NOT NULL DEFAULT 0,
    edit       INTEGER NOT NULL DEFAULT 0,
    qa         INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
)
"""

# 计数列白名单（record_call 据此拼列名，绝不拼接外部输入）
_USAGE_CATEGORIES = ("chat", "generate", "edit", "qa")

# 个人作品库表（Spec5 §5.3）：文件与元数据分离，文件字节在 Server/gallery/。
_CREATE_IMAGES_TABLE = """
CREATE TABLE IF NOT EXISTS images (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    source     TEXT NOT NULL,
    file_name  TEXT NOT NULL,
    ext        TEXT NOT NULL,
    prompt     TEXT,
    created_at TEXT NOT NULL
)
"""

# 画廊按用户 + 时间倒序（Spec5 §5.3 索引）
_CREATE_IMAGES_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_images_user_created "
    "ON images(user_id, created_at DESC)"
)

# 社区帖子表（Spec9 §5.2）：单图 + 文字；图片字节在 Server/community/。
_CREATE_POSTS_TABLE = """
CREATE TABLE IF NOT EXISTS posts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,             -- 作者
    text       TEXT NOT NULL,                -- 心得文字（1~1000 字，前后端校验）
    image_file TEXT NOT NULL,                -- community/ 下持久文件名（uuid + ext）
    ext        TEXT NOT NULL,                -- .jpg|.jpeg|.png|.webp|.gif
    created_at TEXT NOT NULL
)
"""
_CREATE_POSTS_INDEX = "CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC)"

# 帖子点赞/点踩（Spec9 §5.2）：每帖每用户一行
_CREATE_POST_VOTES_TABLE = """
CREATE TABLE IF NOT EXISTS post_votes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    vote       TEXT NOT NULL,                -- 'like' | 'dislike'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(post_id, user_id)
)
"""

# AI 服务反馈（Spec9 §5.2）：一行 = 一次 AI 服务结果（task_id 后端唯一标识）
_CREATE_FEEDBACK_TABLE = """
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER NOT NULL UNIQUE,      -- 标识"哪一次结果"（重启边界见 Spec9 §3.5）
    user_id    INTEGER NOT NULL,             -- 投票人（删用户级联）
    category   TEXT NOT NULL,                -- 'generate' | 'edit' | 'qa'
    vote       TEXT NOT NULL,                -- 'like' | 'dislike'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

# 临时分享链接（Spec9 §5.2）：token 唯一，一个作品一条分享
_CREATE_SHARES_TABLE = """
CREATE TABLE IF NOT EXISTS shares (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT NOT NULL UNIQUE,         -- secrets.token_urlsafe(16)
    image_id   INTEGER NOT NULL,             -- 引用 images.id（作品）
    user_id    INTEGER NOT NULL,             -- 创建者
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL                 -- created_at + SHARE_TTL_SECONDS
)
"""

# 建议箱（Spec9 §5.2）
_CREATE_SUGGESTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS suggestions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,             -- 发送者
    text       TEXT NOT NULL,                -- ≤2000 字
    status     TEXT NOT NULL DEFAULT 'pending', -- pending|read|resolved
    reply      TEXT,                         -- 管理员回复
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""
_CREATE_SUGGESTIONS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_suggestions_user "
    "ON suggestions(user_id, created_at DESC)"
)

# 反馈类别白名单（set_feedback 校验，不拼接外部输入）
_FEEDBACK_CATEGORIES = ("generate", "edit", "qa")
_FEEDBACK_VOTES = ("like", "dislike")
# 建议状态白名单（update_suggestion 校验）
_SUGGESTION_STATUSES = ("pending", "resolved")  # Spec10：收敛两态，去掉 read / 待用户处理


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(AUTH_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "password_hash": row["password_hash"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
    }


def _image_row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "source": row["source"],
        "file_name": row["file_name"],
        "ext": row["ext"],
        "prompt": row["prompt"],
        "created_at": row["created_at"],
    }


def _post_row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """帖子行 → dict（含图片文件元数据，供读图/删除使用）。"""
    if row is None:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "text": row["text"],
        "image_file": row["image_file"],
        "ext": row["ext"],
        "created_at": row["created_at"],
    }


def _share_row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "token": row["token"],
        "image_id": row["image_id"],
        "user_id": row["user_id"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }


def _suggestion_row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "text": row["text"],
        "status": row["status"],
        "reply": row["reply"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------- 生命周期 ----------

def init_db() -> None:
    """建表；users 表为空时按 .env 配置创建初始管理员。"""
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_USAGE_TABLE)
        conn.execute(_CREATE_IMAGES_TABLE)
        conn.execute(_CREATE_IMAGES_INDEX)
        conn.execute(_CREATE_POSTS_TABLE)
        conn.execute(_CREATE_POSTS_INDEX)
        conn.execute(_CREATE_POST_VOTES_TABLE)
        conn.execute(_CREATE_FEEDBACK_TABLE)
        conn.execute(_CREATE_SHARES_TABLE)
        conn.execute(_CREATE_SUGGESTIONS_TABLE)
        conn.execute(_CREATE_SUGGESTIONS_INDEX)
        # Spec10：建议状态收敛为 pending|resolved；老数据 read（已读）迁移为 pending
        conn.execute("UPDATE suggestions SET status = 'pending' WHERE status = 'read'")
        conn.commit()
    if count_users() > 0:
        return
    create_initial_admin()


def create_initial_admin() -> None:
    """创建初始管理员。未配置 / 格式非法 → 启动报错，绝不生成弱口令（Spec2 §7）。"""
    username = config.ADMIN_USERNAME.strip()
    password = config.ADMIN_PASSWORD
    if not username or not password:
        raise RuntimeError(
            "首次启动需要初始管理员：请在 Server/.env 配置 ADMIN_USERNAME 与 ADMIN_PASSWORD"
        )
    if len(username) < 2:
        raise RuntimeError("ADMIN_USERNAME 过短（至少 2 个字符）")
    if len(password) < 6:
        raise RuntimeError("ADMIN_PASSWORD 过短（至少 6 位）")
    from auth import hash_password  # 延迟导入，避免与 auth.py 循环依赖
    create_user(username, hash_password(password), is_admin=True)
    logger.info(f"已创建初始管理员: {username}", extra={"event": "auth.admin.init"})


# ---------- 查询 ----------

def get_user_by_id(user_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_dict(row)


def get_user_by_username(username: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return _row_to_dict(row)


def count_users() -> int:
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    return int(row["n"])


def count_admins() -> int:
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM users WHERE is_admin = 1").fetchone()
    return int(row["n"])


# ---------- 写操作 ----------

def create_user(username: str, password_hash: str, is_admin: bool = False) -> dict:
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) "
                "VALUES (?, ?, ?, ?)",
                (username, password_hash, 1 if is_admin else 0, _now_iso()),
            )
            conn.commit()
            user_id = cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise DuplicateUsernameError(f"用户名已存在: {username}") from exc
    return get_user_by_id(user_id)


def list_users() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY id ASC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_password(user_id: int, password_hash: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def set_admin(user_id: int, is_admin: bool) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?",
            (1 if is_admin else 0, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def delete_user(user_id: int) -> bool:
    """删除用户；连带删除其 usage / images / 社区 / 反馈 / 分享 / 建议记录，保证口径一致
    （Spec4 §3 / Spec5 §3 / Spec9 §3）。

    注意：仅删除数据库记录。gallery/ 物理文件由 gallery.delete_user_gallery 负责、
    community/ 物理文件由 community.delete_user_posts 负责（都先取文件名再删文件，
    见 main.py admin_delete_user）。帖子投票：本函数删该用户投过的票；其帖子上的
    他人投票由 delete_user_post_records 一并处理。
    """
    with _connect() as conn:
        conn.execute("DELETE FROM usage WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM images WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM post_votes WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM feedback WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM shares WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM suggestions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM posts WHERE user_id = ?", (user_id,))
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return cur.rowcount > 0


# ---------- 使用统计（Spec4） ----------

def record_call(user_id: int, category: str) -> None:
    """任务成功完成后累计一次调用（UPSERT，首次调用即计 1）。

    新行各列插 0、目标列插 1；已存在行用 excluded 增量累加，避免首次调用被吞。
    category 取自固定白名单；列名均为静态字面量，不拼接外部输入。
    """
    if category not in _USAGE_CATEGORIES:
        raise ValueError(f"未知统计类别: {category}")
    values = {c: (1 if c == category else 0) for c in _USAGE_CATEGORIES}
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO usage (user_id, chat, generate, edit, qa, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "chat = chat + excluded.chat, "
            "generate = generate + excluded.generate, "
            "edit = edit + excluded.edit, "
            "qa = qa + excluded.qa, "
            "updated_at = excluded.updated_at",
            (user_id, values["chat"], values["generate"], values["edit"],
             values["qa"], now),
        )
        conn.commit()


def get_usage_stats() -> dict:
    """聚合统计（管理员只读）：4 类总数 / 注册人数 / 人均 / 占比。

    - user_count = users 表当前注册人数（含 0 次调用者）。
    - 人均 = 各类总数 ÷ user_count；占比 = 各类总数 ÷ 总调用 × 100。
    - 分母为 0 时对应项全部取 0。
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(chat), 0)     AS chat, "
            "       COALESCE(SUM(generate), 0) AS generate, "
            "       COALESCE(SUM(edit), 0)     AS edit, "
            "       COALESCE(SUM(qa), 0)       AS qa "
            "FROM usage"
        ).fetchone()
        user_count = int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])

    totals = {c: int(row[c]) for c in _USAGE_CATEGORIES}
    total_calls = sum(totals.values())
    per_user_avg = {
        c: round(totals[c] / user_count, 1) if user_count else 0.0
        for c in _USAGE_CATEGORIES
    }
    shares = {
        c: round(totals[c] / total_calls * 100, 1) if total_calls else 0.0
        for c in _USAGE_CATEGORIES
    }
    return {
        "user_count": user_count,
        "total_calls": total_calls,
        "totals": totals,
        "per_user_avg": per_user_avg,
        "shares": shares,
    }


# ---------- 个人作品库（Spec5 §5.3） ----------

def add_image_record(user_id: int, source: str, file_name: str,
                     ext: str, prompt: str | None) -> dict:
    """写一条作品记录，返回完整记录 dict。"""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO images (user_id, source, file_name, ext, prompt, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, source, file_name, ext, prompt, _now_iso()),
        )
        conn.commit()
        image_id = cur.lastrowid
    return get_image_record(image_id)


def get_image_record(image_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
    return _image_row_to_dict(row)


def list_image_records(user_id: int, source: str | None = None) -> list[dict]:
    """按用户取作品记录，时间倒序；source 非空时按来源筛选。"""
    if source:
        sql = ("SELECT * FROM images WHERE user_id = ? AND source = ? "
               "ORDER BY created_at DESC, id DESC")
        params = (user_id, source)
    else:
        sql = ("SELECT * FROM images WHERE user_id = ? "
               "ORDER BY created_at DESC, id DESC")
        params = (user_id,)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_image_row_to_dict(r) for r in rows]


def delete_image_record(image_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
        conn.commit()
    return cur.rowcount > 0


def delete_user_image_records(user_id: int) -> list[str]:
    """删除某用户全部作品记录，返回被删记录的 file_name 列表（供删除物理文件）。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT file_name FROM images WHERE user_id = ?", (user_id,)
        ).fetchall()
        names = [r["file_name"] for r in rows]
        conn.execute("DELETE FROM images WHERE user_id = ?", (user_id,))
        conn.commit()
    return names


# ---------- 社区帖子（Spec9 §5.2） ----------

def create_post_record(user_id: int, text: str, image_file: str, ext: str) -> dict:
    """写一条帖子记录，返回完整记录 dict。"""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO posts (user_id, text, image_file, ext, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, text, image_file, ext, _now_iso()),
        )
        conn.commit()
        post_id = cur.lastrowid
    return get_post_record(post_id)


def get_post_record(post_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    return _post_row_to_dict(row)


def list_posts(user_id: int, offset: int, limit: int) -> list[dict]:
    """社区帖子列表（最新在前），每项含作者信息、like/dislike 计数与当前用户 my_vote。

    字段：id / user_id / text / created_at / author / author_is_admin /
    like_count / dislike_count / my_vote（null|like|dislike）。
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT p.id, p.user_id, p.text, p.created_at, "
            "       u.username AS author, u.is_admin AS author_is_admin, "
            "       COALESCE(SUM(CASE WHEN pv.vote = 'like' THEN 1 ELSE 0 END), 0) AS like_count, "
            "       COALESCE(SUM(CASE WHEN pv.vote = 'dislike' THEN 1 ELSE 0 END), 0) AS dislike_count, "
            "       (SELECT pv2.vote FROM post_votes pv2 "
            "         WHERE pv2.post_id = p.id AND pv2.user_id = ?) AS my_vote "
            "FROM posts p "
            "JOIN users u ON u.id = p.user_id "
            "LEFT JOIN post_votes pv ON pv.post_id = p.id "
            "GROUP BY p.id "
            "ORDER BY p.created_at DESC, p.id DESC "
            "LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "user_id": r["user_id"],
            "text": r["text"],
            "created_at": r["created_at"],
            "author": r["author"],
            "author_is_admin": bool(r["author_is_admin"]),
            "like_count": int(r["like_count"]),
            "dislike_count": int(r["dislike_count"]),
            "my_vote": r["my_vote"],
        }
        for r in rows
    ]


def delete_post_record(post_id: int) -> str | None:
    """删除帖子记录，返回其 image_file（供删除物理文件）；不存在返回 None。"""
    with _connect() as conn:
        row = conn.execute("SELECT image_file FROM posts WHERE id = ?", (post_id,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        conn.execute("DELETE FROM post_votes WHERE post_id = ?", (post_id,))
        conn.commit()
    return row["image_file"]


def delete_user_post_records(user_id: int) -> list[str]:
    """删除某用户全部帖子记录与其相关投票，返回被删帖子的 image_file 列表（供删除物理文件）。

    同时清理：该用户帖子上的他人投票 + 该用户投过的所有票。
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT image_file FROM posts WHERE user_id = ?", (user_id,)
        ).fetchall()
        names = [r["image_file"] for r in rows]
        conn.execute(
            "DELETE FROM post_votes WHERE post_id IN "
            "(SELECT id FROM posts WHERE user_id = ?)",
            (user_id,),
        )
        conn.execute("DELETE FROM post_votes WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM posts WHERE user_id = ?", (user_id,))
        conn.commit()
    return names


# ---------- 帖子点赞 / 点踩（Spec9 §5.2） ----------

def set_post_vote(post_id: int, user_id: int, vote: str | None) -> None:
    """投票：like/dislike UPSERT；vote=None 表示取消（删行）。"""
    now = _now_iso()
    with _connect() as conn:
        if vote is None:
            conn.execute(
                "DELETE FROM post_votes WHERE post_id = ? AND user_id = ?",
                (post_id, user_id),
            )
        else:
            conn.execute(
                "INSERT INTO post_votes (post_id, user_id, vote, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(post_id, user_id) DO UPDATE SET "
                "vote = excluded.vote, updated_at = excluded.updated_at",
                (post_id, user_id, vote, now, now),
            )
        conn.commit()


def get_post_vote_totals(post_id: int) -> dict:
    """现算某帖 like/dislike 计数。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN vote = 'like' THEN 1 ELSE 0 END), 0) AS like_count, "
            "       COALESCE(SUM(CASE WHEN vote = 'dislike' THEN 1 ELSE 0 END), 0) AS dislike_count "
            "FROM post_votes WHERE post_id = ?",
            (post_id,),
        ).fetchone()
    return {"like_count": int(row["like_count"]), "dislike_count": int(row["dislike_count"])}


def get_post_my_vote(post_id: int, user_id: int) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT vote FROM post_votes WHERE post_id = ? AND user_id = ?",
            (post_id, user_id),
        ).fetchone()
    return row["vote"] if row else None


# ---------- AI 服务反馈（Spec9 §5.2） ----------

def set_feedback(task_id: int, user_id: int, category: str, vote: str | None) -> None:
    """记录/切换/取消某次 AI 结果反馈。

    vote=None 表示取消（删行）；否则按 task_id UPSERT（切换不新增行）。
    """
    if category not in _FEEDBACK_CATEGORIES:
        raise ValueError(f"未知反馈类别: {category}")
    if vote is not None and vote not in _FEEDBACK_VOTES:
        raise ValueError(f"未知反馈投票: {vote}")
    now = _now_iso()
    with _connect() as conn:
        if vote is None:
            conn.execute("DELETE FROM feedback WHERE task_id = ?", (task_id,))
        else:
            conn.execute(
                "INSERT INTO feedback (task_id, user_id, category, vote, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET "
                "user_id = excluded.user_id, category = excluded.category, "
                "vote = excluded.vote, updated_at = excluded.updated_at",
                (task_id, user_id, category, vote, now, now),
            )
        conn.commit()


def get_feedback_totals() -> dict:
    """三类 AI 服务 like/dislike 聚合（管理端只读展示）。

    返回 {"generate": {"like": n, "dislike": n}, "edit": {...}, "qa": {...}}。
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT category, vote, COUNT(*) AS n FROM feedback "
            "GROUP BY category, vote"
        ).fetchall()
    totals = {c: {"like": 0, "dislike": 0} for c in _FEEDBACK_CATEGORIES}
    for r in rows:
        cat = totals.get(r["category"])
        if cat is not None and r["vote"] in cat:
            cat[r["vote"]] = int(r["n"])
    return totals


def clear_feedback(category: str | None = None) -> int:
    """清空反馈统计（可 ?category= 单选或全清），返回删除行数。"""
    with _connect() as conn:
        if category:
            if category not in _FEEDBACK_CATEGORIES:
                raise ValueError(f"未知反馈类别: {category}")
            cur = conn.execute("DELETE FROM feedback WHERE category = ?", (category,))
        else:
            cur = conn.execute("DELETE FROM feedback")
        conn.commit()
    return cur.rowcount


# ---------- 临时分享链接（Spec9 §5.2） ----------

def create_share_record(token: str, image_id: int, user_id: int, expires_at: str) -> dict:
    """覆盖写一条分享（同一作品再次生成 = 新 token + 新有效期），返回完整记录 dict。"""
    with _connect() as conn:
        # 先删旧行再插新行：满足「一个作品一条分享」（Spec9 §2.3）
        conn.execute("DELETE FROM shares WHERE image_id = ?", (image_id,))
        cur = conn.execute(
            "INSERT INTO shares (token, image_id, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, image_id, user_id, _now_iso(), expires_at),
        )
        conn.commit()
        share_id = cur.lastrowid
    return get_share_record(share_id)


def get_share_record(share_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM shares WHERE id = ?", (share_id,)).fetchone()
    return _share_row_to_dict(row)


def get_share_by_token(token: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM shares WHERE token = ?", (token,)).fetchone()
    return _share_row_to_dict(row)


def get_share_by_image(image_id: int) -> dict | None:
    """某作品的当前分享（每作品至多一条，Spec9 §2.3）。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM shares WHERE image_id = ? ORDER BY id DESC LIMIT 1",
            (image_id,),
        ).fetchone()
    return _share_row_to_dict(row)


def delete_share(share_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM shares WHERE id = ?", (share_id,))
        conn.commit()
    return cur.rowcount > 0


def delete_shares_for_image(image_id: int) -> None:
    """删除引用某作品的分享（删作品级联，Spec9 §5.3）。"""
    with _connect() as conn:
        conn.execute("DELETE FROM shares WHERE image_id = ?", (image_id,))
        conn.commit()


# ---------- 建议箱（Spec9 §5.2） ----------

def create_suggestion(user_id: int, text: str) -> dict:
    """写一条建议（status=pending），返回完整记录 dict。"""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO suggestions (user_id, text, status, created_at, updated_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (user_id, text, _now_iso(), _now_iso()),
        )
        conn.commit()
        suggestion_id = cur.lastrowid
    return get_suggestion(suggestion_id)


def get_suggestion(suggestion_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    return _suggestion_row_to_dict(row)


def list_suggestions(user_id: int) -> list[dict]:
    """我的建议（最新在前），含 status/reply。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM suggestions WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC",
            (user_id,),
        ).fetchall()
    return [_suggestion_row_to_dict(r) for r in rows]


def list_all_suggestions(status: str | None = None) -> list[dict]:
    """全部建议（管理端），含发送者 username；status 非空时筛选。"""
    if status and status not in _SUGGESTION_STATUSES:
        raise ValueError(f"未知建议状态: {status}")
    sql = ("SELECT s.*, u.username AS author "
           "FROM suggestions s JOIN users u ON u.id = s.user_id ")
    params: tuple = ()
    if status:
        sql += "WHERE s.status = ? "
        params = (status,)
    sql += "ORDER BY s.created_at DESC, s.id DESC"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            **_suggestion_row_to_dict(r),
            "author": r["author"],
        }
        for r in rows
    ]


def update_suggestion(suggestion_id: int, status: str | None = None,
                      reply: str | None = None) -> dict | None:
    """标记状态 / 写回复（可只改其一），刷新 updated_at；返回更新后记录或 None。"""
    if status is not None and status not in _SUGGESTION_STATUSES:
        raise ValueError(f"未知建议状态: {status}")
    sets: list[str] = []
    params: list = []
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if reply is not None:
        sets.append("reply = ?")
        params.append(reply)
    if not sets:
        return get_suggestion(suggestion_id)
    sets.append("updated_at = ?")
    params.append(_now_iso())
    params.append(suggestion_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE suggestions SET {', '.join(sets)} WHERE id = ?",  # noqa: S608
            params,
        )
        conn.commit()
    return get_suggestion(suggestion_id)


def delete_suggestion(suggestion_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM suggestions WHERE id = ?", (suggestion_id,))
        conn.commit()
    return cur.rowcount > 0
