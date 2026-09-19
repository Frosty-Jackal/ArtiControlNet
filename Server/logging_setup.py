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
               "provider", "duration_ms", "kind", "username", "target_user",
               # Spec9 社区 / 反馈 / 分享 / 建议事件字段
               "post_id", "vote", "category", "image_id", "suggestion_id",
               "status", "operator",
               # Spec12 个人作品风格 Wiki 事件字段
               "user_id", "source", "used_count", "style_len", "reason",
               # Spec15 上传作品纳入风格事件字段
               "upload_analyzed", "upload_failed", "affected",
               # Spec18 服务限额事件字段（auth.quota_blocked / auth.admin.set_quota）
               "used", "quota_limit", "path",
               # Spec19 注册申请与审批事件字段。注意这里用 register_id 而不是
               # Spec19 §10 表里写的 request_id：后者在本仓已经是"HTTP X-Request-Id"
               # 的固定含义（每个路由的每行日志都带它），两者同名会让排查时
               # 拿 request_id 一搜就串味。注册申请 id 一律叫 register_id。
               # Spec22 删除："has_phone" —— 注册表单已经没有任何电话字段了，
               #   留着它就是一个永远不会被传进来的白名单项。
               "register_id", "has_email",
               "decision", "was_status",
               # Spec20 注册申请邮件通知事件字段（notify.register_mail_*）。
               # 注意 "error" 不是新概念：main.py / task_queue.py 里早有同名的
               # 事件名（request.error / task.error），但**没有**任何调用方把它
               # 当 extra 键传过——加进白名单不会让既有日志长出字段。
               "to", "error",
               # Spec21 余额与充值事件字段（recharge.submitted / recharge.reviewed / …）。
               # 注意用 recharge_source 而不是 source：后者在本仓已是
               # Spec12 wiki 事件的"作品来源"（generate|edit|upload），
               # 两者同名会让 `grep '"source"'` 一次捞到两种含义的东西。
               # 这与 Spec19 用 register_id 而不是 request_id 是同一条理由。
               "recharge_id", "recharge_source", "amount",
               # Spec22 邮箱验证码与入口统计事件字段。
               # purpose：register | login | reset（email_code.* 事件用）。
               # click_event：**不叫 event** —— event 在本仓是每条日志的"事件名"
               #   （_FIELDS 的第一项，Spec §10 起）。同名会让 `grep '"event"'`
               #   一次捞到两种东西，与 Spec19 的 register_id、Spec21 的
               #   recharge_source 是同一条理由（Spec22 §5.3）。
               # 注意：这是本白名单**第三次**被漏改的地方（Spec20 一次、
               #   Spec21 一次）——没登记的 extra 键会被静默丢弃，不报错、不警告。
               "purpose", "click_event")

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
