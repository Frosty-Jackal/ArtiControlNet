"""Pydantic 请求/响应模型（接口契约见 Spec §8）。"""
from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """POST /api/chat 请求体。"""

    message: str = Field(..., min_length=1, max_length=8000, description="用户消息")
    image_url: Optional[str] = Field(None, description="参考图地址（本站路径或绝对 URL）")
    image_id: Optional[int] = Field(
        None, description="作品库图片 id（Spec17 §6.2；优先于 image_url）")
    thread_id: Optional[str] = Field(None, description="对话 id；复用则续接上下文")


class ChatOut(BaseModel):
    """POST /api/chat 立即返回。"""

    task_id: int
    thread_id: str
    status: str = "PENDING"


class UploadOut(BaseModel):
    """POST /api/images 返回。image_id 为作品库记录 id（Spec17 §6.1）。"""

    image_url: str
    image_id: int


class TaskResult(BaseModel):
    """任务终态结果。kind=text 或 images。"""

    kind: str                      # "text" | "images"
    text: Optional[str] = None
    images: Optional[list[str]] = None


class TaskErrorBody(BaseModel):
    code: int
    message: str


class TaskOut(BaseModel):
    """GET /api/tasks/{task_id} 轮询响应 data。"""

    task_id: int
    thread_id: str
    status: str                    # PENDING|PROCESSING|COMPLETED|FAILED
    kind: Optional[str] = None
    error: Optional[TaskErrorBody] = None
    result: Optional[TaskResult] = None


# Spec17 §6.6：`ThreadMessage` / `ThreadOut` 随 `GET /api/threads/{thread_id}/messages`
# 一并删除——该路由从未被前端调用，历史消息现在由 `GET /api/conversations/{id}/messages`
# 返回（chat_messages 行的原样形态，不再需要单独的响应模型）。


# ---- 认证 / 用户管理（Spec2 §6）----

class LoginRequest(BaseModel):
    """POST /api/auth/login 请求体。格式校验在路由层完成（错误码 40010）。"""

    username: str
    password: str


class LoginOut(BaseModel):
    token: str
    username: str
    is_admin: bool


class MeOut(BaseModel):
    username: str
    is_admin: bool


class AdminCreateUserRequest(BaseModel):
    username: str
    password: str


class AdminResetPasswordRequest(BaseModel):
    password: str


class AdminSetAdminRequest(BaseModel):
    is_admin: bool


# ---- 社区 / 反馈 / 分享 / 建议（Spec9 §6）----

class VoteRequest(BaseModel):
    """POST /api/community/{post_id}/vote 请求体。vote=null 表示取消。"""

    vote: Optional[str] = None          # 'like' | 'dislike' | null


class FeedbackRequest(BaseModel):
    """POST /api/feedback 请求体。vote=null 表示取消。"""

    task_id: int
    category: str                       # 'generate' | 'edit' | 'qa'
    vote: Optional[str] = None          # 'like' | 'dislike' | null


class ShareCreateRequest(BaseModel):
    """POST /api/shares 请求体。"""

    image_id: int


class SuggestionCreateRequest(BaseModel):
    """POST /api/suggestions 请求体。"""

    text: str


class SuggestionUpdateRequest(BaseModel):
    """PUT /api/admin/suggestions/{id} 请求体（可只改其一）。"""

    status: Optional[str] = None        # 'pending' | 'read' | 'resolved'
    reply: Optional[str] = None


# ---- 个人作品风格 Wiki（Spec12 §6.1）----

class WikiStyleRequest(BaseModel):
    """PUT /api/wiki/style 请求体。长度/空值校验在业务层（40014）。"""

    style: str


# ---- 作品备注（Spec16 §6.2）----

class GalleryNoteUpdateRequest(BaseModel):
    """PUT /api/gallery/{item_id}/note 请求体。长度校验在业务层（40015）。"""

    note: str


# ---- 帖子评论（Spec17 §6.10）----

class CommentCreateRequest(BaseModel):
    """POST /api/community/{post_id}/comments 请求体。长度校验在路由层（40016）。"""

    text: str
