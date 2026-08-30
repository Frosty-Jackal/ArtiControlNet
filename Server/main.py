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

from fastapi import FastAPI, File, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import auth
import config
import db
import gallery
import media
import schemas
from agents.supervisor import run_supervisor
from errors import (AppError, AuthTokenError, BadRequestError,
                    CredentialsFormatError, FileMissingError, ForbiddenError,
                    LoginFailedError, LoginRateLimitedError, NotFoundError,
                    UnsupportedImageTypeError, UserNotFoundError)
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

# 放行列表：除登录外，所有 /api 接口都需登录态
PUBLIC_AUTH_PATHS = {"/api/auth/login"}


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
    request_id = _request_id(x_request_id)
    thread_id = payload.thread_id or f"t_{uuid.uuid4().hex[:8]}"
    queue: TaskQueue = request.app.state.queue
    store: ThreadStore = request.app.state.thread_store

    task = await queue.submit(
        thread_id=thread_id, kind="chat", request_id=request_id,
        request={
            "message": payload.message,
            "image_url": payload.image_url,
            "thread_id": thread_id,
            "public_base": _public_base(request),
            "request_id": request_id,
            "user_id": request.state.user["id"],   # 统计归属（Spec4 §5.2）
        },
    )
    # 记录用户消息（供后续路由上下文）
    await store.append(thread_id, {
        "role": "user", "text": payload.message, "image_url": payload.image_url,
    })
    logger.info("收到对话请求", extra={
        "event": "chat.submitted", "request_id": request_id,
        "thread_id": thread_id, "task_id": task.id,
    })
    return _ok({"task_id": task.id, "thread_id": thread_id, "status": task.status})


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
    gallery.save_gallery_image(data, request.state.user["id"], "upload", None)
    logger.info(f"图片上传成功: {url}", extra={
        "event": "image.uploaded", "request_id": request_id,
    })
    return _ok({"image_url": url})


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


@app.get("/api/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str, request: Request):
    store: ThreadStore = request.app.state.thread_store
    return _ok({"messages": await store.get(thread_id)})


# ---------- 个人作品库（Spec5 §6.1）----------

@app.get("/api/gallery")
async def list_gallery(request: Request, source: str = ""):
    """本人作品列表（时间倒序），可 ?source=upload|generate|edit 筛选。鉴权由统一中间件。"""
    user = request.state.user
    items = gallery.list_user_images(user["id"], source or None)
    return _ok({"items": items})


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
    """删除本人作品：记录 + gallery/ 物理文件一并删除。"""
    user = request.state.user
    gallery.delete_item(item_id, user["id"])
    return _ok({"id": item_id})


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
    return _ok(db.list_users())


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
    # 级联删除作品：gallery/ 物理文件 + images 记录（Spec5 §3），随后 db 侧清 usage/images/users
    gallery.delete_user_gallery(user_id)
    db.delete_user(user_id)
    logger.info("删除账号", extra={
        "event": "auth.admin.delete_user", "request_id": request_id,
        "username": operator["username"], "target_user": target["username"],
    })
    return _ok({"id": user_id})


@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    """4 类调用聚合统计（只读；鉴权由统一中间件对 /api/admin/* 限管理员，Spec4 §6.2）。"""
    return _ok(db.get_usage_stats())


# ---------- 静态托管 ----------

app.mount("/images", StaticFiles(directory=config.STORAGE_DIR), name="images")

if (config.STATIC_DIR / "index.html").exists():
    # 后端直接托管前端 dist（本地演示 / 单端口部署）
    app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
