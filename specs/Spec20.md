# ArtiControlNet Spec 20：新注册申请邮件通知

> 目标读者：Claude Code（用于按本 Spec 进行 Spec Coding）与项目作者（FJ）。
> 一句话：**每收到一条新的注册申请，就往 `frostyj@qq.com` 发一封提醒邮件**，让你不用盯着管理端页面也知道有人来了。
> 主题 `ACN-<账号名>-<邮箱或手机号>`，正文 `注册时间是<北京时间>，请立即审批！`
> 本 Spec 是 **Spec.md / Spec2~19 的增量补充**，不推翻原有架构。
> **无数据库变化、无新表、无补列迁移**（邮件是"发出去就完事"，不落库、不记账）。
> **无新依赖**（`smtplib` / `email` 都是 Python 标准库）、**无新持久目录**、**前端零改动**。
> 新增 **1 个后端文件**（`mailer.py`）+ **6 个环境变量**（全部有默认值，全部可留空）。
> 硬约束仍遵守：无本地推理、只有前后端两层、所有凭据只在后端环境变量、除 `artcn.db` 外无其他数据库。
> **不新增 provider、不新增模型、不改任何一个上游调用链、不改 Spec19 的任何路由/表/前端。**

---

## 1. 功能目的

### 1.1 为什么现在做

- **现在靠"自己去翻"。** Spec19 把注册做成了「申请 → 审批」链，但新增的申请**只静静躺在 `register_requests` 表里**——你得主动打开「用户管理」页滚到底部才看得见。付费是预充值模式，**审批延迟 = 用户拿着收款码干等**。
- **申请是低频、偶发、且有时效的事件。** 一天可能来 0 条，也可能来 3 条。为它常驻一个后台页面不值得，为它错过一个已付款的用户更不值得。邮件正好匹配这个形状：**来一条推一条，没来就安静**。
- **邮件里天然带"对账键"。** Spec19 §1.1 说过，申请里的**微信昵称**是唯一能把"这笔转账"和"这条申请"对上的东西。但本 Spec 的主题按用户指定只放账号名 + 联系方式——**微信昵称不在邮件里**，需要看它请点开管理端。这是有意的：邮件是**提醒你去审批**，不是替代审批台（§3.2）。

### 1.2 一件事

**在 `POST /api/auth/register` 成功落库之后，后台发一封通知邮件。** 用户侧、前端、管理端、数据库全都不变。

### 1.3 触发点的口径（这是本 Spec 最容易搞错的地方）

Spec19 §1.3 已经把链路讲清楚了：**「注册申请」不是「注册」，它不创建任何用户。** 于是"有新用户注册"这句话在本系统里对应两个时刻，本 Spec 明确取前者：

| 时刻 | 发生了什么 | 本 Spec 发不发邮件 |
|---|---|---|
| 用户点「提交申请」 | `register_requests` **插入一行**（`status='pending'`） | **发**（这是"有人来了，等你处理"） |
| 管理员点「同意」 | 同一事务建 `users` 行 + 申请置 `approved` | **不发**（这一步是你自己点的按钮，发信等于给自己发通知） |

**挂载点**：`main.py` 的 `register_request()` 里，第 1174 行 `db.create_register_request(...)` 之后、`return _ok(...)` 之前。**只此一处**，`approve` / `reject` / `delete` 三条管理端路由一行都不碰。

---

## 2. 决策记录（为什么这么选）

### 2.1 发信机制：`BackgroundTasks` + **同步** `def`

| 决策 | 选择 | 理由 |
|---|---|---|
| 在哪发 | FastAPI `BackgroundTasks` | 响应**先发出去**，任务在后台跑。注册接口的耗时一秒都不涨——这是本 Spec 唯一不可妥协的点。 |
| 为什么不用 `asyncio.create_task` | 不用 | `create_task` 返回的 task 若无人持引用，**可能在跑完前被 GC 掉**（CPython 文档明确要求保存引用）。要安全就得额外维护一个 set + `done_callback` 摘除，为一个发信动作引入一套生命周期管理不划算。`BackgroundTasks` 是框架自带机制，零新概念。 |
| 为什么不用 `await asyncio.to_thread(...)` | 不用 | 那会**阻塞响应**——`await` 意味着注册接口要等 SMTP 握手完（几百毫秒到数秒）才返回。与"不涨耗时"直接冲突。 |
| 发信函数写成 `async def` 还是 `def` | **必须是同步 `def`** | **这是本 Spec 最容易写错、且写错了会静默劣化的一处**：Starlette 对 `async def` 任务是在事件循环里**直接 await**（阻塞 IO 卡死整个循环，所有并发请求一起等）；只有同步 `def` 才会被丢进 threadpool。见 §10 的实现注释，改签名前请先读这一行。 |
| 代价是什么 | 响应发出后进程若立刻重启，这封邮件会丢 | 可接受。邮件是**尽力而为的提醒**，不是台账——台账是 `register_requests` 表和管理端页面，它们不受影响。失去的只是"这一封提醒"，下一次打开管理端照样看得到。 |

### 2.2 时间：北京时间，且用**固定 +08:00 偏移**

| 决策 | 选择 | 理由 |
|---|---|---|
| 用哪个时区 | **北京时间** | 收件人是你。`_now_iso()`（`db.py:288`）存的是 UTC，原样发过去你每封都得自己加 8 小时，且**凌晨 0~8 点的申请会显示成前一天**——一个会让你误判"这是昨晚的还是今早的"的错误。 |
| 怎么实现 | `timezone(timedelta(hours=8))` | 中国全境单一时区、**无夏令时**，所以固定偏移是**正确**的，不只是权宜。 |
| 为什么不用 `zoneinfo("Asia/Shanghai")` | 不用 | **Windows 没有系统 tz 数据库**，未额外安装 `tzdata` 包时 `ZoneInfo(...)` 会抛 `ZoneInfoNotFoundError`。部署机正是 Windows（见 CLAUDE.md 的命令段）。为了一个恒等于 +08:00 的偏移去引入一个可能运行期爆炸的依赖，不划算。 |
| 格式 | `%Y-%m-%d %H:%M:%S` | 用户原话是"注册时间是<注册时间>"，落在正文里给人看。ISO 带 `T` 和 `Z` 是给机器读的。 |
| 解析失败怎么办 | 原样返回那个 ISO 串 | 宁可显示得难懂，也不能因为一个格式假设就让邮件发不出去（§5.3）。 |

### 2.3 主题的取值口径：`ACN-<账号名>-<联系方式>`

| 决策 | 选择 | 理由 |
|---|---|---|
| 联系方式取哪个 | **优先邮箱，没有才用手机号** | 用户原话"电话或邮箱"没覆盖 Spec19 允许的"两个都填"（§2.1：二选一必填，两个都填不算错）。用户已确认取邮箱优先：邮箱在邮件客户端里可点击、可复制，手机号则要切到手机应用才有用。 |
| 两个都没填呢 | 不可能发生 | `main.py:1150` 的格式校验已保证至少一项非空（否则 40018）。实现里仍写一句 `or "未填写"` 兜底，纯防御，正常路径不可达。 |
| 从哪取 | `main.py` 里**已有的局部变量** `email` / `phone` | 它们已经是 `strip()` 过的。**不回读数据库**——`create_register_request` 把空串存成 NULL，从库里取反而要多处理一次 `None`。 |
| 账号名 | 申请里的 `username`（已 strip） | 与你原话一致，不做任何转义/截断。用户名校验已限 2~32 字符（`main.py:1143`），不会撑爆主题行。 |

### 2.4 未配置 / 失败：一律静默降级

| 决策 | 选择 | 理由 |
|---|---|---|
| 要不要一个 `REGISTER_NOTIFY_ENABLED` 开关 | **不要** | 多一个开关就多一种"配了授权码但忘了打开开关"的静默失败。判据只有一个：**`SMTP_PASSWORD` 是否非空**。空 = 不发，非空 = 发。 |
| 没配 SMTP 时怎么表现 | 注册**完全照常**，只记一条 `skipped` 日志 | 这保证了"升级到 Spec20 但还没去申请授权码"的中间态是**安全**的：行为与 Spec19 逐字节等价（§3.3-1）。 |
| 发信失败（密码错、网络不通、QQ 限流）怎么表现 | 注册**仍然返回 200**，只记一条 `failed` 日志 | **邮件是通知，不是业务。** 让 SMTP 的故障把一次成功的注册变成失败，是本末倒置。 |
| 收件人为什么不直接写 `SUPPORT_EMAIL` | 单独一个 `REGISTER_NOTIFY_TO`，**默认跟随** `SUPPORT_EMAIL` | `SUPPORT_EMAIL` 是**给用户看的**客服邮箱（印在注册弹窗和超额提示上，Spec19 §8）。哪天你把它换成对外的公开邮箱，通知邮件不该跟着改到别人的收件箱里。默认跟随只是"省得你配两遍"。 |
| 发件人用谁 | `SMTP_USER`，默认跟随 `SUPPORT_EMAIL` | 用户已确认"frostyj@qq.com 自己发给自己"：零额外成本，且 QQ 邮箱对"自己发给自己"的信誉判定最宽松。 |
| 发件人显示名 | `ArtiControlNet` | 收件箱列表里显示成 `ArtiControlNet <frostyj@qq.com>`，比一串裸地址好认。 |
| 为什么不落库 | 不建表、不记发送状态 | 邮件没有"重发"需求，也没有"发过没发过"的判据价值。落一张 `notifications` 表等于凭空多一份要维护、要对齐、要清理的状态。 |

---

## 3. 需求边界

### 3.1 范围内

- **新增** `Server/mailer.py`：`beijing_time_text()` + `send_register_notification()`（§5.1）。
- `Server/config.py`：新增 6 个变量（§8），**位置有硬约束**——必须排在 `SUPPORT_EMAIL`（当前第 83 行）之后。
- `Server/main.py`：`from fastapi import ...` 加 `BackgroundTasks`；`import mailer`；`register_request()` 加注入参数 + 1 处 `add_task`（§6.1）。
- `Server/.env.example`：加一段带注释的占位（§8）。
- `CLAUDE.md`：配置段补一句 + 关键注意事项补一条。

### 3.2 不在范围内（明确不做）

| 不做的事 | 为什么不 |
|---|---|
| **不发"审批完成"通知** | §1.3：那是你自己点的按钮。 |
| **不发"用户注册成功"欢迎邮件** | 系统没有自助注册，用户拿号是你在管理端建的，密码是他申请时自己填的。没有需要通知用户的事。 |
| **不在邮件里放微信昵称 / 手机号 / 邮箱原文以外的信息** | 用户指定的正文只有时间。**尤其不放 `password_hash`**——`register_requests` 表里存着它，但它连管理端列表接口都不出（Spec19 §5.1c 的结构性保证），更没有理由进一封会长期躺在收件箱里的邮件。 |
| **不在邮件里放 IP** | Spec19 §10 定的规矩：IP 只用于冷却判重，**任何响应和任何日志都不带**。邮件同理。 |
| **不做重发 / 重试队列** | 见 §2.4：邮件是尽力而为。 |
| **不做邮件的富文本 / HTML 模板** | 正文只有一句话。纯文本反而不会被各家客户端的 HTML 清洗规则搞乱。 |
| **不做前端任何改动** | 用户看不到这件事发生。前端零改动是本 Spec 的验收项之一（§13）。 |
| **不动 Spec19 的任何一张表、任何一条路由、任何一行前端** | 本 Spec 只加一个"旁观者"。 |

### 3.3 已知边界与风险（写入本文档，避免误读）

1. **零配置 = Spec19 原样。** 不设 `SMTP_PASSWORD` 时，本 Spec 的全部效果是：每次注册多一条 `notify.register_mail_skipped` 的 warning 日志。注册接口的响应、耗时、副作用与 Spec19 逐字节等价。
2. **邮件正文不含微信昵称，因此不能只靠邮件完成对账。** 邮件是"去审批"的提示，真正决定批准谁要看管理端页面（那里有微信昵称、有手机号邮箱的完整信息）。这是有意的取舍（§1.1）。
3. **没有全局频率上限。** Spec19 §2.2 的同 IP 24h 冷却保证**同一个 IP**每天最多触发一封；但换 IP 可以绕开。理论上有人可以用大量不同 IP 刷你的收件箱，QQ 邮箱也可能因此限流。本 Spec 不加节流（会引入一个不该为低频事件存在的复杂度）；真要出事时的止损手段是现成的：`REGISTER_ENABLED=false` 一键关掉整个注册入口（Spec19 §8）。
4. **响应发出后进程立刻重启，那一封会丢。** 见 §2.1 末行。
5. **`SMTP_PASSWORD` 是授权码，不是 QQ 登录密码。** 在 QQ 邮箱「设置 → 账户 → POP3/IMAP/SMTP 服务」里开启 SMTP 后生成。填错了的表现是 `notify.register_mail_failed` + `SMTPAuthenticationError`，注册不受影响。
6. **邮件不经由任何第三方服务。** 直连 `smtp.qq.com`，凭据只在本机 `.env` 里，与"所有 Key 只在后端环境变量"的硬约束一致。

---

## 4. 技术栈增量

**无。** 这是本 Spec 的一个明确卖点：

| 项 | 增量 |
|---|---|
| 新依赖（`requirements.txt`） | **0** —— `smtplib` / `email.message` / `email.utils` / `datetime` 全是标准库 |
| 新 provider / 新模型 / 新上游 API | **0** |
| 新数据库 / 新表 / 补列迁移 | **0** |
| 新持久目录 | **0** |
| 新错误码 | **0**（§9） |
| 前端改动 | **0** |

---

## 5. 架构设计（增量）

### 5.1 新增 `Server/mailer.py`

```python
"""注册申请邮件通知（Spec20）。

一个同步阻塞模块：由 FastAPI BackgroundTasks 丢进线程池执行，
**永不抛异常**——邮件是尽力而为的通知，不能反过来影响注册。
"""
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr

import config

logger = logging.getLogger(__name__)

# 中国全境单一时区、无夏令时，所以固定 +08:00 偏移是**正确**的，不只是权宜（§2.2）。
# 刻意不用 zoneinfo("Asia/Shanghai")：Windows 没有系统 tz 数据库，
# 未安装 tzdata 包时 ZoneInfo 会抛 ZoneInfoNotFoundError，而部署机正是 Windows。
_BEIJING = timezone(timedelta(hours=8))

_FROM_NAME = "ArtiControlNet"


def beijing_time_text(created_at_iso: str) -> str:
    """库里的 UTC ISO 串（2026-09-19T07:33:12.451Z）→ '2026-09-19 15:33:12'。

    解析失败时**原样返回**：宁可显示得难懂，也不让邮件发不出去（§2.2）。
    """
    try:
        dt = datetime.strptime(created_at_iso, "%Y-%m-%dT%H:%M:%S.%fZ")
        return dt.replace(tzinfo=timezone.utc).astimezone(_BEIJING).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (ValueError, TypeError):
        return str(created_at_iso)


def send_register_notification(username: str, contact: str, created_at_iso: str) -> None:
    """发一封"有新注册申请"的提醒。**同步阻塞**，调用方负责丢进线程池（§2.1）。

    三种结局，全部静默（§2.4）：
      未配置 SMTP_PASSWORD → warning 日志，直接返回
      发送成功             → info 日志
      发送失败             → warning 日志（异常被吞掉，绝不冒泡到注册请求上）

    ⚠️ 本函数必须保持为**同步 def**。改成 async def 会让 Starlette 在事件循环里
    直接 await 它，smtplib 的阻塞 IO 会卡死整个循环（所有并发请求一起等）。
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
    msg.set_content(f"注册时间是{beijing_time_text(created_at_iso)}，请立即审批！")

    try:
        with smtplib.SMTP_SSL(
            config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT_SECONDS
        ) as smtp:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    except Exception as exc:  # 故意吞掉一切：邮件故障不能让注册失败（§2.4）
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
```

### 5.2 关键数据流

```
POST /api/auth/register
  │
  ├─ ①~⑨ 校验（Spec19 §6.2，一字不改）
  │
  ├─ ⑩ db.create_register_request(...)          → record（含 created_at，UTC ISO）
  │     logger.info("auth.register_submitted")
  │
  ├─ ⑪ background_tasks.add_task(                ← Spec20 唯一新增的一行
  │       mailer.send_register_notification,
  │       username,
  │       email or phone or "未填写",             ← 邮箱优先（§2.3）
  │       record["created_at"],
  │   )
  │
  └─ return _ok({"id": record["id"]})            ← 立刻返回，不等 SMTP
                                                     │
                                        （响应已在网络上）
                                                     ↓
                                    threadpool 里跑 send_register_notification
                                      未配置 → skipped 日志
                                      成功   → sent 日志
                                      失败   → failed 日志
```

**关键：`add_task` 在 `return` 之前注册，但任务在 `return` 之后才执行。** 这两件事的顺序不能反——`add_task` 必须在 `return` 语句**之前**被调用到，否则任务不会被注册。

### 5.3 一致性 / 失败语义

| 场景 | 注册接口表现 | 邮件 | 日志 |
|---|---|---|---|
| 一切正常 | 200 `{id}` | 发出 | `notify.register_mail_sent` |
| 未配 `SMTP_PASSWORD` | 200 `{id}` | 不发 | `notify.register_mail_skipped` |
| 授权码错 / 网络不通 / QQ 限流 | **200 `{id}`** | 不发 | `notify.register_mail_failed` |
| SMTP 服务器无响应 | 200 `{id}` | 不发 | `notify.register_mail_failed`（`timeout` 后，**在线程池里等，不占用事件循环**） |
| 校验失败 / 冷却期内 | 40018 / 40901 / 40902（Spec19 原样） | 不发 | Spec19 原有日志 |
| 响应发出后进程重启 | 200 `{id}` | 可能丢 | 无（任务没跑完） |

**要点：邮件永远不可能改变注册接口的响应。** `send_register_notification` 的所有路径都不抛异常，且它在响应发出之后才执行。

---

## 6. 接口约定

### 6.1 唯一变更：`POST /api/auth/register` 的函数签名

**接口契约零变化**（请求体、响应体、错误码全部照旧），只改 Python 函数签名以注入 `BackgroundTasks`：

```python
# 原（Spec19）
async def register_request(payload: schemas.RegisterRequestCreate, request: Request,
                           x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):

# 新（Spec20）—— 注意 background_tasks 是**无默认值**参数，
# Python 语法要求它排在所有带默认值的参数之前，所以插在 request 之后、x_request_id 之前。
async def register_request(payload: schemas.RegisterRequestCreate, request: Request,
                           background_tasks: BackgroundTasks,
                           x_request_id: Optional[str] = Header(default=None, alias="X-Request-Id")):
```

`main.py` 顶部 import 同步改为：

```python
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, Request, UploadFile
```

并在 `import gallery` 那一组里加 `import mailer`（字母序：`gallery` 与 `media` 之间）。

### 6.2 不变

`GET /api/auth/register-config`、`GET /api/auth/payment-qr`、三条管理端路由、`PUBLIC_AUTH_PATHS`（仍是 4 条）——**全部一字不动**。

---

## 7. 前端交互

**零改动。** 前端不知道这件事发生过，也不该知道。具体地：

- 不新增任何接口，因此 `frontend/src/api/chatApi.js` 不动。
- 注册弹窗的文案、校验、二维码、冷却提示（`RegisterModal.vue`）全部照旧。
- 管理端页面（`AdminPanel.vue`）照旧——邮件是**额外的**提醒，不是替代品，所以不需要在页面上加"已发送通知"之类的状态。
- **验收时会显式确认 `frontend/` 无 diff**（§13）。

---

## 8. 配置 / 环境变量

### 8.1 `config.py` 新增段（**有位置约束**）

追加在 **Spec19 注册块之后**（当前第 102 行 `REGISTER_DAILY_NOTICE` 之后、第 104 行 Spec18 限额块之前）：

```python
# ===== 注册申请邮件通知（Spec20）=====
# 本段必须排在 Spec19 注册块**之后**：SMTP_USER / REGISTER_NOTIFY_TO 的默认值都取
# SUPPORT_EMAIL，而 Python 是从上往下执行的（与 Spec19 §8「位置约束」同一个理）。
#
# 唯一的开关是 SMTP_PASSWORD：**留空 = 完全不发信**，注册行为与 Spec19 逐字节等价。
# 刻意不设 REGISTER_NOTIFY_ENABLED——多一个开关就多一种"配了授权码但忘了打开"的静默失败。
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.qq.com").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))          # 465 = SMTP_SSL（不是 587 STARTTLS）
SMTP_USER = os.getenv("SMTP_USER", SUPPORT_EMAIL).strip()

# 授权码，**不是** QQ 登录密码：QQ 邮箱 → 设置 → 账户 → 开启 SMTP 服务后生成。
# 只放 .env（与 JWT_SECRET 同级处理），绝不进仓库。
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# 收件人。默认跟随 SUPPORT_EMAIL，但**单独一个变量**：SUPPORT_EMAIL 是给用户看的
# 客服邮箱，哪天换成对外公开邮箱时，通知不该跟着寄到别处（§2.4）。
REGISTER_NOTIFY_TO = os.getenv("REGISTER_NOTIFY_TO", SUPPORT_EMAIL).strip()

# SMTP 超时（秒）。发信在线程池里跑，超时只影响那个线程，不影响注册请求（§2.1）。
SMTP_TIMEOUT_SECONDS = int(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))
```

> ⚠️ **位置约束是本段唯一的安装陷阱。** 若把它挪到 `SUPPORT_EMAIL`（第 83 行）之上，`SMTP_USER` / `REGISTER_NOTIFY_TO` 会直接 `NameError`。CLAUDE.md 里已经为 Spec19 记过同类约束，Spec20 是第二例。

### 8.2 `.env.example` 追加

```bash
# ---- 注册申请邮件通知（Spec20，全部可留空）----
# 不配 SMTP_PASSWORD 就完全不发信，注册行为与之前一模一样。
# SMTP_PASSWORD 是 QQ 邮箱的「授权码」，不是 QQ 登录密码。
# 生成方式（新版 QQ 邮箱界面）：mail.qq.com → 右上角头像 → 「账号与安全」
#   → 「安全设置」标签 → 「POP3/IMAP/SMTP/...服务」→ 生成授权码。
# （旧版路径是「设置 → 账户」，该入口已挪走，别再按旧教程找。）
# 授权码只完整显示一次；丢了在「设备管理 / 授权码管理」里重置，旧码随即失效。
# SMTP_HOST=smtp.qq.com
# SMTP_PORT=465
# SMTP_USER=frostyj@qq.com              # 默认跟随 SUPPORT_EMAIL
# SMTP_PASSWORD=                        # 留空 = 关闭通知
# REGISTER_NOTIFY_TO=frostyj@qq.com     # 默认跟随 SUPPORT_EMAIL
# SMTP_TIMEOUT_SECONDS=10
```

### 8.3 变量总览

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SMTP_HOST` | `smtp.qq.com` | SMTP 服务器 |
| `SMTP_PORT` | `465` | SSL 端口（不是 587） |
| `SMTP_USER` | 跟随 `SUPPORT_EMAIL` | 发件账号 |
| `SMTP_PASSWORD` | `""`（空） | **授权码；空 = 不发信，这是唯一开关** |
| `REGISTER_NOTIFY_TO` | 跟随 `SUPPORT_EMAIL` | 收件人 |
| `SMTP_TIMEOUT_SECONDS` | `10` | SMTP 超时（线程池内） |

### 8.4 `.gitignore` / `requirements.txt`

**都不动。** 授权码进 `.env`（已在 `.gitignore` 内），标准库不需要声明。

---

## 9. 错误码

**不新增任何错误码。** 这是有意的设计结果，不是遗漏：

- 邮件失败对**用户**不可见（用户的注册请求已经 200 成功了），所以没有面向用户的错误码可给。
- 对**管理员**而言，唯一的告警通道是日志的 `notify.register_mail_failed` 事件。给一个"管理员才看得见"的错误码没有承载它的接口——没有哪条路由会返回它。
- 因此 `errors.py` **零改动**。

---

## 10. 日志约定

三个新事件，沿用 Spec §10 的单行 JSON 格式。**统一遵守：不记授权码、不记用户的手机号/邮箱、不记 IP。**

| 事件 | 级别 | 字段 | 何时 |
|---|---|---|---|
| `notify.register_mail_sent` | `info` | `username`, `to` | 发送成功 |
| `notify.register_mail_skipped` | `warning` | `reason="smtp_not_configured"`, `username` | `SMTP_PASSWORD` 为空 |
| `notify.register_mail_failed` | `warning` | `username`, `error`（`类型名: 消息`） | SMTP 报错 |

**`to` 为什么可以进日志**：它是**管理员自己的**收件地址（来自配置，是固定值），不是申请人提交的 PII。排障时"到底寄给谁了"是最常问的一句。相较之下 `username` 是申请里填的，但它本来就出现在 Spec19 既有的 `auth.register_submitted` 日志里，口径一致。

**绝不进日志的三样**：`SMTP_PASSWORD`（凭据）、用户的 `phone` / `email`（PII，且已在邮件正文里，无需日志再抄一份）、`ip`（Spec19 §10 的规矩）。

---

## 11. 目录结构增量

```
Server/
  mailer.py          ← 新增（本 Spec 唯一的后端新文件）
  config.py          ← +6 个变量（位置约束见 §8.1）
  main.py            ← +BackgroundTasks import、+import mailer、+1 行 add_task、签名调整
  .env.example       ← +一段占位注释
```

**.gitignore、requirements.txt、frontend/、db.py、errors.py、schemas.py、auth.py、community/、gallery/、providers/ 全部零改动。**

---

## 12. 实施顺序（里程碑）

| # | 动作 | 完成判据 |
|---|---|---|
| 1 | `config.py` 加 Spec20 段（**Spec19 块之后**） | `python -c "import config; print(config.REGISTER_NOTIFY_TO)"` 输出 `frostyj@qq.com`（不报 `NameError`） |
| 2 | 新建 `mailer.py` | `python -c "import mailer; print(mailer.beijing_time_text('2026-09-19T07:33:12.451Z'))"` → `2026-09-19 15:33:12` |
| 3 | `main.py` 加 import（`BackgroundTasks`、`mailer`） | 服务能起来 |
| 4 | `register_request()` 加参数 + `add_task` | 见 §13 用例 1~4 |
| 5 | `.env.example` 加占位段 | — |
| 6 | `CLAUDE.md` 同步（配置段 + 关键注意事项） | — |
| 7 | 走完 §13 全部用例 | 全绿 |

**第 2 步可以独立验证**（`beijing_time_text` 是纯函数，不依赖 SMTP），建议先跑通它再动 `main.py`。

---

## 13. 验收用例（端到端 Smoke）

### 前置

在 `Server/.env` 里配好 `SMTP_USER` / `SMTP_PASSWORD`（真实授权码）/ `REGISTER_NOTIFY_TO`，重启后端。
**注意**：Spec19 的同 IP 24h 冷却会妨碍反复测试——每验一条新的提交用例，要么换 IP，要么删除上一条申请记录解封（Spec19 §2.2 的逃生通道：管理员点「删除」）。

### 主链路

```bash
# 1. 提交一条申请（两个联系方式都填）→ 200 + 一个 id
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"mailtest1","password":"abc123","wechat":"测试昵称",
       "phone":"13800138000","email":"zhang@qq.com"}'
#    → {"code":200,...,"data":{"id":N}}
#    ✅ 收件箱（frostyj@qq.com）收到一封：
#       主题：ACN-mailtest1-zhang@qq.com          ← 邮箱优先（§2.3）
#       正文：注册时间是2026-09-19 15:33:12，请立即审批！   ← 北京时间（§2.2）
#    ✅ 日志：notify.register_mail_sent
#    ✅ **注册接口的响应时间与不配 SMTP 时无肉眼差别**（§2.1 的核心验收点）

# 2. 只填手机号（换 IP 或先删掉上一条记录）
#    → 主题：ACN-mailtest2-13800138001            ← 回落到手机号

# 3. 只填邮箱
#    → 主题：ACN-mailtest3-li@qq.com

# 4. 北京时间正确性：申请一条，把邮件里的时间与
#    sqlite3 artcn.db "SELECT created_at FROM register_requests ORDER BY id DESC LIMIT 1"
#    的输出对照 —— 邮件时间应比库里的 UTC 时间**恰好早 8 小时**
#    （例：库里 2026-09-19T07:33:12.451Z → 邮件 2026-09-19 15:33:12）
```

### 降级链路（**本 Spec 最重要的两条**）

```bash
# 5. 清空 .env 里的 SMTP_PASSWORD，重启，再提交一条申请
#    → 接口仍然 200 + id
#    → 没有邮件
#    → 日志：notify.register_mail_skipped, reason=smtp_not_configured
#    → **管理端列表里这条申请照常出现**（邮件不影响业务，§5.3）

# 6. 把 SMTP_PASSWORD 改成一个错的授权码，重启，再提交一条申请
#    → 接口**仍然 200 + id**          ← 如果这里返回了 5xx，本 Spec 就没做对
#    → 没有邮件
#    → 日志：notify.register_mail_failed，error 里含 SMTPAuthenticationError
#    → **管理端列表里这条申请照常出现**
#    → 后端进程**没有崩、没有卡**，紧接着的其它请求照常响应

# 7. 把 SMTP_HOST 改成 10.255.255.1（黑洞地址），重启，提交
#    → 接口仍然 200（响应**不等待**那 10 秒超时）
#    → 约 10 秒后日志出现 notify.register_mail_failed（timeout）
#    → 这 10 秒期间其它接口**照常响应**  ← 验证同步 def 走的是线程池而非事件循环（§2.1）
```

### 零回归

```bash
# 8. git diff --stat 应只包含：Server/mailer.py(新增)、Server/config.py、
#    Server/main.py、Server/.env.example、CLAUDE.md（+ 本 Spec）
#    → 逐字节确认 **frontend/ 无 diff、db.py 无 diff、errors.py 无 diff、
#      schemas.py 无 diff、requirements.txt 无 diff**

# 9. Spec19 全链路回归：注册 → 管理端看到 pending → 同意 → 新号能登录
#    （§13 的 Spec19 用例 3、6、7、8）→ 行为与 Spec19 完全一致

# 10. 审批/拒绝/删除三条管理端路由 → **不发任何邮件**（收件箱零新增）
```

---

## 14. 补充

### 14.1 与 Spec19「注册申请是台账」的关系

Spec19 §2.4 定的调子是：申请记录**只增不隐**，同意/拒绝都保留，只有「删除」才真删行。**本 Spec 不碰这条台账的任何一格**——邮件是一条纯粹向外的旁路，发完即止，不写库、不改状态、不影响任何一条记录的可见性。

换句话说：**把 `.env` 里的 `SMTP_PASSWORD` 清空，你就回到了 Spec19。** 这个"可完全回退"的性质是本 Spec 设计上的要求，也是 §13 用例 5 要验的东西。

### 14.2 为什么正文只有一句话，不带链接

管理端的入口在 SPA 内部（没有 vue-router，是 `AdminPanel.vue` 的一个视图状态），**没有一条可以直接跳过去的 URL**。硬造一个（比如 `?admin=1` 深链接，Spec19 §7.4 已有 `?register=1` 的先例）意味着要在邮件模板里维护一个前端路由约定，而收益只是省你点两下。

真正需要处理申请时，你本来就会打开管理端。所以正文保持用户原话的那一句，不加链接。

### 14.3 将来若要改的地方（写入本文档，供实际用起来之后回头改）

| 想改什么 | 改哪 | 成本 |
|---|---|---|
| 换个收件人 | `.env` 里设 `REGISTER_NOTIFY_TO` | 零代码 |
| 换成别的发件邮箱（163 / 企业邮） | `.env` 里设 `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | 零代码。注意 587 端口是 STARTTLS，本实现用的是 `SMTP_SSL`（465）——换 587 要改 `mailer.py` 那两行 |
| 加微信昵称到正文 | `mailer.py` 的 `set_content`（要一并改函数签名，让 `main.py` 把 `wechat` 传进来） | 约 3 行 |
| 一次来多条时合并成一封 | 需要引入缓冲 + 定时器，**不建议** | 大。且与"来一条推一条"的初衷相悖 |
| 临时关掉通知 | 清空 `SMTP_PASSWORD` 并重启 | 零代码 |
