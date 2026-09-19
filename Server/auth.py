"""认证与授权（Spec2 §5 / §6 / §9）：bcrypt 哈希 + JWT 签发/校验 + 登录限速。

- 密码只存 bcrypt 加盐哈希，绝不存明文；密码不出现在任何日志 / 响应体 / 前端。
- JWT 只携带 user_id / username，不写 is_admin —— 每次请求实时查库取最新权限，
  因此撤销某用户管理员立即生效（Spec2 §5.2）。
- 登录失败按 IP 限速（内存，防暴力破解）：窗口内失败超限返回 42901。
  Spec22 §2.6 起**验证码猜错也算**：`login-by-email` / `verify-email-code` /
  `reset-password` 与注册提交四处的码校验失败都调同一个 record_login_failure。
"""
import logging
import time
from typing import Any

import bcrypt
import jwt

import config
from errors import AuthTokenError

logger = logging.getLogger("auth")

ALGORITHM = "HS256"

# 密码长度规则（**全仓唯一来源**）。Spec22 §2.10：把下限从写死的 6 降成 2，
# 同时把 Spec2 留下的死代码 MAX_PASSWORD_LEN 一起用起来——设定密码的路原来有
# 三条，各写各的字面量（注册 6~72、管理员建号 ≥6、重置 ≥6）。现在三处都引用
# 这两个常量，"改一处就够了"。
# ⚠️ 初始管理员那道 ≥6（db.create_initial_admin）**故意不跟着改**：它不是用户
#    输入，是部署者自己写在 .env 里的口令，那条线是防"顺手写 123 当管理员密码"
#    的（§2.10）。
MIN_PASSWORD_LEN = 2

MAX_PASSWORD_LEN = 72          # bcrypt 只处理前 72 字节，上限在此截断校验

# ---------- 登录限速（内存）----------
# 限速的对象是**IP**，不是账号：同一个 IP 猜密码和猜验证码是一回事（§2.6）。
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_MAX_FAILURES = 5
_login_failures: dict[str, list[float]] = {}


def client_ip(request: Any) -> str:
    """取客户端 IP；内网穿透 / 反代场景优先取 X-Forwarded-For 首个 IP。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune(ip: str) -> list[float]:
    now = time.time()
    cutoff = now - _LOGIN_WINDOW_SECONDS
    lst = [t for t in _login_failures.get(ip, []) if t >= cutoff]
    _login_failures[ip] = lst
    return lst


def is_login_blocked(ip: str) -> bool:
    """该 IP 是否已被限速（Spec22 §2.6 起也管"验证码猜错"）。

    函数名保留 `login_*` 不改：改名要让 main.py 四处调用点 + Spec2 文档全线
    对不上，而收益只是措辞准确——本仓的做法是在 docstring 里写清楚。
    """
    return len(_prune(ip)) >= _LOGIN_MAX_FAILURES


def record_login_failure(ip: str) -> None:
    """记一次失败（密码错 / 验证码错，两者同一个计数器，§2.6）。

    为什么验证码也要计：4 位数字只有 9000 种可能，10 分钟 TTL 内不限次数地猜，
    一个脚本几分钟就能撞开任意一个已知邮箱的账号——这不是理论风险，是邮箱登录
    这条通道自己开出来的洞。5 次 / 5 分钟 / IP 之后概率降到 < 0.12%。
    """
    _prune(ip)
    _login_failures[ip].append(time.time())


def reset_login_failures(ip: str) -> None:
    _login_failures.pop(ip, None)


# ---------- bcrypt ----------

def hash_password(password: str) -> str:
    """生成加盐 bcrypt 哈希（ASCII 字符串，入库）。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码与库中哈希是否匹配；哈希损坏按不匹配处理。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ---------- JWT ----------

def create_token(user_id: int, username: str,
                 expires_seconds: int | None = None) -> str:
    """签发 JWT。仅携带身份（user_id / username），权限实时查库。"""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + (expires_seconds or config.JWT_EXPIRE_SECONDS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """校验并解析 token；缺失密钥 / 无效 / 过期 → AuthTokenError(40103)。"""
    if not config.JWT_SECRET:
        raise AuthTokenError("后端未配置 JWT_SECRET")
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthTokenError("登录态已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthTokenError("登录态无效") from exc
    user_id = payload.get("sub")
    username = payload.get("username")
    if user_id is None or username is None:
        raise AuthTokenError("登录态无效")
    return {"user_id": int(user_id), "username": username}
