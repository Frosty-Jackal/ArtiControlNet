"""认证与授权（Spec2 §5 / §6 / §9）：bcrypt 哈希 + JWT 签发/校验 + 登录限速。

- 密码只存 bcrypt 加盐哈希，绝不存明文；密码不出现在任何日志 / 响应体 / 前端。
- JWT 只携带 user_id / username，不写 is_admin —— 每次请求实时查库取最新权限，
  因此撤销某用户管理员立即生效（Spec2 §5.2）。
- 登录失败按 IP 限速（内存，防暴力破解）：窗口内失败超限返回 42901。
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
MAX_PASSWORD_LEN = 72          # bcrypt 只处理前 72 字节，上限在此截断校验

# ---------- 登录限速（内存）----------
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
    return len(_prune(ip)) >= _LOGIN_MAX_FAILURES


def record_login_failure(ip: str) -> None:
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
