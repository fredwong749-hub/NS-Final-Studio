"""项目方待办通知中心（L-134，项目方原话：“http://127.0.0.1:5173/#/queue 任何需要我做的，在这里发 notification，点击跳到对应页面 approval or reject”）。

GET /api/owner/inbox  = 原“待你看”队列（owner_queue.build：必须拍板 / 机签抽检 / 审美挑选 —— 资产挑选、风格挑选、成人镜触发等
                         由各 loop 投递到 data/owner_queue/requests.json 的事都在里面）+ 写作闸门（每部在写的剧：故事线 / 各集闸门）。
                         顶栏“待你看”数字、浏览器标签页标题上的数字、#/queue 页都读这一个接口，只有一个数据来源。
                         返回结构 = /api/owner/queue 的超集：多一类 kind="gate"（counts.gate），每条带 link（深链接：带 run 和锚点）。
“处理完的自动消失”：闸门状态由各剧 autoflow / owner_gates 现算，项目方点了“用这版 / 修改”闸门状态变了就不再出现，不另存一份。
L-123：通知不放“不要”；reject = 到对应页面点“修改”。

给别的闸门接入：在 gate_items() 里加一类，或往 data/owner_queue/requests.json 投一条 kind=decide（带 link 即可跳转）。
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter

from ns_api import look_confirm as _LC  # noqa: F401  V2CUT-O：启动即登记 owner_pick 的 look 处理器（通知里一键确认本集造型）
from ns_api import owner_queue as OQ
from ns_api import script_library as SLIB

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["owner-inbox"])

KIND_LABEL_GATE = "要你看"
_CLOSED = {"archived", "deleted", "trashed", "done", "finished", "completed", "delivered"}


def _flow_link(run: str, anchor: str = "story") -> str:
    return f"#/script-create?new=1&flow={run}&anchor={anchor}"


def _item(run: str, key: str, title: str, detail: str, at: str | None, anchor: str = "story") -> dict:
    return {"id": f"gate:{run}:{key}", "kind": "gate", "kind_label": KIND_LABEL_GATE, "category": "gate", "category_label": "写作闸门",
            "title": title, "detail": detail, "source": "写作流程", "run": run, "at": at or "", "media": [], "scores": [], "options": [],
            "recommend": None, "link": _flow_link(run, anchor)}


def gate_items(root: Path = REPO) -> list[dict]:
    """每部在写的剧里等项目方的闸门（故事线 / 各集）；只读各剧 autoflow 状态，处理完就不再产生"""
    from ns_api import script_autoflow as SA
    out: list[dict] = []
    reg = SLIB._registry().get("runs") or {}
    for run, meta in reg.items():
        if (meta or {}).get("status") in _CLOSED:
            continue
        d = root / "data" / "pipeline" / "runs" / run
        if not (d / "autoflow.json").is_file():
            continue
        try:
            st = SA.status(run)
        except Exception:  # noqa: BLE001  某部剧读不出来不拖垮整个通知中心
            continue
        name = SLIB.run_title_of(d) or "新剧（未定名）"
        gate = ((st.get("owner_gates") or {}).get("gates") or {}).get("P1") or {}
        rv = st.get("p1_review") or {}
        od = rv.get("owner_direction") or {}
        thr = (rv.get("threshold") or {}).get("min_mean", 34)
        latest = rv.get("latest") or {}
        if gate.get("status") in (None, "pending"):   # approved / revise_requested / revising / redirect_requested 都不是等项目方；p1_review_failed / p1_fill_failed 是转总调度，也不进通知
            if st.get("verdict") == "owner_direction":
                why = od.get("why") or "这一版没到门槛"
                fill = od.get("fill_note") or ""
                out.append(_item(run, "P1", f"《{name}》故事线没到门槛，等你定方向",
                                 f"{why}，总调度转给你定方向：用这版、修改，或在“修改”里选“换个方向重写”。{fill}", od.get("at")))
            elif st.get("verdict") == "awaiting_owner_p1":
                mean = latest.get("mean")
                out.append(_item(run, "P1", f"《{name}》故事线写好了，等你看",
                                 (f"三位评委打了 {mean}，过了 {thr} 分的门槛。" if mean is not None else "评审过了门槛。") + "你点“用这版”才会接着写各集大纲；想改点“修改”。",
                                 latest.get("at") or st.get("started")))
        for n, e in sorted((st.get("episodes") or {}).items(), key=lambda kv: int(kv[0])):
            v = (e or {}).get("verdict") or ""
            if v.startswith("awaiting_owner") and v not in ("awaiting_owner_p1", "owner_direction") and not (int(n) == 1 and out and out[-1]["run"] == run):
                out.append(_item(run, f"ep{int(n):02d}", f"《{name}》第 {int(n)} 集等你看", (e or {}).get("next_action") or "这一集写好了，等你点“用这版”或“修改”。", None, "eps"))
    return out


def inbox(root: Path = REPO, now: float | None = None) -> dict:
    try:                    # V2CUT-O 11-03：资产包剧每集“确认造型”投进通知（已有不重投、已确认 / 排期改了的关掉）；出错不拖垮通知中心
        from ns_api import look_confirm as LC
        LC.sync_picks(root)
    except Exception:  # noqa: BLE001
        pass
    q = OQ.build(root, now)
    gates = gate_items(root)
    items = gates + list(q["items"])
    counts = {"gate": len(gates), **q["counts"]}
    return {**q, "schema": "nsfs.owner_inbox/1", "items": items, "count": len(items), "counts": counts}


@router.get("/api/owner/inbox")
def get_inbox():
    return inbox()
