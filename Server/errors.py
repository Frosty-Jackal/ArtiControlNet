"""统一错误类（错误码定义见 Spec §9）。

- 同步端点抛出的错误直接映射为 HTTP 状态码（status_code）。
- 任务执行期抛出的错误（code 61xxx）由 Worker 捕获写入 task.error，
  HTTP 提交响应仍为 200，通过轮询响应体返回。
"""
from typing import Optional


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
    """用户名或密码格式非法（用户名 <2 字符 / 密码 <6 位）。"""

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
    """登录失败过于频繁（限速）。"""

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
