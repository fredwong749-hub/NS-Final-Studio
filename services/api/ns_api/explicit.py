"""
露骨红标（兼容层）。2026-10-30 项目方要求取消 Claude 加的成人过滤器后，这里不再拦任何动作：
`hold()` 永远返回 None，画布仍可读 `explicit_hold` 字段（恒为 None），/api/explicit-holds 返回空表。

保留模块是为了不改动画布与旧客户端的字段；真正的判定来源（gpu3 status.json / BLOCKED.jsonl / 剧本 H3校验）
只作为历史记录存在，不再影响出图、重出、生成建议或按集运行。
"""
from __future__ import annotations

CODE = "explicit_content_not_supported"
LABEL = "露骨·项目方自行处理"


def hold(s, slug: str) -> dict | None:
    """永远返回 None：露骨红标不再阻止任何自动动作。"""
    return None


def refuse_detail(shot_id: str) -> str:
    """兼容旧调用方；当前不会抛出。"""
    return f"{shot_id} 曾标为露骨（{CODE}），过滤器已取消"
