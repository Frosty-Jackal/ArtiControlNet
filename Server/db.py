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


# ---------- 生命周期 ----------

def init_db() -> None:
    """建表；users 表为空时按 .env 配置创建初始管理员。"""
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(_CREATE_TABLE)
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
    with _connect() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return cur.rowcount > 0
