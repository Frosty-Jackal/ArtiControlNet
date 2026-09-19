"""注册申请 / 充值申请邮件通知（Spec20、Spec21 §5.5）。

一个同步阻塞模块：由 FastAPI BackgroundTasks 丢进线程池执行，
**永不抛异常**——邮件是尽力而为的通知，不能反过来影响注册 / 充值。

时间格式化已搬到 timefmt.py（Spec21 §5.2）；本模块只是把它重新导出，
`mailer.beijing_time_text(...)` 依然可调用（Spec20 §13 的验收命令逐字照旧）。
"""
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

import config
from timefmt import beijing_time_text   # noqa: F401（对外仍是 mailer.beijing_time_text）

logger = logging.getLogger("mailer")

_FROM_NAME = "ArtiControlNet"


def send_register_notification(username: str, contact: str, wechat: str,
                               created_at_iso: str) -> None:
    """发一封"有新注册申请"的提醒。**同步阻塞**，调用方负责丢进线程池（Spec20 §2.1）。

    三种结局，全部静默（Spec20 §2.4）：
      未配置 SMTP_PASSWORD → warning 日志，直接返回
      发送成功             → info 日志
      发送失败             → warning 日志（异常被吞掉，绝不冒泡到注册请求上）

    日志里**不带**用户手机号 / 邮箱 / IP（Spec20 §10）：前两者是申请人的 PII 且已在
    邮件正文里，IP 是 Spec19 §10 定的"任何日志都不带"。`to` 是配置里的固定值，可以记。

    Spec21 §2.7：正文前面加了「微信充值账号是<昵称>，」；「注册时间是」这个措辞
    **保留**（用户只要求"前面加一句"，改一个没被要求的词会让 Spec20 的验收用例
    与邮件历史对不上）。于是三封邮件的句式并不完全一致——**有意照抄用户原话**。

    ⚠️ 本函数必须保持为**同步 def**。改成 async def 会让 Starlette 在事件循环里
    直接 await 它，smtplib 的阻塞 IO 会卡死整个循环（所有并发请求一起等），
    而且**不报错、只是变慢**——最难查的那类劣化。同步 def 才会被丢进 threadpool。
    """
    if not config.SMTP_PASSWORD:
        logger.warning("注册通知未发送：SMTP 未配置", extra={
            "event": "notify.register_mail_skipped",
            "reason": "smtp_not_configured",
            "username": username,
        })
        return

    msg = EmailMessage()
    msg["Subject"] = f"ACN-{username}-{contact}"
    msg["From"] = formataddr((_FROM_NAME, config.SMTP_USER))
    msg["To"] = config.REGISTER_NOTIFY_TO
    msg.set_content(
        f"微信充值账号是{wechat}，注册时间是{beijing_time_text(created_at_iso)}，请立即审批！"
    )

    try:
        with smtplib.SMTP_SSL(
            config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT_SECONDS
        ) as smtp:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    except Exception as exc:  # 故意吞掉一切：邮件故障不能让注册失败（Spec20 §2.4）
        logger.warning("注册通知发送失败", extra={
            "event": "notify.register_mail_failed",
            "username": username,
            "error": f"{type(exc).__name__}: {exc}",
        })
        return

    logger.info("注册通知已发送", extra={
        "event": "notify.register_mail_sent",
        "username": username,
        "to": config.REGISTER_NOTIFY_TO,
    })


def send_recharge_notification(username: str, contact: str, wechat: str,
                               created_at_iso: str, overdue: bool) -> None:
    """发一封"有人提交了充值申请"的提醒（Spec21 §5.5）。**同步阻塞**，调用方丢线程池。

    overdue=True  → 主题 ACN欠费充值-<账号>-<联系方式>（登录页那条路）
    overdue=False → 主题 ACN充值-<账号>-<联系方式>

    四种结局，全部静默（与 Spec20 §2.4 逐字同款）：
      未配置 SMTP_PASSWORD → warning 日志，直接返回
      发送成功             → info 日志
      发送失败             → warning 日志（异常被吞掉，绝不冒泡到充值请求上）

    正文照抄用户原话：**没有感叹号**（§2.7 的注册那封有，这封没有，不是笔误）。

    ⚠️ 与 send_register_notification 一样必须保持为**同步 def**（理由同上）。
    """
    if not config.SMTP_PASSWORD:
        logger.warning("充值通知未发送：SMTP 未配置", extra={
            "event": "notify.recharge_mail_skipped",
            "reason": "smtp_not_configured", "username": username,
        })
        return

    prefix = "ACN欠费充值" if overdue else "ACN充值"
    msg = EmailMessage()
    msg["Subject"] = f"{prefix}-{username}-{contact}"
    msg["From"] = formataddr((_FROM_NAME, config.SMTP_USER))
    msg["To"] = config.RECHARGE_NOTIFY_TO
    msg.set_content(
        f"微信充值账号是{wechat}，申请时间是{beijing_time_text(created_at_iso)}，请立即审批"
    )
    try:
        with smtplib.SMTP_SSL(
            config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT_SECONDS
        ) as smtp:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    except Exception as exc:  # 故意吞掉一切（Spec20 §2.4）
        logger.warning("充值通知发送失败", extra={
            "event": "notify.recharge_mail_failed",
            "username": username, "error": f"{type(exc).__name__}: {exc}",
        })
        return

    logger.info("充值通知已发送", extra={
        "event": "notify.recharge_mail_sent",
        "username": username, "to": config.RECHARGE_NOTIFY_TO,
    })
