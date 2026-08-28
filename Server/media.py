"""图片落盘 / 读取 / 转存 / 校验（storage/ 临时目录，TTL 1h，非持久化）。

统一约定：站内图片以 /images/{file} 表示；对外返回绝对 URL。
"""
import asyncio
import io
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image

import config
from errors import (FileMissingError, ImageProcessError, ImageTooLargeError,
                    UnsupportedImageTypeError)

_FILENAME_SAFE = re.compile(r"^[a-zA-Z0-9_\-]+\.(jpg|jpeg|png|webp|gif)$")


# ---------- 保存 ----------

def save_image(image_bytes: bytes, public_base: str = "", ext: str | None = None) -> str:
    """把图片字节写入 storage/ 并返回 URL。

    public_base 为空时返回站内相对路径 /images/{file}。
    """
    if not ext:
        ext = detect_ext(image_bytes)
    name = f"{uuid.uuid4().hex}{ext}"
    (config.STORAGE_DIR / name).write_bytes(image_bytes)
    path = f"/images/{name}"
    return _to_public(path, public_base)


def save_upload(image_bytes: bytes, public_base: str, ext: str) -> str:
    return save_image(image_bytes, public_base, ext)


def _to_public(path: str, public_base: str) -> str:
    base = (public_base or "").rstrip("/")
    return f"{base}{path}" if base else path


# ---------- 读取 ----------

def _read_storage(path_or_url: str) -> bytes:
    file = Path(path_or_url).name
    if not _FILENAME_SAFE.match(file):
        raise ImageProcessError(f"非法图片路径: {path_or_url}")
    fp = config.STORAGE_DIR / file
    if not fp.exists():
        raise ImageProcessError(f"图片不存在或已过期: {path_or_url}")
    return fp.read_bytes()


def is_local_site_url(image_url: str) -> bool:
    return image_url.startswith("/images/")


async def fetch_image_bytes(image_url: str, public_base: str = "") -> bytes:
    """取图片字节。优先读本地 storage/（自己站点的 URL），否则 httpx 下载。"""
    if not image_url:
        raise ImageProcessError("缺少图片地址")

    # 本站相对路径
    if image_url.startswith("/images/"):
        return _read_storage(image_url)

    parsed = urlparse(image_url)
    base_netloc = urlparse(public_base or "").netloc
    # 绝对 URL 指向本站 → 直接读本地文件，避免自环 HTTP
    if parsed.netloc and base_netloc and parsed.netloc == base_netloc:
        if parsed.path.startswith("/images/"):
            return _read_storage(parsed.path)

    # 外部 URL → 下载
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
        return resp.content
    except ImageProcessError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ImageProcessError(f"图片下载失败: {exc}") from exc


# ---------- 校验 / 缩放 ----------

def detect_ext(image_bytes: bytes) -> str:
    """识别图片格式并返回标准扩展名（.jpg/.png/.webp/.gif）。"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise UnsupportedImageTypeError("无法识别图片内容") from exc
    fmt = (img.format or "").lower()
    if fmt in ("jpg", "jpeg"):
        return ".jpg"
    if fmt in ("png", "webp", "gif"):
        return f".{fmt}"
    raise UnsupportedImageTypeError(f"不支持的图片格式: {fmt or '未知'}")


def validate_upload(image_bytes: bytes, max_bytes: int | None = None) -> str:
    """校验上传图片：大小与格式，返回标准扩展名。"""
    if not image_bytes:
        raise FileMissingError("文件缺失或损坏")
    limit = max_bytes or config.UPLOAD_MAX_BYTES
    if len(image_bytes) > limit:
        raise ImageTooLargeError(f"图片超过 {limit // (1024 * 1024)}MB 限制")
    return detect_ext(image_bytes)


def downscale_to_max_side(image_bytes: bytes, max_side: int = config.SKETCH_MAX_SIDE_PX) -> bytes:
    """把图片最长边缩放至 ≤ max_side（线稿生图接口限制，Spec §7.2）。"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        fmt = img.format or "PNG"
        w, h = img.size
        if max(w, h) <= max_side:
            return image_bytes
        scale = max_side / float(max(w, h))
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.LANCZOS)
        buf = io.BytesIO()
        if fmt in ("JPEG", "JPG"):
            img.convert("RGB").save(buf, format="JPEG", quality=90)
        else:
            img.save(buf, format=fmt if fmt in ("PNG", "WEBP") else "PNG")
        return buf.getvalue()
    except ImageProcessError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ImageProcessError(f"图片缩放失败: {exc}") from exc


def enforce_sketch_input(image_bytes: bytes) -> bytes:
    """把线稿图片压缩到满足生图输入限制（base64 ≤6MB，Spec §7.2）。

    先缩放到最长边 ≤2000px，仍超限则逐级减半（512/256...），尽量保留有效线稿。
    """
    import base64 as _b64

    side = config.SKETCH_MAX_SIDE_PX
    data = downscale_to_max_side(image_bytes, side)
    max_base64 = 6 * 1024 * 1024
    while len(_b64.b64encode(data)) > max_base64 and side >= 128:
        side //= 2
        data = downscale_to_max_side(image_bytes, side)
    if len(_b64.b64encode(data)) > max_base64:
        raise ImageTooLargeError("线稿图片压缩后仍超过 6MB，无法处理")
    return data


# ---------- 清理 ----------

def cleanup_all() -> None:
    """启动时清空 storage/。"""
    config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    for fp in config.STORAGE_DIR.iterdir():
        try:
            if fp.is_file():
                fp.unlink()
        except OSError:
            pass


def cleanup_old_files(ttl: float = config.IMAGE_TTL_SECONDS) -> int:
    """删除超过 TTL 的文件，返回删除数量。"""
    now = time.time()
    removed = 0
    for fp in config.STORAGE_DIR.iterdir():
        try:
            if fp.is_file() and now - fp.stat().st_mtime > ttl:
                fp.unlink()
                removed += 1
        except OSError:
            pass
    return removed


async def janitor_loop(stop_event: asyncio.Event) -> None:
    """周期清理过期文件。"""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=config.JANITOR_INTERVAL_SECONDS)
            break
        except asyncio.TimeoutError:
            cleanup_old_files()
