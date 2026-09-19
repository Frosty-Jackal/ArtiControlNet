"""邮箱验证码的生成与场景白名单（Spec22 §5.4）。

只做两件事：生成一个 4 位码、给出合法的 purpose 列表。
**校验**（TTL、冷却、任一命中）全部在 db 层用 SQL 做 —— 它需要读库，
放在这里只会多绕一层（§14.2：这也是 timefmt.py 的同一种切法）。

不放进 auth.py 的理由：那个文件的职责是"密码哈希 + JWT + 登录限速"，全是
**不依赖库**的纯函数与内存状态；而验证码的三条规则必须查库。搬过去就要让
auth.py import db，而它被 main.py 与 db.py 两边都碰，循环引用的风险立刻出现。
"""
import secrets

# 场景白名单：发码与校验都按它比对，不拼接外部输入（本仓的既有做法）。
# register = 注册前验证邮箱；login = 邮箱验证码登录；reset = 修改密码前的身份验证。
# 校验时**必须**按 purpose 匹配，否则一个为"注册"发的码可以直接拿去登录（§2.2）。
PURPOSES = ("register", "login", "reset")

# 4 位是**契约**，不是旋钮：邮件正文的措辞、前端 maxlength 都绑死它（§2.3）。
# 想改长度要同时改这三处，所以不做成环境变量。
CODE_LENGTH = 4

# 取值 1000~9999，**刻意不带前导零**：`0042` 这种码用户十有八九会输成 `42`，
# 然后看到"验证码错误"而完全不知道错在哪（§2.3）。熵少 0.15 bit，可以忽略。
_CODE_MIN = 10 ** (CODE_LENGTH - 1)
_CODE_SPAN = 9 * _CODE_MIN


def generate_code() -> str:
    """返回一个 4 位数字串（1000~9999）。用 secrets：验证码是凭据。"""
    return str(_CODE_MIN + secrets.randbelow(_CODE_SPAN))
