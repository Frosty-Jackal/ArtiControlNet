"""ArtiControlNet 后端环境配置（唯一配置源）。

读取 Server/.env（python-dotenv），所有环境变量均有默认值。
真实密钥只放 Server/.env，不写进仓库。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# ===== 路径 =====
BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"          # 临时图片目录（/images 静态挂载，TTL 1h）
GALLERY_DIR = BASE_DIR / "gallery"          # 个人作品库持久目录（Spec5，与 storage/ 无关）
COMMUNITY_DIR = BASE_DIR / "community"      # 社区帖子图片持久目录（Spec9，与 storage/ 无关）
STATIC_DIR = BASE_DIR / "static"            # 生产环境挂载 frontend/dist

load_dotenv(BASE_DIR / ".env")

# ===== DeepSeek（Supervisor 路由 + 图像 QA）=====
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-v4-flash")            # 纯文本路由
VLM_MODEL = os.getenv("VLM_MODEL", "deepseek-v4-flash-vision-exp")   # 视觉 QA

# ===== TokenHub 统一生图（文生图 + 线稿生图，hy-image-v3）=====
TOKENHUB_API_KEY = os.getenv("TOKENHUB_API_KEY", "")
TOKENHUB_API_URL = os.getenv(
    "TOKENHUB_API_URL",
    "https://tokenhub.tencentmaas.com/v1/wand/hunyuan-image/v3-generation",
)
HUNYUAN_IMAGE_MODEL = os.getenv("HUNYUAN_IMAGE_MODEL", "hy-image-v3")
HUNYUAN_IMAGE_SIZE = os.getenv("HUNYUAN_IMAGE_SIZE", "1024x1024")
TOKENHUB_TIMEOUT_SECONDS = int(os.getenv("TOKENHUB_TIMEOUT_SECONDS", "180"))

# ===== 服务 =====
MAIN_SERVER_HOST = os.getenv("MAIN_SERVER_HOST", "0.0.0.0")
MAIN_SERVER_PORT = int(os.getenv("MAIN_SERVER_PORT", "8000"))
# 对外暴露的基址，用于拼绝对图片 URL；未配置时按请求 Host 推导（见 main.py）
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
CORS_ALLOW_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

# ===== 社区 / 分享 / 建议（Spec9）=====
SHARE_TTL_SECONDS = int(os.getenv("SHARE_TTL_SECONDS", "604800"))  # 分享链接有效期（默认 7 天）
COMMUNITY_POST_TEXT_MAX = 1000        # 社区帖子文字上限（前后端同值）
SUGGESTION_TEXT_MAX = 2000            # 建议文字上限（前后端同值）

# ===== 对话历史 / 评论（Spec17）=====
COMMENT_TEXT_MAX = int(os.getenv("COMMENT_TEXT_MAX", "200"))                 # 单条评论字数上限
CONVERSATION_LIST_LIMIT = int(os.getenv("CONVERSATION_LIST_LIMIT", "50"))    # 侧边栏对话列表上限（不分页）

# ===== 个人作品风格 Wiki（Spec12）=====
WIKI_STYLE_MAX = int(os.getenv("WIKI_STYLE_MAX", "2000"))               # 手编 / 生成的风格文本上限（字）
WIKI_PROMPT_ITEM_MAX = int(os.getenv("WIKI_PROMPT_ITEM_MAX", "500"))    # 单条作品 prompt 提取上限（字）
WIKI_PROMPT_TOTAL_MAX = int(os.getenv("WIKI_PROMPT_TOTAL_MAX", "6000")) # 一次合并送入 LLM 的参考文字总上限（字）

# ---- 上传作品纳入风格（Spec15）----
WIKI_UPLOAD_QA_MAX = int(os.getenv("WIKI_UPLOAD_QA_MAX", "10"))                 # 单次刷新最多分析的上传图张数
WIKI_UPLOAD_QA_CONCURRENCY = int(os.getenv("WIKI_UPLOAD_QA_CONCURRENCY", "3"))  # 视觉 QA 并发路数
WIKI_UPLOAD_ANSWER_MAX = int(os.getenv("WIKI_UPLOAD_ANSWER_MAX", "300"))        # 单条上传图分析结果的截断上限（字）
WIKI_UPLOAD_QA_MAX_SIDE = int(os.getenv("WIKI_UPLOAD_QA_MAX_SIDE", "1024"))     # 送模型前缩放的最长边（px）
# 调参建议：WIKI_UPLOAD_QA_MAX × WIKI_UPLOAD_ANSWER_MAX 宜 ≤ WIKI_PROMPT_TOTAL_MAX（默认 10×300=3000 ≤ 6000）
# WIKI_UPLOAD_QA_MAX=0 是合法但特殊的取值：上传作品永远轮不到分析（临时关掉上传分析的排障开关，非常规配置）

# ===== 认证（Spec2：登录 + 用户管理）=====
JWT_SECRET = os.getenv("JWT_SECRET", "")              # JWT 签名密钥，只放 .env，未配置则启动报错
JWT_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", "604800"))  # token 有效期（默认 7 天）
# 首次启动时自动创建的初始管理员（仅 users 表为空时使用；建号后即可在管理端修改）
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
AUTH_DB_PATH = BASE_DIR / "artcn.db"                  # 本地 SQLite 账号库（持久化，与 storage/ 无关）

# ===== 注册申请与审批（Spec19）=====
# 客服 / 管理员邮箱（**唯一来源**）。注册页的客服行、每日提示，以及 Spec20 的
# SMTP_USER / REGISTER_NOTIFY_TO、Spec21 的 RECHARGE_NOTIFY_TO 都跟随它。
#
# 注意本段**曾经**必须排在 Spec18 限额块之前（那时 SPEC18 的 QUOTA_CONTACT_EMAIL
# 取这里的 SUPPORT_EMAIL）。QUOTA_CONTACT_EMAIL 已随超额文案改版删除，那条位置
# 约束**不再存在**——现在的约束只剩一条：Spec20 / Spec21 两段必须排在**本段之后**
# （它们的默认值取 SUPPORT_EMAIL）。不要照旧注释里的说法去"维持"一段已经无所谓的顺序。
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "frostyj@qq.com").strip()

# 注册申请开关：置 false 时 /api/auth/register 返回 40305，前端同时隐藏注册入口（Spec19 §3.3-7）。
# 取值照抄"字符串转布尔"的宽松写法，只有明确的假值才算关。
REGISTER_ENABLED = os.getenv("REGISTER_ENABLED", "true").strip().lower() not in (
    "0", "false", "no", "off", "",
)

# 同一 IP 的申请冷却期（秒）。默认 86400 = 24 小时（Spec19 §2.2 的滚动窗口）。
REGISTER_IP_WINDOW_SECONDS = int(os.getenv("REGISTER_IP_WINDOW_SECONDS", "86400"))

# 收款码文件（**不进仓库**，见 .gitignore；部署时手动放到这个位置）。
# 不是环境变量：它是一条路径，与 AUTH_DB_PATH 同类。
PAYMENT_QR_PATH = BASE_DIR / "payment.jpg"

# 两句给用户看的提示语（唯一来源，前端零副本——与 QUOTA_EXCEEDED_MESSAGE 同一原则）
REGISTER_PRICE_NOTICE = "请先预充值，0.9 元起充，参考价格：0.9 元约 10 次设计服务"
REGISTER_DAILY_NOTICE = (
    f"每人每天只能申请一个账号，若操作失误或其他需求请联系在线客服 {SUPPORT_EMAIL}"
)

# ===== 注册申请邮件通知（Spec20）=====
# 本段必须排在 Spec19 注册块**之后**：SMTP_USER / REGISTER_NOTIFY_TO 的默认值都取
# SUPPORT_EMAIL，而 Python 是从上往下执行的（与上面那段同一个理，Spec20 §8.1）。
#
# 唯一的开关是 SMTP_PASSWORD：**留空 = 完全不发信**，注册行为与 Spec19 逐字节等价。
# 刻意不设 REGISTER_NOTIFY_ENABLED——多一个开关就多一种"配了授权码但忘了打开"的静默失败。
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.qq.com").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))          # 465 = SMTP_SSL（不是 587 STARTTLS）
SMTP_USER = os.getenv("SMTP_USER", SUPPORT_EMAIL).strip()

# 授权码，**不是** QQ 登录密码：QQ 邮箱 → 右上角头像 → 「账号与安全」→「安全设置」
# → 「POP3/IMAP/SMTP/...服务」→ 生成授权码。只放 .env（与 JWT_SECRET 同级处理），绝不进仓库。
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# 收件人。默认跟随 SUPPORT_EMAIL，但**单独一个变量**：SUPPORT_EMAIL 是给用户看的
# 客服邮箱，哪天换成对外公开邮箱时，通知不该跟着寄到别处（Spec20 §2.4）。
REGISTER_NOTIFY_TO = os.getenv("REGISTER_NOTIFY_TO", SUPPORT_EMAIL).strip()

# SMTP 超时（秒）。发信在线程池里跑，超时只影响那个线程，不影响注册请求（Spec20 §2.1）。
SMTP_TIMEOUT_SECONDS = int(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))

# ===== 余额与充值（Spec21）=====
# 本段必须排在 Spec19 注册块**之后**：RECHARGE_NOTIFY_TO 的默认值取 SUPPORT_EMAIL，
# 而 Python 是从上往下执行的（与本文件里前两段同一个理，Spec21 §8.1）。
#
# 充值弹窗里那句参考价（唯一来源，前端零副本——与 REGISTER_PRICE_NOTICE 同一原则）。
# 注意它与余额公式的口径**故意不同**：余额按 1 元 = 10 次的名义价算（用户给定，
# Spec21 §2.9），而这句说的是实收价（0.9 元约 10 次）。两者不一致是有意的，别"统一"。
RECHARGE_PRICE_NOTICE = "充值参考：0.9元约10次设计服务"

# 微信昵称的长度上限（前后端同值？**不是**——前端只拦必填，长度由后端 40019 报，
# 与 Spec19 对手机号/邮箱的处理同一个立场：规则只有一份中文 message，在后端）。
RECHARGE_WECHAT_MAX = int(os.getenv("RECHARGE_WECHAT_MAX", "64"))

# 同一用户的充值申请冷却期（秒）。默认 180 = 3 分钟（用户给的频次限制）。
# 冷却期内再提交 → 后端返回 40905，前端跳出告警（那句文案见下面）。
# 它同时是**发信**的频次上限：每条新申请最多一封信，而新申请最多每 3 分钟一条。
RECHARGE_COOLDOWN_SECONDS = int(os.getenv("RECHARGE_COOLDOWN_SECONDS", "180"))

# 冷却期告警的文案（唯一来源，前端零副本——与 QUOTA_EXCEEDED_MESSAGE 同一原则）。
# 分钟数是**从上面的秒数推出来的**，不是另写一个 "3"：改了冷却期而忘了改文案，
# 就会出现"提示说 3 分钟、实际拦 10 分钟"这种没人查得出来的谎话。
# 不足 1 分钟按 1 分钟说（宁可把窗口说长，也不说"每 0 分钟"）。
RECHARGE_COOLDOWN_MESSAGE = (
    f"每{max(1, RECHARGE_COOLDOWN_SECONDS // 60)}分钟才可以申报一次充值！"
    "请耐心等待，若已充值，金额会在30秒内尽快到账！"
)

# 充值提醒的收件人。默认跟随 SUPPORT_EMAIL，但**单独一个变量**：
# SUPPORT_EMAIL 是给用户看的客服邮箱，哪天换成对外公开邮箱，充值提醒不该跟着寄到别处
# （与 Spec20 的 REGISTER_NOTIFY_TO 同一个取舍）。
RECHARGE_NOTIFY_TO = os.getenv("RECHARGE_NOTIFY_TO", SUPPORT_EMAIL).strip()

# ===== 服务限额（Spec18：API 服务调用计量与用户限额）=====
QUOTA_DEFAULT_LIMIT = int(os.getenv("QUOTA_DEFAULT_LIMIT", "25"))    # 新建用户的默认限额（累计次数）
QUOTA_LIMIT_MAX = int(os.getenv("QUOTA_LIMIT_MAX", "100000"))        # 管理员可设的限额上限（防误输入天文数字）
# 超额提示语（唯一来源；前端只负责显示后端返回的 message，不做同值副本）
#
# ⚠️ 文案里**不再带客服邮箱**（用户改的口径）：提示语本身已经把用户指向「充值面板」，
# 而收款码与参考价都在那个面板里，再塞一个邮箱只会让人去发邮件而不去点面板。
# 因此原本只为拼这句而存在的 QUOTA_CONTACT_EMAIL 已删除——留一个「设了也不生效」的
# 环境变量，正是本仓反复记录的那类静默失败（同 Spec20 不设 REGISTER_NOTIFY_ENABLED
# 的理由）。客服邮箱仍是 SUPPORT_EMAIL，注册页那行「有问题请致信官方客服」照常用它。
QUOTA_EXCEEDED_MESSAGE = "您的余额已不足，若您单击登录键则会跳出充值面板！"
# 注意 QUOTA_DEFAULT_LIMIT 的作用域：它只在「新建用户」与「补列迁移给存量行填初值」两处生效，
# 改它**不会**影响任何已存在的用户（Spec18 §3.3-5）。要给某人加额度走
# PUT /api/admin/users/{id}/quota。

# ===== 任务引擎 =====
MAX_PENDING_TASKS = int(os.getenv("MAX_PENDING_TASKS", "100"))     # 待处理上限，超过返回 50301
TASK_TIMEOUT_SECONDS = int(os.getenv("TASK_TIMEOUT_SECONDS", "300"))
THREAD_HISTORY_LIMIT = int(os.getenv("THREAD_HISTORY_LIMIT", "20"))
TERMINAL_TASK_TTL_SECONDS = 3600         # 终态任务保留时长
JANITOR_INTERVAL_SECONDS = 300           # 清理巡检间隔
PENDING_INTENT_TTL_SECONDS = 1800        # 挂起意图有效期（Spec5 §5.5，到期视为新会话）

# ===== 图片 / 上传 =====
UPLOAD_MAX_BYTES = 10 * 1024 * 1024          # 上传 ≤10MB
QA_IMAGE_MAX_BYTES = 32 * 1024 * 1024        # QA 模型单图 ≤32MiB
SKETCH_MAX_SIDE_PX = 2000                    # 线稿单边 >2000px 视为超限，先缩放
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_IMAGE_MIME = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
}
IMAGE_TTL_SECONDS = 3600                     # storage 文件 TTL 1h
GALLERY_NOTE_MAX = int(os.getenv("GALLERY_NOTE_MAX", "200"))   # 上传作品备注字数上限（Spec16）
# 注意：前端 GalleryPanel.vue 的 GALLERY_NOTE_MAX 是同值副本，改这里必须同步改前端

# 启动时确保目录存在
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
GALLERY_DIR.mkdir(parents=True, exist_ok=True)
COMMUNITY_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
