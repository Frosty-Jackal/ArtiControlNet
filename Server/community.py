"""社区帖子（Spec9 §5.3）：持久目录 Server/community/ + SQLite posts/post_votes 表。

单图 + 文字（作者拍板，Spec9 §2.1）。图片来源两种：
  1. 从作品库选（gallery_id）：校验 images.user_id == 当前用户（否则 40403），
     复制 gallery/ 字节到 community/（删除原作品不影响已发帖）。
  2. 新上传（image_bytes）：media.validate_upload 校验后写 community/，
     同时照 Spec5「上传即入库」落 gallery/（保持不变量）。

所有读图对任何登录用户开放（社区对所有人可见）；删除限作者或管理员（40302）。
"""
import re
import uuid

import config
import db
import gallery
from errors import (GalleryItemNotFoundError, PostForbiddenError,
                    PostNotFoundError)

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_\-]+\.(jpg|jpeg|png|webp|gif)$")

_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _read_community_file(file_name: str) -> bytes:
    if not _SAFE_NAME.match(file_name):
        raise PostNotFoundError()
    fp = config.COMMUNITY_DIR / file_name
    if not fp.exists():
        raise PostNotFoundError()
    return fp.read_bytes()


def _read_gallery_file(file_name: str) -> bytes:
    if not _SAFE_NAME.match(file_name):
        raise GalleryItemNotFoundError()
    fp = config.GALLERY_DIR / file_name
    if not fp.exists():
        raise GalleryItemNotFoundError()
    return fp.read_bytes()


def _unlink_community_file(file_name: str) -> None:
    try:
        (config.COMMUNITY_DIR / file_name).unlink(missing_ok=True)
    except OSError:
        pass


def mime_for(post: dict) -> str:
    return _MIME.get(post.get("ext"), "application/octet-stream")


def create_post(user_id: int, text: str, *, gallery_id: int | None = None,
                image_bytes: bytes | None = None, ext: str | None = None) -> dict:
    """发帖（单图 + 文字），返回 posts 记录 dict。

    图片来源二选一：gallery_id（作品库选择）或 image_bytes（新上传，ext 已校验）。
    """
    if gallery_id is not None:
        # 作品库来源：校验归属（40403）→ 复制字节到 community/
        record = db.get_image_record(gallery_id)
        if record is None or record["user_id"] != user_id:
            raise GalleryItemNotFoundError()
        image_bytes = _read_gallery_file(record["file_name"])
        ext = record["ext"]
    # 写 community/ 持久文件
    file_name = f"{uuid.uuid4().hex}{ext}"
    (config.COMMUNITY_DIR / file_name).write_bytes(image_bytes)
    post = db.create_post_record(user_id, text, file_name, ext)
    # 新上传来源：照 Spec5「上传即入库」一并落作品库（Spec9 §5.3 链路 2）
    if gallery_id is None:
        gallery.save_gallery_image(image_bytes, user_id, "upload", None)
    return post


def list_posts(user_id: int, offset: int, limit: int) -> list[dict]:
    """社区帖子列表（最新在前），每项带 image_url 供前端拉取。"""
    return [
        {**p, "image_url": f"/api/community/{p['id']}/image"}
        for p in db.list_posts(user_id, offset, limit)
    ]


def read_post_image(post_id: int) -> tuple[dict, bytes]:
    """帖子图片（任何登录用户可看，不校验归属——社区对所有人开放）。"""
    post = db.get_post_record(post_id)
    if post is None:
        raise PostNotFoundError()
    return post, _read_community_file(post["image_file"])


def vote(post_id: int, user_id: int, vote: str | None) -> dict:
    """点赞 / 点踩 / 取消；vote=None 删行。返回现算计数与当前用户选择。"""
    if db.get_post_record(post_id) is None:
        raise PostNotFoundError()
    db.set_post_vote(post_id, user_id, vote)
    totals = db.get_post_vote_totals(post_id)
    return {
        "post_id": post_id,
        "like_count": totals["like_count"],
        "dislike_count": totals["dislike_count"],
        "my_vote": db.get_post_my_vote(post_id, user_id),
    }


def delete_post(post_id: int, user_id: int, is_admin: bool) -> None:
    """删帖：作者或管理员 → 删 community/ 文件 + posts 行 + 该帖全部投票。"""
    post = db.get_post_record(post_id)
    if post is None:
        raise PostNotFoundError()
    if post["user_id"] != user_id and not is_admin:
        raise PostForbiddenError()
    file_name = db.delete_post_record(post_id)   # 含删除该帖全部 post_votes
    _unlink_community_file(file_name)


def delete_user_posts(user_id: int) -> None:
    """删除某用户全部帖子：物理文件 + posts 行 + 相关投票（删用户级联，Spec9 §3.1）。"""
    names = db.delete_user_post_records(user_id)
    for name in names:
        _unlink_community_file(name)
