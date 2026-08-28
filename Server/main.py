"""ArtiControlNet 后端入口（Spec §8 / §5）。

编排层：/api/chat 异步提交 → 主 Agent 单跳路由 → 子 Agent 调外部 API → 结果入内存任务。
无数据库，无状态；图片落 storage/（TTL 1h）。
"""
import asyncio
import logging
import uuid
from collections import deque
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import config
import media
import schemas
from agents.supervisor import run_supervisor
from errors import AppError, FileMissingError, NotFoundError, UnsupportedImageTypeError
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


# ---------- Worker 处理器 ----------

def _make_handler(store: ThreadStore):
    async def handle_task(task: Task) -> dict:
        request = task.request
        try:
            result = await run_supervisor(request, await store.get(task.thread_id),
                                          task.request_id)
        except AppError as exc:
            await store.append(task.thread_id, {
                "role": "assistant", "text": f"（任务失败：{exc.message}）",
            })
            raise
        except Exception as exc:  # noqa: BLE001
            await store.append(task.thread_id, {
                "role": "assistant", "text": f"（任务失败：{exc}）",
            })
            raise
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
    media.cleanup_all()                       # 启动时清空 storage/

    store = ThreadStore()
    app.state.thread_store = store
    app.state.queue = TaskQueue(_make_handler(store))
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


# ---------- 静态托管 ----------

app.mount("/images", StaticFiles(directory=config.STORAGE_DIR), name="images")

if (config.STATIC_DIR / "index.html").exists():
    # 后端直接托管前端 dist（本地演示 / 单端口部署）
    app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
