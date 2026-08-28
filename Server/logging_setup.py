"""单行 JSON 日志（格式见 Spec §10）。

用法：模块内 `import logging; logger = logging.getLogger("task_queue")`，
需要附带上下文时通过 extra 传入，如：
    logger.info("生成完成", extra={"event": "task.completed", "task_id": 42})
未提供的字段自动缺省。禁止把 API Key 等敏感信息写进日志。
"""
import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """把日志记录格式化为单行 JSON。"""

    _FIELDS = ("event", "request_id", "thread_id", "task_id",
               "provider", "duration_ms", "kind")

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3] + "Z"
        payload = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for f in self._FIELDS:
            v = record.__dict__.get(f)
            if v is not None:
                payload[f] = v
        if record.exc_info and record.exc_info[0]:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    """安装 JSON handler 到根 logger。访问日志（uvicorn）保持默认。"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # uvicorn 访问日志单独保留默认格式，不重复 JSON
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
