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


class AdminSetQuotaRequest(BaseModel):
    """PUT /api/admin/users/{user_id}/quota 请求体（Spec18 §6.2）。

    非整数由 FastAPI/Pydantic 的 `int` 校验拦下 → 40001；
    取值范围（0 ~ QUOTA_LIMIT_MAX）在路由层判 → 40017。
    """

    quota_limit: int


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


# ---- 注册申请与审批（Spec19 §6.2 / §6.5）----

class RegisterRequestCreate(BaseModel):
    """POST /api/auth/register 请求体（Spec22 §6.1，Spec19 §6.2 的改造版）。

    全部字段都是裸 str：格式规则（长度、纯数字、@ 位置）一律在路由层判，
    好让每一条都有自己的中文 message。Pydantic 只负责"字段在不在"。

    ⚠️ **没有 `phone` 了**。删字段**不是**改成 Optional：留着一个可选字段，
    就留了一条能被写进已删列的路（§5.1）。
    """

    username: str
    password: str
    email: str          # Spec22：必填（原 phone / email 二选一已成历史）
    code: str           # Spec22：邮箱验证码（4 位数字，格式在路由层判）
    wechat: str


class RegisterApproveRequest(BaseModel):
    """POST /api/admin/register-requests/{id}/approve 请求体（Spec19 §6.5）。

    非整数由 Pydantic 拦下 → 40001；取值范围在路由层判 → 40017（复用 Spec18）。
    """

    quota_limit: int


# ---- 余额与充值（Spec21 §6.2~§6.5）----

class RechargeRequestCreate(BaseModel):
    """POST /api/recharge/requests 请求体（Spec21 §6.2）。
    长度/空值校验在路由层（40019），Pydantic 只负责"字段在不在"。"""

    wechat: str


class RechargeOverdueCreate(BaseModel):
    """POST /api/auth/recharge-request 请求体（Spec21 §6.3）。同上。"""

    username: str
    wechat: str


class RechargeApproveRequest(BaseModel):
    """POST /api/admin/recharge-requests/{id}/approve 请求体（Spec21 §6.5）。
    非整数由 Pydantic 拦下 → 40001；取值范围（≥1 且不超 QUOTA_LIMIT_MAX）在路由层判。"""

    amount: int


# ---- 邮箱验证码与入口统计（Spec22 §6.1~§6.6）----

class EmailCodeRequest(BaseModel):
    """POST /api/auth/email-code 请求体（Spec22 §6.2）。
    purpose 的白名单在路由层判（40020「未知的验证场景」）。"""

    email: str
    purpose: str        # register | login | reset


class EmailCodeVerifyRequest(BaseModel):
    """POST /api/auth/verify-email-code 请求体（Spec22 §6.3）。
    供「修改密码」展开密码栏之前使用；登录与注册不用它。"""

    email: str
    purpose: str
    code: str


class EmailLoginRequest(BaseModel):
    """POST /api/auth/login-by-email 请求体（Spec22 §6.4）。
    响应与 POST /api/auth/login **完全同形**，前端直接复用收尾逻辑。"""

    email: str
    code: str


class ResetPasswordRequest(BaseModel):
    """POST /api/auth/reset-password 请求体（Spec22 §6.5）。

    只有一个 password —— **没有** confirm 字段：两次输入是否一致是前端的事，
    后端根本收不到第二个框（§2.10）。不需要旧密码（邮箱已证明身份，§2.7）。
    """

    email: str
    code: str
    password: str


class ClickEventRequest(BaseModel):
    """POST /api/click 请求体（Spec22 §6.6）。白名单在路由层判（40021）。"""

    event: str
