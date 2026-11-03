"""项目方待办通知中心（L-134，项目方原话：“http://127.0.0.1:5173/#/queue 任何需要我做的，在这里发 notification，点击跳到对应页面 approval or reject”）。

GET /api/owner/inbox  = 原“待你看”队列（owner_queue.build：必须拍板 / 机签抽检 / 审美挑选 —— 资产挑选、风格挑选、成人镜触发等
                         由各 loop 投递到 data/owner_queue/requests.json 的事都在里面）+ 写作闸门（每部在写的剧：故事线 / 各集闸门）。
                         顶栏“待你看”数字、浏览器标签页标题上的数字、#/queue 页都读这一个接口，只有一个数据来源。
                         返回结构 = /api/owner/queue 的超集：多一类 kind="gate"（counts.gate），每条带 link（深链接：带 run 和锚点）。
“处理完的自动消失”：闸门状态由各剧 autoflow / owner_gates 现算，项目方点了“用这版 / 修改”闸门状态变了就不再出现，不另存一份。
L-123：通知不放“不要”；reject = 到对应页面点“修改”。

给别的闸门接入：在 gate_items() 里加一类，或往 data/owner_queue/requests.json 投一条 kind=decide（带 link 即可跳转）。
通知直说（L-172 分期 1，11-03）：每条带 say_what / why / actions[] / block_level（owner_queue.humanize）；要你做的在前（red → yellow），
  只读告知（readonly[]：总调度在定的、卡点板上阻断生产线的工单）在后、没有按钮、不计入 count（顶栏数字只数要你做的）。
"""
from __future__ import annotations

import sys
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
    gates = OQ.enrich(gate_items(root), root)
    items = sorted(gates + list(q["items"]), key=OQ.sort_key)     # 要你做的在前（按阻塞程度），同级按类型
    counts = {"gate": len(gates), **q["counts"]}
    return {**q, "schema": "nsfs.owner_inbox/2", "items": items, "count": len(items), "counts": counts,
            "levels": OQ.level_counts(items), "readonly": readonly_items(root, q)}


READONLY_MAX = 3


def _issue_word(i: dict) -> str:
    what = OQ.plain(str(i.get("what") or ""))
    what = what.split("：", 1)[0] if len(what) > 70 else what
    return (what[:70] + ("…" if len(what) > 70 else "")).rstrip("，、；")


def readonly_items(root: Path, q: dict | None = None) -> list[dict]:
    """只读告知（灰、无按钮、不进 count）：① 总调度在定的事；② 卡点板上阻断生产线、还没关的工单（最新 3 条）——
    “{卡点}，系统已派 {who} 处理，不需要你做事”。读不出来就空列表，不拖垮通知中心"""
    out: list[dict] = []
    mw = (q or {}).get("master_waits") or {}
    if mw.get("n"):
        out.append({"id": "ro:master_waits", "kind": "info", "sub_kind": "info", "block_level": "grey", "level_label": OQ.LEVEL_LABEL["grey"],
                    "say_what": f"总调度在定 {mw['n']} 项，不需要你做事", "why": "等总调度的事不打扰你；定了需要你拍板的会另出一条", "actions": [],
                    "title": mw.get("title") or "", "detail": "", "source": "总调度", "at": "", "media": [], "scores": [], "options": [], "recommend": None, "link": None})
    try:
        import json as _json  # noqa: PLC0415
        p = root / "data" / "pipeline" / "issues.jsonl"
        live: dict[str, dict] = {}
        if p.is_file():
            for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()[-600:]:
                if not ln.strip():
                    continue
                try:
                    e = _json.loads(ln)
                except ValueError as e:   # arch-ok: 坏行只跳过并记 stderr，不拖垮只读告知
                    print(f"[owner_inbox] issues.jsonl 坏行跳过：{e!r}"[:200], file=sys.stderr)
                    continue
                if e.get("event") == "close":
                    live.pop(e.get("id"), None)
                elif e.get("event") == "open" and e.get("id"):
                    live[e["id"]] = e
        blocking = [i for i in live.values() if i.get("blocking")]
        for i in sorted(blocking, key=lambda x: str(x.get("time") or ""), reverse=True)[:READONLY_MAX]:
            who = str(i.get("who") or "系统")
            out.append({"id": f"ro:{i['id']}", "kind": "info", "sub_kind": "info", "block_level": "grey", "level_label": OQ.LEVEL_LABEL["grey"],
                        "say_what": f"{_issue_word(i)}，系统已派 {who} 处理，不需要你做事",
                        "why": (f"{OQ._ep_word(i.get('episode'))}卡在这一步；" if i.get("episode") else "") + "处理完这条会自己消失", "actions": [],
                        "title": str(i.get("what") or "")[:120], "detail": str(i.get("fix_hint") or "")[:200], "source": who, "at": str(i.get("time") or ""),
                        "media": [], "scores": [], "options": [], "recommend": None, "link": None, "run": i.get("run"), "episode": i.get("episode")})
    except Exception as e:  # noqa: BLE001  只读告知读不出：记 stderr、返回已算出的部分（不进 count，不算队列读取失败）
        print(f"[owner_inbox] 只读告知（卡点板）读不出：{e!r}"[:200], file=sys.stderr)
    return out


@router.get("/api/owner/inbox")
def get_inbox():
    return inbox()
