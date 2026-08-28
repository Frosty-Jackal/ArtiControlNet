"""任务引擎：asyncio.Queue + Worker + 内存任务注册表。

状态机：PENDING → PROCESSING → COMPLETED / FAILED。
- 提交时队列已满（超过 MAX_PENDING_TASKS）→ 抛 QueueCapacityError（50301）。
- 任务处理带超时（TASK_TIMEOUT_SECONDS）→ 61002。
- 终态任务保留 TERMINAL_TASK_TTL_SECONDS 后由 prune 淘汰。
"""
import asyncio
import itertools
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import config
from errors import AppError, QueueCapacityError

logger = logging.getLogger("task_queue")

Handler = Callable[["Task"], Awaitable[dict]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Task:
    """内存任务对象（Spec §8.3）。"""

    def __init__(self, task_id: int, thread_id: str, kind: str,
                 request: dict, request_id: str):
        self.id = task_id
        self.thread_id = thread_id
        self.kind = kind                    # chat|generate|edit|qa
        self.request = request
        self.request_id = request_id
        self.status = "PENDING"
        self.result: Optional[dict] = None
        self.error: Optional[dict] = None
        self.created_at = _now_iso()
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self._created_ts = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.id,
            "thread_id": self.thread_id,
            "kind": self.kind,
            "status": self.status,
            "request": self.request,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class TaskQueue:
    def __init__(self, handler: Handler, *,
                 max_pending: int | None = None,
                 timeout: int | None = None):
        self._handler = handler
        self._queue: asyncio.Queue[int] = asyncio.Queue(
            maxsize=max_pending or config.MAX_PENDING_TASKS
        )
        self._registry: dict[int, Task] = {}
        self._lock = asyncio.Lock()
        self._counter = itertools.count(1)
        self._timeout = timeout or config.TASK_TIMEOUT_SECONDS
        self._worker_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    # ---- 生命周期 ----

    async def start(self) -> None:
        self._stop.clear()
        self._worker_task = asyncio.create_task(self._worker(), name="task-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    # ---- 提交 / 查询 ----

    async def submit(self, *, thread_id: str, kind: str,
                     request: dict, request_id: str) -> Task:
        async with self._lock:
            task = Task(next(self._counter), thread_id, kind, request, request_id)
            self._registry[task.id] = task
        try:
            self._queue.put_nowait(task.id)
        except asyncio.QueueFull:
            async with self._lock:
                self._registry.pop(task.id, None)
            raise QueueCapacityError("待处理任务超过上限")
        self._log(task, "task.submitted", message="任务已提交，进入队列")
        return task

    def get(self, task_id: int) -> Optional[dict]:
        task = self._registry.get(task_id)
        return task.to_dict() if task else None

    async def prune(self) -> None:
        """淘汰超时终态任务。"""
        now = time.time()
        async with self._lock:
            stale = [
                tid for tid, t in self._registry.items()
                if t.status in ("COMPLETED", "FAILED")
                and now - t._created_ts > config.TERMINAL_TASK_TTL_SECONDS
            ]
            for tid in stale:
                self._registry.pop(tid, None)
        if stale:
            self._log_info("task.pruned", f"淘汰终态任务 {len(stale)} 个")

    # ---- Worker ----

    async def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                task_id = await self._queue.get()
            except asyncio.CancelledError:
                break
            try:
                task = self._registry.get(task_id)
                if task is not None:
                    await self._process(task)
            finally:
                self._queue.task_done()

    async def _process(self, task: Task) -> None:
        task.status = "PROCESSING"
        task.started_at = _now_iso()
        started = time.time()
        self._log(task, "task.started", message="worker 开始处理")
        try:
            result = await asyncio.wait_for(self._handler(task), timeout=self._timeout)
            task.result = result
            task.status = "COMPLETED"
            self._finish(task, "task.completed", started, "任务完成")
        except asyncio.TimeoutError:
            task.status = "FAILED"
            task.error = {"code": 61002, "message": "任务处理超过时限"}
            self._finish(task, "task.failed", started, "任务超时")
        except AppError as exc:
            task.status = "FAILED"
            task.error = {"code": exc.code, "message": exc.message}
            self._finish(task, "task.failed", started, exc.message,
                         provider=exc.provider)
        except Exception as exc:  # noqa: BLE001
            logger.exception("task crash", extra={"event": "task.error",
                                                  "task_id": task.id})
            task.status = "FAILED"
            task.error = {"code": 61999, "message": str(exc) or "未知任务失败"}
            self._finish(task, "task.failed", started, "未知任务失败")

    def _finish(self, task: Task, event: str, started: float, message: str,
                provider: Optional[str] = None) -> None:
        task.finished_at = _now_iso()
        self._log(task, event, duration_ms=(time.time() - started) * 1000,
                  message=message, provider=provider)

    # ---- 日志 ----

    def _log(self, task: Task, event: str, *, message: str = "",
             duration_ms: Optional[float] = None,
             provider: Optional[str] = None) -> None:
        extra: dict[str, Any] = {
            "event": event,
            "request_id": task.request_id,
            "thread_id": task.thread_id,
            "task_id": task.id,
            "kind": task.kind,
        }
        if duration_ms is not None:
            extra["duration_ms"] = round(duration_ms, 1)
        if provider:
            extra["provider"] = provider
        # 注意：logging 保留 message 属性，正文只能通过 msg 传入
        logger.info(message or event, extra=extra)

    def _log_info(self, event: str, message: str) -> None:
        logger.info(message, extra={"event": event})
