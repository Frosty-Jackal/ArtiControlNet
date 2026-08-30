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
    """删除用户；连带删除其 usage 计数行与 images 记录，保证口径一致（Spec4 §3 / Spec5 §3）。

    注意：仅删除数据库记录；gallery/ 下的物理文件由 gallery.delete_user_gallery 负责
    （先取 file_name 列表再删文件），见 main.py admin_delete_user。
    """
    with _connect() as conn:
        conn.execute("DELETE FROM usage WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM images WHERE user_id = ?", (user_id,))
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
