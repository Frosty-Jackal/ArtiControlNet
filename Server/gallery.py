"""个人作品库（Spec5 §5.3 / §8）：持久目录 Server/gallery/ + SQLite images 表。

文件与元数据分离：库管"谁的、哪来的、什么时候"，目录管字节。
与临时 storage/（TTL 1h、启动清空）完全分开：重启不清、不受 TTL 影响。
所有读取/删除先校验 images.user_id == 当前用户，否则 40403（不泄露存在性）。
"""
import logging
import re
import uuid

import config
import db
import media
from errors import GalleryItemNotFoundError

logger = logging.getLogger("gallery")

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_\-]+\.(jpg|jpeg|png|webp|gif)$")

_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def save_gallery_image(image_bytes: bytes, user_id: int, source: str,
                       prompt: str | None) -> dict:
    """把图片字节写入 gallery/ 并落 images 表，返回记录 dict。

    source ∈ upload|generate|edit；prompt 仅生成/编辑存完整描述（含合并风格），上传为 None。
    """
    ext = media.detect_ext(image_bytes)
    file_name = f"{uuid.uuid4().hex}{ext}"
    (config.GALLERY_DIR / file_name).write_bytes(image_bytes)
    record = db.add_image_record(user_id, source, file_name, ext, prompt)
    logger.info("作品入库", extra={
        "event": "gallery.saved", "user_id": user_id, "source": source,
        "prompt": (prompt or "")[:200],
    })
    return record


def list_user_images(user_id: int, source: str | None = None) -> list[dict]:
    """本人作品列表（时间倒序），每项带前端可用的 url。"""
    return [_with_url(it) for it in db.list_image_records(user_id, source)]


def _with_url(record: dict) -> dict:
    return {
        "id": record["id"],
        "source": record["source"],
        "url": f"/api/gallery/{record['id']}/file",
        "prompt": record["prompt"],
        "created_at": record["created_at"],
    }


def _get_owned(item_id: int, user_id: int) -> dict:
    """取本人作品记录；不存在或归属他人 → 40403（不泄露存在性）。"""
    record = db.get_image_record(item_id)
    if record is None or record["user_id"] != user_id:
        raise GalleryItemNotFoundError()
    return record


def _read_file(file_name: str) -> bytes:
    if not _SAFE_NAME.match(file_name):
        raise GalleryItemNotFoundError()
    fp = config.GALLERY_DIR / file_name
    if not fp.exists():
        raise GalleryItemNotFoundError()
    return fp.read_bytes()


def read_gallery_file(item_id: int, user_id: int) -> tuple[dict, bytes]:
    """查看原图：校验归属后返回 (记录, 图片字节)。"""
    record = _get_owned(item_id, user_id)
    return record, _read_file(record["file_name"])


def mime_for(record: dict) -> str:
    return _MIME.get(record["ext"], "application/octet-stream")


def delete_item(item_id: int, user_id: int) -> None:
    """删除作品：校验归属 → 删文件 → 删记录。"""
    record = _get_owned(item_id, user_id)
    _unlink_file(record["file_name"])
    db.delete_image_record(item_id)
    logger.info("删除作品", extra={
        "event": "gallery.deleted", "user_id": user_id, "item_id": item_id,
    })


def delete_user_gallery(user_id: int) -> None:
    """删除某用户全部作品：先取 file_name 列表，再删文件 + 记录（删用户级联，Spec5 §3）。"""
    names = db.delete_user_image_records(user_id)
    for name in names:
        _unlink_file(name)


def _unlink_file(file_name: str) -> None:
    try:
        (config.GALLERY_DIR / file_name).unlink(missing_ok=True)
    except OSError:
        pass
