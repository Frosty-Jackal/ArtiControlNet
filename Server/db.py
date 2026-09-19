"""SQLite 账号库封装（Spec2 §5.2 / §5.3）。

- 零新依赖：Python 标准库 `sqlite3`，单文件 Server/artcn.db。
- 持久化：与 storage/ 临时目录无关，后端重启不清库。
- 线程安全：每次操作开新连接；启用 WAL 提升并发读写。
- 首次启动（users 表为空）时按 .env 的 ADMIN_USERNAME/ADMIN_PASSWORD 自动创建初始管理员，
  避免"建号需要管理员但还没有管理员"的死锁。
"""
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import config
from errors import DuplicateUsernameError

logger = logging.getLogger("db")

AUTH_DB_PATH = config.AUTH_DB_PATH

# 新建用户的默认服务限额（Spec18 §5.1b）。只在 DDL 里用；int() 过一遍，无注入面。
# 存量库由 _migrate_users_quota_limit 补列、取同一个 _QUOTA_DEFAULT，
# 因此「默认限额」在全仓只有一个来源（config.QUOTA_DEFAULT_LIMIT）。
_QUOTA_DEFAULT = int(config.QUOTA_DEFAULT_LIMIT)

_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    quota_limit   INTEGER NOT NULL DEFAULT {_QUOTA_DEFAULT},
    email         TEXT           -- Spec21 补的列，Spec22 起是唯一联系方式（可空：管理员手工建的号没有）
)
"""

# 5 类调用计数表（Spec4 §5.4，Spec18 §5.1c 补 style 列）：每用户一行，任务成功完成后 +1。
# style（Spec18）粒度不同：按**实际发出的上游调用**计，见 record_call 的说明。
_CREATE_USAGE_TABLE = """
CREATE TABLE IF NOT EXISTS usage (
    user_id    INTEGER PRIMARY KEY,
    chat       INTEGER NOT NULL DEFAULT 0,
    generate   INTEGER NOT NULL DEFAULT 0,
    edit       INTEGER NOT NULL DEFAULT 0,
    qa         INTEGER NOT NULL DEFAULT 0,
    style      INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
)
"""

# 计费账户（Spec18 §5.1a）：每用户一行，单调累计，**永不清零**。
# 与 usage 表的分工见 Spec18 §2.2：usage 是"区间统计"（可被 Spec11 的清空按钮删行），
# user_quota 是"终身账本"（只增不减）。两处由 record_call 在同一事务里写入，永远同步。
# 管理员同样有行（照常累计与展示），只是不参与限额判定。
# 本表**不放进 init_db 的建表清单**，由 _backfill_user_quota 负责——那正是它的幂等判据（§5.1e）。
_CREATE_USER_QUOTA_TABLE = """
CREATE TABLE IF NOT EXISTS user_quota (
    user_id    INTEGER PRIMARY KEY,
    used       INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT    NOT NULL
)
"""

# 计数列白名单（record_call 据此拼列名，绝不拼接外部输入）
_USAGE_CATEGORIES = ("chat", "generate", "edit", "qa", "style")

# 个人作品库表（Spec5 §5.3）：文件与元数据分离，文件字节在 Server/gallery/。
# wiki_used（Spec12 §5.1b）：该作品是否已被纳入过个人风格更新（1 = 已考虑）。
# note（Spec16 §5.1a）：上传作品的备注（用户自写；生成/绘图作品恒为 NULL，与 prompt 互斥）。
_CREATE_IMAGES_TABLE = """
CREATE TABLE IF NOT EXISTS images (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    source     TEXT NOT NULL,
    file_name  TEXT NOT NULL,
    ext        TEXT NOT NULL,
    prompt     TEXT,
    note       TEXT,
    created_at TEXT NOT NULL,
    wiki_used  INTEGER NOT NULL DEFAULT 0
)
"""

# 画廊按用户 + 时间倒序（Spec5 §5.3 索引）
_CREATE_IMAGES_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_images_user_created "
    "ON images(user_id, created_at DESC)"
)

# 社区帖子表（Spec9 §5.2）：文字 + 可选单图；图片字节在 Server/community/。
# Spec17 §5.1c：image_file / ext 改为可空——帖子可以只有文字（纯文字帖）。
_CREATE_POSTS_TABLE = """
CREATE TABLE IF NOT EXISTS posts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,             -- 作者
    text       TEXT NOT NULL,                -- 心得文字（1~1000 字，前后端校验）
    image_file TEXT,                         -- community/ 下持久文件名；纯文字帖为 NULL
    ext        TEXT,                         -- .jpg|.jpeg|.png|.webp|.gif；纯文字帖为 NULL
    created_at TEXT NOT NULL
)
"""
_CREATE_POSTS_INDEX = "CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC)"

# 帖子评论（Spec17 §5.1d）：只增不删不改——**没有 updated_at 列**，
# 因为评论不可编辑（§2.3）。要改只能删了重发。
_CREATE_POST_COMMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS post_comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL,             -- 引用 posts.id
    user_id    INTEGER NOT NULL,             -- 评论者
    text       TEXT    NOT NULL,             -- 1~COMMENT_TEXT_MAX 字
    created_at TEXT    NOT NULL
)
"""
_CREATE_POST_COMMENTS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_post_comments_post "
    "ON post_comments(post_id, id)"
)

# 对话（Spec17 §5.1a）：按用户保存的聊天分段。
# id 沿用既有的 thread_id 形态（t_ + uuid4 前 8 位），前端/后端/日志三处同一个值。
_CREATE_CONVERSATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,          -- = thread_id（t_xxxxxxxx）
    user_id    INTEGER NOT NULL,          -- 归属用户（删用户级联）
    created_at TEXT NOT NULL,             -- 发起时间（侧边栏显示的就是它）
    updated_at TEXT NOT NULL              -- 最后一条消息时刻（列表排序用）
)
"""
_CREATE_CONVERSATIONS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_conversations_user "
    "ON conversations(user_id, updated_at DESC)"
)

# 对话消息（Spec17 §5.1b）：记录用户与助手双方的内容。
# image_id 引用 images.id（Spec5 作品库）——**不复制字节**；该图可能被用户在
# 「我的作品」里删掉，此时本行成为悬挂引用，前端渲染 404 → 「图片已删除」占位。
# task_id / tool 仅助手侧的工具结果有值（Spec9 反馈行用）。
_CREATE_CHAT_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id    TEXT    NOT NULL,          -- conversations.id
    user_id    INTEGER NOT NULL,          -- 归属用户（删用户级联）
    role       TEXT    NOT NULL,          -- 'user' | 'assistant'
    text       TEXT,                      -- 文本内容（纯图片消息为 NULL）
    image_id   INTEGER,                   -- images.id（无图为 NULL）
    task_id    INTEGER,                   -- 该结果的 task_id（仅工具结果；反馈用）
    tool       TEXT,                      -- 'generate_image'|'edit_image'|'qa_image'
    created_at TEXT    NOT NULL
)
"""
_CREATE_CHAT_MESSAGES_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_conv "
    "ON chat_messages(conv_id, id)"
)

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

# 通用键值元数据（Spec11 §5.1）：记录各统计块的"上次清零时间"（usage / feedback 各自独立）
_CREATE_META_TABLE = """
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""
_CREATE_SUGGESTIONS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_suggestions_user "
    "ON suggestions(user_id, created_at DESC)"
)

# 个人作品风格 Wiki（Spec12 §5.1a）：每用户一行，成对保存「当前风格」与「上次更新前的风格」
_CREATE_WIKI_TABLE = """
CREATE TABLE IF NOT EXISTS wiki (
    user_id          INTEGER PRIMARY KEY,
    style            TEXT NOT NULL DEFAULT '',   -- 当前「个人作品风格」（空串 = 尚未建立）
    prev_style       TEXT,                       -- 「上次更新前的个人作品风格」（NULL = 从未更新过）
    style_updated_at TEXT,                       -- 当前风格的产生时刻（UTC ISO；NULL = 尚未建立）
    updated_at       TEXT                        -- 本行最后修改时刻（UTC ISO）
)
"""

# 注册申请（Spec19 §5.1a）：一行 = 一条待处理/已处理的注册申请。
# **不是用户表**：申请阶段不创建任何 users 行，同意时才在同一事务里建号（§1.3）。
# 刻意**没有** UNIQUE(username)：同一用户名允许多条被拒绝的历史记录，
# 唯一性由 users.username 的 UNIQUE 在同意那一刻兜底（§3.3-2）。
#
# Spec22 §2.1：**删掉了 phone 与 ip 两列**（不可逆）。email 成为必填的唯一定位键
# ——注册要过邮箱验证码，所以"至少填一项联系方式"这个二选一不存在了。
# ip 一列连同它的冷却索引一并删除：注册的防刷改由邮箱验证码承担（§2.5），
# 于是 register_requests 在本仓第一次不含任何非必要 PII。
# 存量行的 email 可能是 NULL（旧申请只有手机号），故本列**可空**——读路径要容忍。
_CREATE_REGISTER_REQUESTS_TABLE = """
CREATE TABLE IF NOT EXISTS register_requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL,             -- 申请的用户名（同意时原样建号）
    password_hash TEXT NOT NULL,             -- bcrypt；同意后置为 ''（§2.1）
    email         TEXT,                      -- 邮箱（唯一联系方式；存量旧行可能为 NULL）
    wechat        TEXT NOT NULL,             -- 用于支付的微信昵称（管理员对账用）
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at    TEXT NOT NULL,             -- 提交时刻（UTC ISO）
    reviewed_at   TEXT                       -- 同意/拒绝的时刻（NULL = 尚未处理）
)
"""

# 列表查询走这条：pending 优先 + 组内 id 倒序（§6.4）
_CREATE_REGISTER_REQUESTS_STATUS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_register_requests_status "
    "ON register_requests(status, id DESC)"
)

# 充值台账（Spec21 §5.3）：一行 = 一条待处理/已处理的充值申请。
# 「台账」语义与 Spec19 的 register_requests 完全相同：同意/拒绝都保留记录（status），
# 只有「删除」才真删行（§2.3）。刻意**没有** UNIQUE(user_id, status)——
# 被拒绝之后必须能再申请，唯一性靠 status='pending' 的幂等查询兜（§2.4）。
# 刻意**没有** ip 列：防刷靠幂等而不是冷却，于是本表不含任何多余 PII（§2.3）。
_CREATE_RECHARGE_REQUESTS_TABLE = """
CREATE TABLE IF NOT EXISTS recharge_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,             -- 加额度的目标（users.id）
    username    TEXT NOT NULL,                -- 提交时刻的账号名快照（台账要能脱离 users 读）
    wechat      TEXT NOT NULL,                -- 充值用的微信昵称（唯一的对账键）
    source      TEXT NOT NULL DEFAULT 'user', -- 'user'（系统内主动充值）| 'overdue'（欠费被拦时提交）
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    amount      INTEGER,                      -- 同意时管理员填的加次数（NULL = 尚未处理）
    created_at  TEXT NOT NULL,                -- 提交时刻（UTC ISO）
    reviewed_at TEXT                          -- 同意/拒绝的时刻（NULL = 尚未处理）
)
"""

# 幂等查询走这条：WHERE user_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1
_CREATE_RECHARGE_REQUESTS_USER_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_recharge_requests_user "
    "ON recharge_requests(user_id, status, id DESC)"
)

# 列表查询走这条：pending 优先 + 组内 id 倒序（与 Spec19 §6.4 同款）
_CREATE_RECHARGE_REQUESTS_STATUS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_recharge_requests_status "
    "ON recharge_requests(status, id DESC)"
)

# 邮箱验证码（Spec22 §5.2）：只装**最近 TTL 内**的码，发一次码顺手清一次过期行。
#
# **不是台账**：与 register_requests / recharge_requests 不同，这张表没有 status、
# 没有"同意/拒绝"、不保留历史（§3.3-10）。别把它当审计表用。
# purpose 一列是这个设计的关键：三个场景（注册 / 登录 / 改密码）共一张表，就必须
# 回答"这个码是给哪个场景发的"——**校验时按 purpose 匹配**，否则一个为"注册"发的
# 码可以直接拿去登录（§2.2）。
# 刻意**没有** used 标记：用户要的是"TTL 内只要有一个对了都算数"（§2.2）。
# 刻意**不给 code 加索引**：没有任何查询按 code 走（查的是 email+purpose+时间）。
_CREATE_EMAIL_VERIFICATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS email_verifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL,   -- 已小写化（§2.8，路由层保证）
    purpose    TEXT NOT NULL,   -- register | login | reset（发码时按场景隔离，§2.2）
    code       TEXT NOT NULL,   -- 4 位数字串，1000~9999（§2.3）
    created_at TEXT NOT NULL    -- 发码时刻（UTC ISO）
)
"""

# 三个查询都走这条：冷却（最近一条）、校验（TTL 内的全部）、清理（过期的）
_CREATE_EMAIL_VERIFICATIONS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_email_verifications_lookup "
    "ON email_verifications(email, purpose, created_at DESC)"
)

# 入口点击（Spec22 §5.3）：一行 = 某个事件被某个 IP 点过**一次**。
# `UNIQUE(event, ip)` 是业务约束，不是数据库洁癖：它让 COUNT(*) 直接等于
# "不重复 IP 数"，且 INSERT OR IGNORE 天然幂等——两个并发请求同时到达也只会记
# 一行（§2.9）。不要在应用层写"先查再插"，那是两个线程能同时通过检查的经典竞态。
# 唯一性是**永久**的（直到管理端点「清空入口统计」），没有时间窗口（§2.9）。
_CREATE_CLICK_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS click_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event      TEXT NOT NULL,   -- 见 _CLICK_EVENTS 白名单
    ip         TEXT NOT NULL,   -- auth.client_ip(request)；只落库、只参与 COUNT（§2.9）
    created_at TEXT NOT NULL,
    UNIQUE(event, ip)           -- 去重就靠它，配 INSERT OR IGNORE
)
"""

# 统计走这条：SELECT event, COUNT(*) ... GROUP BY event
_CREATE_CLICK_EVENTS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_click_events_event ON click_events(event)"
)

# 埋点事件白名单（§5.5，路由与 get_click_stats 共用，不拼接外部输入）。
# 「点击登录主页」的口径是"打开登录页"（用户已确认，§2.9）。
_CLICK_EVENTS = ("login_page", "register", "community", "gallery", "recharge")

# 来源 / 状态白名单（校验用，不拼接外部输入）
_RECHARGE_SOURCES = ("user", "overdue")
_RECHARGE_STATUSES = ("pending", "approved", "rejected")

# 反馈类别白名单（set_feedback 校验，不拼接外部输入）
_FEEDBACK_CATEGORIES = ("generate", "edit", "qa")
_FEEDBACK_VOTES = ("like", "dislike")
# 建议状态白名单（update_suggestion 校验）
_SUGGESTION_STATUSES = ("pending", "resolved")  # Spec10：收敛两态，去掉 read / 待用户处理

# 申请状态白名单（Spec19 §5.1b，approve / reject 校验，不拼接外部输入）
_REGISTER_STATUSES = ("pending", "approved", "rejected")

# 待考虑作品来源白名单（Spec15 §5.1）：生成/绘图作品带 prompt，上传作品带图片字节
# （走视觉 QA 逐张分析）。三者同一套 wiki_used 语义——真的被纳入过才置 1。
_PENDING_SOURCES = ("generate", "edit", "upload")

# app_meta 键：值 = UTC ISO 时间，表示"存量上传作品已放回待考虑队列"（Spec15 §5.1b）
WIKI_UPLOAD_MIGRATED_KEY = "wiki_upload_migrated"

# app_meta 键：值 = 已发出的最大 task_id（十进制字符串）。
# Spec17 §3.4：TaskQueue 是内存发号器，重启从 1 重排会让持久化对话里的
# 历史 👍/👎 与新任务撞号，覆盖他人 feedback 行。持久化后 task_id 全局单调、永不重用。
TASK_ID_SEQ_KEY = "task_id_seq"

# app_meta 键：user_quota 存量回填的执行时间（UTC ISO，Spec18 §5.1e）。
# 信息性——真正的幂等判据是 sqlite_master 里表存在与否（§5.1e），这个键只供排障。
QUOTA_BACKFILLED_KEY = "quota_backfilled_at"

# app_meta 键：入口点击统计的上次清零时间（UTC ISO，Spec22 §5.5）。
# 与 usage_cleared_at / feedback_cleared_at 同款——它是本仓的**第三个**清零口径。
CLICKS_CLEARED_KEY = "clicks_cleared_at"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(AUTH_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# 用户查询统一带上配额状态（Spec18 §5.1f）——所有读 users 的地方都走它。
# LEFT JOIN 而非 JOIN：用户可能还没有 user_quota 行（理论上不该有，但缺失时
# 必须退化成"已用 0 次"而不是"查不到这个人"）。
_USER_SELECT = (
    "SELECT u.*, COALESCE(q.used, 0) AS used "
    "FROM users u LEFT JOIN user_quota q ON q.user_id = u.id"
)


def _row_to_dict(row: sqlite3.Row | None, *, with_secret: bool = False) -> dict | None:
    """users 行 → dict（行须来自 _USER_SELECT）。

    Spec18 §5.1f：**默认不再带出 `password_hash`**。它是 bcrypt 哈希、不是明文，
    但 `GET /api/admin/users` 一直在把它返回给前端，而前端从来没用过——一个只在
    登录时需要的秘密，没有任何理由出现在列表接口里。改成"要用必须显式要"，
    这个保证就从"调用方自觉"变成了结构性的。

    新增：`quota_limit`（users 列）、`used`（user_quota 累计，见 _USER_SELECT）。

    Spec21 §5.1 带出了 `phone` / `email` 两项联系方式；**Spec22 §5.1 起只剩 `email`
    一项 PII**（`phone` 列已从库里删掉）。它仍然会流向若干地方，其中**只有
    `list_users()` → `GET /api/admin/users` 是接口响应**（仅管理员）；其余
    （get_user_by_id / get_user_by_username / set_user_quota / approve_register_request）
    的调用方都只取自己需要的字段再手写一个小 dict 返回，不会把整个 dict 直接
    `_ok(...)` 出去。**新增读 users 的路由时要保持这个约定。**

    `with_secret=True` 全仓只有 `get_user_by_username` 一处（登录校验密码）。
    """
    if row is None:
        return None
    record = {
        "id": row["id"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
        "quota_limit": int(row["quota_limit"]),
        "used": int(row["used"]),
        "email": row["email"],        # Spec22：唯一联系方式，可能为 None（管理员手工建的号）
    }
    if with_secret:
        record["password_hash"] = row["password_hash"]
    return record


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
        "note": row["note"],                   # Spec16：上传作品的备注（可空）
        "created_at": row["created_at"],
        "wiki_used": bool(row["wiki_used"]),   # Spec12：是否已纳入过个人风格更新
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


def _wiki_row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "style": row["style"],
        "prev_style": row["prev_style"],
        "style_updated_at": row["style_updated_at"],
        "updated_at": row["updated_at"],
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


def _conversation_row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """对话行 → dict（Spec17 §5.1a）。"""
    if row is None:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _chat_message_row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """对话消息行 → dict（Spec17 §5.1b）。"""
    if row is None:
        return None
    return {
        "id": row["id"],
        "conv_id": row["conv_id"],
        "user_id": row["user_id"],
        "role": row["role"],
        "text": row["text"],
        "image_id": row["image_id"],
        "task_id": row["task_id"],
        "tool": row["tool"],
        "created_at": row["created_at"],
    }


def _post_comment_row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """评论行 → dict（Spec17 §5.1d）；带上 JOIN users 得到的 author 字段。"""
    if row is None:
        return None
    keys = row.keys()
    record = {
        "id": row["id"],
        "post_id": row["post_id"],
        "user_id": row["user_id"],
        "text": row["text"],
        "created_at": row["created_at"],
    }
    if "author" in keys:
        record["author"] = row["author"]
        record["author_is_admin"] = bool(row["author_is_admin"])
    return record


def _register_row_to_dict(row: sqlite3.Row | None, *, with_secret: bool = False) -> dict | None:
    """申请行 → dict（Spec19 §5.1c）。

    与 _row_to_dict（users）同样的约定：**默认不带出 `password_hash`**。
    它只有一处真正需要——同意时把哈希写进新建的 users 行（批准路径），
    因此 `with_secret=True` 全仓只出现在 `approve_register_request` 与
    批准路由的预检两处。列表接口（GET /api/admin/register-requests）
    拿到的字典在结构上就不可能有这个键。

    Spec22 §5.1：`phone` 与 `ip` 两列随需求 3 一起从库里删掉了，所以本函数
    **没有**"要记得不带出 ip"这回事了——列都没了。剩下的唯一联系方式是 `email`
    （存量旧行可能为 NULL）。
    """
    if row is None:
        return None
    record = {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "wechat": row["wechat"],
        "status": row["status"],
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
    }
    if with_secret:
        record["password_hash"] = row["password_hash"]
    return record


def _recharge_row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """充值行 → dict（Spec21 §5.4）。

    **没有 `with_secret`**——本表根本没有密码列（对比 `_register_row_to_dict`）。
    **不带出 `ip`**——本表连这一列都没有（§2.3，防刷靠幂等而不是冷却）。
    """
    if row is None:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "wechat": row["wechat"],
        "source": row["source"],
        "status": row["status"],
        "amount": row["amount"],
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
    }


# ---------- 生命周期 ----------

def _migrate_images_wiki_used(conn: sqlite3.Connection) -> None:
    """存量库补列（Spec12 §5.1b）：PRAGMA 查得无 wiki_used 才 ALTER，幂等。

    新建库由 _CREATE_IMAGES_TABLE 自带该列，此分支只服务已存在的 artcn.db，
    两条路径最终 schema 一致。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(images)").fetchall()}
    if "wiki_used" not in cols:
        conn.execute(
            "ALTER TABLE images ADD COLUMN wiki_used INTEGER NOT NULL DEFAULT 0"
        )
        logger.info("images.wiki_used 列已补齐", extra={"event": "db.migrate"})


def _migrate_upload_wiki_used(conn: sqlite3.Connection) -> None:
    """Spec15 §5.1b：旧口径把上传作品无条件标记为"已考虑"（假账），放回待考虑队列。

    幂等保护：app_meta 里有键就不再执行——否则每次重启都会把 Spec15 之后
    新标记的上传图重置回 0，同一张图被反复重分析。
    """
    row = conn.execute(
        "SELECT value FROM app_meta WHERE key = ?", (WIKI_UPLOAD_MIGRATED_KEY,)
    ).fetchone()
    if row is not None:
        return
    cur = conn.execute("UPDATE images SET wiki_used = 0 WHERE source = 'upload'")
    _upsert_meta(conn, WIKI_UPLOAD_MIGRATED_KEY, _now_iso())
    conn.commit()
    logger.info("存量上传作品已放回待考虑队列", extra={
        "event": "wiki.upload_migrated", "affected": cur.rowcount,
    })


def _migrate_images_note(conn: sqlite3.Connection) -> None:
    """存量库补列（Spec16 §5.1b）：PRAGMA 查得无 note 才 ALTER，幂等。

    新建库由 _CREATE_IMAGES_TABLE 自带该列，此分支只服务已存在的 artcn.db。
    两条路径的**列顺序不同**（存量库把 note 追加在末尾），但所有读取一律按
    列名取值（`row["note"]`），行为无差别。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(images)").fetchall()}
    if "note" not in cols:
        conn.execute("ALTER TABLE images ADD COLUMN note TEXT")
        logger.info("images.note 列已补齐", extra={"event": "db.migrate"})


def _migrate_users_quota_limit(conn: sqlite3.Connection) -> None:
    """存量库补 users.quota_limit（Spec18 §5.1b）：PRAGMA 查得无该列才 ALTER，幂等。

    默认值取模块级的 _QUOTA_DEFAULT（= config.QUOTA_DEFAULT_LIMIT，§5.1b），
    与新库的 _CREATE_TABLE 同源。**它只在建表/补列时生效，改它不影响已存在的用户**
    （见 §3.3-5）。
    列顺序：存量库追加在末尾，新库在 _CREATE_TABLE 里；读取一律按列名，行为无差别。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "quota_limit" not in cols:
        conn.execute(
            f"ALTER TABLE users ADD COLUMN quota_limit INTEGER NOT NULL "
            f"DEFAULT {_QUOTA_DEFAULT}"
        )
        logger.info("users.quota_limit 列已补齐", extra={"event": "db.migrate"})


def _migrate_users_contact(conn: sqlite3.Connection) -> None:
    """存量库补 users.email（Spec21 §5.1），并把已开通用户的联系方式回填一次。

    回填只在"确实补过列"的那次跑：库里的 register_requests 是唯一来源，
    它不会变（Spec19 的申请行只增不隐），所以回填天然一次性。

    只认 status='approved' 的行：被拒绝的申请里的联系方式**不属于任何账号**
    （那个人从来没被开通），拿它填进去等于凭空捏造一条联系方式（§2.1）。

    已知边界（§3.3-7，**不修**）：用户被删后重建同名账号，回填会把前一个人的
    联系方式填到新账号上——那是同名的两个人，本函数无法区分。

    Spec22 §5.1：本函数原来还负责 `phone` 那半（补列 + 回填），随电话三列的
    删除一起去掉了——现在只补/回填 `email` 一列。⚠️ 位置约束：它必须排在
    `_migrate_drop_phone_and_ip` **之前**（顺序反了，旧库的 phone 会被这里加回来）。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "email" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    else:
        return
    # ORDER BY r.id DESC LIMIT 1 是**纯防御**：users.username 有 UNIQUE，所以同一个
    # 用户名最多只会有一条 approved 申请（第二条会在建号时撞 40001）。写明它只是
    # 为了让"取哪一条"有一个确定的答案。
    conn.execute(
        "UPDATE users SET "
        "  email = (SELECT r.email FROM register_requests r "
        "           WHERE r.username = users.username AND r.status = 'approved' "
        "           ORDER BY r.id DESC LIMIT 1) "
        "WHERE EXISTS (SELECT 1 FROM register_requests r "
        "              WHERE r.username = users.username AND r.status = 'approved')"
    )
    logger.info("users.email 列已补齐并回填", extra={"event": "db.migrate"})


def _migrate_drop_phone_and_ip(conn: sqlite3.Connection) -> None:
    """删掉 users.phone、register_requests.phone、register_requests.ip（Spec22 §2.1）。

    为什么是真删而不是留着不用：见 §2.1 —— 留一列谁都不读写的死数据，是本仓
    反复记录的那类"看起来还在生效"的陷阱。代价（历史电话数据永久丢失）已确认。

    位置约束：必须排在 _migrate_users_contact **之后**。顺序反了的话，
    一个 Spec21 之前的旧库会先被"无列可删"跳过，然后 _migrate_users_contact
    再把 phone 列加回来 —— 白删一次。

    三列各自独立判存在性：不许共用一个 if。上一次跑了个半截（删了 phone、
    没删 ip）时，共用一个判断会让 ip 永远删不掉。

    SQLite 的 DROP COLUMN 需要 3.35+（2021-03）。老版本上只记一条**显眼**的
    warning 并整段跳过：那几列留着，但没有任何代码读写它们（等于自动降级成
    "保留列"形态），功能零影响。让服务因为一个删列失败而起不来，是拿可用性换洁癖。
    """
    user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    req_cols = {r["name"] for r in conn.execute("PRAGMA table_info(register_requests)").fetchall()}
    targets = (
        [("users", c) for c in ("phone",) if c in user_cols]
        + [("register_requests", c) for c in ("phone", "ip") if c in req_cols]
    )
    if not targets:
        return
    if sqlite3.sqlite_version_info < (3, 35, 0):
        logger.warning(
            f"SQLite {sqlite3.sqlite_version} 版本过低，跳过删列"
            "（users.phone / register_requests.phone|ip）——三列保留，但无代码读写",
            extra={"event": "db.migrate", "reason": "sqlite_too_old"},
        )
        return
    # ip 上有索引，SQLite 拒绝删一个被索引引用的列 —— 必须先删索引。
    # 这不是可选步骤，是 DROP COLUMN 的前置条件（§2.1）。
    conn.execute("DROP INDEX IF EXISTS idx_register_requests_ip")
    for table, col in targets:
        # 表名/列名来自上面的字面量白名单，非外部输入
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    conn.commit()
    logger.info("已删除 phone / ip 列", extra={"event": "db.migrate"})


def _migrate_lowercase_emails(conn: sqlite3.Connection) -> None:
    """把存量邮箱统一成小写（Spec22 §2.8）。

    不做的话，一个在 Spec21 时代用大写邮箱注册的账号，**邮箱登录永远进不去**
    （而用户完全不知道为什么）。两条 UPDATE 各自幂等：第二次启动影响 0 行。

    注意这边**不碰**空串/NULL：`email <> LOWER(email)` 对 NULL 求值为 NULL，
    行不会被选中，正是我们要的。
    """
    for table in ("users", "register_requests"):
        conn.execute(f"UPDATE {table} SET email = LOWER(email) WHERE email <> LOWER(email)")
    conn.commit()


def _migrate_usage_style(conn: sqlite3.Connection) -> None:
    """存量库补 usage.style（Spec18 §5.1c）：PRAGMA 查得无该列才 ALTER，幂等。

    存量行一律为 0：Spec15 之前的风格归纳调用**没有记过**，无法追溯（§3.2）。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(usage)").fetchall()}
    if "style" not in cols:
        conn.execute("ALTER TABLE usage ADD COLUMN style INTEGER NOT NULL DEFAULT 0")
        logger.info("usage.style 列已补齐", extra={"event": "db.migrate"})


def _backfill_user_quota(conn: sqlite3.Connection) -> None:
    """首次引入 user_quota 表时，把既有 usage 的前四类求和回填为已用次数（Spec18 §5.1e）。

    判据：sqlite_master 里查不到 user_quota 表 → 说明这是升级后的第一次启动，
    此刻建表并回填。之后每次启动该表都存在，直接返回（绝不覆盖运行期数据）。

    **只回填 chat/generate/edit/qa**：style 是本次新加的列，存量行恒为 0，
    回填它没有意义（Spec15~17 期间的视觉调用没记过，§3.2）。

    回填的直接后果：旧库里已用满默认限额的普通用户，升级后立刻被锁（§3.3-4）。
    这是本函数存在的理由——不回填等于上线即给所有人清零，与"计费"语义矛盾。
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_quota'"
    ).fetchone()
    if exists:
        return
    conn.execute(_CREATE_USER_QUOTA_TABLE)
    conn.execute(
        "INSERT INTO user_quota (user_id, used, updated_at) "
        "SELECT user_id, "
        "       COALESCE(chat, 0) + COALESCE(generate, 0) "
        "     + COALESCE(edit, 0) + COALESCE(qa, 0), "
        "       ? "
        "FROM usage WHERE user_id IS NOT NULL",
        (_now_iso(),),
    )
    _upsert_meta(conn, QUOTA_BACKFILLED_KEY, _now_iso())
    logger.info("user_quota 已建表并回填存量用量", extra={"event": "db.migrate"})


def _migrate_posts_nullable_image(conn: sqlite3.Connection) -> None:
    """存量库把 posts.image_file / ext 改为可空（Spec17 §5.1c：纯文字帖）。

    SQLite 不支持 ALTER COLUMN，只能重建表。幂等判据：PRAGMA 查得 image_file
    的 notnull 标志为 1 才动手——重建后该标志变 0，再启动不会重复执行。
    新建库由 _CREATE_POSTS_TABLE 直接写成可空，本函数只服务已存在的 artcn.db，
    两条路径最终 schema 一致。

    DROP TABLE posts 会连带删掉 idx_posts_created，故重建后一并补回。
    脚本用显式 BEGIN/COMMIT 包住：executescript 本身不开启事务，不写这两句
    就没有"失败即回滚、posts 表保持原样"的保证（§3.4 的前提）。
    """
    cols = {r["name"]: r["notnull"]
            for r in conn.execute("PRAGMA table_info(posts)").fetchall()}
    if not cols.get("image_file"):
        return                                  # 已是可空 / 列不存在 → 无事可做
    conn.executescript("""
        BEGIN;
        CREATE TABLE posts_new (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            text       TEXT    NOT NULL,
            image_file TEXT,
            ext        TEXT,
            created_at TEXT    NOT NULL
        );
        INSERT INTO posts_new (id, user_id, text, image_file, ext, created_at)
            SELECT id, user_id, text, image_file, ext, created_at FROM posts;
        DROP TABLE posts;
        ALTER TABLE posts_new RENAME TO posts;
        CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
        COMMIT;
    """)
    logger.info("posts.image_file / ext 已改为可空", extra={"event": "db.migrate"})


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
        conn.execute(_CREATE_META_TABLE)
        conn.execute(_CREATE_WIKI_TABLE)
        conn.execute(_CREATE_CONVERSATIONS_TABLE)
        conn.execute(_CREATE_CONVERSATIONS_INDEX)
        conn.execute(_CREATE_CHAT_MESSAGES_TABLE)
        conn.execute(_CREATE_CHAT_MESSAGES_INDEX)
        conn.execute(_CREATE_POST_COMMENTS_TABLE)
        conn.execute(_CREATE_POST_COMMENTS_INDEX)
        # Spec19 §5.1a：注册申请表。全新空表，CREATE TABLE IF NOT EXISTS 对新库与
        # 存量库行为一致，**不需要**迁移函数（与 Spec18 的 _backfill_user_quota 不同，
        # 那个要给已存在的数据补一份派生账本，这里没有已存在的数据）。
        conn.execute(_CREATE_REGISTER_REQUESTS_TABLE)
        # Spec22 §5.8 删除：conn.execute(_CREATE_REGISTER_REQUESTS_IP_INDEX)
        #   ip 列已删，留着这句每次启动都撞 "no such column: ip"，服务直接起不来（§2.1）。
        conn.execute(_CREATE_REGISTER_REQUESTS_STATUS_INDEX)
        # Spec21 §5.3：充值台账。与 register_requests 同类——全新空表，
        # CREATE TABLE IF NOT EXISTS 对新库/存量库行为一致，不需要迁移函数。
        conn.execute(_CREATE_RECHARGE_REQUESTS_TABLE)
        conn.execute(_CREATE_RECHARGE_REQUESTS_USER_INDEX)
        conn.execute(_CREATE_RECHARGE_REQUESTS_STATUS_INDEX)
        # Spec22 §5.2 / §5.3：邮箱验证码表 + 入口点击表。与 recharge_requests 同款——
        # 全新空表，CREATE TABLE IF NOT EXISTS 对新库/存量库行为一致，不需要迁移函数。
        conn.execute(_CREATE_EMAIL_VERIFICATIONS_TABLE)
        conn.execute(_CREATE_EMAIL_VERIFICATIONS_INDEX)
        conn.execute(_CREATE_CLICK_EVENTS_TABLE)
        conn.execute(_CREATE_CLICK_EVENTS_INDEX)
        # Spec21 §5.1：users 补 email 并回填。
        # ⚠️ 位置约束：必须排在 _CREATE_REGISTER_REQUESTS_TABLE **之后**（回填要读它）。
        _migrate_users_contact(conn)
        # Spec22 §5.1：删掉 users.phone / register_requests.phone / register_requests.ip。
        # ⚠️ 位置约束：**必须排在 _migrate_users_contact 之后**。顺序反了的话，一个
        #    pre-Spec21 的旧库会先被"无列可删"跳过、再被上面那行把 phone 加回来。
        _migrate_drop_phone_and_ip(conn)
        # Spec22 §2.8：存量邮箱小写化（否则大写邮箱的账号永远登录不进去）。
        # 排在删列之后：保证**任何**读 email 的迁移都看到小写后的值。
        _migrate_lowercase_emails(conn)
        # Spec10：建议状态收敛为 pending|resolved；老数据 read（已读）迁移为 pending
        conn.execute("UPDATE suggestions SET status = 'pending' WHERE status = 'read'")
        # Spec12 §5.1b：存量库补 images.wiki_used 列
        _migrate_images_wiki_used(conn)
        # Spec15 §5.1b：存量上传作品放回待考虑队列（必须在 app_meta 建表之后）
        _migrate_upload_wiki_used(conn)
        # Spec16 §5.1b：存量库补 images.note 列
        _migrate_images_note(conn)
        # Spec18 §5.1d：两次补列迁移，必须在 _backfill_user_quota **之前**
        _migrate_users_quota_limit(conn)
        _migrate_usage_style(conn)
        # Spec18 §5.1e：建 user_quota 表 + 回填存量用量。
        # 位置约束一：必须在 _migrate_usage_style 之后（否则求和语句里没有 style 列）。
        # 位置约束二：必须在 _CREATE_META_TABLE 之后（回填会写 app_meta 键）。
        # 它**不在**上面的建表清单里——`CREATE TABLE IF NOT EXISTS` 会让
        # `sqlite_master` 判据在第一次启动时提前成立，回填被静默跳过。
        _backfill_user_quota(conn)
        # Spec17 §5.1c：存量库把 posts.image_file / ext 改为可空（纯文字帖）
        _migrate_posts_nullable_image(conn)
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
        row = conn.execute(f"{_USER_SELECT} WHERE u.id = ?", (user_id,)).fetchone()
    return _row_to_dict(row)


def get_user_by_username(username: str) -> dict | None:
    """按用户名取用户（**唯一**带出 password_hash 的地方，登录校验密码用）。"""
    with _connect() as conn:
        row = conn.execute(
            f"{_USER_SELECT} WHERE u.username = ?", (username,)
        ).fetchone()
    return _row_to_dict(row, with_secret=True)


def get_user_by_email(email: str) -> dict | None:
    """按邮箱取用户（Spec22 §5.5：邮箱登录 / 改密码 / 发码查重都走它）。

    **`ORDER BY id ASC LIMIT 1` 是口径，不是随手写的**：`users.email` 上
    **没有** UNIQUE 约束（§2.8——加索引的风险是存量重复数据会让服务起不来，
    而唯一性由发码前的查重保证）。两条同邮箱的存量账号因此是可能的，必须给
    "登录进哪一个"一个确定的答案：**先注册的那个**（id 小的）。

    默认**不带** `password_hash`（`_row_to_dict` 的约定）——本函数的三个消费者
    都不校验密码。传进来的 email 由路由保证已 strip + lower（§2.8，db 层不做
    隐式转换）。
    """
    with _connect() as conn:
        row = conn.execute(
            f"{_USER_SELECT} WHERE u.email = ? ORDER BY u.id ASC LIMIT 1", (email,)
        ).fetchone()
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

def create_user(username: str, password_hash: str, is_admin: bool = False,
                email: str | None = None) -> dict:
    """建号。email（Spec21 §5.1 加的列）只有注册审批路径会传——
    `POST /api/admin/users`（管理员手工建号）不传，落 NULL，前端显示「无」。

    Spec22 §5.1：`phone` 参数**整个删掉**，不是留个默认值——留参数就是留一条
    能写进已删列的路。"""
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at, email) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, password_hash, 1 if is_admin else 0, _now_iso(), email),
            )
            conn.commit()
            user_id = cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise DuplicateUsernameError(f"用户名已存在: {username}") from exc
    return get_user_by_id(user_id)


def list_users() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            f"{_USER_SELECT} ORDER BY u.id ASC"
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


def set_user_quota(user_id: int, quota_limit: int) -> dict | None:
    """设置某用户的服务限额（Spec18 §6.2），返回更新后的用户记录或 None。

    只动 users.quota_limit 一列——**已用次数（user_quota.used）是历史事实，不碰**。
    管理员的"续费"动作就是把限额改大（§2.4）。对管理员设置同样允许（判定时被
    is_admin 豁免），这样"设为/撤销管理员"与限额两个动作正交（§6.2）。

    取值合法性（0 ~ QUOTA_LIMIT_MAX）由路由层校验，本函数不做判断。
    """
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET quota_limit = ? WHERE id = ?", (quota_limit, user_id)
        )
        conn.commit()
    if cur.rowcount == 0:
        return None
    return get_user_by_id(user_id)


def delete_user(user_id: int) -> bool:
    """删除用户；连带删除其 usage / user_quota / images / 社区 / 反馈 / 分享 / 建议 / wiki /
    对话 / 评论记录，保证口径一致（Spec4 §3 / Spec5 §3 / Spec9 §3 / Spec12 §5.3 / Spec17 §5.1f /
    Spec18 §5.1h）。

    注意：仅删除数据库记录。gallery/ 物理文件由 gallery.delete_user_gallery 负责、
    community/ 物理文件由 community.delete_user_posts 负责（都先取文件名再删文件，
    见 main.py admin_delete_user）。帖子投票：本函数删该用户投过的票；其帖子上的
    他人投票由 delete_user_post_records 一并处理。

    Spec17 §5.1f 顺序要求：删"该用户帖子上的他人评论"必须排在 `DELETE FROM posts`
    **之前**，否则子查询已经取不到帖子 id。

    Spec21 §2.6 补充：`recharge_requests` 也在级联清单里（但 `register_requests` 不在
    ——它是审批台账且没有 user_id，理由见 §2.6 的对照表）。
    """
    with _connect() as conn:
        # Spec18 §5.1h：只删账本行，不删 usage 的既有语句（两者都留，各自级联）
        conn.execute("DELETE FROM user_quota WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM usage WHERE user_id = ?", (user_id,))
        # Spec21 §2.6：充值记录是该用户的业务数据，与它们同类——留一堆 user_id 指向
        # 不存在用户的挂账记录，只会让管理端列表里出现点不动的行。
        # （register_requests 相反：它是审批台账且没有 user_id，删号不动它。）
        conn.execute("DELETE FROM recharge_requests WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM images WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM post_votes WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM feedback WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM shares WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM suggestions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM wiki WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        # 评论：先清"挂在该用户帖子上的（含他人的）"，再清"该用户发出的"——顺序不能反
        conn.execute(
            "DELETE FROM post_comments WHERE post_id IN "
            "(SELECT id FROM posts WHERE user_id = ?)",
            (user_id,),
        )
        conn.execute("DELETE FROM post_comments WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM posts WHERE user_id = ?", (user_id,))
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return cur.rowcount > 0


# ---------- 使用统计（Spec4） ----------

def record_call(user_id: int, category: str) -> None:
    """累计一次调用：usage（区间统计）+ user_quota（计费账户）**同一事务**写入。

    新行各列插 0、目标列插 1；已存在行用 excluded 增量累加，避免首次调用被吞。
    category 取自固定白名单；列名均为静态字面量，不拼接外部输入。

    Spec18 §2.2：两个表的和必须永远同步，否则会出现"统计涨了但没扣费"的窗口。
    因此这里刻意开一次连接、写两条语句、一次 commit —— 不要拆成两个函数、
    也不要在调用方串两次。

    调用时机由调用方决定，本函数不做任何"该不该计"的判断：
    - 四类任务（chat/generate/edit/qa）：任务**成功完成后**计一次（Spec4 既有口径，不变）；
    - style：**上游调用发出前**计一次（Spec18 §5.2B，理由见 §2.1"为什么不能沿用成功才计"）。
    """
    if category not in _USAGE_CATEGORIES:
        raise ValueError(f"未知统计类别: {category}")
    values = {c: (1 if c == category else 0) for c in _USAGE_CATEGORIES}
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO usage (user_id, chat, generate, edit, qa, style, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "chat = chat + excluded.chat, "
            "generate = generate + excluded.generate, "
            "edit = edit + excluded.edit, "
            "qa = qa + excluded.qa, "
            "style = style + excluded.style, "
            "updated_at = excluded.updated_at",
            (user_id, values["chat"], values["generate"], values["edit"],
             values["qa"], values["style"], now),
        )
        conn.execute(
            "INSERT INTO user_quota (user_id, used, updated_at) VALUES (?, 1, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "used = used + 1, updated_at = excluded.updated_at",
            (user_id, now),
        )
        conn.commit()


def get_usage_stats() -> dict:
    """聚合统计（管理员只读）：5 类总数 / 注册人数 / 人均 / 占比。

    - user_count = users 表当前注册人数（含 0 次调用者）。
    - 人均 = 各类总数 ÷ user_count；占比 = 各类总数 ÷ 总调用 × 100。
    - 分母为 0 时对应项全部取 0。
    - Spec18：total_calls = sum(totals.values()) 自动含 style；响应结构不变。
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(chat), 0)     AS chat, "
            "       COALESCE(SUM(generate), 0) AS generate, "
            "       COALESCE(SUM(edit), 0)     AS edit, "
            "       COALESCE(SUM(qa), 0)       AS qa, "
            "       COALESCE(SUM(style), 0)    AS style "
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


# ---------- 清零 / 统计区间起点（Spec11 §5.1） ----------

# app_meta 键：值 = UTC ISO 时间，表示"该统计块从何时开始重计"（无该键 = 从未清零）
USAGE_CLEARED_KEY = "usage_cleared_at"
FEEDBACK_CLEARED_KEY = "feedback_cleared_at"


def _upsert_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """在给定连接内 UPSERT 一条 app_meta（供清空函数同一事务里写时间）。"""
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(key: str) -> str | None:
    """读 app_meta 键值；键不存在返回 None（= 该统计块从未清零）。"""
    with _connect() as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    """写一条 app_meta（公开入口，Spec17 §5.1e 起供 TaskQueue 持久化 task_id 用）。"""
    with _connect() as conn:
        _upsert_meta(conn, key, value)
        conn.commit()


def get_cleared_times() -> dict:
    """usage / feedback / clicks 三个"上次清零时间"，供 GET /api/admin/stats 一并返回。

    Spec22 §5.5：多一个 `clicks_cleared_at`。`GET /api/admin/stats` 那句
    `stats.update(db.get_cleared_times())` **一个字都不用改**。
    """
    return {
        USAGE_CLEARED_KEY: get_meta(USAGE_CLEARED_KEY),
        FEEDBACK_CLEARED_KEY: get_meta(FEEDBACK_CLEARED_KEY),
        CLICKS_CLEARED_KEY: get_meta(CLICKS_CLEARED_KEY),
    }


def clear_usage() -> int:
    """清零五类调用计数（删行重计），返回清零前五类调用总次数。

    - 删行而非逐列置 0：清零后首次成功调用由 record_call 的 UPSERT 重建新行、从 0 累计。
    - 只动 usage 表，users（注册人数）/ images / posts 等一概不碰。
    - Spec18 §14.1：清零从此**只重置统计区间，不再有任何计费含义**——
      user_quota 一个字都不动，超额用户不会被解封。
    - 同事务内记录 usage_cleared_at，作为新一段统计区间的起点。
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(chat), 0) + COALESCE(SUM(generate), 0) "
            "     + COALESCE(SUM(edit), 0) + COALESCE(SUM(qa), 0) "
            "     + COALESCE(SUM(style), 0) AS total "
            "FROM usage"
        ).fetchone()
        total = int(row["total"])
        conn.execute("DELETE FROM usage")
        _upsert_meta(conn, USAGE_CLEARED_KEY, _now_iso())
        conn.commit()
    return total


# ---------- 个人作品库（Spec5 §5.3） ----------

def add_image_record(user_id: int, source: str, file_name: str,
                     ext: str, prompt: str | None,
                     note: str | None = None) -> dict:
    """写一条作品记录，返回完整记录 dict。

    note（Spec16）只有作品库直传路径会传；既有 4 处调用都是位置传参、不带它，
    默认值 None 使它们一行都不用改。
    """
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO images (user_id, source, file_name, ext, prompt, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, source, file_name, ext, prompt, note, _now_iso()),
        )
        conn.commit()
        image_id = cur.lastrowid
    return get_image_record(image_id)


def set_image_note(image_id: int, note: str | None) -> bool:
    """改写某作品的备注（Spec16 §5.2C）；note=None 即清空备注。

    只动 note 一列——created_at 不变，所以列表排序位置不变；wiki_used 不碰。
    归属校验由调用方（gallery.update_note 的 _get_owned）负责。
    """
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE images SET note = ? WHERE id = ?", (note, image_id)
        )
        conn.commit()
    return cur.rowcount > 0


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

    字段：id / user_id / text / image_file / created_at / author / author_is_admin /
    like_count / dislike_count / my_vote（null|like|dislike）。

    Spec17：带出 image_file——它是"有没有图"的唯一判据（纯文字帖为 NULL），
    业务层据此决定 image_url 是路径还是 None。**不对外暴露**：路由响应里没有这一项。
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT p.id, p.user_id, p.text, p.image_file, p.created_at, "
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
            "image_file": r["image_file"],
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
    """删除帖子记录及其全部评论，返回其 image_file（供删除物理文件）。

    不存在返回 None；纯文字帖（Spec17）的 image_file 本身也是 None——两种 None
    在调用方走的是同一个 `_unlink_community_file` 分支，无需区分。
    """
    with _connect() as conn:
        row = conn.execute("SELECT image_file FROM posts WHERE id = ?", (post_id,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        conn.execute("DELETE FROM post_votes WHERE post_id = ?", (post_id,))
        conn.execute("DELETE FROM post_comments WHERE post_id = ?", (post_id,))
        conn.commit()
    return row["image_file"]


def delete_user_post_records(user_id: int) -> list[str]:
    """删除某用户全部帖子记录与其相关投票/评论，返回被删帖子的 image_file 列表（供删物理文件）。

    同时清理：该用户帖子上的他人投票 + 该用户投过的所有票 + 该用户发出的全部评论
    + 挂在其帖子上的他人评论（Spec17 §5.1f）。
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
        # 评论两处清理都必须在 DELETE FROM posts 之前（子查询要能取到帖子 id）
        conn.execute(
            "DELETE FROM post_comments WHERE post_id IN "
            "(SELECT id FROM posts WHERE user_id = ?)",
            (user_id,),
        )
        conn.execute("DELETE FROM post_comments WHERE user_id = ?", (user_id,))
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
    """清空反馈统计（可 ?category= 单选或全清），返回删除行数。

    Spec11：**全清（category=None）**时同事务内记录 feedback_cleared_at，作为反馈统计
    新一段区间的起点；**按类单选清空不更新**——会留下其它类的旧数据，语义上不算"归零重计"。
    """
    with _connect() as conn:
        if category:
            if category not in _FEEDBACK_CATEGORIES:
                raise ValueError(f"未知反馈类别: {category}")
            cur = conn.execute("DELETE FROM feedback WHERE category = ?", (category,))
        else:
            cur = conn.execute("DELETE FROM feedback")
            _upsert_meta(conn, FEEDBACK_CLEARED_KEY, _now_iso())
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


# ---------- 个人作品风格 Wiki（Spec12 §5.1 / §5.2） ----------

def get_wiki(user_id: int) -> dict:
    """读本人 Wiki；行不存在返回全空默认值，**不建行**（读操作不写库，Spec12 §5.2A）。"""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM wiki WHERE user_id = ?", (user_id,)).fetchone()
    return _wiki_row_to_dict(row) or {
        "user_id": user_id,
        "style": "",
        "prev_style": None,
        "style_updated_at": None,
        "updated_at": None,
    }


def list_pending_style_images(user_id: int) -> list[dict]:
    """待考虑作品（Spec15 §5.2B）：source ∈ {generate, edit, upload} 且 wiki_used = 0，时间倒序。

    三种来源一视同仁：生成/绘图作品提供 prompt，上传作品提供图片字节（调用方按 source
    分组，上传图走视觉 QA 逐张分析，见 wiki._analyze_uploads）。
    """
    placeholders = ", ".join("?" for _ in _PENDING_SOURCES)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id, source, file_name, prompt, created_at FROM images "  # noqa: S608（占位符由白名单长度生成）
            f"WHERE user_id = ? AND source IN ({placeholders}) AND wiki_used = 0 "
            "ORDER BY created_at DESC, id DESC",
            (user_id, *_PENDING_SOURCES),
        ).fetchall()
    return [
        {"id": r["id"], "source": r["source"], "file_name": r["file_name"],
         "prompt": r["prompt"], "created_at": r["created_at"]}
        for r in rows
    ]


def _upsert_wiki(conn: sqlite3.Connection, user_id: int, style: str,
                 prev_style: str | None, now: str) -> None:
    """在给定连接内写 wiki 行（行不存在则 INSERT，Spec12 §5.2B 第 5 步）。"""
    conn.execute(
        "INSERT INTO wiki (user_id, style, prev_style, style_updated_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "style = excluded.style, prev_style = excluded.prev_style, "
        "style_updated_at = excluded.style_updated_at, updated_at = excluded.updated_at",
        (user_id, style, prev_style, now, now),
    )


def _mark_images_wiki_used(conn: sqlite3.Connection, user_id: int,
                           image_ids: list[int]) -> int:
    """把本次真正纳入合并的作品标记为已用于更新（同一事务内）。"""
    if not image_ids:
        return 0
    placeholders = ", ".join("?" for _ in image_ids)
    cur = conn.execute(
        f"UPDATE images SET wiki_used = 1 "  # noqa: S608（占位符数量由入参长度生成，不含外部文本）
        f"WHERE user_id = ? AND id IN ({placeholders})",
        (user_id, *image_ids),
    )
    return cur.rowcount


def commit_style_update(user_id: int, style: str,
                        used_image_ids: list[int] | None = None) -> dict:
    """写风格：单事务内 upsert wiki（旧 style → prev_style）+ 标记作品（Spec12 §5.3）。

    - `used_image_ids=None`：手动编辑路径，只写 wiki，**不触碰** images.wiki_used。
    - `used_image_ids=[...]`：按钮更新路径，**只**标记这些真正被纳入的作品（含分析成功的
      上传图，Spec15 §5.2B 第 F 步）——没有"顺带标记"这种假账了。

    上游调用失败时不会走到这里，故不存在"作品被标记但风格没更新"的中间态。
    返回写入后的 wiki 记录（含新的 prev_style / style_updated_at）。
    """
    now = _now_iso()
    with _connect() as conn:
        row = conn.execute("SELECT style FROM wiki WHERE user_id = ?", (user_id,)).fetchone()
        prev_style = row["style"] if row is not None else ""   # 首次更新：prev_style 存空串
        _upsert_wiki(conn, user_id, style, prev_style, now)
        if used_image_ids is not None:
            _mark_images_wiki_used(conn, user_id, used_image_ids)
        conn.commit()
    return get_wiki(user_id)


# ---------- 对话历史（Spec17 §5.1g） ----------

def ensure_conversation(conv_id: str, user_id: int) -> dict:
    """取对话；不存在则建（created_at = updated_at = now）。返回记录 dict。

    用 ON CONFLICT DO NOTHING 而非"先查后插"：并发两次提交同一 thread_id 时
    两条 INSERT 都不会撞主键，第二个静默落空（Spec17 §5.3）。
    """
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, user_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
            (conv_id, user_id, now, now),
        )
        conn.commit()
    return get_conversation(conv_id)


def get_conversation(conv_id: str) -> dict | None:
    """按 id 取对话；不存在返回 None。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
    return _conversation_row_to_dict(row)


def find_owned_conversation(conv_id: str, user_id: int) -> dict | None:
    """取本人对话；不存在或不属于本人一律返回 None（调用方转 40407，不泄露存在性）。"""
    conv = get_conversation(conv_id)
    if conv is None or conv["user_id"] != user_id:
        return None
    return conv


def list_conversations(user_id: int, limit: int) -> list[dict]:
    """本人对话列表，updated_at 倒序（侧边栏排序用，显示的是 created_at）。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE user_id = ? "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [_conversation_row_to_dict(r) for r in rows]


def touch_conversation(conv_id: str) -> None:
    """把 updated_at 推到当前时刻（每次追加消息后调用）。"""
    with _connect() as conn:
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (_now_iso(), conv_id),
        )
        conn.commit()


def add_chat_message(conv_id: str, user_id: int, role: str, *,
                     text: str | None, image_id: int | None,
                     task_id: int | None, tool: str | None) -> dict:
    """追加一条消息并 touch 对话（同一事务）。返回完整记录 dict。

    消息 INSERT 与对话 UPDATE 同一事务，避免出现"消息在但顺序不对"（Spec17 §5.3）。
    调用方负责保证 conversations 行已存在（先 ensure_conversation）。
    """
    now = _now_iso()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO chat_messages "
            "(conv_id, user_id, role, text, image_id, task_id, tool, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (conv_id, user_id, role, text, image_id, task_id, tool, now),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id)
        )
        conn.commit()
        message_id = cur.lastrowid
    return get_chat_message(message_id)


def get_chat_message(message_id: int) -> dict | None:
    """按 id 取单条消息（add_chat_message 回读用）。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM chat_messages WHERE id = ?", (message_id,)
        ).fetchone()
    return _chat_message_row_to_dict(row)


def list_chat_messages(conv_id: str) -> list[dict]:
    """某段对话的全部消息，按 id 升序（= 时间正序）。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE conv_id = ? ORDER BY id ASC",
            (conv_id,),
        ).fetchall()
    return [_chat_message_row_to_dict(r) for r in rows]


def list_recent_chat_messages(conv_id: str, limit: int) -> list[dict]:
    """某段对话最近 limit 条，**按 id 升序**返回（供 ThreadStore 回填路由上下文）。

    先倒序 LIMIT 取最近 N 条，再正序返回——路由上下文的时序不能反。
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE conv_id = ? ORDER BY id DESC LIMIT ?",
            (conv_id, limit),
        ).fetchall()
    return [_chat_message_row_to_dict(r) for r in reversed(rows)]


def count_chat_messages(conv_id: str) -> int:
    """某段对话的消息条数（删除对话时记日志用）。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM chat_messages WHERE conv_id = ?", (conv_id,)
        ).fetchone()
    return int(row["n"])


def delete_conversation(conv_id: str) -> None:
    """删对话及其全部消息。**不触碰 images**（Spec17 §2.1：删对话不删作品）。"""
    with _connect() as conn:
        conn.execute("DELETE FROM chat_messages WHERE conv_id = ?", (conv_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        conn.commit()


# ---------- 帖子评论（Spec17 §5.1d / §5.1g） ----------

def create_comment(post_id: int, user_id: int, text: str) -> dict:
    """写一条评论，返回带 author / author_is_admin 的记录 dict。"""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO post_comments (post_id, user_id, text, created_at) "
            "VALUES (?, ?, ?, ?)",
            (post_id, user_id, text, _now_iso()),
        )
        conn.commit()
        comment_id = cur.lastrowid
    return get_comment(comment_id)


def get_comment(comment_id: int) -> dict | None:
    """按 id 取评论（含 author 字段）；不存在返回 None。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT c.*, u.username AS author, u.is_admin AS author_is_admin "
            "FROM post_comments c JOIN users u ON u.id = c.user_id "
            "WHERE c.id = ?",
            (comment_id,),
        ).fetchone()
    return _post_comment_row_to_dict(row)


def list_comments_for_posts(post_ids: list[int]) -> dict[int, list[dict]]:
    """批量取多帖的评论，按 post_id 分组，组内 id 升序。

    一次 JOIN users 查完（见 §5.1g），避免列表接口变成 N+1。post_ids 为空直接返回 {}。
    """
    if not post_ids:
        return {}
    placeholders = ", ".join("?" for _ in post_ids)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT c.*, u.username AS author, u.is_admin AS author_is_admin "  # noqa: S608（占位符数量由入参长度生成）
            "FROM post_comments c JOIN users u ON u.id = c.user_id "
            f"WHERE c.post_id IN ({placeholders}) "
            "ORDER BY c.id ASC",
            tuple(post_ids),
        ).fetchall()
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        record = _post_comment_row_to_dict(row)
        grouped.setdefault(record["post_id"], []).append(record)
    return grouped


def delete_comment(comment_id: int) -> None:
    """删一条评论。"""
    with _connect() as conn:
        conn.execute("DELETE FROM post_comments WHERE id = ?", (comment_id,))
        conn.commit()


# ---------- 注册申请与审批（Spec19 §5.1d）----------

def create_register_request(username: str, password_hash: str,
                            email: str | None, wechat: str) -> dict:
    """插入一条 pending 申请，返回完整记录（**不含** password_hash）。

    Spec22 §5.1：`phone` / `ip` 两个参数**整个删掉**（调用方也不再算 ip）——
    留参数就是留一条能写进已删列的路。防重改由邮箱验证码承担（§2.5）。
    """
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO register_requests "
            "(username, password_hash, email, wechat, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (username, password_hash, email, wechat, _now_iso()),
        )
        conn.commit()
        request_id = cur.lastrowid
    return get_register_request(request_id)


def get_register_request(request_id: int, *, with_secret: bool = False) -> dict | None:
    """按 id 取申请；不存在返回 None。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM register_requests WHERE id = ?", (request_id,)
        ).fetchone()
    return _register_row_to_dict(row, with_secret=with_secret)


def list_register_requests() -> list[dict]:
    """全部申请：**pending 优先**，组内 id 倒序（最新在前）。不含 password_hash。

    排序写成 `ORDER BY (status = 'pending') DESC, id DESC`：
    SQLite 里布尔表达式求值为 0/1，所以"是 pending 的排前面"是一行 SQL 的事。
    已处理的记录按时间倒序跟在后面——它们是台账，不是待办。
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM register_requests "
            "ORDER BY (status = 'pending') DESC, id DESC"
        ).fetchall()
    return [_register_row_to_dict(r) for r in rows]


def find_pending_register_by_email(email: str) -> dict | None:
    """该邮箱是否已有一条**待审批**申请；有则返回那一行，没有则 None。

    Spec22 §2.4 新增的判据：删掉 IP 冷却之后，"同一邮箱反复提交、你反复收到
    同一份审批邮件"就只剩这一道闸门。**只看 pending**——已同意/已拒绝的历史行
    不该挡住新的申请（Spec19 §2.2：被拒了可以再申请，那正是台账要保留的东西）。

    §5.5 的函数清单里漏了这一个（清单只列了 `get_user_by_email` 与四个新表的
    函数），但 §6.2 第 5 条的 pending 分支必须有它——以 §2.4 / §6.2 为准。

    email 由路由层小写化后传入（§2.8），这里不做隐式转换。
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM register_requests "
            "WHERE email = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
            (email,),
        ).fetchone()
    return _register_row_to_dict(row)


# Spec22 §5.5 删除：find_recent_register_by_ip(ip, window_seconds)
#   它的唯一消费者是"同一 IP 24 小时一次"的注册冷却（Spec19 §2.2），
#   需求 3 把那条限制整个删掉了。防重改由邮箱验证码承担。
#   注意 auth.client_ip 仍在——它还有登录限速与点击埋点两个消费者（§2.11）。


def approve_register_request(request_id: int, quota_limit: int) -> dict | None:
    """同意：**单事务**内建号 + 改状态 + 置空哈希。返回新建的用户 dict；
    该行已不是 pending（并发抢跑）时返回 None（调用方转 40903）。
    用户名撞 UNIQUE 时抛 DuplicateUsernameError（调用方转 40901）。

    为什么必须一个事务：若先 create_user() 提交、再单独改状态，中间会开出一个
    "号已经建了，但申请记录还是 pending"的窗口。管理员此时再点一次「同意」→ 撞
    `40901 用户名已存在` → 那条记录永远停在 pending、永远点不动。这与 Spec18
    §5.1g「record_call 必须一次事务写两张表」是同一类错误：跨表的状态必须同生同死。

    quota_limit 直接写在 INSERT 里，而不是建完号再调 set_user_quota：后者是第二次
    事务，同样会开出"号建了但限额还是默认值"的窗口。users.quota_limit 本来就有列
    默认值（QUOTA_DEFAULT_LIMIT），显式传值只是覆盖它——一条语句解决。

    user_quota 行不用建：_USER_SELECT 用 LEFT JOIN + COALESCE(q.used, 0)，
    没有 quota 行等价于"已用 0 次"。新建的号由第一次 record_call 的 UPSERT 建行
    ——与既有的 create_user 行为完全一致，不引入第二条路径。
    """
    req = get_register_request(request_id, with_secret=True)
    if req is None:
        return None
    now = _now_iso()
    try:
        with _connect() as conn:
            # Spec21 §5.1 / Spec22 §5.1：联系方式（只剩 email）直接取申请行
            # （get_register_request(with_secret=True) 已经把它带出来了）。
            # 手工建号那条路不传，落 NULL。旧申请行的 email 可能是 NULL。
            cur = conn.execute(
                "INSERT INTO users "
                "(username, password_hash, is_admin, created_at, quota_limit, email) "
                "VALUES (?, ?, 0, ?, ?, ?)",
                (req["username"], req["password_hash"], now, quota_limit, req["email"]),
            )
            user_id = cur.lastrowid
            # 并发判据用 WHERE ... AND status='pending' 的 rowcount，而不是"先查后写"：
            # 两个管理员同时点同意时，后到的那个 UPDATE 影响 0 行 → 整个事务回滚。
            marked = conn.execute(
                "UPDATE register_requests "
                "SET status = 'approved', reviewed_at = ?, password_hash = '' "
                "WHERE id = ? AND status = 'pending'",
                (now, request_id),
            )
            if marked.rowcount == 0:
                conn.rollback()
                return None
            conn.commit()
    except sqlite3.IntegrityError as exc:      # users.username UNIQUE 撞车
        raise DuplicateUsernameError(f"用户名已存在: {req['username']}") from exc
    return get_user_by_id(user_id)


def reject_register_request(request_id: int) -> dict | None:
    """拒绝：只改状态。**保留 password_hash**（该密码从未生效，见 §3.3-5）。
    该行已不是 pending 时返回 None。"""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE register_requests SET status = 'rejected', reviewed_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (_now_iso(), request_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    return get_register_request(request_id)


def delete_register_request(request_id: int) -> bool:
    """删掉一条申请记录（任意状态）。**不触碰 users**（§5.3）。返回是否有行被删。"""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM register_requests WHERE id = ?", (request_id,))
        conn.commit()
    return cur.rowcount > 0


# ---------- 余额与充值（Spec21 §5.4）----------

def create_recharge_request(user_id: int, username: str, wechat: str, source: str) -> dict:
    """落一条充值申请。source 必须已在路由层过白名单（本函数只再兜一次底）。

    username 是**提交时刻的快照**：台账要能脱离 users 表被读懂（§2.3）。
    """
    if source not in _RECHARGE_SOURCES:
        raise ValueError(f"未知充值来源: {source}")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO recharge_requests "
            "(user_id, username, wechat, source, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (user_id, username, wechat, source, _now_iso()),
        )
        conn.commit()
        request_id = cur.lastrowid
    return get_recharge_request(request_id)


def get_recharge_request(request_id: int) -> dict | None:
    """按 id 取一条充值记录；不存在返回 None。**没有 with_secret**——本表没有密码。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM recharge_requests WHERE id = ?", (request_id,)
        ).fetchone()
    return _recharge_row_to_dict(row)


def find_pending_recharge(user_id: int) -> dict | None:
    """该用户是否已有一条待审批的充值申请（幂等判据，§2.4）。

    只认 pending：被拒绝（比如昵称填错了）之后重新提交是**正常且必要**的路径，
    已同意的也不拦（加完额度后用户可能还想再充）。
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM recharge_requests WHERE user_id = ? AND status = 'pending' "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return _recharge_row_to_dict(row)


def find_recent_recharge_by_user(user_id: int, window_seconds: int) -> dict | None:
    """该用户在冷却期内的最近一条充值申请；没有则 None（Spec21 §2.4 的频次限制）。

    与 find_pending_recharge 的区别：那个只看 `status='pending'`，这个**不看状态**。
    冷却期管的是"提交这个动作"的频次，也就是发信的频次——被拒 / 已同意之后马上
    再点一次，同样不该再发一封信（那正是刷邮箱的路径）。

    截止时刻的算法与 find_recent_email_verification 完全同款（那边有详细理由）：
    created_at 是 `YYYY-MM-DDTHH:MM:SS.mmmZ`，同格式同宽度的 ISO 串字典序即时间序，
    所以在 Python 侧算好 cutoff 再交给 SQL 比字符串，**不要**用 SQLite 的 datetime()。
    """
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=window_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM recharge_requests WHERE user_id = ? AND created_at >= ? "
            "ORDER BY id DESC LIMIT 1",
            (user_id, cutoff),
        ).fetchone()
    return _recharge_row_to_dict(row)


def list_recharge_requests() -> list[dict]:
    """全部充值记录：**pending 优先**，组内 id 倒序（最新在前）。

    排序写法与 list_register_requests 同款：SQLite 里布尔表达式求值为 0/1。
    已处理的记录按时间倒序跟在后面——它们是台账，不是待办。
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM recharge_requests "
            "ORDER BY (status = 'pending') DESC, id DESC"
        ).fetchall()
    return [_recharge_row_to_dict(r) for r in rows]


def approve_recharge_request(request_id: int, amount: int) -> dict | None:
    """同意：**单事务**内 置 approved + 记 amount + users.quota_limit += amount。
    返回加完额度后的用户 dict；该行已不是 pending（并发抢跑）时返回 None（调用方转 40904）。

    为什么必须一个事务：先改状态再单独加额度，中间会开出"记录已批准，但额度没到账"
    的窗口——用户拿着批准记录来找你，而系统显示他没充过。这与 Spec19 §5.2B
    「建号 + 改状态必须同生同死」是同一类错误。

    **不动 user_quota.used**：它是历史事实（Spec18 §2.2），充值改变的是"还能用多少次"。
    也**不做上限校验**：取值范围（≥1 且加完不超 QUOTA_LIMIT_MAX）由路由层判。

    并发判据用 `WHERE ... AND status='pending'` 的 rowcount，而不是"先查后写"：
    两个管理员同时点同意时，后到的那个 UPDATE 影响 0 行 → rollback，额度只加一次。
    ⚠️ UPDATE recharge 必须排在 UPDATE users **之前**：rowcount 是回滚的判据，
    而回滚要能撤销已经发生的加额度。
    """
    req = get_recharge_request(request_id)
    if req is None:
        return None
    now = _now_iso()
    with _connect() as conn:
        marked = conn.execute(
            "UPDATE recharge_requests SET status = 'approved', reviewed_at = ?, amount = ? "
            "WHERE id = ? AND status = 'pending'",
            (now, amount, request_id),
        )
        if marked.rowcount == 0:
            conn.rollback()
            return None
        credited = conn.execute(
            "UPDATE users SET quota_limit = quota_limit + ? WHERE id = ?",
            (amount, req["user_id"]),
        )
        # 第二道 rowcount 检查。正常路径下**到不了这里**：delete_user 会在同一个事务里
        # 删掉该用户的 recharge_requests 行（§2.6），所以"用户没了但充值行还在"这个
        # 状态不存在——那时上面的 marked.rowcount 已经是 0。留着它是为了万一将来
        # 有人改了 delete_user 的级联清单：宁可这次点不动（40904），也绝不能留下
        # 一条"记录已批准、额度没到账"的挂账（§2.5）。
        if credited.rowcount == 0:
            conn.rollback()
            return None
        conn.commit()
    return get_user_by_id(req["user_id"])


def reject_recharge_request(request_id: int) -> dict | None:
    """拒绝：只改状态。该行已不是 pending 时返回 None。**不加额度、不删记录**。"""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE recharge_requests SET status = 'rejected', reviewed_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (_now_iso(), request_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    return get_recharge_request(request_id)


def delete_recharge_request(request_id: int) -> bool:
    """删掉一条充值记录（任意状态）。**不触碰 users**（§2.6）。

    删除一条**已同意**的记录**不会**把加过的额度收回来——那要走「改限额」。
    """
    with _connect() as conn:
        cur = conn.execute("DELETE FROM recharge_requests WHERE id = ?", (request_id,))
        conn.commit()
    return cur.rowcount > 0


# ---------- 邮箱验证码（Spec22 §5.5）----------
# 生成码的**纯逻辑**在 verifications.py（不读库）；要读库的三条规则在这里：
# TTL、重发冷却、"TTL 内任一命中都算数"（§14.2 说明了这条切法的理由）。

def create_email_verification(email: str, purpose: str, code: str,
                              ttl_seconds: int) -> dict:
    """落一个码，**同一个事务**里顺手删掉已过期的行，返回新行。

    为什么顺手清理而不是定时任务：表里最多只有"最近 TTL 内发出的码"，
    不可能长大（§2.2）。为一个几十行的表引入一个定时器不值得（§14.3-2）。

    cutoff 在 **Python 侧**算好再传进 SQL，不用 SQLite 的 datetime('now', ...)：
    created_at 是 `YYYY-MM-DDTHH:MM:SS.mmmZ` 形态（_now_iso），与 SQLite 默认的
    `YYYY-MM-DD HH:MM:SS` 格式**字符串不可比**。同格式同宽度的 ISO 串，
    字典序即时间序，直接比较是安全的（这是本仓的既定做法）。
    """
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with _connect() as conn:
        conn.execute("DELETE FROM email_verifications WHERE created_at < ?", (cutoff,))
        cur = conn.execute(
            "INSERT INTO email_verifications (email, purpose, code, created_at) "
            "VALUES (?, ?, ?, ?)",
            (email, purpose, code, _now_iso()),
        )
        conn.commit()
        row_id = cur.lastrowid
    return get_email_verification(row_id)


def get_email_verification(verification_id: int) -> dict | None:
    """按 id 取一行（仅供 create_email_verification 回读刚插入的那行）。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM email_verifications WHERE id = ?", (verification_id,)
        ).fetchone()
    return dict(row) if row else None


def find_recent_email_verification(email: str, purpose: str,
                                   window_seconds: int) -> dict | None:
    """该邮箱在该场景下冷却期内的最近一条码；没有则 None（重发冷却的判据）。

    按 **(email, purpose)** 隔离，不是只看 email：给"注册"发的码与给"登录"发的
    码是两个独立的 1 分钟窗口，互不影响（§2.2 的 purpose 列就是这个用途）。
    """
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=window_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM email_verifications "
            "WHERE email = ? AND purpose = ? AND created_at >= ? "
            "ORDER BY id DESC LIMIT 1",
            (email, purpose, cutoff),
        ).fetchone()
    return dict(row) if row else None


def match_email_verification(email: str, purpose: str, code: str,
                             ttl_seconds: int) -> bool:
    """TTL 内该 (邮箱, 场景) 是否存在这个码。

    `SELECT 1 ... LIMIT 1` 而非数数：只要有一个命中就算数——这正是用户要的
    "10 分钟 TTL 内生成的数字串只要有一个对了都算数"（§2.2）。**同一时间可以有
    多个有效的码**（重发过），它们全都算数。
    """
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM email_verifications "
            "WHERE email = ? AND purpose = ? AND code = ? AND created_at >= ? LIMIT 1",
            (email, purpose, code, cutoff),
        ).fetchone()
    return row is not None


# ---------- 入口点击统计（Spec22 §5.3 / §5.5）----------

def record_click(event: str, ip: str) -> bool:
    """记一次点击，返回**这是不是一个新记下的不重复 IP**（§2.9）。

    返回值只用于决定要不要打日志——不是"成功了没"。重复点击（同 IP 同事件）
    走 UNIQUE(event, ip) 被 INSERT OR IGNORE 静静吞掉，rowcount 为 0。

    不要在应用层写"先查再插"：那是两个并发请求能同时通过检查的经典竞态，
    而数据库的唯一约束天然是原子的。
    """
    with _connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO click_events (event, ip, created_at) VALUES (?, ?, ?)",
            (event, ip, _now_iso()),
        )
        conn.commit()
    return cur.rowcount == 1


def get_click_stats() -> dict:
    """每个事件的**不重复 IP 数**，**恒含白名单里全部 5 个键**（没有记录的为 0）。

    补齐缺键是刻意的：前端不用处理"这个键可能不存在"，也不用在模板里写 `?? 0`
    （§6.8）。
    """
    stats = {event: 0 for event in _CLICK_EVENTS}
    with _connect() as conn:
        rows = conn.execute(
            "SELECT event, COUNT(*) AS n FROM click_events GROUP BY event"
        ).fetchall()
    for row in rows:
        stats[row["event"]] = int(row["n"])
    return stats


def clear_clicks() -> int:
    """清空入口点击统计（删行重计），返回删掉的行数。

    与 Spec18 的 clear_usage 同款：**一个事务**里删行 + 写"上次清零时间"
    ——清零与它必须同生同死，否则会出现"数字归零了、时间还是上一次"的错位。
    它只重置统计区间，不动任何计费口径（点击本来就不计费，§6.7）。
    """
    with _connect() as conn:
        cur = conn.execute("DELETE FROM click_events")
        cleared = cur.rowcount
        _upsert_meta(conn, CLICKS_CLEARED_KEY, _now_iso())
        conn.commit()
    return cleared
