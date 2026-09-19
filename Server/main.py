"""ArtiControlNet 后端入口（Spec §8 / §5）。

编排层：/api/chat 异步提交 → 主 Agent 单跳路由 → 子 Agent 调外部 API → 结果入内存任务。
无数据库，无状态；图片落 storage/（TTL 1h）。
"""
import asyncio
import logging
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import auth
import chat_history
import community
import config
import db
import gallery
import mailer
import media
import schemas
import shares
import timefmt
import verifications
import wiki
from agents.supervisor import run_supervisor
from errors import (AppError, AuthTokenError, BadRequestError,
                    ClickEventError, CommentContentError, CredentialsFormatError,
                    DuplicateUsernameError, EmailCodeRateLimitedError,
                    EmailCodeRejectedError, EmailCodeRequestError,
                    EmailServiceUnavailableError, FeedbackParamError,
                    FileMissingError,
                    ForbiddenError,
                    GalleryItemNotFoundError, LoginFailedError,
                    LoginRateLimitedError, NotFoundError, PaymentQrMissingError,
                    PostContentError, PostNotFoundError, QuotaExceededError,
                    QuotaLimitError, RechargeAlreadyReviewedError,
                    RechargeNotFoundError, RechargeRateLimitedError,
                    RechargeRequestError,
                    RegisterClosedError,
                    RegisterRequestError,
                    ShareNotFoundError, SuggestionContentError,
                    SuggestionNotFoundError, UnsupportedImageTypeError,
                    UserNotFoundError)
from logging_setup import configure_logging
from task_queue import Task, TaskQueue

logger = logging.getLogger("main")


# ---------- 工具 ----------

def _request_id(x_request_id: Optional[str]) -> str:
    return x_request_id or uuid.uuid4().hex[:12]


def _public_base(request: Request) -> str:
    if config.PUBLIC_BASE_URL:
        return config.PUBLIC_BASE_URL
    return str(request.base_url).rstrip("/")


def _ok(data=None, message: str = "ok") -> dict:
    return {"code": 200, "message": message, "data": data}


# ---------- 使用统计归类（Spec4 §5.3） ----------

# Supervisor 打上的工具标签 → 统计类别；无标签 = 纯文本对话。
_TOOL_CATEGORY = {
    "generate_image": "generate",
    "edit_image": "edit",
    "qa_image": "qa",
}


def _usage_category(result: dict) -> str | None:
    """按 result["tool"] 归类；未知工具标签不计数（返回 None）。"""
    tool = result.get("tool")
    if tool is None:
        return "chat"
    return _TOOL_CATEGORY.get(tool)


# ---------- 会话历史（内存，仅用于路由上下文）----------

class ThreadStore:
    def __init__(self, limit: int = config.THREAD_HISTORY_LIMIT):
        self._threads: dict[str, deque] = {}
        self._lock = asyncio.Lock()
        self._limit = limit

    async def append(self, thread_id: str, entry: dict) -> None:
        async with self._lock:
            q = self._threads.setdefault(thread_id, deque(maxlen=self._limit))
            q.append(entry)

    async def get(self, thread_id: str) -> list[dict]:
        async with self._lock:
            q = self._threads.get(thread_id)
            return list(q) if q else []

    async def ensure_loaded(self, thread_id: str, user_id: int) -> None:
        """内存 miss 时从 chat_messages 回填最近 N 条（Spec17 §5.2B）。

        对话持久化后，后端重启 / 换进程之后点历史对话"接着聊"不能失忆——
        原来只活在内存里的路由上下文必须能从库里重建。

        `user_id` 目前不参与查询（调用方已在路由层做过归属校验），保留形参是为了
        让这一个入口自带"是谁的对话"这一信息，将来若要把回填收窄到本人也能就地加。

        双检锁：慢路径（查库）在锁外，两把锁之间的间隙由第二次 `in` 判断兜住，
        并发两次请求同一段对话只会灌一次。
        """
        async with self._lock:
            if thread_id in self._threads:
                return
        entries = chat_history.load_recent_entries(thread_id, self._limit)
        if not entries:
            return
        async with self._lock:
            if thread_id not in self._threads:
                self._threads[thread_id] = deque(entries, maxlen=self._limit)


# ---------- 挂起意图（Spec5 §5.5，内存，按 thread_id）----------

class PendingStore:
    """多轮追问的挂起意图存储：仅内存，重启即丢（作者拍板，Spec5 §2 决策记录）。

    - 生命周期：交付真实工具 → 清；结果为非 clarify → 清；超时 → 访问时清，视为新会话。
    - 并发安全：asyncio.Lock（与 ThreadStore 同级）。
    """

    def __init__(self, ttl: float = config.PENDING_INTENT_TTL_SECONDS):
        self._pending: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._ttl = ttl

    async def get(self, thread_id: str) -> Optional[dict]:
        """取挂起意图；超过 TTL 视为过期，清除并返回 None。"""
        async with self._lock:
            p = self._pending.get(thread_id)
            if p is None:
                return None
            if time.time() - p.get("created_at", 0) > self._ttl:
                self._pending.pop(thread_id, None)
                return None
            return dict(p)

    async def set(self, thread_id: str, pending: dict) -> None:
        async with self._lock:
            pending["created_at"] = time.time()
            self._pending[thread_id] = pending

    async def clear(self, thread_id: str) -> bool:
        async with self._lock:
            return self._pending.pop(thread_id, None) is not None


# ---------- Worker 处理器 ----------

def _make_handler(store: ThreadStore, pending_store: PendingStore):
    def persist_reply(task: Task, result: dict) -> None:
        """把成功结果落库为一条助手消息（Spec17 §5.2C）。

        落库只是"记录"，不是任务的一部分：它自己出错不能让一个已经成功、
        结果也已经交付给用户的任务翻成 FAILED（与 §5.2C 对 `image_ids` 空值的
        兜底同一个立场）。失败/超时/排队被拒的结果不走这里——那类结果不落库（§3.4）。
        """
        user_id = task.request.get("user_id")
        if user_id is None:
            return
        try:
            chat_history.record_assistant_reply(task.thread_id, user_id, result, task.id)
        except Exception:  # noqa: BLE001
            logger.exception("助手消息落库失败", extra={
                "event": "chat.persist_failed", "thread_id": task.thread_id,
                "task_id": task.id,
            })

    async def handle_task(task: Task) -> dict:
        request = task.request
        try:
            # 挂起意图存在 → 注入本轮请求（含 TTL 检查；过期当无）
            pending = await pending_store.get(task.thread_id)
            if pending:
                request = {**request, "pending": pending}
            result = await run_supervisor(request, await store.get(task.thread_id),
                                          task.request_id)
        except AppError as exc:
            # 失败即作废挂起意图（Spec7 §5.3）：重试所需上下文由会话历史兜底
            await pending_store.clear(task.thread_id)
            await store.append(task.thread_id, {
                "role": "assistant", "text": f"（任务失败：{exc.message}）",
            })
            raise
        except Exception as exc:  # noqa: BLE001
            await pending_store.clear(task.thread_id)   # 同上
            await store.append(task.thread_id, {
                "role": "assistant", "text": f"（任务失败：{exc}）",
            })
            raise

        # 追问：结果为 clarify → 写入/覆盖挂起意图，并把追问文案作为普通文本返回（Spec5 §5.2）
        # missing 一并挂起，供下一轮主 Agent 知道还缺哪些参数（Spec6 §5.1）。
        if result.get("kind") == "clarify":
            intent = result.get("intent")
            question = result.get("question") or ""
            missing = result.get("missing") or []
            image_url = result.get("image_url") or (pending or {}).get("image_url")
            await pending_store.set(task.thread_id, {
                "intent": intent, "image_url": image_url, "question": question,
                "missing": missing,
            })
            result = {"kind": "text", "text": question}
            await store.append(task.thread_id, {
                "role": "assistant", "text": question,
            })
            persist_reply(task, result)      # 追问也是助手说过的话，历史里要看得到
            logger.info("发起追问", extra={
                "event": "clarify.asked", "thread_id": task.thread_id,
                "intent": intent,
            })
            return result

        # 非追问 → 清挂起意图（交付完成 / 用户开新话题，Spec5 §5.2）
        cleared = await pending_store.clear(task.thread_id)
        if cleared:
            logger.info("挂起意图已交付/清除", extra={
                "event": "clarify.resolved", "thread_id": task.thread_id,
                "intent": (pending or {}).get("intent"),
            })

        # 记录助手结果到会话历史
        if result.get("kind") == "text":
            await store.append(task.thread_id, {
                "role": "assistant", "text": result.get("text", ""),
            })
        else:
            await store.append(task.thread_id, {
                "role": "assistant", "text": "（已生成图片）",
                "images": result.get("images") or [],
            })
        persist_reply(task, result)          # 内存上下文 + 持久化各记一份（§5.2C）
        # 成功路径：按工具标签累计使用统计（Spec4 §5.2）；失败/超时/排队被拒不计
        category = _usage_category(result)
        if category:
            user_id = request.get("user_id")
            if user_id is not None:
                db.record_call(user_id, category)
        return result

    return handle_task


async def _janitor(queue: TaskQueue, store: ThreadStore) -> None:
    while True:
        try:
            await asyncio.sleep(config.JANITOR_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break
        try:
            removed = media.cleanup_old_files()
            await queue.prune()
            if removed:
                logger.info(f"清理过期图片 {removed} 个", extra={"event": "storage.cleanup"})
        except Exception as exc:  # noqa: BLE001
            logger.exception("janitor error", extra={"event": "storage.cleanup"})
            logger.warning(f"清理巡检异常: {exc}", extra={"event": "storage.cleanup"})


# ---------- 应用 ----------

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    try:
        db.init_db()                          # 建表 + 首次启动自动建初始管理员
    except RuntimeError as exc:
        logger.error(str(exc), extra={"event": "auth.db_init_failed"})
        raise
    media.cleanup_all()                       # 启动时清空 storage/

    store = ThreadStore()
    app.state.thread_store = store
    pending_store = PendingStore()
    app.state.pending_store = pending_store
    app.state.queue = TaskQueue(_make_handler(store, pending_store))
    await app.state.queue.start()
    app.state.janitor = asyncio.create_task(_janitor(app.state.queue, store))

    logger.info("server started", extra={"event": "server.start"})
    yield

    app.state.janitor.cancel()
    await app.state.queue.stop()
    logger.info("server stopped", extra={"event": "server.stop"})


app = FastAPI(title="ArtiControlNet", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 统一鉴权中间件（Spec2 §6.2）----------

# 放行列表：除登录、注册链路、欠费充值、邮箱验证码与点击埋点外，所有 /api 接口
# 都需登录态（Spec19 §6.8 / Spec21 §6.3 / Spec22 §6.9）。
# 这十条是**精确匹配**（`path not in PUBLIC_AUTH_PATHS`），不是前缀匹配——
# 新增路径时必须原样写全，别写成 /api/auth/register 就以为能覆盖 -config。
PUBLIC_AUTH_PATHS = {
    "/api/auth/login",
    "/api/auth/register",        # Spec19：提交注册申请（Spec22 起内部要验证码，但仍公开）
    "/api/auth/register-config", # Spec19：注册弹窗的公开配置
    "/api/auth/payment-qr",      # Spec19：收款码图片
    # Spec21：欠费充值申请。用户此时正被 40304 拦在门外，手里没有 token；
    # 它只能产生一条**待审批**记录，不能给任何人加额度（§3.3-2）。
    "/api/auth/recharge-request",
    # Spec22 新增 5 条
    "/api/auth/email-code",      # 发验证码（用户此刻必然没有 token）
    "/api/auth/verify-email-code",  # 校验验证码（改密码的前置）
    "/api/auth/login-by-email",  # 邮箱登录（就是用来拿 token 的）
    "/api/auth/reset-password",  # 自助改密码（忘了密码的人没有 token）
    "/api/click",                # 点击埋点（「打开登录页」发生时用户还没 token）
}

# ⚠️ 中间件对白名单里的路径**不判限额**——所以 /api/auth/login-by-email 必须
# **自己**判 40304（Spec22 §6.4）：漏了它，一个已经欠费被拦的用户只要用邮箱登录
# 就能绕过去。这与 /api/auth/login 的处境完全一样（Spec21 §5.7 的四处副本之一
# 就在登录路由里）。


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def _auth_reject(request: Request, code: int, message: str,
                 status_code: int) -> JSONResponse:
    logger.warning(message, extra={
        "event": "auth.rejected",
        "request_id": request.headers.get("x-request-id"),
    })
    return JSONResponse(status_code=status_code,
                        content={"code": code, "message": message, "data": None})


def _quota_reject(request: Request, user: dict) -> JSONResponse:
    """服务次数耗尽：与 _auth_reject 分开，用独立 event 名（排障时一眼可辨，Spec18 §6.4）。"""
    logger.warning("服务次数已达上限，拒绝访问", extra={
        "event": "auth.quota_blocked",
        "request_id": request.headers.get("x-request-id"),
        "username": user["username"], "used": user["used"],
        "quota_limit": user["quota_limit"],
        "path": request.url.path,
    })
    return JSONResponse(
        status_code=403,
        content={"code": 40304, "message": config.QUOTA_EXCEEDED_MESSAGE, "data": None},
    )


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # CORS 预检放行（由 CORSMiddleware 处理 OPTIONS）
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_AUTH_PATHS:
        token = _bearer_token(request)
        if not token:
            return _auth_reject(request, 40103, "缺少登录态", 401)
        try:
            payload = auth.decode_token(token)
        except AuthTokenError as exc:
            return _auth_reject(request, 40103, exc.message, 401)
        # 实时查库取最新 is_admin（撤销管理员即时生效）
        user = db.get_user_by_id(payload["user_id"])
        if user is None:
            return _auth_reject(request, 40103, "登录态无效", 401)
        request.state.user = {
            "id": user["id"],
            "username": user["username"],
            "is_admin": user["is_admin"],
        }
        # Spec18 §6.4：普通用户服务次数用满即全拦（含 /api/auth/me），
        # 前端据 40304 清 token 回登录页并弹出提示。
        # 位置：放在 request.state.user 之后（日志/上下文需要它），
        #       放在 /api/admin/* 判断之前（管理员恒豁免，顺序上先排掉更省分支）。
        # 这一次判定不额外查库：used 已由 db.get_user_by_id 的 LEFT JOIN 带出（§2.3）。
        # Spec21 §5.7：判据是 `used > quota_limit`（**不是** `>=`）——整数下与
        # `>= limit + 1` 等价，但少一次加法、也不会有人把 +1 写在括号外。
        # 效果：限额 25 的用户能做完第 26 次调用（原口径下第 25 次一成功就被踢，
        # 结果拿不到、钱却已经花了）。四处副本，见 §5.7。
        if not user["is_admin"] and user["used"] > user["quota_limit"]:
            return _quota_reject(request, user)
        if path.startswith("/api/admin/"):
            if not user["is_admin"]:
                return _auth_reject(request, 40301, "无权限：仅管理员可访问", 403)
    return await call_next(request)


# ---------- 异常处理 ----------

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    logger.warning(exc.message, extra={
        "event": "request.error",
        "request_id": request.headers.get("x-request-id"),
        "provider": exc.provider,
    })
    return JSONResponse(status_code=exc.status_code,
                        content={"code": exc.code, "message": exc.message, "data": None})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    logger.warning("参数校验失败", extra={"event": "request.error",
                                        "request_id": request.headers.get("x-request-id")})
    return JSONResponse(status_code=400,
                        content={"code": 40001, "message": "请求参数非法", "data": None})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("未捕获异常", extra={"event": "request.error",
                                         "request_id": request.headers.get("x-request-id")})
    return JSONResponse(status_code=500,
                        content={"code": 50001, "message": "内部错误", "data": None})


# ---------- 路由 ----------

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/api/chat")
async def create_chat(payload: schemas.ChatRequest, request: Request,
                      x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """发起一轮对话：解析对话 → 校验参考图 → 回填路由上下文 → 用户消息落库 → 入队。

    步骤顺序是契约的一部分（Spec17 §5.2B）：第 3 步的回填**必须**早于第 4 步的
    落库，否则刚写进库的这条用户消息会被回填进内存上下文，第 6 步再 append 一次，
    同一句话在路由上下文里出现两遍。
    """
    request_id = _request_id(x_request_id)
    user = request.state.user
    queue: TaskQueue = request.app.state.queue
    store: ThreadStore = request.app.state.thread_store

    # 1. 对话 id：复用则必须是本人的（Spec17 §6.2 语义收紧，原先接受任意字符串）
    if payload.thread_id:
        chat_history.require_owned(payload.thread_id, user["id"])
        thread_id = payload.thread_id
        is_new_conversation = False
    else:
        thread_id = f"t_{uuid.uuid4().hex[:8]}"    # 新 id，此时还不落库
        is_new_conversation = True

    # 2. 参考图归属校验：image_id 优先，越权 / 不存在 → 40403
    image_id = payload.image_id
    if image_id is not None:
        record = db.get_image_record(image_id)
        if record is None or record["user_id"] != user["id"]:
            raise GalleryItemNotFoundError()
        # 路由上下文与后续会话都引用作品库（§5.2A）。只传 image_url 的调用方走回退分支，
        # 该轮结束时 chat_messages.image_id 为 NULL——前端 Spec17 起一律传 image_id。
        image_ref = f"/api/gallery/{image_id}/file"
    else:
        image_ref = payload.image_url

    # 3. 内存 miss 时从库回填路由上下文（后端重启后"接着聊"不失忆）
    await store.ensure_loaded(thread_id, user["id"])

    # 4. 用户消息落库：conversations 行在这一步才真正创建（"消息驱动"，§5.3）
    chat_history.start_turn(thread_id, user["id"], text=payload.message,
                            image_id=image_id)
    if is_new_conversation:
        logger.info("新对话", extra={
            "event": "chat.conversation_started", "request_id": request_id,
            "thread_id": thread_id, "user_id": user["id"],
        })

    # 5. 提交任务（失败/超时/排队被拒都不会撤掉上面那条用户消息，§3.4）
    task = await queue.submit(
        thread_id=thread_id, kind="chat", request_id=request_id,
        request={
            "message": payload.message,
            "image_url": image_ref,
            "thread_id": thread_id,
            "public_base": _public_base(request),
            "request_id": request_id,
            "user_id": user["id"],   # 统计归属（Spec4 §5.2）+ 消息落库归属（Spec17）
        },
    )
    # 6. 记录用户消息（供后续路由上下文）
    await store.append(thread_id, {
        "role": "user", "text": payload.message, "image_url": image_ref,
    })
    logger.info("收到对话请求", extra={
        "event": "chat.submitted", "request_id": request_id,
        "thread_id": thread_id, "task_id": task.id,
    })
    return _ok({"task_id": task.id, "thread_id": thread_id, "status": task.status})


# ---------- 对话历史（Spec17 §6.3~§6.5）----------

@app.get("/api/conversations")
async def list_conversations(request: Request):
    """本人对话列表（updated_at 倒序，上限 CONVERSATION_LIST_LIMIT，不分页）。

    只返回本人的（`WHERE user_id = ?`），无管理员视角——聊天记录是私域数据。
    """
    return _ok({"items": chat_history.list_conversations(request.state.user["id"])})


@app.get("/api/conversations/{conv_id}/messages")
async def get_conversation_messages(conv_id: str, request: Request):
    """某段对话的全部消息（时间正序）。不存在 / 非本人 → 40407（不泄露存在性）。"""
    return _ok(chat_history.get_conversation_messages(conv_id, request.state.user["id"]))


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str, request: Request,
                              x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """删除本人的某段对话及其全部消息；**不删任何图片**（§6.5）。

    重复删除返回 40407 而不是静默 200：前端只会拿到自己列表里的 id，触发即 bug。
    """
    request_id = _request_id(x_request_id)
    user = request.state.user
    result = chat_history.delete_conversation(conv_id, user["id"])
    logger.info("删除对话", extra={
        "event": "chat.conversation_deleted", "request_id": request_id,
        "thread_id": conv_id, "user_id": user["id"],
        "messages": result["message_count"],       # 正文不入日志（§10）
    })
    return _ok({"id": conv_id})


@app.post("/api/images")
async def upload_image(request: Request, file: UploadFile = File(...),
                       x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    request_id = _request_id(x_request_id)
    data = await file.read()
    if file.content_type and file.content_type not in config.ALLOWED_IMAGE_MIME:
        raise UnsupportedImageTypeError(f"不支持的图片格式: {file.content_type}")
    ext = media.validate_upload(data)                  # 40002 / 40003 / 40004
    url = media.save_upload(data, _public_base(request), ext)
    # 上传即入库：除临时 storage/ 外，额外持久化到个人作品库（Spec5 §5.2 链路 1）
    # Spec17 §6.1：返回值不再丢弃——前端要把 image_id 带进 /api/chat，让这一轮
    # 的参考图落库为作品库引用，而不是活 1 小时的 storage/ 地址。
    record = gallery.save_gallery_image(data, request.state.user["id"], "upload", None)
    logger.info(f"图片上传成功: {url}", extra={
        "event": "image.uploaded", "request_id": request_id,
        "image_id": record["id"],
    })
    return _ok({"image_url": url, "image_id": record["id"]})


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: int, request: Request):
    queue: TaskQueue = request.app.state.queue
    task = queue.get(task_id)
    if task is None:
        raise NotFoundError("任务不存在")
    return _ok({
        "task_id": task["task_id"],
        "thread_id": task["thread_id"],
        "kind": task["kind"],
        "status": task["status"],
        "error": task["error"],
        "result": task["result"],
    })


# Spec17 §6.6：`GET /api/threads/{thread_id}/messages` 已删除——它是死代码（前端从未调用，
# 历史改由 `GET /api/conversations/{id}/messages` 提供），且没有归属校验（任何人凭
# thread_id 就能读到别人的对话）。`ThreadStore` 本身保留：它是路由上下文，不是接口。


# ---------- 个人作品库（Spec5 §6.1）----------

@app.get("/api/gallery")
async def list_gallery(request: Request, source: str = ""):
    """本人作品列表（时间倒序），可 ?source=upload|generate|edit 筛选；每项含可空 share（Spec9 §6.1）。"""
    user = request.state.user
    items = gallery.list_user_images(user["id"], source or None, _public_base(request))
    return _ok({"items": items})


@app.post("/api/gallery")
async def create_gallery_item(request: Request, file: UploadFile = File(...),
                              note: str = Form(default="")):
    """作品库直传（Spec16 §6.1）：multipart file 必填 + note 可选。

    与 /api/images 的区别：那条是**聊天附件**通道，额外写临时 storage/ 并返回 image_url；
    这条只往持久作品库放一张图——不写 storage/、不产生 task、不计 usage。
    备注长度校验在业务层（40015），路由层只做 content_type 白名单。
    """
    data = await file.read()
    if file.content_type and file.content_type not in config.ALLOWED_IMAGE_MIME:
        raise UnsupportedImageTypeError(f"不支持的图片格式: {file.content_type}")
    media.validate_upload(data)                        # 40002 / 40003 / 40004
    item = gallery.create_upload(data, request.state.user["id"], note,
                                 _public_base(request))
    return _ok(item)


@app.put("/api/gallery/{item_id}/note")
async def update_gallery_note(item_id: int, payload: schemas.GalleryNoteUpdateRequest,
                              request: Request):
    """改 / 清空本人上传作品的备注（Spec16 §6.2）：note 传空串即清空。

    非上传作品（生成/绘图）→ 40015；不存在 / 非本人 → 40403；超长 → 40015。
    """
    item = gallery.update_note(item_id, request.state.user["id"], payload.note,
                               _public_base(request))
    return _ok(item)


@app.get("/api/gallery/{item_id}/file")
async def gallery_file(item_id: int, request: Request, download: bool = False):
    """查看原图：带 token 拉取（<img> 无法带 Authorization 头，前端用 blob 渲染）。

    ?download=1 → Content-Disposition: attachment（触发浏览器保存）。
    非本人 / 不存在 → 404（40403）。
    """
    user = request.state.user
    record, data = gallery.read_gallery_file(item_id, user["id"])
    media_type = gallery.mime_for(record)
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{record["file_name"]}"'
    return Response(content=data, media_type=media_type, headers=headers)


@app.delete("/api/gallery/{item_id}")
async def delete_gallery_item(item_id: int, request: Request):
    """删除本人作品：记录 + gallery/ 物理文件一并删除（分享级联在 gallery.delete_item 内）。"""
    user = request.state.user
    gallery.delete_item(item_id, user["id"])
    return _ok({"id": item_id})


# ---------- 个人作品风格 Wiki（Spec12 §6.1）----------

@app.get("/api/wiki")
async def get_wiki(request: Request):
    """读本人风格 Wiki；行不存在返回全空默认值，不建行（Spec12 §5.2A）。"""
    return _ok(wiki.get_wiki(request.state.user["id"]))


@app.post("/api/wiki/style/refresh")
async def refresh_wiki_style(request: Request,
                             x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """基于未纳入过的作品更新风格（同步等 LLM）。

    无待考虑作品 → 200 + updated:false / reason="nothing_new"（正常业务状态，非错误）；
    上游失败 → 既有 61001 / 61002，wiki 与 images.wiki_used 均不变。
    """
    request_id = _request_id(x_request_id)
    user = request.state.user
    data = await wiki.refresh_style(user["id"])
    if data["updated"]:
        logger.info("更新个人作品风格", extra={
            "event": "wiki.style_updated", "request_id": request_id,
            "user_id": user["id"], "source": "refresh",
            "used_count": data["used_count"], "style_len": len(data["style"]),
            "upload_analyzed": data["upload_analyzed"],
            "upload_failed": data["upload_failed"],
        })
    else:
        extra = {
            "event": "wiki.refresh_skipped", "request_id": request_id,
            "user_id": user["id"], "reason": data["reason"],
        }
        if data["reason"] == "analysis_failed":
            extra["upload_failed"] = data["upload_failed"]
        logger.info("本次无可用材料", extra=extra)
    return _ok(data)


@app.put("/api/wiki/style")
async def update_wiki_style(payload: schemas.WikiStyleRequest, request: Request,
                            x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """手动覆盖风格：旧值进 prev_style（Spec12 §5.2C）；空 / 超长 → 40014。"""
    request_id = _request_id(x_request_id)
    user = request.state.user
    record = wiki.update_style_manually(user["id"], payload.style)
    logger.info("手动更新个人作品风格", extra={
        "event": "wiki.style_updated", "request_id": request_id,
        "user_id": user["id"], "source": "manual", "used_count": 0,
        "style_len": len(record["style"]),
        "upload_analyzed": 0, "upload_failed": 0,
    })
    return _ok(record)


# ---------- 社区（Spec9 §6.1）----------

@app.post("/api/community")
async def create_community_post(request: Request,
                                text: str = Form(...),
                                gallery_id: Optional[int] = Form(None),
                                file: Optional[UploadFile] = File(None),
                                x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """发帖：文字（1~1000 字）+ **可选**单图（作品库 gallery_id 或新上传 file）。

    Spec17 §5.2D：图片来源从"必须二选一"改为「不能同时给，但可以都不给」——
    两者皆无即纯文字帖。多图仍不在范围内。
    """
    request_id = _request_id(x_request_id)
    user = request.state.user
    body = (text or "").strip()
    if not body or len(body) > config.COMMUNITY_POST_TEXT_MAX:
        raise PostContentError(f"帖子文字需为 1~{config.COMMUNITY_POST_TEXT_MAX} 字")
    has_gallery = gallery_id is not None
    has_file = file is not None and file.filename
    if has_gallery and has_file:
        raise PostContentError("图片来源最多一张：从作品库选择或上传新图，不能同时给")
    image_bytes = None
    ext = None
    if has_file:
        data = await file.read()
        ext = media.validate_upload(data)               # 40002 / 40003 / 40004
        image_bytes = data
    post = community.create_post(user["id"], body, gallery_id=gallery_id,
                                 image_bytes=image_bytes, ext=ext)
    logger.info("发帖", extra={
        "event": "community.posted", "request_id": request_id,
        "user_id": user["id"], "post_id": post["id"],
        "has_image": bool(post["image_file"]),
    })
    return _ok({"post": {
        "id": post["id"],
        "text": post["text"],
        "author": user["username"],
        "author_is_admin": user["is_admin"],
        "image_url": (f"/api/community/{post['id']}/image"
                      if post["image_file"] else None),
        "like_count": 0,
        "dislike_count": 0,
        "my_vote": None,
        "comments": [],                            # 新帖必然无评论（§6.7）
        "created_at": post["created_at"],
    }})


@app.get("/api/community")
async def list_community(request: Request, offset: int = 0, limit: int = 50):
    """帖子列表，最新在前；每项含作者、计数、我的投票、**全量内嵌评论**。

    limit≤100；评论不参与分页（§6.8）——前端零额外请求，一条 GET 拿全。
    """
    user = request.state.user
    offset = max(0, offset)
    limit = max(1, min(limit, 100))
    return _ok({"items": community.list_posts(user["id"], offset, limit)})


# ---------- 帖子评论（Spec17 §6.10）----------
#
# 有意**没有 PUT**：评论不可编辑（§2.3），要改只能删了重发。全仓唯一如此。

@app.post("/api/community/{post_id}/comments")
async def create_comment(post_id: int, payload: schemas.CommentCreateRequest,
                         request: Request,
                         x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """发表评论（1~COMMENT_TEXT_MAX 字）。帖子不存在 → 40404；文字非法 → 40016。"""
    request_id = _request_id(x_request_id)
    user = request.state.user
    body = (payload.text or "").strip()
    if not body or len(body) > config.COMMENT_TEXT_MAX:
        raise CommentContentError(f"评论需为 1~{config.COMMENT_TEXT_MAX} 字")
    comment = community.create_comment(post_id, user["id"], body)
    logger.info("发表评论", extra={
        "event": "community.commented", "request_id": request_id,
        "user_id": user["id"], "post_id": post_id, "comment_id": comment["id"],
        # 评论正文不入日志（§10）：用户私人文字只记 id
    })
    return _ok({"comment": comment})


@app.get("/api/community/{post_id}/comments")
async def list_comments(post_id: int, request: Request):
    """某帖的全部评论（id ASC，时间正序）；帖子不存在 → 40404。

    前端不调用它——评论已随 `GET /api/community` 内嵌返回（§6.8）。保留是因为
    POST/DELETE 挂在 `/comments` 下而缺 GET 会让资源形态残缺，也没法用 curl
    单独验证某帖的评论。
    """
    return _ok({"items": community.list_comments(post_id)})


@app.delete("/api/community/{post_id}/comments/{comment_id}")
async def delete_comment(post_id: int, comment_id: int, request: Request,
                         x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """删评论（评论作者或管理员）。评论不存在 / 不挂在该帖上 → 40408；越权 → 40303。"""
    request_id = _request_id(x_request_id)
    user = request.state.user
    result = community.delete_comment(post_id, comment_id, user["id"], user["is_admin"])
    logger.info("删除评论", extra={
        "event": "community.comment_deleted", "request_id": request_id,
        "post_id": post_id, "comment_id": comment_id,
        "actor_id": user["id"], "by_admin": result["by_admin"],
    })
    return _ok({"id": comment_id})


@app.get("/api/community/{post_id}/image")
async def community_image(post_id: int, request: Request):
    """帖子图片（任何登录用户可看，不校验归属——社区对所有人开放）。"""
    post, data = community.read_post_image(post_id)
    return Response(content=data, media_type=community.mime_for(post))


@app.post("/api/community/{post_id}/vote")
async def community_vote(post_id: int, payload: schemas.VoteRequest, request: Request):
    """点赞 / 点踩 / 取消（vote=null 删行）；返回现算计数与我的选择。"""
    user = request.state.user
    vote = payload.vote
    if vote not in (None, "like", "dislike"):
        raise PostContentError("投票取值只能为 like / dislike / null")
    result = community.vote(post_id, user["id"], vote)
    logger.info("投票", extra={
        "event": "community.voted", "post_id": post_id,
        "user_id": user["id"], "vote": vote or "cancel",
    })
    return _ok(result)


@app.delete("/api/community/{post_id}")
async def delete_community_post(post_id: int, request: Request,
                                x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """删帖（作者或管理员）；文件与投票级联删除。"""
    request_id = _request_id(x_request_id)
    user = request.state.user
    community.delete_post(post_id, user["id"], user["is_admin"])
    logger.info("删帖", extra={
        "event": "community.deleted", "request_id": request_id,
        "user_id": user["id"], "post_id": post_id,
    })
    return _ok({"id": post_id})


# ---------- AI 服务反馈（Spec9 §6.1）----------

_FEEDBACK_CATEGORIES = ("generate", "edit", "qa")


@app.post("/api/feedback")
async def post_feedback(payload: schemas.FeedbackRequest, request: Request,
                        x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """服务结果 👍/👎 / 取消（vote=null 删行）。category 限定三类生成服务。"""
    request_id = _request_id(x_request_id)
    user = request.state.user
    if payload.category not in _FEEDBACK_CATEGORIES:
        raise FeedbackParamError("反馈类别需为 generate / edit / qa")
    if payload.vote not in (None, "like", "dislike"):
        raise FeedbackParamError("反馈投票需为 like / dislike / null")
    db.set_feedback(payload.task_id, user["id"], payload.category, payload.vote)
    logger.info("服务反馈", extra={
        "event": "feedback.voted", "request_id": request_id,
        "user_id": user["id"], "task_id": payload.task_id,
        "category": payload.category, "vote": payload.vote or "cancel",
    })
    return _ok({"task_id": payload.task_id, "category": payload.category, "vote": payload.vote})


@app.post("/api/admin/feedback/clear")
async def admin_clear_feedback(request: Request, category: str = "",
                               x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """管理员清空反馈统计（可 ?category= 只清一类）。"""
    request_id = _request_id(x_request_id)
    user = request.state.user
    cat = category or None
    if cat is not None and cat not in _FEEDBACK_CATEGORIES:
        raise FeedbackParamError("反馈类别需为 generate / edit / qa")
    cleared = db.clear_feedback(cat)
    logger.info("清空反馈统计", extra={
        "event": "feedback.cleared", "request_id": request_id,
        "operator": user["username"], "category": cat or "all",
    })
    return _ok({"cleared": cleared})


@app.post("/api/admin/usage/clear")
async def admin_clear_usage(request: Request,
                            x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """管理员清零四类调用计数（对话/文生图/图文生图/图像QA）并记录清零时间（Spec11）。

    cleared = 清零前四类调用总数（信息性，供日志/提示）；清零即开启一段新的统计区间。
    """
    request_id = _request_id(x_request_id)
    user = request.state.user
    cleared = db.clear_usage()
    logger.info("清零调用统计", extra={
        "event": "usage.cleared", "request_id": request_id,
        "operator": user["username"], "cleared": cleared,
    })
    return _ok({"cleared": cleared})


# ---------- 作品分享链接（Spec9 §6.1）----------

@app.post("/api/shares")
async def create_share(payload: schemas.ShareCreateRequest, request: Request,
                       x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """为本人作品生成公开免登录临时分享链接（覆盖旧 token，7 天有效）。"""
    request_id = _request_id(x_request_id)
    user = request.state.user
    result = shares.create_share(user["id"], payload.image_id, _public_base(request))
    logger.info("生成分享链接", extra={
        "event": "share.created", "request_id": request_id,
        "user_id": user["id"], "image_id": payload.image_id,
    })
    return _ok(result)


@app.delete("/api/shares/{share_id}")
async def revoke_share(share_id: int, request: Request,
                       x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """撤销本人分享链接（仅本人，40403 不泄露存在性）。"""
    request_id = _request_id(x_request_id)
    user = request.state.user
    image_id = shares.revoke_share(share_id, user["id"])
    logger.info("撤销分享链接", extra={
        "event": "share.revoked", "request_id": request_id,
        "user_id": user["id"], "image_id": image_id,
    })
    return _ok({"id": share_id})


@app.get("/share/{token}")
async def share_page(token: str):
    """免登录分享页：紫色主题 HTML + 大图 + 作者 + 下载链接。非 /api 路径天然公开。"""
    share, image = shares.resolve_token(token)
    author = db.get_user_by_id(share["user_id"])["username"]
    return HTMLResponse(content=shares.render_share_page(share, image, author))


@app.get("/share/{token}/image")
async def share_image(token: str, download: bool = False):
    """分享页原图（读 gallery/ 原字节）；?download=1 触发浏览器下载。"""
    share, image = shares.resolve_token(token)
    data = shares.read_share_image(image)
    media_type = gallery.mime_for(image)
    if download:
        ext = image.get("ext", ".jpg")
        headers = {"Content-Disposition": f'attachment; filename="artcn_share_{share["id"]}{ext}"'}
        return Response(content=data, media_type=media_type, headers=headers)
    return Response(content=data, media_type=media_type)


# ---------- 建议箱（Spec9 §6.1）----------

@app.post("/api/suggestions")
async def create_suggestion(payload: schemas.SuggestionCreateRequest, request: Request,
                            x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """任意登录用户写信（1~2000 字）；管理员只能审批、不能写（Spec10 §2.2）。"""
    request_id = _request_id(x_request_id)
    user = request.state.user
    if user["is_admin"]:
        logger.info("管理员写建议被拒", extra={
            "event": "suggestion.rejected", "request_id": request_id,
            "user_id": user["id"],
        })
        raise ForbiddenError("管理员不能提交建议，只能审批")
    text = (payload.text or "").strip()
    if not text or len(text) > config.SUGGESTION_TEXT_MAX:
        raise SuggestionContentError(f"建议内容需为 1~{config.SUGGESTION_TEXT_MAX} 字")
    sug = db.create_suggestion(user["id"], text)
    logger.info("新建议", extra={
        "event": "suggestion.created", "request_id": request_id,
        "user_id": user["id"], "suggestion_id": sug["id"], "status": sug["status"],
    })
    return _ok({"suggestion": sug})


@app.get("/api/suggestions/mine")
async def list_my_suggestions(request: Request):
    """我的建议（含管理员回复与状态），新→旧。"""
    user = request.state.user
    return _ok({"items": db.list_suggestions(user["id"])})


@app.get("/api/admin/suggestions")
async def admin_list_suggestions(request: Request, status: str = ""):
    """管理员查看全部建议，可 ?status=pending|resolved 筛选。"""
    st = status or None
    if st is not None and st not in ("pending", "resolved"):
        raise SuggestionContentError("建议状态需为 pending / resolved")
    return _ok({"items": db.list_all_suggestions(st)})


@app.put("/api/admin/suggestions/{suggestion_id}")
async def admin_update_suggestion(suggestion_id: int, payload: schemas.SuggestionUpdateRequest,
                                  request: Request,
                                  x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """管理员标记状态 / 写回复（可只改其一，一次落库）；status/reply 非法或不存在 → 错误码。"""
    request_id = _request_id(x_request_id)
    user = request.state.user
    if payload.status is not None and payload.status not in ("pending", "resolved"):
        raise SuggestionContentError("建议状态需为 pending / resolved")
    if db.get_suggestion(suggestion_id) is None:
        raise SuggestionNotFoundError()
    reply = payload.reply
    if reply is not None and len(reply.strip()) > config.SUGGESTION_TEXT_MAX:
        raise SuggestionContentError(f"回复内容需 ≤{config.SUGGESTION_TEXT_MAX} 字")
    sug = db.update_suggestion(
        suggestion_id,
        status=payload.status,
        reply=reply.strip() if reply is not None else None,
    )
    logger.info("更新建议", extra={
        "event": "suggestion.updated", "request_id": request_id,
        "operator": user["username"], "suggestion_id": suggestion_id,
        "status": sug["status"],
    })
    return _ok({"id": sug["id"], "status": sug["status"], "reply": sug["reply"]})


@app.delete("/api/admin/suggestions/{suggestion_id}")
async def admin_delete_suggestion(suggestion_id: int, request: Request,
                                  x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """管理员删除建议。"""
    request_id = _request_id(x_request_id)
    user = request.state.user
    if not db.delete_suggestion(suggestion_id):
        raise SuggestionNotFoundError()
    logger.info("删除建议", extra={
        "event": "suggestion.deleted", "request_id": request_id,
        "operator": user["username"], "suggestion_id": suggestion_id,
    })
    return _ok({"id": suggestion_id})


# ---------- 邮箱验证码 / 入口埋点的工具（Spec22 §2.8 / §5.7）----------
# 四个校验点（注册提交 / verify-email-code / login-by-email / reset-password）
# 共用下面这几个函数——**一份规则，一个地方**（§2.6 要求"限速口径只有一份"）。

def _norm_email(raw: Optional[str]) -> str:
    """邮箱规范化：`strip()` + `lower()`。**全仓唯一的邮箱规则**（§2.8）。

    手机键盘会自动把首字母大写：用户注册时打的是 `Zhang@qq.com`、改密码时打的是
    `zhang@qq.com`，不规范化就是"同一个人在系统里有两个邮箱"——改密码说他
    "还未注册"，注册又说"已注册账号 zhang"，这类故障用户根本描述不清。

    db 层**不做**隐式转换：与其它字段的 strip 放在一起，规则只在这一处
    （Spec19 对手机号 / 邮箱格式的处理就是这个立场）。
    """
    return (raw or "").strip().lower()


def _email_ok(email: str) -> bool:
    """邮箱格式：含 `@`、`@` 前后都有内容、长度 ≤128（Spec19 §6.2 的原判据）。"""
    if not email or len(email) > 128 or "@" not in email:
        return False
    local, _, domain = email.partition("@")
    return bool(local) and bool(domain)


def _code_ok(code: str) -> bool:
    """验证码形态：4 位**半角**数字（长度是契约，见 `verifications.CODE_LENGTH`）。

    多一个 `isascii()` 而不是只用 `isdigit()`：`'１２３４'.isdigit()` 是 `True`，
    全角数字能过格式校验、却永远比不上库里的半角码——用户只会看到"验证码错误"
    而完全不知道该改什么。这类"看着对、其实不对"的输入没有理由放进来。
    """
    return (len(code) == verifications.CODE_LENGTH
            and code.isascii() and code.isdigit())


def _reject_if_rate_limited(ip: str, request_id: str, purpose: str) -> None:
    """入口限速（Spec22 §2.6）：猜验证码与猜密码是同一件事，共用 Spec2 的计数器。

    `auth.is_login_blocked` / `record_login_failure` 的函数名保留 `login_*` 不改
    （改名要让 main.py 四处调用点 + Spec2 文档全线对不上），语义已写在它的 docstring 里。

    `purpose` 是**外部输入**，所以只把白名单内的值写进日志——否则这个字段会变成
    一个可以塞任意字符串的地方（Spec19 §10 的"不拼接外部输入"同一原则）。
    """
    if auth.is_login_blocked(ip):
        logger.warning("验证码尝试过于频繁", extra={
            "event": "auth.login_failed", "request_id": request_id,
            "purpose": purpose if purpose in verifications.PURPOSES else "unknown",
        })
        raise LoginRateLimitedError()


def _verify_code(request_id: str, ip: str, email: str, purpose: str, code: str) -> None:
    """校验验证码；**失败即记一次登录限速**并抛 40020。四个校验点共用（§2.6）。

    为什么失败要计数：4 位数字只有 9000 种可能，10 分钟 TTL 内不限次数地猜，
    一个脚本几分钟就能撞开任意一个已知邮箱的账号——这是邮箱登录这条通道自己
    开出来的洞。5 次 / 5 分钟 / IP 之后撞中概率降到 < 0.12%（§2.6）。

    ⚠️ 日志里**绝不带 `code`**（它是凭据）、**绝不带 `email`**（PII）——两者都
    只记 `purpose`（§10.2）。失败那条**每次都要记**：它是爆破的指纹。
    """
    if db.match_email_verification(email, purpose, code, config.EMAIL_CODE_TTL_SECONDS):
        logger.info("验证码校验通过", extra={
            "event": "email_code.verified", "request_id": request_id,
            "purpose": purpose,
        })
        return
    auth.record_login_failure(ip)      # 失败的**唯一**处理点，别在调用方再记一次
    logger.warning("验证码校验失败", extra={
        "event": "email_code.verify_failed", "request_id": request_id,
        "purpose": purpose,
    })
    raise EmailCodeRequestError("验证码错误或已过期")


def _reject_duplicate_email(email: str, purpose: str, request_id: str) -> None:
    """发码前的查重（Spec22 §2.4 那张表）。命中即记 `email_code.rejected` 并抛 40907。

    | purpose | 判据 | 结果 |
    |---|---|---|
    | `register` | 邮箱已在 `users` | 40907「已注册账号{username}，请前往登录界面…」 |
    | `login` / `reset` | 邮箱不在 `users` | 40907「还未注册，请宝子前往新用户注册~」 |

    两句话共用一个码（40907）：前端本来也不需要知道是哪一种，显示 message 就完了。
    文案**全部来自 config**，前端零副本（与 QUOTA_EXCEEDED_MESSAGE 同一原则）。

    Spec23 §2.7：register 分支的中间那支（既有 pending 申请）随 register_requests
    表一起删除（表见 §2.2）。于是 register 分支剩下的判据与 login/reset 分支
    **互为镜像**（一边查"在不在"，另一边查"不在不在"），但**不合并**：两句话不一样，
    而且 register 那句要 `.format(username=...)`。
    ⚠️ 这一支删掉是有代价的：Spec22 §2.4 那句"这是'同一邮箱反复提交、你反复收到
    同一份审批邮件'的**唯一**闸门"随表一起失效——现在注册的刹车只剩登录限速
    （§3.3-1，已知并接受）。

    ⚠️ 第一句会**泄露用户名**给任何知道这个邮箱的人——这是用户明确要的文案
    （匿掉用户名会让"去登录、密码忘了就去改密码"这半句失去用处），
    已记入 Spec22 §3.3-3，**知悉并接受**，不要"顺手脱敏"。
    """
    if purpose == "register":
        user = db.get_user_by_email(email)
        if user is not None:
            reason = "registered"
            message = config.EMAIL_CODE_REGISTERED_NOTICE.format(username=user["username"])
        else:
            return
    elif db.get_user_by_email(email) is None:
        reason, message = "unregistered", config.EMAIL_CODE_UNREGISTERED_NOTICE
    else:
        return

    logger.info("发码被查重拒绝", extra={
        "event": "email_code.rejected", "request_id": request_id,
        "purpose": purpose, "reason": reason,
    })
    raise EmailCodeRejectedError(message)


# ---------- 认证 / 用户管理（Spec2 §6）----------

@app.post("/api/auth/login")
async def login(payload: schemas.LoginRequest, request: Request,
                x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    request_id = _request_id(x_request_id)
    ip = auth.client_ip(request)
    username = (payload.username or "").strip()
    password = payload.password or ""

    if auth.is_login_blocked(ip):
        logger.warning("登录过于频繁", extra={
            "event": "auth.login_failed", "request_id": request_id, "username": username,
        })
        raise LoginRateLimitedError()
    if not username or not password:
        raise CredentialsFormatError("用户名和密码不能为空")

    user = db.get_user_by_username(username)
    if user is None or not auth.verify_password(password, user["password_hash"]):
        auth.record_login_failure(ip)
        logger.warning("登录失败", extra={
            "event": "auth.login_failed", "request_id": request_id, "username": username,
        })
        raise LoginFailedError()

    # Spec18 §6.3：限额判定放在密码校验之后（否则任何人都能拿用户名探测账号状态），
    # 放在 reset_login_failures 之前（被拒绝的请求不产生任何"部分成功"的副作用）。
    # 管理员永远走不到这个分支。
    # Spec21 §5.7：阈值与中间件那一处同步改成 `>`（原文是 `>=`）。
    if not user["is_admin"] and user["used"] > user["quota_limit"]:
        logger.warning("服务次数已达上限，拒绝登录", extra={
            "event": "auth.quota_blocked", "request_id": request_id,
            "username": user["username"], "used": user["used"],
            "quota_limit": user["quota_limit"],
        })
        raise QuotaExceededError()

    auth.reset_login_failures(ip)
    token = auth.create_token(user["id"], user["username"])
    logger.info("登录成功", extra={
        "event": "auth.login_success", "request_id": request_id, "username": user["username"],
    })
    return _ok({"token": token, "username": user["username"], "is_admin": user["is_admin"]})


@app.get("/api/auth/me")
async def me(request: Request):
    user = request.state.user
    return _ok({"username": user["username"], "is_admin": user["is_admin"]})


# ---------- 注册申请与审批（Spec19 §6.1~§6.3，前三个公开、后三个管理端）----------

@app.get("/api/auth/register-config")
async def register_config(request: Request):
    """注册弹窗的公开配置（Spec19 §6.1）：是否开放、客服邮箱、收款码地址、两句提示语。

    前端对客服邮箱与提示语**零副本**（与 Spec18 的 QUOTA_EXCEEDED_MESSAGE 同一条原则）。
    **永远返回 200**，即使 enabled=false——前端要读 contact_email 才能显示客服行、
    读 enabled 才知道要不要画注册按钮。

    qr_url 用 _public_base 拼**绝对地址**（与作品/分享图一致），前端直接用，
    不做任何拼接，这样 VITE_API_BASE 的独立部署场景也不用管。

    Spec22 §2.11：**去掉了 `daily_notice`**（「每人每天只能申请一个账号…」那条规则
    已随 IP 冷却一起删除）。留着一个描述不存在规则的字段，就是界面上继续承诺它。
    其余键一个不动——尤其是 qr_url，欠费充值面板还复用着它。

    Spec23 §6.3：**只有最后一个键改名 + 换形状**——`price_notice`(str) 变成
    `price_line`(list)。`qr_url` 保留：`RegisterModal` 不再用它了（注册弹窗里的
    收款码随自助注册一起删了），但**欠费充值面板**（RechargeModal mode="overdue"）
    还在用。`price_line` 是**单片段、无删除线**——那句文案一个字不改（§0 第 3-b 条），
    与 /api/recharge/info 形状一致只为让前端两个模式共用一个渲染分支（§2.8）。
    """
    return _ok({
        "enabled": config.REGISTER_ENABLED,
        "contact_email": config.SUPPORT_EMAIL,
        "qr_url": f"{_public_base(request)}/api/auth/payment-qr",
        "price_line": [dict(seg) for seg in config.REGISTER_PRICE_LINE],
    })


@app.get("/api/auth/payment-qr")
async def payment_qr():
    """收款码图片（Spec19 §6.3）。**公开**：注册弹窗在登录之前，未登录访客必须能扫码。

    收款码本身就是拿来给人扫的，公开不构成新的暴露面（§3.3-6）。
    留在 /api 前缀内（而不是 /payment.jpg）：与分享页那种"故意公开的页面"不同，
    这是一张给弹窗用的静态资源，PUBLIC_AUTH_PATHS 机制本来就能表达"公开"。
    """
    if not config.PAYMENT_QR_PATH.exists():
        # 404 而不是 500：这是"部署时忘了放图"，不是服务坏了（§5.3）。
        # 注册链路的其余部分照常工作——用户可以照常提交申请，线下联系时再收款。
        raise PaymentQrMissingError()
    data = config.PAYMENT_QR_PATH.read_bytes()
    # 收款码不会天天换，弹窗每次打开都重拉一遍没必要
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.post("/api/auth/register")
async def register(payload: schemas.RegisterRequestCreate, request: Request,
                   background_tasks: BackgroundTasks,
                   x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """自助注册（Spec23 §5.4，Spec22 §6.1 的改造版）：**验证码一过直接建号 + 签发 JWT**。

    与旧版（Spec19/22）的区别，按影响面排序：
      1. **不再落申请行**——`db.create_register_request` 换成 `db.create_user`（§2.1）
      2. **响应体从 {id} 变成 {token, username, is_admin}**，与 /api/auth/login 逐字同形（§2.5）
      3. **请求体少一个 wechat**（§0 第 1 条）——连带删掉那一条格式校验
      4. 不再有"审批"这个概念，所以 `auth.register_submitted` 事件改名 `auth.registered`

    校验顺序即契约（顺序变了，用户体验就变了）：格式 → 邮箱已注册 → 验证码 → 用户名占用。
    **删掉的**：原来的"手机号与邮箱至少一项"与"手机号 11 位"（表单里早没电话了）、
    "同 IP 24 小时冷却"（Spec22 删的，40902 退休），以及微信昵称那一条。

    ⚠️ 顺序上有一处刻意：**⑧ 必须排在 ⑨ 之前**（Spec22 §6.1 记过）——查重不泄露
    新东西：发码那条路本来就会把同一句话说给任何知道这个邮箱的人（Spec22 §3.3-3）；
    而对**填错邮箱的正常用户**，这个提示有用得多。

    ⚠️ 函数名从 `register_request` 改成 `register`：旧名字描述的是"提交申请"，
    那个动作没有了。**路由路径 `/api/auth/register` 一个字不变**（PUBLIC_AUTH_PATHS
    里的字符串、前端 chatApi.js、Spec19 的文档全都引用它）。
    """
    request_id = _request_id(x_request_id)
    ip = auth.client_ip(request)

    # ⓪ 限速（Spec22 §2.6）。注册的码校验是四个校验点之一，而限速的完整机制是
    #    **两半**：入口判 42901 + 失败计数。只记不判的话，被限速的人换到这条路由
    #    就能继续猜码——同一个码、同一个 oracle，绕过去只需要换一个 URL。
    _reject_if_rate_limited(ip, request_id, "register")

    # ① 开关
    if not config.REGISTER_ENABLED:
        raise RegisterClosedError()

    # ②~⑥ 格式（每条都有自己的中文 message，所以都在这里判，而不是交给 Pydantic）
    username = (payload.username or "").strip()
    password = payload.password or ""
    email = _norm_email(payload.email)      # Spec22 §2.8：strip + lower 一条规则
    code = (payload.code or "").strip()
    if not 2 <= len(username) <= 32:
        raise RegisterRequestError("用户名需为 2~32 个字符")
    if not auth.MIN_PASSWORD_LEN <= len(password) <= auth.MAX_PASSWORD_LEN:
        raise RegisterRequestError(
            f"密码需为 {auth.MIN_PASSWORD_LEN}~{auth.MAX_PASSWORD_LEN} 位"
        )
    # Spec23 删除：微信昵称那一条（"请填写用于支付的微信昵称"）。表单里已经没有
    #   这个字段了，留着就是一条永远走不到的分支 + 一句指向不存在输入框的报错。
    if not _email_ok(email):
        raise RegisterRequestError("邮箱格式不正确（需包含 @，且 @ 前后都有内容）")
    if not _code_ok(code):
        raise RegisterRequestError("请填写 4 位数字验证码")

    # ⑦ 邮箱已注册（提交时**再查一遍**：从发码到提交隔着几分钟，中间可能有人
    #    先注册了同一个邮箱。Spec23 之后这是**唯一的**邮箱唯一性业务判据，
    #    因为"pending 申请"那道闸门随表消失了——它的分量比 Spec22 时更重）
    existing = db.get_user_by_email(email)
    if existing is not None:
        raise EmailCodeRejectedError(
            config.EMAIL_CODE_REGISTERED_NOTICE.format(username=existing["username"])
        )

    # ⑧ 验证码（注册是一条公开的猜码入口，所以这里的失败**计入登录限速**，Spec22 §2.6）
    _verify_code(request_id, ip, email, "register", code)

    # ⑨ 用户名占用。Spec23 之后这条从"提前告知"变成了**真正的闸门**（§3.3-4）：
    #    旧流程最后还有管理员点同意时撞 UNIQUE 兜底，现在没有那一步了，所以
    #    这里的报错就是用户唯一会看到的东西。仍然只是"查一次库"——并发的原子
    #    保证依旧是 users.username 的 UNIQUE 索引（create_user 里 IntegrityError → 40001）。
    if db.get_user_by_username(username) is not None:
        raise DuplicateUsernameError()

    # ⑩ 建号（限额由 create_user 显式写 _QUOTA_DEFAULT，见 §2.4）
    #    email 走 create_user 的参数——这是 Spec23 之后**唯一**会传 email 的调用方
    #    （管理员手工建号仍不传，落 NULL，那是允许的形态）。
    user = db.create_user(username, auth.hash_password(password), email=email)

    # ⑪ 签发 token（与 /api/auth/login 逐字同款）
    token = auth.create_token(user["id"], user["username"])

    logger.info("新用户已注册", extra={
        "event": "auth.registered", "request_id": request_id,
        "username": username, "user_id": user["id"],
    })

    # Spec20：注册通知邮件。在 return **之前**登记（否则任务不会被登记），
    # 在响应发出**之后**才跑——注册接口的耗时一秒都不涨。
    # Spec23 §2.6：少了 wechat 参数（正文前缀「微信充值账号是…，」随之删除）、
    #    正文重写；仍然**永不抛异常**（Spec20 §2.4）。
    # ⚠️ 参数位置：`background_tasks` 没有默认值，**必须**排在 `request: Request`
    #    之后、`x_request_id`（有默认值）之前——Spec20 §6.1 为这条路由踩过 SyntaxError。
    # created_at 取 `user["created_at"]`（建号那一刻库里存的 UTC ISO），不是"现在"
    #    再算一次——两者差几毫秒，但用返回值是唯一不会漂的来源。
    background_tasks.add_task(
        mailer.send_register_notification,
        username,
        email,
        user["created_at"],
    )

    return _ok({"token": token, "username": user["username"], "is_admin": user["is_admin"]})


# ---------- 邮箱验证码 / 邮箱登录 / 自助改密码 / 入口埋点（Spec22 §6.2 ~ §6.6）----------
# 五条**全部公开**（PUBLIC_AUTH_PATHS，§6.9）：来用它们的人必然还没有 token。
# ⚠️ 中间件对白名单里的路径**不判限额**，所以 login-by-email 必须自己判 40304。

@app.post("/api/auth/email-code")
async def request_email_code(payload: schemas.EmailCodeRequest, request: Request,
                             background_tasks: BackgroundTasks,
                             x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """发一封 4 位验证码到该邮箱（Spec22 §6.2）。**公开**。

    校验顺序即契约：**可预知的服务故障 → 格式 → 频率 → 业务规则**（§6.2）。
    冷却排在查重之前：一个被拒的邮箱反复点「获取验证码」会一直撞 40907，这没问题；
    但顺序反过来的话，连点的人会因为走到哪个分支不同而看到交替的提示。

    **绝不回显 `code`**（任何情况下，§2.2）：它是凭据，只有收件箱里有。
    """
    request_id = _request_id(x_request_id)
    email = _norm_email(payload.email)
    purpose = (payload.purpose or "").strip()

    # ① 未配 SMTP：唯一**可以预知**的失败，在花钱 / 落库之前拦掉（§2.5）。
    #    与 Spec20/21 的"静默降级"立场刻意不同——那两次邮件只是通知（不发不影响
    #    业务），而验证码是业务的前置条件，静默降级在这里的含义是"接口 200、用户傻等"。
    if not config.SMTP_PASSWORD:
        raise EmailServiceUnavailableError()

    # ② 邮箱格式 ③ 场景白名单（不拼接外部输入，本仓的既有做法）
    if not _email_ok(email):
        raise EmailCodeRequestError("邮箱格式不正确（需包含 @，且 @ 前后都有内容）")
    if purpose not in verifications.PURPOSES:
        raise EmailCodeRequestError("未知的验证场景")

    # ④ 同一邮箱 + 同一场景的重发冷却（按 (email, purpose) 隔离：给"注册"发的码
    #    与给"登录"发的码是两个独立的窗口，互不影响，§2.2）
    if db.find_recent_email_verification(
            email, purpose, config.EMAIL_CODE_RESEND_SECONDS) is not None:
        logger.info("发码被冷却拒绝", extra={
            "event": "email_code.rate_limited", "request_id": request_id,
            "purpose": purpose,
        })
        raise EmailCodeRateLimitedError()

    # ⑤ 查重（§2.4 的表）
    _reject_duplicate_email(email, purpose, request_id)

    # ⑥ 生成 + 落库 ⑦ 发信入队 ⑧ 回 {"sent": true}
    code = verifications.generate_code()
    db.create_email_verification(email, purpose, code, config.EMAIL_CODE_TTL_SECONDS)
    logger.info("验证码已生成", extra={
        "event": "email_code.requested", "request_id": request_id,
        "purpose": purpose,
    })
    # 与 Spec20 §2.1 同款：任务在 return **之前**登记（否则不会被登记），
    # 在响应发出**之后**才跑——用户不等那一次 SMTP 往返（黑洞地址时是 10 秒）。
    background_tasks.add_task(mailer.send_email_code, email, code, purpose)
    return _ok({"sent": True})


@app.post("/api/auth/verify-email-code")
async def verify_email_code(payload: schemas.EmailCodeVerifyRequest, request: Request,
                            x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """只回答"这个码现在对不对"（Spec22 §6.3）。**公开**。

    供「修改密码」展开密码栏之前用（§2.7）；登录与注册**不用**它——它们各自在
    自己的提交里校验。
    ⚠️ 这个接口**不消费验证码**：它只是一次问答，真正的授权发生在
    `reset-password` 的那次**重新校验**上（前端状态不可信）。
    """
    request_id = _request_id(x_request_id)
    ip = auth.client_ip(request)
    email = _norm_email(payload.email)
    purpose = (payload.purpose or "").strip()
    code = (payload.code or "").strip()

    _reject_if_rate_limited(ip, request_id, purpose)
    if not _email_ok(email):
        raise EmailCodeRequestError("邮箱格式不正确（需包含 @，且 @ 前后都有内容）")
    if purpose not in verifications.PURPOSES:
        raise EmailCodeRequestError("未知的验证场景")
    if not _code_ok(code):
        raise EmailCodeRequestError("请填写 4 位数字验证码")

    _verify_code(request_id, ip, email, purpose, code)
    auth.reset_login_failures(ip)
    return _ok({"verified": True})


@app.post("/api/auth/login-by-email")
async def login_by_email(payload: schemas.EmailLoginRequest, request: Request,
                         x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """邮箱验证码登录（Spec22 §6.4）。**公开**，响应与 `POST /api/auth/login` 完全同形。

    ⚠️ **本路由在白名单里，中间件不为它判限额**，所以下面那次 40304 判定必须自己写。
    这是本 Spec 最容易漏的一处安全缺口：漏了它，一个已经欠费被拦的用户只要改用
    邮箱登录就能绕过去（§6.4）。判据与登录路由**逐字相同**（`used > quota_limit`，
    Spec21 §5.7 的 `>`）——四处副本，一处都不能漏。

    校验顺序与 §5.7 B 的流程图一致：限速 → 格式 → 邮箱在不在 → 码 → 限额 → 发 token。
    """
    request_id = _request_id(x_request_id)
    ip = auth.client_ip(request)
    email = _norm_email(payload.email)
    code = (payload.code or "").strip()

    _reject_if_rate_limited(ip, request_id, "login")
    if not _email_ok(email):
        raise EmailCodeRequestError("邮箱格式不正确（需包含 @，且 @ 前后都有内容）")
    if not _code_ok(code):
        raise EmailCodeRequestError("请填写 4 位数字验证码")

    # 「还未注册」这句在**这里**也要给一次：这条路不先发码也能到达（§6.4）。
    # 管理员手工建的号没有邮箱，所以它永远走不到这里——那条路本来就不该有人走。
    user = db.get_user_by_email(email)
    if user is None:
        logger.info("邮箱登录被拒：该邮箱未注册", extra={
            "event": "email_code.rejected", "request_id": request_id,
            "purpose": "login", "reason": "unregistered",
        })
        raise EmailCodeRejectedError(config.EMAIL_CODE_UNREGISTERED_NOTICE)

    _verify_code(request_id, ip, email, "login", code)

    # 限额判定（照登录路由：管理员永远走不到这个分支）。放在码校验**之后**——
    # 否则任何人都能拿邮箱探测账号状态；放在 reset_login_failures **之前**——
    # 被拒绝的请求不产生任何"部分成功"的副作用。
    if not user["is_admin"] and user["used"] > user["quota_limit"]:
        logger.warning("服务次数已达上限，拒绝邮箱登录", extra={
            "event": "auth.quota_blocked", "request_id": request_id,
            "username": user["username"], "used": user["used"],
            "quota_limit": user["quota_limit"],
        })
        raise QuotaExceededError()

    auth.reset_login_failures(ip)
    token = auth.create_token(user["id"], user["username"])
    logger.info("邮箱登录成功", extra={
        "event": "auth.email_login", "request_id": request_id,
        "username": user["username"],       # **不带 email**（PII，§10.2）
    })
    return _ok({"token": token, "username": user["username"], "is_admin": user["is_admin"]})


@app.post("/api/auth/reset-password")
async def reset_password(payload: schemas.ResetPasswordRequest, request: Request,
                         x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """用邮箱验证码自助改密码（Spec22 §6.5）。**公开**：忘了密码的人没有 token。

    **不需要旧密码**——用户已经用邮箱证明了自己（§2.7）。
    **不吊销任何 token**：本仓从 Spec2 起就没有 token 黑名单（JWT 无状态、7 天有效），
    所以"改了密码别人就进不来了"是**错的**，这是真实的边界（§3.3-4）。

    码在这里**再校验一次**：前端"展开密码栏"只是 UI，服务端唯一能信的是提交那一刻
    （§2.7）。返回 username 供前端预填登录框。
    """
    request_id = _request_id(x_request_id)
    ip = auth.client_ip(request)
    email = _norm_email(payload.email)
    code = (payload.code or "").strip()
    password = payload.password or ""

    _reject_if_rate_limited(ip, request_id, "reset")
    if not _email_ok(email):
        raise EmailCodeRequestError("邮箱格式不正确（需包含 @，且 @ 前后都有内容）")
    if not _code_ok(code):
        raise EmailCodeRequestError("请填写 4 位数字验证码")
    if not auth.MIN_PASSWORD_LEN <= len(password) <= auth.MAX_PASSWORD_LEN:
        # 40018 是 RegisterRequestError 的码，这里**复用**它——§6.5 与 §9 的表格
        # 都点名了 40018（与 42901 被复用到"验证码猜错"上是同一种复用）。
        raise RegisterRequestError(
            f"密码需为 {auth.MIN_PASSWORD_LEN}~{auth.MAX_PASSWORD_LEN} 位"
        )

    user = db.get_user_by_email(email)
    if user is None:
        raise EmailCodeRejectedError(config.EMAIL_CODE_UNREGISTERED_NOTICE)

    _verify_code(request_id, ip, email, "reset", code)

    db.update_password(user["id"], auth.hash_password(password))
    auth.reset_login_failures(ip)
    logger.info("自助修改密码成功", extra={
        "event": "auth.password_reset", "request_id": request_id,
        "username": user["username"],       # **不带 email**（PII，§10.2）
    })
    return _ok({"username": user["username"]})


@app.post("/api/click")
async def record_click(payload: schemas.ClickEventRequest, request: Request,
                       x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """入口点击埋点（Spec22 §6.6）。**公开**——「打开登录页」发生时用户还没有 token。

    幂等：同 IP 同事件重复上报返回同样的 200，库里不新增行（`UNIQUE(event, ip)`
    + `INSERT OR IGNORE`），前端不需要区分。响应**不回传计数**——前端不需要，
    也没有"实时计数"这个需求。

    IP **只落库、只参与 COUNT**：响应里只有 `{"ok": true}`，日志里也没有 IP
    （Spec19 §10 的规矩）。面板展示的是"数量"，不是"名单"（§3.3-5）。
    """
    request_id = _request_id(x_request_id)
    event = (payload.event or "").strip()
    if event not in db._CLICK_EVENTS:
        # **不静默忽略**：只有我们自己的前端会调它，收到未知事件名说明代码写错了，
        # 静默会让这个错误永远不被发现（§2.9）。
        raise ClickEventError()

    if db.record_click(event, auth.client_ip(request)):
        # 只在**新增了一个不重复 IP** 时打一行：重复点击不打，所以日志本身
        # 就等于一份增量报表（每个 IP 每个事件最多一行，量不可能爆）。
        logger.info("记录一个入口点击", extra={
            "event": "click.recorded", "request_id": request_id,
            "click_event": event,       # **不叫 event**：那是每行日志的事件名（§5.3）
        })
    return _ok({"ok": True})


# ---------- 余额与充值（Spec21 §6.1 ~ §6.3）----------

@app.post("/api/auth/recharge-request")
async def overdue_recharge_request(payload: schemas.RechargeOverdueCreate, request: Request,
                                   background_tasks: BackgroundTasks,
                                   x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """欠费充值申请（Spec21 §6.3）：**公开**，无登录态。

    用户此刻正被 40304 拦在登录页上，手里没有 token。收款码本身已经是公开的
    （Spec19 §3.3-6），这条路由的暴露面与它同级——它**只能产生一条待审批记录**，
    不能给任何人加额度。**不校验密码**（已确认）：代价见 §3.3-2，上限是"你的欠费
    账号数"（幂等保证每个账号最多一条 pending），不是攻击者的资源数。

    校验顺序即契约（与 Spec19 §6.2 同一个写法）：账号 → 昵称 → 账号存在 → 确实欠费 → 幂等。
    """
    request_id = _request_id(x_request_id)
    username = (payload.username or "").strip()
    wechat = (payload.wechat or "").strip()

    if not username:
        raise RechargeRequestError("请填写账号")
    if not wechat or len(wechat) > config.RECHARGE_WECHAT_MAX:
        raise RechargeRequestError("请填写用于支付的微信昵称")

    user = db.get_user_by_username(username)
    if user is None:
        raise RechargeRequestError("账号不存在")
    # "确实已超额"用的就是 §5.7 那个阈值（第 5 处使用，但它是新增代码，不在
    # "改动既有副本"的清单里）。管理员不受限额，没有"欠费"这回事。
    if user["is_admin"] or user["used"] <= user["quota_limit"]:
        raise RechargeAlreadyReviewedError("当前账号无需充值")

    # 频次限制（比幂等更靠前，见 §6.2 同款注释）。**公开端点上的已知代价**：
    # 谁都能替一个欠费账号提交，从而把这个账号的冷却期一直续上——上限是"拖延他
    # 3 分钟"，加额度仍然只发生在管理员点「同意」那一刻，与 §3.3-2 的取舍同级。
    recent = db.find_recent_recharge_by_user(user["id"], config.RECHARGE_COOLDOWN_SECONDS)
    if recent is not None:
        logger.info("欠费充值申请过于频繁（冷却期内）", extra={
            "event": "recharge.rate_limited", "request_id": request_id,
            "username": user["username"], "recharge_id": recent["id"],
            "recharge_source": "overdue",
        })
        raise RechargeRateLimitedError()

    existing = db.find_pending_recharge(user["id"])
    if existing is not None:
        logger.info("欠费充值申请重复提交（幂等命中）", extra={
            "event": "recharge.submitted_duplicate", "request_id": request_id,
            "username": user["username"], "recharge_id": existing["id"],
            "recharge_source": "overdue",
        })
        return _ok({"id": existing["id"]})

    record = db.create_recharge_request(user["id"], user["username"], wechat, "overdue")
    logger.info("收到欠费充值申请", extra={
        "event": "recharge.submitted", "request_id": request_id,
        "username": user["username"], "recharge_id": record["id"],
        "recharge_source": "overdue",
    })
    # 联系方式恒为邮箱（Spec22 §5.1：电话三列已删，没有可回落的东西了）。
    # `or "未填写"` 是纯防御：管理员手工建的号没有邮箱（§2.1），那是**允许的形态**。
    background_tasks.add_task(
        mailer.send_recharge_notification,
        user["username"], user["email"] or "未填写",
        wechat, record["created_at"], True,
    )
    return _ok({"id": record["id"]})


@app.get("/api/recharge/info")
async def get_recharge_info(request: Request):
    """余额与充值弹窗的配置（Spec21 §6.1）：余额 + 收款码地址 + 参考价备注。

    **余额由后端算**：前端根本拿不到 quota_limit / used（/api/auth/me 只返回
    username/is_admin），而且这与"文案唯一来源在后端"是同一条原则（§2.9）。
    公式照用户原话：`(quota_limit - used) / 10` 元，保留 1 位小数。
    **负数照原样显示**——超额用户欠你 1 次，抹成 0 是撒谎。

    qr_url 用 _public_base 拼**绝对地址**（与 register-config 完全同款），
    前端直接塞进 <img src>，不做任何拼接。

    管理员照常拿到数字（前端不画入口，§2.9）——少一个分支，也少一个
    "接口和按钮不一致"的坑。
    收款码文件缺失时本接口**不报错**：它只返回 URL，裂图由 payment_qr 的 40410 决定。

    Spec23 §6.4：**同样只有最后一个键改名 + 换形状**——`price_notice`(str) 变成
    `price_line`(list)，`balance` / `quota_limit` / `used` / `qr_url` 一字不变。
    这份片段数组里有一个 `strike=True` 的片段（"6.99"，划掉的原价）——那个删除线
    落在**句子中间**（"0.9"紧前面），一整串字符串表达不了那个位置（§2.8）。
    ⚠️ `strike` 键**只在需要划线时出现**（其它片段不带这个键，不是 false），
    前端用真值判断即可（§14 陷阱 11）。
    """
    user = request.state.user
    record = db.get_user_by_id(user["id"])      # 登录态里没有 quota/used，回读库
    return _ok({
        "balance": round((record["quota_limit"] - record["used"]) / 10, 1),
        "quota_limit": record["quota_limit"],
        "used": record["used"],
        "qr_url": f"{_public_base(request)}/api/auth/payment-qr",
        "price_line": [dict(seg) for seg in config.RECHARGE_PRICE_LINE],
    })


@app.post("/api/recharge/requests")
async def submit_recharge(payload: schemas.RechargeRequestCreate, request: Request,
                          background_tasks: BackgroundTasks,
                          x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """系统内主动充值（Spec21 §6.2）：普通用户点顶部「余额与充值」后提交。

    身份取自 token（`request.state.user["id"]`），**不接受客户端传 username**。
    source 恒为 "user"（另一条入口是公开的 /api/auth/recharge-request，"overdue"）。

    幂等（§2.4）：同一用户已有 pending → **不落库、不发信**，照常返回那条的 id。
    这是"我已经点过了"的正常行为，不是攻击；前端也**不区分**（成功面板永远一句话）。

    **频次限制**（用户后来加的）排在幂等**之前**：不然连点两下会被幂等那条静静接住、
    200 返回同一个 id，用户看不到任何反馈——而这正是他连点时要问的事（"我到底提交上没有"）。
    冷却期一过，幂等照旧生效，两条规则各管一段，不打架。
    """
    request_id = _request_id(x_request_id)
    user_id = request.state.user["id"]
    wechat = (payload.wechat or "").strip()
    if not wechat or len(wechat) > config.RECHARGE_WECHAT_MAX:
        raise RechargeRequestError("请填写用于支付的微信昵称")

    recent = db.find_recent_recharge_by_user(user_id, config.RECHARGE_COOLDOWN_SECONDS)
    if recent is not None:
        logger.info("充值申请过于频繁（冷却期内）", extra={
            "event": "recharge.rate_limited", "request_id": request_id,
            "username": request.state.user["username"],
            "recharge_id": recent["id"], "recharge_source": "user",
        })
        raise RechargeRateLimitedError()

    existing = db.find_pending_recharge(user_id)
    if existing is not None:
        logger.info("充值申请重复提交（幂等命中）", extra={
            "event": "recharge.submitted_duplicate", "request_id": request_id,
            "username": request.state.user["username"],
            "recharge_id": existing["id"], "recharge_source": "user",
        })
        return _ok({"id": existing["id"]})

    # 回读库拿 email：登录态里只有 id/username/is_admin（§2.7）
    user = db.get_user_by_id(user_id)
    record = db.create_recharge_request(user_id, user["username"], wechat, "user")
    logger.info("收到充值申请", extra={
        "event": "recharge.submitted", "request_id": request_id,
        "username": user["username"], "recharge_id": record["id"],
        "recharge_source": "user",
    })
    # 联系方式恒为邮箱（Spec22 §5.1）——见上面 overdue 那条的同款注释。
    background_tasks.add_task(
        mailer.send_recharge_notification,
        user["username"], user["email"] or "未填写",
        wechat, record["created_at"], False,
    )
    return _ok({"id": record["id"]})


@app.post("/api/admin/users")
async def admin_create_user(payload: schemas.AdminCreateUserRequest, request: Request,
                            x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    request_id = _request_id(x_request_id)
    operator = request.state.user
    username = (payload.username or "").strip()
    password = payload.password or ""
    if len(username) < 2:
        raise CredentialsFormatError("用户名至少 2 个字符")
    # Spec22 §2.10：下限从写死的 6 降成 auth.MIN_PASSWORD_LEN。设定密码的路一共
    # 三条（注册 / 建号 / 重置），**同一份规则**——别在这里再写一个 6。
    if not auth.MIN_PASSWORD_LEN <= len(password) <= auth.MAX_PASSWORD_LEN:
        raise CredentialsFormatError(
            f"密码至少 {auth.MIN_PASSWORD_LEN} 位")
    user = db.create_user(username, auth.hash_password(password), is_admin=False)
    logger.info("创建账号", extra={
        "event": "auth.admin.create_user", "request_id": request_id,
        "username": operator["username"], "target_user": user["username"],
    })
    return _ok({"id": user["id"], "username": user["username"], "is_admin": user["is_admin"]})


@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    """用户列表（Spec18 §6.1）：每项带 quota_limit / used / email，**不含** password_hash。

    Spec22 §5.1：`phone` 键随列一起消失。`email` 是**唯一**的联系方式，也是本接口
    唯一带出的 PII（仅管理员可见，`_row_to_dict` 的 docstring 记了这条约定）。

    不返回"是否超额"这个派生布尔——前端用 `!u.is_admin && u.used > u.quota_limit`
    现算，超额的判据只有一处，复制到接口层就多了一个会漂移的副本。
    （Spec21 §5.7：阈值由 `>=` 改成 `>`，四处副本见 §5.7。）

    Spec21 §5.2：额外带一个 `created_at_beijing`。**不覆盖 `created_at`**——UTC ISO
    仍是它本来的值（排序 / 排障 / 将来别的消费者都用得上），展示串是"多出来的一个键"。
    前端转时区会给出**浏览器所在时区**，而用户要的是"北京时间"这个绝对量，
    于是它不该取决于谁在看（§2.2）。
    """
    items = db.list_users()
    for u in items:
        u["created_at_beijing"] = timefmt.beijing_time_text(u["created_at"])
    return _ok(items)


@app.put("/api/admin/users/{user_id}/quota")
async def admin_set_quota(user_id: int, payload: schemas.AdminSetQuotaRequest,
                          request: Request,
                          x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """设置某用户的累计服务限额（Spec18 §6.2）。**仅管理员**（/api/admin/* 前缀，中间件保证）。

    0 是合法取值：等于禁止该用户使用任何服务（新建即锁）；负数非法。
    允许对管理员设置（返回值照常），只是判定时被 is_admin 豁免——这样"设为/撤销
    管理员"与"改限额"两个动作正交。
    """
    request_id = _request_id(x_request_id)
    operator = request.state.user
    if payload.quota_limit < 0 or payload.quota_limit > config.QUOTA_LIMIT_MAX:
        raise QuotaLimitError()
    target = db.set_user_quota(user_id, payload.quota_limit)
    if target is None:
        raise UserNotFoundError("用户不存在")
    logger.info("设置服务限额", extra={
        "event": "auth.admin.set_quota", "request_id": request_id,
        "username": operator["username"], "target_user": target["username"],
        "quota_limit": payload.quota_limit,
    })
    # 回带 used：前端不必再拉一次整表就能就地更新那一行
    return _ok({"id": target["id"], "quota_limit": target["quota_limit"],
                "used": target["used"]})


@app.put("/api/admin/users/{user_id}/password")
async def admin_reset_password(user_id: int, payload: schemas.AdminResetPasswordRequest,
                               request: Request,
                               x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    request_id = _request_id(x_request_id)
    operator = request.state.user
    password = payload.password or ""
    # Spec22 §2.10：与建号那处同一套常量（三处副本一次收口）。
    if not auth.MIN_PASSWORD_LEN <= len(password) <= auth.MAX_PASSWORD_LEN:
        raise CredentialsFormatError(
            f"密码至少 {auth.MIN_PASSWORD_LEN} 位")
    if db.get_user_by_id(user_id) is None:
        raise UserNotFoundError("用户不存在")
    db.update_password(user_id, auth.hash_password(password))
    logger.info("重置密码", extra={
        "event": "auth.admin.reset_password", "request_id": request_id,
        "username": operator["username"], "target_user": str(user_id),
    })
    return _ok({"id": user_id})


@app.put("/api/admin/users/{user_id}/admin")
async def admin_set_admin(user_id: int, payload: schemas.AdminSetAdminRequest,
                          request: Request,
                          x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    request_id = _request_id(x_request_id)
    operator = request.state.user
    target = db.get_user_by_id(user_id)
    if target is None:
        raise UserNotFoundError("用户不存在")
    db.set_admin(user_id, payload.is_admin)
    logger.info("设置/撤销管理员", extra={
        "event": "auth.admin.toggle_admin", "request_id": request_id,
        "username": operator["username"], "target_user": target["username"],
        "is_admin": payload.is_admin,
    })
    return _ok({"id": user_id})


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, request: Request,
                            x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    request_id = _request_id(x_request_id)
    operator = request.state.user
    target = db.get_user_by_id(user_id)
    if target is None:
        raise UserNotFoundError("用户不存在")
    if user_id == operator["id"]:
        raise BadRequestError("不能删除自己")
    if target["is_admin"] and db.count_admins() <= 1:
        raise BadRequestError("不能删除最后一个管理员")
    # 级联删除作品与社区帖子：gallery/ 与 community/ 物理文件 + 记录（Spec5 §3 / Spec9 §3.1），
    # 随后 db 侧清 usage/images/社区/反馈/分享/建议/users
    gallery.delete_user_gallery(user_id)
    community.delete_user_posts(user_id)
    db.delete_user(user_id)
    logger.info("删除账号", extra={
        "event": "auth.admin.delete_user", "request_id": request_id,
        "username": operator["username"], "target_user": target["username"],
    })
    return _ok({"id": user_id})


# ---------- 充值审批（Spec21 §6.5，仅管理员）----------

@app.get("/api/admin/recharge-requests")
async def admin_list_recharge_requests(request: Request):
    """充值台账（Spec21 §6.5）：pending 优先，组内 id 倒序（最新在前）。

    每项额外带 `created_at_beijing`；`reviewed_at` 非 None 时再带
    `reviewed_at_beijing`（为 None 时**不加这个键**，前端 v-if 判空）。
    不含 ip —— 本表根本没有这一列（防刷靠幂等而不是冷却，§2.3）。
    """
    items = db.list_recharge_requests()
    for c in items:
        c["created_at_beijing"] = timefmt.beijing_time_text(c["created_at"])
        if c["reviewed_at"] is not None:
            c["reviewed_at_beijing"] = timefmt.beijing_time_text(c["reviewed_at"])
    return _ok(items)


@app.post("/api/admin/recharge-requests/{request_id}/approve")
async def admin_approve_recharge(request_id: int, payload: schemas.RechargeApproveRequest,
                                 request: Request,
                                 background_tasks: BackgroundTasks,
                                 x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """同意充值申请（Spec21 §6.5）：**同一事务**内置 approved + 记 amount + 加额度。

    加多少次由管理员当次给定（与 Spec19 §6.5 同一个理由：弹窗上写着「0.9 元约 10 次」，
    但**实收金额是你在微信里看到的**，只有你知道；写死 +10 会在有人付了 2 元时
    变成一个改不了的错）。下界是 1：加 0 次是一次无意义的点击，几乎必然是手滑。
    上界复用 QuotaLimitError（40017）——超上限的后果与「改限额」超上限完全一样。

    校验顺序见 §6.5（amount → 记录存在 → 仍 pending → 目标用户还在 → 上界 → 事务）。
    目标用户已被删除时**预检**：让 UPDATE users 影响 0 行然后静默提交，会留下
    "记录显示已批准、钱没到账"的挂账（§2.5）。

    Spec22 §2.12：按下去之后**多一封信**——发给**该用户本人**的到账通知，
    `source` 决定是哪一封（`user` → 「充值已到账」/ `overdue` → 「账号已恢复」）。
    请求体 / 响应体 / 状态码 / 错误码 / 事务语义 / 日志事件**全部不变**。
    ⚠️ `background_tasks` 的插入位置理由见 admin_approve_register 的 docstring。
    """
    rid = _request_id(x_request_id)
    operator = request.state.user
    if payload.amount < 1:
        raise QuotaLimitError("充值次数需为不小于 1 的整数")
    record = db.get_recharge_request(request_id)
    if record is None:
        raise RechargeNotFoundError()
    if record["status"] != "pending":
        # 不能静默改成 rejected——那是在替管理员做决定
        raise RechargeAlreadyReviewedError()
    target = db.get_user_by_id(record["user_id"])
    if target is None:
        raise UserNotFoundError("用户已被删除，无法充值")
    if target["quota_limit"] + payload.amount > config.QUOTA_LIMIT_MAX:
        raise QuotaLimitError()
    user = db.approve_recharge_request(request_id, payload.amount)
    if user is None:                      # 并发抢跑：事务已整体回滚，额度没加
        raise RechargeAlreadyReviewedError()
    logger.info("同意充值申请", extra={
        "event": "recharge.reviewed", "request_id": rid,
        "recharge_id": request_id, "operator": operator["username"],
        "target_user": user["username"], "decision": "approved",
        "amount": payload.amount,
    })
    # Spec22 §5.7 D：通知用户本人。`target` 是上面那次 40402 预检取到的行，
    # **不用再查一遍库**；overdue 直接由 record["source"] 推出（这正是那一列的意义，
    # §2.12）——**不新增请求字段**。没有邮箱（管理员手工建的号）交给 mailer 判空跳过
    # + reason=no_email，**额度照加**。
    background_tasks.add_task(
        mailer.send_recharge_approved_notification,
        user["username"], target["email"] or "", record["created_at"],
        record["source"] == "overdue",
        request_id,      # 同上：§5.6 的草图漏了，§10/§13 用例 18 要它
    )
    # 回带 used：前端不必再拉一次整表就能就地更新那一行（与 admin_set_quota 同款）
    return _ok({"id": user["id"], "username": user["username"],
                "quota_limit": user["quota_limit"], "used": user["used"]})


@app.post("/api/admin/recharge-requests/{request_id}/reject")
async def admin_reject_recharge(request_id: int, request: Request,
                                x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """拒绝充值申请（Spec21 §6.5）：只改状态，**不加额度、不删记录**。

    amount 保持 NULL（从未批准过，也就没有"加了多少"这回事）。
    """
    rid = _request_id(x_request_id)
    operator = request.state.user
    record = db.get_recharge_request(request_id)
    if record is None:
        raise RechargeNotFoundError()
    if db.reject_recharge_request(request_id) is None:
        raise RechargeAlreadyReviewedError()
    logger.info("拒绝充值申请", extra={
        "event": "recharge.reviewed", "request_id": rid,
        "recharge_id": request_id, "operator": operator["username"],
        "target_user": record["username"], "decision": "rejected",
    })
    return _ok({"id": request_id})


@app.delete("/api/admin/recharge-requests/{request_id}")
async def admin_delete_recharge(request_id: int, request: Request,
                                x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """删除一条充值记录（Spec21 §6.5，任意状态都能删）。

    **不触碰 users**（§2.6）：删除一条**已同意**的记录**不会**把加过的额度收回来
    ——那要走「改限额」（PUT /api/admin/users/{id}/quota），那条路是幂等的绝对值设置，
    比"反向加负数"安全得多。这个副作用写在确认文案里（§7.3）。
    """
    rid = _request_id(x_request_id)
    operator = request.state.user
    record = db.get_recharge_request(request_id)
    if record is None:
        raise RechargeNotFoundError()
    db.delete_recharge_request(request_id)
    logger.info("删除充值记录", extra={
        "event": "recharge.deleted", "request_id": rid,
        "recharge_id": request_id, "operator": operator["username"],
        "target_user": record["username"], "was_status": record["status"],
    })
    return _ok({"id": request_id})


@app.post("/api/admin/clicks/clear")
async def admin_clear_clicks(request: Request,
                             x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """清空入口点击统计（Spec22 §6.7，仅管理员——中间件保证）。

    与 Spec18 的「清空调用统计」同款：**只重置统计区间**，不动任何计费口径
    （点击本来就不计费）。`db.clear_clicks()` 在一个事务里删行 + 写
    `app_meta.clicks_cleared_at`——清零与"上次清零时间"必须同生同死。
    """
    request_id = _request_id(x_request_id)
    cleared = db.clear_clicks()
    logger.info("清空入口点击统计", extra={
        "event": "click.cleared", "request_id": request_id,
        "operator": request.state.user["username"], "affected": cleared,
    })
    return _ok({"cleared": cleared})


@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    """4 类调用聚合统计 + AI 服务反馈汇总 + 入口点击 + 三个清零时间（只读；限管理员）。

    Spec11：额外返回 usage_cleared_at / feedback_cleared_at（null | UTC ISO），
    供前端展示各统计块"上次清零"的时间起点。
    Spec22 §6.8：再多一个 clicks_cleared_at（`get_cleared_times()` 已经带上它，
    下面那句 `stats.update(...)` **一个字都不用改**）与一组 clicks。
    """
    stats = db.get_usage_stats()
    stats["feedback_totals"] = db.get_feedback_totals()
    stats["clicks"] = db.get_click_stats()
    stats.update(db.get_cleared_times())
    return _ok(stats)


# ---------- 静态托管 ----------

app.mount("/images", StaticFiles(directory=config.STORAGE_DIR), name="images")

if (config.STATIC_DIR / "index.html").exists():
    # 后端直接托管前端 dist（本地演示 / 单端口部署）
    app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
