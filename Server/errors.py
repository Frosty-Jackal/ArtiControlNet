"""统一错误类（错误码定义见 Spec §9）。

- 同步端点抛出的错误直接映射为 HTTP 状态码（status_code）。
- 任务执行期抛出的错误（code 61xxx）由 Worker 捕获写入 task.error，
  HTTP 提交响应仍为 200，通过轮询响应体返回。
"""
from typing import Optional

import config


class AppError(Exception):
    """业务错误基类。code 为业务错误码，status_code 为该错误对应的 HTTP 状态。"""

    def __init__(
        self,
        code: int,
        message: str,
        status_code: int = 200,
        *,
        provider: Optional[str] = None,
        upstream_code: Optional[str] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.provider = provider          # deepseek / tencent
        self.upstream_code = upstream_code  # 上游错误码，如 FailedOperation.*

    def to_body(self) -> dict:
        return {"code": self.code, "message": self.message}


# ---- HTTP 层（§9.1）----
class BadRequestError(AppError):
    def __init__(self, message="请求参数非法", code: int = 40001):
        super().__init__(code, message, status_code=400)


class FileMissingError(AppError):
    def __init__(self, message="文件缺失或损坏"):
        super().__init__(40002, message, status_code=400)


class UnsupportedImageTypeError(AppError):
    def __init__(self, message="不支持的图片格式"):
        super().__init__(40003, message, status_code=400)


class ImageTooLargeError(AppError):
    def __init__(self, message="图片超限"):
        super().__init__(40004, message, status_code=400)


class MissingApiKeyError(AppError):
    def __init__(self, provider: str, code: int = 40101):
        super().__init__(code, f"后端未配置 {provider} 对应 API Key", status_code=401, provider=provider)


class NotFoundError(AppError):
    def __init__(self, message="资源不存在", code: int = 40401):
        super().__init__(code, message, status_code=404)


# ---- 认证 / 授权（Spec2 §9，追加到 Spec §9）----
class CredentialsFormatError(AppError):
    """用户名或密码格式非法（用户名 <2 字符 / 密码 <auth.MIN_PASSWORD_LEN 位）。

    Spec22 §2.10：密码下限从 6 降到 2，所以"<6 位"这个说法不再成立——
    下限由 `auth.MIN_PASSWORD_LEN` 定义，本类只负责抛，不定义规则。
    """

    def __init__(self, message="用户名或密码格式非法"):
        super().__init__(40010, message, status_code=400)


class LoginFailedError(AppError):
    """用户名或密码错误。"""

    def __init__(self, message="用户名或密码错误"):
        super().__init__(40102, message, status_code=401)


class AuthTokenError(AppError):
    """登录态缺失 / 无效 / 过期。"""

    def __init__(self, message="登录态无效或已过期"):
        super().__init__(40103, message, status_code=401)


class ForbiddenError(AppError):
    """无权限（非管理员访问管理接口）。"""

    def __init__(self, message="无权限：仅管理员可访问"):
        super().__init__(40301, message, status_code=403)


class UserNotFoundError(NotFoundError):
    def __init__(self, message="用户不存在"):
        super().__init__(message, code=40402)


class GalleryItemNotFoundError(NotFoundError):
    """作品不存在或不属于当前用户（Spec5 §9）：越权访问他人作品也返回 404，不泄露存在性。"""

    def __init__(self, message="作品不存在或不属于当前用户"):
        super().__init__(message, code=40403)


class DuplicateUsernameError(AppError):
    """用户名已存在。"""

    def __init__(self, message="用户名已存在"):
        super().__init__(40901, message, status_code=409)


class LoginRateLimitedError(AppError):
    """登录失败过于频繁（限速）。

    Spec22 §2.6：同一个限速器（`auth.is_login_blocked` / `record_login_failure`）
    现在也管**验证码猜错**——`verify-email-code` / `login-by-email` /
    `reset-password` / 注册提交的验证码校验四处失败都计入。同一个 IP 猜密码和
    猜验证码是一回事，用同一个码让前端与限速口径只有一份。
    """

    def __init__(self, message="登录尝试过于频繁，请稍后再试"):
        super().__init__(42901, message, status_code=429)


# ---- 社区 / 反馈 / 分享 / 建议（Spec9 §9，追加到 Spec.md / Spec2 / Spec5 §9 之后）----

class PostContentError(BadRequestError):
    """帖子内容非法（缺图片 / 双来源或都缺 / 文字为空或超长）。"""

    def __init__(self, message="帖子内容非法"):
        super().__init__(message, code=40011)


class FeedbackParamError(BadRequestError):
    """反馈参数非法（vote 或 category 不在白名单）。"""

    def __init__(self, message="反馈参数非法"):
        super().__init__(message, code=40012)


class SuggestionContentError(BadRequestError):
    """建议内容非法（文字为空或超长）。"""

    def __init__(self, message="建议内容非法"):
        super().__init__(message, code=40013)


# ---- 个人作品风格 Wiki（Spec12 §9，追加到 Spec9 §9 之后）----

class WikiContentError(BadRequestError):
    """风格内容非法（手动编辑提交的文本 strip 后为空、或超过 WIKI_STYLE_MAX）。"""

    def __init__(self, message="风格内容非法"):
        super().__init__(message, code=40014)


# ---- 作品备注（Spec16 §9，追加到 Spec12 §9 之后）----

class GalleryNoteError(BadRequestError):
    """作品备注非法（上传作品才可写备注；或备注超过 GALLERY_NOTE_MAX）。"""

    def __init__(self, message="作品备注非法"):
        super().__init__(message, code=40015)


class PostForbiddenError(AppError):
    """无权操作该帖子（非作者且非管理员删除他人帖子）。"""

    def __init__(self, message="无权操作该帖子"):
        super().__init__(40302, message, status_code=403)


class PostNotFoundError(NotFoundError):
    """帖子不存在。"""

    def __init__(self, message="帖子不存在"):
        super().__init__(message, code=40404)


class ShareNotFoundError(NotFoundError):
    """分享链接不存在或已过期（伪造 token / 已撤销 / 过期 / 作品已删除）。"""

    def __init__(self, message="分享链接不存在或已过期"):
        super().__init__(message, code=40405)


class SuggestionNotFoundError(NotFoundError):
    """建议不存在。"""

    def __init__(self, message="建议不存在"):
        super().__init__(message, code=40406)


# ---- 对话历史 / 评论（Spec17 §9，追加到 Spec16 §9 之后）----

class ConversationNotFoundError(NotFoundError):
    """对话不存在或不属于当前用户（不泄露存在性；越权与不存在同码）。"""

    def __init__(self, message="对话不存在或不属于当前用户"):
        super().__init__(message, code=40407)


class CommentContentError(BadRequestError):
    """评论内容非法（strip 后为空或超过 COMMENT_TEXT_MAX）。"""

    def __init__(self, message="评论内容非法"):
        super().__init__(message, code=40016)


class CommentForbiddenError(AppError):
    """无权删除该评论（非作者且非管理员）。"""

    def __init__(self, message="无权删除该评论"):
        super().__init__(40303, message, status_code=403)


class CommentNotFoundError(NotFoundError):
    """评论不存在，或不属于路径里的那个帖子（`post_id` / `comment_id` 错配）。"""

    def __init__(self, message="评论不存在"):
        super().__init__(message, code=40408)


# ---- 服务限额（Spec18 §9，追加到 Spec17 §9 之后）----

class QuotaExceededError(AppError):
    """普通用户的服务调用次数已达限额（登录被拒 / 已在系统里被踢出）。

    HTTP 403 而非 401：登录态本身是有效的，只是无权继续使用。用 401 会被前端
    既有的"401 → 清 token"分支当成 token 失效处理——结果碰巧一样，但语义错，
    且会让日志里分不清"登录态坏了"和"额度用完了"。

    提示语来自 config.QUOTA_EXCEEDED_MESSAGE（唯一来源，前端零副本）。
    """

    def __init__(self, message: str | None = None):
        super().__init__(40304, message or config.QUOTA_EXCEEDED_MESSAGE, status_code=403)


class QuotaLimitError(BadRequestError):
    """管理员设置的限额非法（负数，或超过 QUOTA_LIMIT_MAX）。"""

    def __init__(self, message: str | None = None):
        super().__init__(
            message or f"服务限额需为 0~{config.QUOTA_LIMIT_MAX} 之间的整数",
            code=40017,
        )


# ---- 注册申请与审批（Spec19 §9，追加到 Spec18 §9 之后）----

class RegisterRequestError(BadRequestError):
    """注册申请字段非法（长度 / 纯数字 / @ 位置）。"""

    def __init__(self, message: str = "注册申请信息非法"):
        super().__init__(message, code=40018)


class RegisterClosedError(AppError):
    """注册申请暂未开放（REGISTER_ENABLED=false）。"""

    def __init__(self, message: str | None = None):
        super().__init__(
            40305,
            message or f"注册申请暂未开放，请联系客服 {config.SUPPORT_EMAIL}",
            status_code=403,
        )


# Spec23 §9 删除：class RegisterRequestNotFoundError(NotFoundError)  # 40409
#   唯一语义是"这条注册申请不存在/已被删"，消费者是 approve/reject/delete 三条路由
#   （它们都删了，§6.2）。
#   ⚠️ **不把这个码改嫁给任何新语义**：重定义既有码会让旧日志里的 40409 变成假话
#   （Spec22 §2.11 删 40902 时定的规矩，同款）。


class PaymentQrMissingError(NotFoundError):
    """收款码文件缺失（部署时忘了放 Server/payment.jpg）。"""

    def __init__(self, message: str | None = None):
        super().__init__(
            message or f"收款码暂未配置，请联系客服 {config.SUPPORT_EMAIL}", code=40410
        )


# Spec22 删除：class RegisterRateLimitedError(AppError)  # 40902
#   它的唯一语义是"同一 IP 24 小时内已提交过注册申请"（Spec19 §2.2）。
#   需求 3 删掉了那个限制 → 这个码没有生产者了 → 整个类删掉。
#   **不把它改嫁给"验证码重发冷却"**：重定义既有码会让旧日志里的 40902 变成假话（§2.11）。


# Spec23 §9 删除：class RegisterAlreadyReviewedError(AppError)  # 40903
#   唯一语义是"这条申请已经不是 pending 了"，消费者同上三条被删的路由
#   （含 db 层并发抢跑返回 None 的那两支）。
#   同样**不改嫁**（理由与上面 40409 一致）。


# ---- 余额与充值（Spec21 §9，追加到 Spec19 §9 之后）----

class RechargeRequestError(BadRequestError):
    """充值申请字段非法 / 账号不存在 / 账号无需充值。

    多个不同 message 共用一个码，与 Spec19 的 RegisterRequestError（40018）同款。
    """

    def __init__(self, message: str = "充值申请信息非法"):
        super().__init__(message, code=40019)


class RechargeNotFoundError(NotFoundError):
    """充值记录不存在。"""

    def __init__(self, message: str = "充值记录不存在"):
        super().__init__(message, code=40411)


class RechargeRateLimitedError(AppError):
    """同一用户在冷却期内又提交了一次充值申请（Spec21 §2.4 的频次限制）。

    与 RegisterRateLimitedError（40902）同一个 family：都是"这东西你已经给了，
    先等着"的冲突，不是字段错误（40019），也不是身份问题。用 409 而非 429：
    本仓没有 429，且前端只认 code，多一套 HTTP 语义反而多一处要对齐的东西。
    """

    def __init__(self, message: str | None = None):
        super().__init__(
            40905, message or config.RECHARGE_COOLDOWN_MESSAGE, status_code=409
        )


class RechargeAlreadyReviewedError(AppError):
    """该充值记录已被处理（或两个管理员同时点了同意，后到的那个）。"""

    def __init__(self, message: str = "该充值记录已处理"):
        super().__init__(40904, message, status_code=409)


# ---- 邮箱验证码与入口统计（Spec22 §9，追加到 Spec21 §9 之后）----

class EmailCodeRequestError(BadRequestError):
    """验证码链路的字段/校验失败。

    多个不同 message 共用一个码，与 Spec19 的 RegisterRequestError（40018）、
    Spec21 的 RechargeRequestError（40019）同款：
    邮箱格式不对 / 验证场景未知 / 验证码不是 4 位数字 / **验证码错误或已过期**。
    """

    def __init__(self, message: str = "验证码请求非法"):
        super().__init__(message, code=40020)


class ClickEventError(BadRequestError):
    """埋点事件名不在白名单里（只有我们自己的前端会调它，出现即代码写错）。

    **不静默忽略**：静默会让"前端写错了一个事件名"这件事永远不被发现（§2.9）。
    """

    def __init__(self, message: str = "未知的埋点事件"):
        super().__init__(message, code=40021)


class EmailCodeRateLimitedError(AppError):
    """同一邮箱在同一场景下的重发冷却期内（默认 1 分钟）。

    文案来自 config.EMAIL_CODE_COOLDOWN_MESSAGE（前端零副本）。

    新开一个 40906 而不是复用 40902：那个码的语义是"同一 IP 24 小时一次"，
    改嫁会让旧日志里的 40902 变成一句假话（§2.11）。
    """

    def __init__(self, message: str | None = None):
        super().__init__(40906, message or config.EMAIL_CODE_COOLDOWN_MESSAGE,
                         status_code=409)


class EmailCodeRejectedError(AppError):
    """查重拒绝：邮箱已注册 / 已有待审批申请 / 还未注册。

    三句话共用一个码（用户看到的是 message，不需要知道是哪一种）。
    第一句里要填用户名，所以 message 由**路由**拼好传进来（模板在 config，
    理由见 §2.4：文案的唯一来源是 config，不是这条路由）。
    """

    def __init__(self, message: str = "该邮箱无法申请验证码"):
        super().__init__(40907, message, status_code=409)


class EmailServiceUnavailableError(AppError):
    """未配置 SMTP_PASSWORD —— 验证码发不出去，三条链路都走不通（§2.5）。

    这是**唯一可预知**的失败，所以从"静默降级"改成"明确报错"。Spec20/21 里
    邮件只是通知（不发不影响业务），而验证码是业务的前置条件——静默降级在这里
    的含义变成"接口 200、用户傻等"。
    用 503 而不是 500：这是服务暂时不可用，不是代码错了。
    """

    def __init__(self, message: str | None = None):
        super().__init__(
            50302, message or f"邮箱服务暂不可用，请联系客服 {config.SUPPORT_EMAIL}",
            status_code=503,
        )


class InternalError(AppError):
    def __init__(self, message="内部错误"):
        super().__init__(50001, message, status_code=500)


class UpstreamApiError(AppError):
    def __init__(self, provider: str, message="上游模型 API 错误", upstream_code: Optional[str] = None):
        super().__init__(
            61001, f"上游 {provider} 出错: {message}", status_code=502,
            provider=provider, upstream_code=upstream_code,
        )


class UpstreamTimeoutError(AppError):
    def __init__(self, provider: str, message="上游超时"):
        super().__init__(61002, f"上游 {provider} 超时: {message}", status_code=502, provider=provider)


class QueueCapacityError(AppError):
    def __init__(self, message="队列已满 / 并发超限"):
        super().__init__(50301, message, status_code=503)


# ---- 任务级（§9.2，code 61xxx）----
class TaskError(AppError):
    """任务执行期错误，写入轮询响应的 data.error。status_code 仅占位，任务侧不使用。"""

    def __init__(self, code: int, message: str, *, provider: Optional[str] = None):
        super().__init__(code, message, status_code=200, provider=provider)


class TaskTimeoutError(TaskError):
    def __init__(self, message="任务处理超过时限"):
        super().__init__(61002, message)


class ImageProcessError(TaskError):
    def __init__(self, message="图片下载/解码/转存失败"):
        super().__init__(61003, message)


class RouterError(TaskError):
    def __init__(self, message="主 Agent 路由失败"):
        super().__init__(61004, message)


class UnknownTaskError(TaskError):
    def __init__(self, message="未知任务失败"):
        super().__init__(61999, message)
