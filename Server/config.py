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

# Spec22 删除：REGISTER_IP_WINDOW_SECONDS
#   唯一消费者是"同一 IP 24 小时一次"的注册冷却，需求 3 已把它整个删掉（§2.11）。
#   留一个"设了也不生效"的变量，正是 CLAUDE.md 为 QUOTA_CONTACT_EMAIL 记过的那类静默失败。

# 收款码文件（**不进仓库**，见 .gitignore；部署时手动放到这个位置）。
# 不是环境变量：它是一条路径，与 AUTH_DB_PATH 同类。
PAYMENT_QR_PATH = BASE_DIR / "payment.jpg"

# 给用户看的提示语（唯一来源，前端零副本——与 QUOTA_EXCEEDED_MESSAGE 同一原则）
#
# Spec23 §2.8 删除：REGISTER_PRICE_NOTICE，改成下面的 REGISTER_PRICE_LINE。
#   它原来还兼着"注册弹窗里那句预充值提示"的职责，那个块整个删了（注册弹窗里
#   的收款码与预充值提示都随自助注册一起消失）。现在它只服务**欠费充值面板**
#   （登录页被踢出来时弹的那个），文案一个字不改。
#
# 欠费充值面板的参考价（Spec19 §6.1 起就有的那个键，Spec23 换了形状）。
# 单片段、无删除线——需求只要求给「余额与充值」页加划线价（§0 第 3-b 条）。
# 与 RECHARGE_PRICE_LINE 形状一致，所以 RechargeModal 两个模式共用一份渲染。
REGISTER_PRICE_LINE = (
    {"text": "请先预充值，0.9 元起充，参考价格：0.9 元约 10 次设计服务"},
)
# Spec22 删除：REGISTER_DAILY_NOTICE
#   原文「每人每天只能申请一个账号…」随同一条限制一起消失。
#   连带 GET /api/auth/register-config 不再返回 daily_notice、RegisterModal 删掉那一行（§2.11）。

# ===== 邮箱验证码（Spec22）=====
# 本段与 SMTP 无关（只放两个数字与几句文案），所以不需要等 Spec20 的变量，
# 放在 Spec19 注册块之后、Spec20 邮件块之前即可。

# 验证码 TTL（秒）。默认 600 = 10 分钟。存进 email_verifications.created_at 的
# cutoff 由它算出来，邮件正文里那句"验证码 N 分钟内有效"也由它推出来
# （照 RECHARGE_COOLDOWN_MESSAGE 的先例：分钟数永远跟着秒数走，改一处就够）。
EMAIL_CODE_TTL_SECONDS = int(os.getenv("EMAIL_CODE_TTL_SECONDS", "600"))

# 同一邮箱、同一场景的重发冷却（秒）。默认 60 = 1 分钟。
EMAIL_CODE_RESEND_SECONDS = int(os.getenv("EMAIL_CODE_RESEND_SECONDS", "60"))

# 给用户看的提示语（**唯一来源，前端零副本** —— 与 QUOTA_EXCEEDED_MESSAGE /
# REGISTER_PRICE_LINE / RECHARGE_COOLDOWN_MESSAGE 同一原则）。
# Spec23 §2.7：原来这里有三句，中间那句（"已提交过申请"）随
#   register_requests 表一起删掉了，现在只剩两句（下面这两句）。
# 两句都是用户逐字给的原文（含「宝子」与那个弯引号）。
# 第一句里的按钮名是「修改密码」——用户原话写的是"找回/修改密码"，而按钮已经
# 改名（§0 第 6-a 条），指着一个不存在的按钮是错的。要改称呼只动这一行。
EMAIL_CODE_REGISTERED_NOTICE = (
    "已注册账号{username}，请前往登录界面。忘记密码请前往登录界面“修改密码”"
)
# Spec23 §2.7 删除：EMAIL_CODE_PENDING_NOTICE
#   原文「该邮箱已提交过注册申请，请等待管理员审批」。它的唯一触发分支是
#   "该邮箱已有一条 pending 注册申请"，而 register_requests 表整个删了（§2.2、§2.7）。
#   留着一句描述不存在状态的提示语，正是本仓为 QUOTA_CONTACT_EMAIL /
#   REGISTER_DAILY_NOTICE 记过的那类静默失败。
EMAIL_CODE_UNREGISTERED_NOTICE = "还未注册，请宝子前往新用户注册~"

# 重发冷却那句告警。**分钟数由秒数推出来**，不是另写一个 "1"
# （CLAUDE.md 已为 RECHARGE_COOLDOWN_MESSAGE 记过同一条：改冷却期文案会自动跟着变）。
EMAIL_CODE_COOLDOWN_MESSAGE = (
    f"验证码发送过于频繁，请 {max(1, EMAIL_CODE_RESEND_SECONDS // 60)} 分钟后重试"
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
# 充值弹窗里那句参考价（唯一来源，前端零副本——与 REGISTER_PRICE_LINE 同一原则）。
# 注意它与余额公式的口径**故意不同**：余额按 1 元 = 10 次的名义价算（用户给定，
# Spec21 §2.9），而这句说的是实收价（0.9 元约 10 次）。两者不一致是有意的，别"统一"。
#
# Spec23 §2.8：从一整串字符串拆成"排版片段"——删除线落在**句子中间**（"0.9"紧前面），
# 一整串字符串表达不了那个位置。strike=True 的片段前端套 <s>。
# ⚠️ 用片段数组，**不是** v-html（那是个 XSS 面），**也不是**让前端在句子里找 "0.9"
#    （那等于把价格复制到前端，正是本仓从 Spec18 起一直在避免的）。
# ⚠️ "6.99" 与 "0.9" 的口径**故意不一致**（划掉的原价 vs 实收价折算的参考次数），
#    与上面那句余额公式的立场同款——别去"统一"。
# ⚠️ **第三个**片段以空格**开头**（" 0.9元约10次设计服务"）：那个空格替代了原来
#    "6.99" 与 "0.9" 之间的分隔。别用 {"text": " "} 再单独做一个只有空格的片段
#    ——那会多出一段，前端 v-for 照渲染，看起来一样但数据形状是错的。
RECHARGE_PRICE_LINE = (
    {"text": "充值参考："},
    {"text": "6.99", "strike": True},
    {"text": " 0.9元约10次设计服务"},
)

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

# ===== 服务限额（Spec18：API 服务调用计量与用户限额；Spec23 §2.3 语义升格）=====
# Spec23 §2.3：这个数现在就是「**新用户的免费试用额度**」。它同时管三条路
# （自助注册 / 管理员手工建号 / 新建库的列默认值）。
# ⚠️ 它**只影响新建的账号**——存量账号（当时拿 25 的）不被追溯修改（Spec23 §2.10）。
#    写一条"把所有人的额度刷成 10"的迁移是错的：那会让一些账号当场变超额被踢下线。
# ⚠️ 但 `create_user` 必须**显式**把它写进 INSERT —— 列 DEFAULT 在建库那一刻就
#    烤死在 schema 里了，改这个常量对**已存在**的库的列默认值毫无影响（Spec23 §2.4）。
QUOTA_DEFAULT_LIMIT = int(os.getenv("QUOTA_DEFAULT_LIMIT", "10"))    # 新用户的免费试用额度（累计次数）
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
