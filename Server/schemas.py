"""Pydantic 请求/响应模型（接口契约见 Spec §8）。"""
from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """POST /api/chat 请求体。"""

    message: str = Field(..., min_length=1, max_length=8000, description="用户消息")
    image_url: Optional[str] = Field(None, description="参考图地址（本站 /images/ 或绝对 URL）")
    thread_id: Optional[str] = Field(None, description="会话 ID，复用则续接上下文")


class ChatOut(BaseModel):
    """POST /api/chat 立即返回。"""

    task_id: int
    thread_id: str
    status: str = "PENDING"


class UploadOut(BaseModel):
    """POST /api/images 返回。"""

    image_url: str


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


class ThreadMessage(BaseModel):
    """GET /api/threads/{thread_id}/messages 中的单条消息。"""

    role: str                      # user | assistant
    content: Any


class ThreadOut(BaseModel):
    messages: list[ThreadMessage]


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
