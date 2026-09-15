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
