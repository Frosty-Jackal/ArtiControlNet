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

from fastapi import FastAPI, File, Form, Header, Request, UploadFile
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
import media
import schemas
import shares
import wiki
from agents.supervisor import run_supervisor
from errors import (AppError, AuthTokenError, BadRequestError,
                    CommentContentError, CredentialsFormatError,
                    DuplicateUsernameError, FeedbackParamError, FileMissingError,
                    ForbiddenError,
                    GalleryItemNotFoundError, LoginFailedError,
                    LoginRateLimitedError, NotFoundError, PaymentQrMissingError,
                    PostContentError, PostNotFoundError, QuotaExceededError,
                    QuotaLimitError, RegisterAlreadyReviewedError,
                    RegisterClosedError, RegisterRateLimitedError,
                    RegisterRequestError, RegisterRequestNotFoundError,
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

# 放行列表：除登录与注册链路的三个公开接口外，所有 /api 接口都需登录态（Spec19 §6.8）。
# 这四个是**精确匹配**（`path not in PUBLIC_AUTH_PATHS`），不是前缀匹配——
# 新增路径时必须原样写全，别写成 /api/auth/register 就以为能覆盖 -config。
PUBLIC_AUTH_PATHS = {
    "/api/auth/login",
    "/api/auth/register",        # Spec19：提交注册申请（无登录态）
    "/api/auth/register-config", # Spec19：注册弹窗的公开配置
    "/api/auth/payment-qr",      # Spec19：收款码图片
}


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
        if not user["is_admin"] and user["used"] >= user["quota_limit"]:
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
    if not user["is_admin"] and user["used"] >= user["quota_limit"]:
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
    """
    return _ok({
        "enabled": config.REGISTER_ENABLED,
        "contact_email": config.SUPPORT_EMAIL,
        "qr_url": f"{_public_base(request)}/api/auth/payment-qr",
        "price_notice": config.REGISTER_PRICE_NOTICE,
        "daily_notice": config.REGISTER_DAILY_NOTICE,
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
async def register_request(payload: schemas.RegisterRequestCreate, request: Request,
                           x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """提交注册申请（Spec19 §6.2）：**落一条申请，不创建任何用户**。

    校验顺序即契约（顺序变了，用户体验就变了）：格式 → 用户名占用 → IP 冷却。
    格式全部排在冷却之前，否则一个手滑把手机号打成 10 位的用户会被直接锁 24 小时。
    bcrypt 排在最后：它是故意慢的（约 100 ms 量级），没有理由在一条注定要被拒的
    请求上做它。
    """
    request_id = _request_id(x_request_id)

    # ① 开关
    if not config.REGISTER_ENABLED:
        raise RegisterClosedError()

    # ②~⑦ 格式（每条都有自己的中文 message，所以都在这里判，而不是交给 Pydantic）
    username = (payload.username or "").strip()
    password = payload.password or ""
    wechat = (payload.wechat or "").strip()
    phone = (payload.phone or "").strip()
    email = (payload.email or "").strip()
    if not 2 <= len(username) <= 32:
        raise RegisterRequestError("用户名需为 2~32 个字符")
    if not 6 <= len(password) <= 72:
        raise RegisterRequestError("密码需为 6~72 位")
    if not wechat or len(wechat) > 64:
        raise RegisterRequestError("请填写用于支付的微信昵称")
    if not phone and not email:
        raise RegisterRequestError("手机号与邮箱请至少填写一项")
    if phone and (not phone.isdigit() or len(phone) != 11):
        raise RegisterRequestError("手机号需为 11 位数字")
    if email and ("@" not in email or not email.split("@")[0]
                  or not email.split("@")[-1] or len(email) > 128):
        raise RegisterRequestError("邮箱格式不正确（需包含 @，且 @ 前后都有内容）")

    # ⑧ 用户名占用（**只是提前告知**：真正的唯一性约束仍是 users.username 的
    #    UNIQUE 索引，在管理员点同意那一刻兜底，见 §3.3-2）
    if db.get_user_by_username(username) is not None:
        raise DuplicateUsernameError()

    # ⑨ 同 IP 24 小时冷却（滚动窗口，判据见 §2.2）
    ip = auth.client_ip(request)
    if db.find_recent_register_by_ip(ip, config.REGISTER_IP_WINDOW_SECONDS) is not None:
        # 日志里**不记 IP**——它已经存在库里（判重必需），再往日志里抄一份只是
        # 让排障截图变成一次额外的信息泄露（§10）。
        logger.warning("注册申请被冷却拒绝", extra={
            "event": "auth.register_blocked", "request_id": request_id,
            "username": username,
        })
        raise RegisterRateLimitedError()

    # ⑩ 落库（密码在提交时就 bcrypt，库里全程没有明文）
    record = db.create_register_request(
        username, auth.hash_password(password),
        phone or None, email or None,   # 空串存 NULL："没填"只有一种表示
        wechat, ip,
    )
    logger.info("收到注册申请", extra={
        "event": "auth.register_submitted", "request_id": request_id,
        "register_id": record["id"], "username": username,
        "has_phone": bool(phone), "has_email": bool(email),
    })
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
    if len(password) < 6:
        raise CredentialsFormatError("密码至少 6 位")
    user = db.create_user(username, auth.hash_password(password), is_admin=False)
    logger.info("创建账号", extra={
        "event": "auth.admin.create_user", "request_id": request_id,
        "username": operator["username"], "target_user": user["username"],
    })
    return _ok({"id": user["id"], "username": user["username"], "is_admin": user["is_admin"]})


@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    """用户列表（Spec18 §6.1）：每项带 quota_limit / used，**不含** password_hash。

    不返回"是否超额"这个派生布尔——前端用 `!u.is_admin && u.used >= u.quota_limit`
    现算，超额的判据只有一处，复制到接口层就多了一个会漂移的副本。
    """
    return _ok(db.list_users())


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
    if len(password) < 6:
        raise CredentialsFormatError("密码至少 6 位")
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


# ---------- 注册申请审批（Spec19 §6.4~§6.7，仅管理员）----------

@app.get("/api/admin/register-requests")
async def admin_list_register_requests(request: Request):
    """注册申请台账（Spec19 §6.4）：pending 优先，组内 id 倒序（最新在前）。

    **不含** password_hash（_register_row_to_dict 的默认行为，结构性保证），
    **不含** ip（它只服务于冷却期判定，对"批准谁"这个决策没有帮助）。
    无分页、无筛选：量级由 IP 冷却天然限制（每台设备每天最多 1 条）。
    """
    return _ok(db.list_register_requests())


@app.post("/api/admin/register-requests/{request_id}/approve")
async def admin_approve_register(request_id: int, payload: schemas.RegisterApproveRequest,
                                 request: Request,
                                 x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """同意注册申请（Spec19 §6.5）：**同一事务**内建号 + 改状态 + 置空哈希。

    限额必须由管理员当次给定（0 ~ QUOTA_LIMIT_MAX）：弹窗里写着「1 元约 10 次」，
    管理员按实收金额填才算把"预付"落到了账上。留空 = 用默认值会引出隐藏分支，
    所以前端也不给默认值（§2.4）。
    """
    rid = _request_id(x_request_id)
    operator = request.state.user
    if payload.quota_limit < 0 or payload.quota_limit > config.QUOTA_LIMIT_MAX:
        raise QuotaLimitError()
    # 预检（with_secret=True 的两处之一；另一处是 db.approve_register_request 自己）：
    # 它负责把"不存在"与"已处理"分成两个不同的码，真正的并发抢跑仍由
    # db 层 `UPDATE ... AND status='pending'` 的 rowcount 兜底（§5.2B）。
    record = db.get_register_request(request_id, with_secret=True)
    if record is None:
        raise RegisterRequestNotFoundError()
    if record["status"] != "pending":
        # 不能静默改成 rejected——那是在替管理员做决定
        raise RegisterAlreadyReviewedError()
    user = db.approve_register_request(request_id, payload.quota_limit)
    if user is None:                      # 并发抢跑：事务已整体回滚，没有建出号
        raise RegisterAlreadyReviewedError()
    logger.info("同意注册申请", extra={
        "event": "auth.register_reviewed", "request_id": rid,
        "register_id": request_id, "operator": operator["username"],
        "target_user": user["username"], "decision": "approved",
        "quota_limit": payload.quota_limit,
    })
    return _ok({"id": user["id"], "username": user["username"],
                "is_admin": user["is_admin"], "quota_limit": user["quota_limit"]})


@app.post("/api/admin/register-requests/{request_id}/reject")
async def admin_reject_register(request_id: int, request: Request,
                                x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """拒绝注册申请（Spec19 §6.6）：只改状态，**不建号、不删记录**。

    记录留下来当台账（要清理得手动点「删除」），密码哈希也**保留**——
    该密码从来没有生效过（§3.3-5）。
    """
    rid = _request_id(x_request_id)
    operator = request.state.user
    record = db.get_register_request(request_id)
    if record is None:
        raise RegisterRequestNotFoundError()
    if db.reject_register_request(request_id) is None:
        raise RegisterAlreadyReviewedError()
    logger.info("拒绝注册申请", extra={
        "event": "auth.register_reviewed", "request_id": rid,
        "register_id": request_id, "operator": operator["username"],
        "target_user": record["username"], "decision": "rejected",
    })
    return _ok({"id": request_id})


@app.delete("/api/admin/register-requests/{request_id}")
async def admin_delete_register(request_id: int, request: Request,
                                x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """删除一条申请记录（Spec19 §6.7，任意状态都能删）。

    **不触碰 users**（§5.3）：users 是账号资源，register_requests 是审批台账，
    两者没有级联关系——删除一条已同意的记录不会删除它建出来的用户。
    副作用是"该 IP 的冷却期就此结束"（若这是它唯一的记录），这是一条有意的
    逃生通道：用户手滑填错，管理员删掉废申请即可让他重填（§2.2）。
    """
    rid = _request_id(x_request_id)
    operator = request.state.user
    record = db.get_register_request(request_id)
    if record is None:
        raise RegisterRequestNotFoundError()
    db.delete_register_request(request_id)
    logger.info("删除注册申请", extra={
        "event": "auth.register_deleted", "request_id": rid,
        "register_id": request_id, "operator": operator["username"],
        "target_user": record["username"], "was_status": record["status"],
    })
    return _ok({"id": request_id})


@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    """4 类调用聚合统计 + AI 服务反馈汇总 + 两个清零时间（只读；/api/admin/* 限管理员）。

    Spec11：额外返回 usage_cleared_at / feedback_cleared_at（null | UTC ISO），
    供前端展示各统计块"上次清零"的时间起点。
    """
    stats = db.get_usage_stats()
    stats["feedback_totals"] = db.get_feedback_totals()
    stats.update(db.get_cleared_times())
    return _ok(stats)


# ---------- 静态托管 ----------

app.mount("/images", StaticFiles(directory=config.STORAGE_DIR), name="images")

if (config.STATIC_DIR / "index.html").exists():
    # 后端直接托管前端 dist（本地演示 / 单端口部署）
    app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
