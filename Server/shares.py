"""作品临时分享链接（Spec9 §5.3 / §2.3）。

- 公开免登录：`/share/{token}` 与 `/share/{token}/image` 走非 /api 路径，
  统一鉴权中间件（只拦 /api/*）天然放行；token + 过期校验在本模块（40405）。
- 一个作品一条分享：再次生成 = 覆盖旧 token / 有效期。
- 级联：删除作品 / 删除用户 → 其分享立即失效（调用方负责删 shares 行）。
- 分享页由后端生成独立紫色主题 HTML，不依赖 SPA / 登录。
"""
import secrets
from datetime import datetime, timedelta, timezone

import config
import db
import gallery
from errors import GalleryItemNotFoundError, ShareNotFoundError


def _expires_iso() -> str:
    """expires_at = 当前时间 + SHARE_TTL_SECONDS（默认 7 天）。"""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=config.SHARE_TTL_SECONDS)
    return exp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _not_expired(expires_at: str) -> bool:
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return exp > datetime.now(timezone.utc)


def create_share(user_id: int, image_id: int, public_base: str) -> dict:
    """生成 / 覆盖本人作品的分享链接；非本人作品 → 40403（不泄露存在性）。"""
    image = db.get_image_record(image_id)
    if image is None or image["user_id"] != user_id:
        raise GalleryItemNotFoundError()
    token = secrets.token_urlsafe(16)
    record = db.create_share_record(token, image_id, user_id, _expires_iso())
    return {
        "id": record["id"],
        "url": f"{public_base}/share/{token}",
        "expires_at": record["expires_at"],
    }


def revoke_share(share_id: int, user_id: int) -> int:
    """撤销分享（仅本人）；非本人或不存在 → 40403。返回 image_id 供日志。"""
    share = db.get_share_record(share_id)
    if share is None or share["user_id"] != user_id:
        raise GalleryItemNotFoundError()
    db.delete_share(share_id)
    return share["image_id"]


def resolve_token(token: str) -> tuple[dict, dict]:
    """校验分享 token + 过期；伪造 / 已撤销 / 过期 / 作品已删除 → 40405。"""
    share = db.get_share_by_token(token)
    if share is None or not _not_expired(share["expires_at"]):
        raise ShareNotFoundError()
    image = db.get_image_record(share["image_id"])
    if image is None:
        raise ShareNotFoundError()
    return share, image


def read_share_image(image: dict) -> bytes:
    """读 gallery/ 原图字节（分享直接读原图，不复制）。"""
    return gallery.read_share_image_bytes(image["file_name"])


def render_share_page(share: dict, image: dict, author: str) -> str:
    """免登录分享页：紫色主题 HTML（大图 + 作者 + 下载链接）。"""
    token = share["token"]
    image_url = f"/share/{token}/image"
    download_url = f"{image_url}?download=1"
    ext = image.get("ext", ".jpg")
    file_name = f"artcn_share_{share['id']}{ext}"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>作品分享 · ArtiControlNet</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #0c0915; color: #f5f0ff;
    font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    min-height: 100vh; display: flex; flex-direction: column; align-items: center;
    padding: 40px 16px;
  }}
  .card {{
    background: #1e1533; border: 1px solid #2e2249; border-radius: 20px;
    max-width: 860px; width: 100%; box-shadow: 0 12px 40px rgba(0,0,0,.45);
    overflow: hidden;
  }}
  .card-head {{
    padding: 18px 24px; border-bottom: 1px solid #2e2249;
    display: flex; align-items: center; gap: 10px;
  }}
  .dot {{ width: 12px; height: 12px; border-radius: 50%;
          background: linear-gradient(135deg, #a855f7, #6d28d9); }}
  .brand {{ font-size: 16px; font-weight: 700;
            background: linear-gradient(135deg, #d8b4fe, #a855f7);
            -webkit-background-clip: text; background-clip: text; color: transparent; }}
  .card-body {{ padding: 0; text-align: center; }}
  .card-body img {{
    display: block; width: 100%; max-height: 70vh; object-fit: contain;
    background: #150f24;
  }}
  .card-foot {{
    padding: 20px 24px; border-top: 1px solid #2e2249;
    display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
    gap: 14px;
  }}
  .author {{ color: #c4b5fd; font-size: 14px; }}
  .author b {{ color: #f5f0ff; }}
  .hint {{ color: #8b7aad; font-size: 12px; margin-top: 4px; }}
  .btn {{
    display: inline-block; text-decoration: none;
    background: #9333ea; color: #fff; font-weight: 600; font-size: 14px;
    padding: 10px 20px; border-radius: 999px; transition: background .15s ease;
  }}
  .btn:hover {{ background: #a855f7; }}
</style>
</head>
<body>
  <div class="card">
    <div class="card-head">
      <span class="dot"></span><span class="brand">ArtiControlNet · 作品分享</span>
    </div>
    <div class="card-body"><img src="{image_url}" alt="AI 作品"></div>
    <div class="card-foot">
      <div>
        <div class="author">作者：<b>{author}</b></div>
        <div class="hint">本链接为临时公开分享，由原作者生成</div>
      </div>
      <a class="btn" href="{download_url}" download="{file_name}">下载原图</a>
    </div>
  </div>
</body>
</html>"""
