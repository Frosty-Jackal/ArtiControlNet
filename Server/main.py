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
import community
import config
import db
import gallery
import media
import schemas
import shares
from agents.supervisor import run_supervisor
from errors import (AppError, AuthTokenError, BadRequestError,
                    CredentialsFormatError, FeedbackParamError, FileMissingError,
                    ForbiddenError, LoginFailedError, LoginRateLimitedError,
                    NotFoundError, PostContentError, PostNotFoundError,
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
    """本人作品列表（时间倒序），可 ?source=upload|generate|edit 筛选；每项含可空 share（Spec9 §6.1）。"""
    user = request.state.user
    items = gallery.list_user_images(user["id"], source or None, _public_base(request))
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
    """删除本人作品：记录 + gallery/ 物理文件一并删除（分享级联在 gallery.delete_item 内）。"""
    user = request.state.user
    gallery.delete_item(item_id, user["id"])
    return _ok({"id": item_id})


# ---------- 社区（Spec9 §6.1）----------

@app.post("/api/community")
async def create_community_post(request: Request,
                                text: str = Form(...),
                                gallery_id: Optional[int] = Form(None),
                                file: Optional[UploadFile] = File(None),
                                x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
    """发帖：单图（作品库选择 gallery_id 或新上传 file）+ 文字（1~1000 字）。"""
    request_id = _request_id(x_request_id)
    user = request.state.user
    body = (text or "").strip()
    if not body or len(body) > config.COMMUNITY_POST_TEXT_MAX:
        raise PostContentError(f"帖子文字需为 1~{config.COMMUNITY_POST_TEXT_MAX} 字")
    has_gallery = gallery_id is not None
    has_file = file is not None and file.filename
    if has_gallery == has_file:
        raise PostContentError("图片来源需二选一：从作品库选择或上传新图")
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
    })
    return _ok({"post": {
        "id": post["id"],
        "text": post["text"],
        "author": user["username"],
        "author_is_admin": user["is_admin"],
        "image_url": f"/api/community/{post['id']}/image",
        "like_count": 0,
        "dislike_count": 0,
        "my_vote": None,
        "created_at": post["created_at"],
    }})


@app.get("/api/community")
async def list_community(request: Request, offset: int = 0, limit: int = 50):
    """帖子列表，最新在前；每项含作者、计数、我的投票。limit≤100。"""
    user = request.state.user
    offset = max(0, offset)
    limit = max(1, min(limit, 100))
    return _ok({"items": community.list_posts(user["id"], offset, limit)})


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


@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    """4 类调用聚合统计 + AI 服务反馈汇总（只读；/api/admin/* 限管理员，Spec4 §6.2 / Spec9 §6.1）。"""
    stats = db.get_usage_stats()
    stats["feedback_totals"] = db.get_feedback_totals()
    return _ok(stats)


# ---------- 静态托管 ----------

app.mount("/images", StaticFiles(directory=config.STORAGE_DIR), name="images")

if (config.STATIC_DIR / "index.html").exists():
    # 后端直接托管前端 dist（本地演示 / 单端口部署）
    app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
