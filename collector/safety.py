from __future__ import annotations

import re

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")

HIGH_RISK_KEYWORDS = [
    "博彩", "赌博", "赌场", "六合彩", "百家乐", "跑分", "洗钱", "资金盘",
    "社工库", "开盒", "查档", "轰炸机", "呼死你", "ddos", "钓鱼",
    "外围", "约炮", "迷奸", "全套", "品茶", "成人视频", "里番",
    "破解软件", "破解版", "盗刷", "黑卡", "免流", "暗网",
]


def contains_chinese(text: str | None) -> bool:
    return bool(CJK_RE.search(text or ""))


def is_high_risk_text(text: str | None) -> bool:
    value = (text or "").lower()
    return any(keyword in value for keyword in HIGH_RISK_KEYWORDS)


def safe_snippet(text: str | None, max_len: int = 500) -> str:
    value = (text or "").replace("\r", " ").replace("\n", " ").strip()
    value = re.sub(r"\s+", " ", value)
    if len(value) > max_len:
        return value[: max_len - 3] + "..."
    return value
