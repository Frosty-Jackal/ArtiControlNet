"""社区帖子（Spec9 §5.3）：持久目录 Server/community/ + SQLite posts/post_votes 表。

单图 + 文字（作者拍板，Spec9 §2.1）。图片来源两种：
  1. 从作品库选（gallery_id）：校验 images.user_id == 当前用户（否则 40403），
     复制 gallery/ 字节到 community/（删除原作品不影响已发帖）。
  2. 新上传（image_bytes）：media.validate_upload 校验后写 community/，
     同时照 Spec5「上传即入库」落 gallery/（保持不变量）。

Spec17 §5.2D：**图片变为可选**——两者都不给即纯文字帖（image_file/ext 落 NULL）。

Spec17 §5.2E：帖子评论（post_comments）。只增 / 删 / 查，**没有编辑**（§2.3）——
改口供会让对话上下文失去意义，这是全仓唯一没有 PUT 的资源，有意为之。

所有读图对任何登录用户开放（社区对所有人可见）；删除帖子限作者或管理员（40302）；
删除评论限评论作者或管理员（40303）。
"""
import logging
import re
import uuid

import config
import db
import gallery
from errors import (CommentForbiddenError, CommentNotFoundError,
                    GalleryItemNotFoundError, PostForbiddenError,
                    PostNotFoundError)

logger = logging.getLogger("community")

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


def _unlink_community_file(file_name: str | None) -> None:
    if not file_name:                       # Spec17：纯文字帖没有文件可删
        return
    try:
        (config.COMMUNITY_DIR / file_name).unlink(missing_ok=True)
    except OSError:
        pass


def mime_for(post: dict) -> str:
    return _MIME.get(post.get("ext"), "application/octet-stream")


def create_post(user_id: int, text: str, *, gallery_id: int | None = None,
                image_bytes: bytes | None = None, ext: str | None = None) -> dict:
    """发帖（文字 + 可选单图），返回 posts 记录 dict。

    Spec17 起图片可选：三者皆空 = 纯文字帖（image_file/ext 落 NULL）。
    图片来源仍最多一个——gallery_id（作品库选择）或 image_bytes（新上传，ext 已校验）；
    "不能同时给"由路由层拦（40011），这里只管"可以都不给"。
    """
    if gallery_id is not None:
        # 作品库来源：校验归属（40403）→ 复制字节到 community/
        record = db.get_image_record(gallery_id)
        if record is None or record["user_id"] != user_id:
            raise GalleryItemNotFoundError()
        image_bytes = _read_gallery_file(record["file_name"])
        ext = record["ext"]

    if image_bytes is None:                 # Spec17：纯文字帖
        return db.create_post_record(user_id, text, None, None)

    # 写 community/ 持久文件
    file_name = f"{uuid.uuid4().hex}{ext}"
    (config.COMMUNITY_DIR / file_name).write_bytes(image_bytes)
    post = db.create_post_record(user_id, text, file_name, ext)
    # 新上传来源：照 Spec5「上传即入库」一并落作品库（Spec9 §5.3 链路 2）
    if gallery_id is None:
        gallery.save_gallery_image(image_bytes, user_id, "upload", None)
    return post


def list_posts(user_id: int, offset: int, limit: int) -> list[dict]:
    """社区帖子列表（最新在前）；图片可空，评论全量内嵌（Spec17 §5.2D/§5.2E）。

    评论用**一次**批量查询再分组挂上去（`db.list_comments_for_posts`），
    不让列表接口退化成每帖一次查询的 N+1。
    """
    posts = db.list_posts(user_id, offset, limit)
    by_post = db.list_comments_for_posts([p["id"] for p in posts])
    items = []
    for p in posts:
        item = dict(p)
        has_image = bool(item.pop("image_file"))   # 内部字段，不进响应（§6.8）
        item["image_url"] = f"/api/community/{p['id']}/image" if has_image else None
        item["comments"] = [_comment_out(c) for c in by_post.get(p["id"], [])]
        items.append(item)
    return items


def read_post_image(post_id: int) -> tuple[dict, bytes]:
    """帖子图片（任何登录用户可看，不校验归属——社区对所有人开放）。

    Spec17：纯文字帖没有图。在"取图片"这个语境下，"没有"就是"不存在"，
    复用 40404 而不新增错误码（§2.2）。
    """
    post = db.get_post_record(post_id)
    if post is None or not post["image_file"]:
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
    """删除某用户全部帖子：物理文件 + posts 行 + 相关投票（删用户级联，Spec9 §3.1）。

    Spec17：评论的级联两项都在 `db.delete_user_post_records` 里完成
    （该用户帖子上的全部评论 + 该用户发在别人帖子上的评论），本条无需额外动作。
    """
    names = db.delete_user_post_records(user_id)
    for name in names:
        _unlink_community_file(name)


# ---------- 评论（Spec17 §5.2E）----------

def _comment_out(record: dict) -> dict:
    """评论对外形态（列表内嵌与新增返回**同形**，前端可无差别 append）。"""
    return {
        "id": record["id"],
        "post_id": record["post_id"],
        "author": record["author"],
        "author_is_admin": bool(record["author_is_admin"]),
        "text": record["text"],
        "created_at": record["created_at"],
    }


def list_comments(post_id: int) -> list[dict]:
    """某帖的全部评论，按 id ASC（时间正序）。帖子不存在 → 40404。"""
    if db.get_post_record(post_id) is None:
        raise PostNotFoundError()
    by_post = db.list_comments_for_posts([post_id])
    return [_comment_out(c) for c in by_post.get(post_id, [])]


def create_comment(post_id: int, user_id: int, text: str) -> dict:
    """发一条评论，返回对外形态。

    文字长度校验在路由层（40016）；这里只管帖子存不存在（40404）。
    """
    if db.get_post_record(post_id) is None:
        raise PostNotFoundError()
    return _comment_out(db.create_comment(post_id, user_id, text))


def delete_comment(post_id: int, comment_id: int, user_id: int,
                   is_admin: bool) -> dict:
    """删一条评论：评论作者或管理员。返回 {id, post_id, by_admin}。

    路径里带 `post_id` 是为了校验"这条评论确实挂在这个帖子上"——否则
    `post_id=A` + `comment_id=<挂在 B 帖上的>` 这种错配会让权限判断对着错误的
    帖子做，也可能误删别人帖子下的评论（§6.10）。错配一律 40408。
    """
    comment = db.get_comment(comment_id)
    if comment is None or comment["post_id"] != post_id:
        raise CommentNotFoundError()
    if comment["user_id"] != user_id and not is_admin:
        raise CommentForbiddenError()
    db.delete_comment(comment_id)
    return {"id": comment_id, "post_id": post_id, "by_admin": bool(is_admin)}
