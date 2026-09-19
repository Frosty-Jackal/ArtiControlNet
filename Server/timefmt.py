"""UTC ISO ↔ 北京时间展示串（Spec21 §5.2，Spec20 §2.2 的实现搬家）。

唯一职责：把库里存的 UTC ISO 串转成给人看的北京时间。
搬出 mailer.py 的原因：Spec21 之后 main.py 的三个管理端列表也要用它
（Spec21 §2.2），而一个叫 mailer 的模块不该拥有通用的时间格式化。
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("timefmt")

# 中国全境单一时区、无夏令时，所以固定 +08:00 偏移是**正确**的，不只是权宜。
# 刻意不用 zoneinfo("Asia/Shanghai")：Windows 没有系统 tz 数据库，
# 未安装 tzdata 包时 ZoneInfo 会抛 ZoneInfoNotFoundError，而部署机正是 Windows。
_BEIJING = timezone(timedelta(hours=8))


def beijing_time_text(created_at_iso: str) -> str:
    """库里的 UTC ISO 串（2026-09-19T07:33:12.451Z）→ '2026-09-19 15:33:12'。

    解析失败时**原样返回**：宁可显示得难懂，也不让调用方（发信 / 列表接口）出错。
    """
    try:
        dt = datetime.strptime(created_at_iso, "%Y-%m-%dT%H:%M:%S.%fZ")
    except (ValueError, TypeError):
        return str(created_at_iso)
    return dt.replace(tzinfo=timezone.utc).astimezone(_BEIJING).strftime("%Y-%m-%d %H:%M:%S")
