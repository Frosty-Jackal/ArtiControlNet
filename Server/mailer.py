"""注册申请 / 充值申请邮件通知（Spec20、Spec21 §5.5）+ 邮箱验证码与审批结果通知（Spec22）。

一个同步阻塞模块：由 FastAPI BackgroundTasks 丢进线程池执行，
**永不抛异常**——邮件是尽力而为的通知，不能反过来影响注册 / 充值。

Spec22 起收件人分两类：前三个函数发给**你自己**（config.*_NOTIFY_TO，日志里可以带
`to`），后三个发给**用户本人**（日志里**不带** `to`，那是 PII）。

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


# ---------- Spec22：发给**用户本人**的邮件 ----------
# 与上面三个函数的**关键区别**：收件人是用户，不是 config.*_NOTIFY_TO。
# 所以下面每一个都**不带 `to` 进日志** —— 那是用户的邮箱，是 PII（§10.2）。
# 上面三个带 `to` 是因为那个地址是你自己的、固定不变的。
#
# ⚠️ 三个都必须是**同步 def**，理由与上面两个完全一样（Spec20 §2.1）。


def _send(to_email: str, subject: str, body: str) -> None:
    """发一封纯文本邮件。**内部助手**，调用方负责判空 / 配没配 / 吞异常。

    抽出来只为少抄三遍 SMTP_SSL 那五行——三个公开函数的"结局处理"（记哪条日志、
    带哪些字段）各不相同，所以那部分**不**抽。
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((_FROM_NAME, config.SMTP_USER))
    msg["To"] = to_email
    msg.set_content(body)
    with smtplib.SMTP_SSL(
        config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT_SECONDS
    ) as smtp:
        smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.send_message(msg)


def send_email_code(to_email: str, code: str, purpose: str) -> None:
    """把 4 位验证码发给**用户本人**（Spec22 §5.6）。**同步阻塞**，调用方丢线程池。

    ⚠️ 日志里**不带 `to`**（用户的邮箱 = PII），也**绝不带 `code`**（它是凭据）。
    两个都只记 `purpose`——排障靠时间戳与 `error`（§10.2）。

    未配 SMTP_PASSWORD 时这里只是**双保险**：路由层已经在落库之前拦过一次并返回
    50302（§2.5），走到这里说明是别的调用方。
    """
    if not config.SMTP_PASSWORD:
        logger.warning("验证码邮件未发送：SMTP 未配置", extra={
            "event": "notify.email_code_mail_skipped",
            "reason": "smtp_not_configured", "purpose": purpose,
        })
        return

    try:
        # 分钟数由秒数推出来，不写死 "10"（照 RECHARGE_COOLDOWN_MESSAGE 的先例：
        # 改 TTL 时文案自动跟着变，不可能出现"设了 5 分钟、邮件说 10 分钟"）。
        _send(to_email, "ArtiControlNet-邮箱验证",
              f"您的邮箱验证码为：{code}。验证码{config.EMAIL_CODE_TTL_SECONDS // 60}分钟内有效。")
    except Exception as exc:  # 故意吞掉一切：邮件故障不能让请求失败（Spec20 §2.4）
        logger.warning("验证码邮件发送失败", extra={
            "event": "notify.email_code_mail_failed",
            "purpose": purpose, "error": f"{type(exc).__name__}: {exc}",
        })
        return

    logger.info("验证码邮件已发送", extra={
        "event": "notify.email_code_mail_sent", "purpose": purpose,
    })


def send_recharge_approved_notification(username: str, to_email: str,
                                        created_at_iso: str, overdue: bool,
                                        recharge_id: int) -> None:
    """充值审批通过 → 通知**该用户**（Spec22 §5.6 / §2.12）。**同步阻塞**。

    两个变体只差标题与正文最后半句，按 recharge_requests.source 分流。
    正文里的时间是**申请时间**（记录的 created_at → 北京时间），不是审批时刻——
    用户给的三句话说的都是"申请时间"，台账里的 reviewed_at 三句都没用（§2.12）。

    ⚠️ `recharge_id` 是为了日志（§10 的字段表、§13 用例 18 都要它），
    §5.6 的签名草图漏了它——以 §10/§13 为准。

    没有邮箱（管理员手工建的号）时 → 跳过发信 + `reason=no_email`，**业务照做**：
    邮件是通知，不是业务（Spec20 §5.3 的原则在这里仍然成立）。
    """
    if not config.SMTP_PASSWORD:
        logger.warning("充值到账通知未发送：SMTP 未配置", extra={
            "event": "notify.recharge_approved_mail_skipped",
            "reason": "smtp_not_configured", "username": username,
            "recharge_id": recharge_id,
        })
        return
    if not to_email:
        logger.warning("充值到账通知未发送：该用户没有邮箱", extra={
            "event": "notify.recharge_approved_mail_skipped",
            "reason": "no_email", "username": username,
            "recharge_id": recharge_id,
        })
        return

    when = beijing_time_text(created_at_iso)
    if overdue:
        subject = "ArtiControlNet-账号已恢复"
        body = (f"ArtiControlNet的用户您好，您于{when}充值的金额已到账，"
                f"您的账号可以恢复使用啦，感谢您的支持~")
    else:
        subject = "ArtiControlNet-充值已到账"
        body = f"ArtiControlNet的用户您好，您于{when}充值的金额已到账，感谢您的支持~"

    try:
        _send(to_email, subject, body)
    except Exception as exc:  # 故意吞掉一切（Spec20 §2.4）
        logger.warning("充值到账通知发送失败", extra={
            "event": "notify.recharge_approved_mail_failed",
            "username": username, "recharge_id": recharge_id,
            "error": f"{type(exc).__name__}: {exc}",
        })
        return

    logger.info("充值到账通知已发送", extra={
        "event": "notify.recharge_approved_mail_sent",
        "username": username, "recharge_id": recharge_id,
    })


def send_register_approved_notification(username: str, to_email: str,
                                        created_at_iso: str, register_id: int) -> None:
    """注册审批通过 → 通知**该注册者**（Spec22 §5.6 / §2.12）。**同步阻塞**。

    只有**一个**变体（不像充值那封要按 source 分流）——注册审批没有"欠费"这种形态。
    正文里的时间是**申请时间**（申请行的 created_at → 北京时间），不是审批时刻。

    ⚠️ 正文开头**没有**「ArtiControlNet的用户您好」（充值那两封有）：用户给的原文
    就是「您于…」，照抄，别顺手补上称呼。
    ⚠️ 主题拼写是 **ControlNet**（§0 第 8-a 条），不是 ConrtolNet。
    ⚠️ `register_id` 的理由同上一封（§10 字段表 / §13 用例 15）。

    没有邮箱时（Spec22 之前提交的、只留了手机号的 pending 旧行）→
    跳过发信 + `reason=no_email`，**号照建**。
    """
    if not config.SMTP_PASSWORD:
        logger.warning("注册成功通知未发送：SMTP 未配置", extra={
            "event": "notify.register_approved_mail_skipped",
            "reason": "smtp_not_configured", "username": username,
            "register_id": register_id,
        })
        return
    if not to_email:
        logger.warning("注册成功通知未发送：该申请没有邮箱", extra={
            "event": "notify.register_approved_mail_skipped",
            "reason": "no_email", "username": username,
            "register_id": register_id,
        })
        return

    try:
        _send(to_email, "ArtiControlNet-注册成功",
              f"您于{beijing_time_text(created_at_iso)}申请的注册已通过，"
              f"您现在可以开始享用ArtiControlNet啦！")
    except Exception as exc:  # 故意吞掉一切（Spec20 §2.4）
        logger.warning("注册成功通知发送失败", extra={
            "event": "notify.register_approved_mail_failed",
            "username": username, "register_id": register_id,
            "error": f"{type(exc).__name__}: {exc}",
        })
        return

    logger.info("注册成功通知已发送", extra={
        "event": "notify.register_approved_mail_sent",
        "username": username, "register_id": register_id,
    })
