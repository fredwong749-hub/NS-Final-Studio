"""新建剧本：故事提纲 → 写作链 P0→P1→P2→P3→P4（UIRSI 2026-10-31）。

项目方在 #/script-create（① 新建剧本）填 P0 Brief → 本路由起后台线程，逐段调用 CHAINSPEC 的
tools/pipeline/run_chain.run(upto=P1…P4)。run_chain 会复用已通过的产物，所以每次 upto 加一段就等于逐段推进，
每段完成后 state 立刻可见。每段的产物都可以查看、编辑原文（编辑后重新校验，下游产物挪到 superseded/，不删）。
没过校验时可以“返修”：把这一段和它下游的产物挪开，再让写作模型重写这一段。
P4 通过后“送去导入”：原样存成剧本输入草稿（data/staging_input），之后仍走原导入流程，由项目方勾选确认，不绕过。

系统只收发和校验格式，不写、不改、不评价剧本内容。写作模型 = config/llm_providers.json 的用途 script_write。
运行目录：data/pipeline/runs/ui_<时间>_epNN/（与 CHAINSPEC 的 runs 同目录；列表也会显示命令行跑的 runs，只读）。

接口：
  GET  /api/story-runs                      列表（最新在上）
  POST /api/story-runs                      {brief, episode, upto?, budget_usd?, reasoning?} → 新建并开始
  GET  /api/story-runs/{id}                 状态 + 每段（状态、轮数、花费、校验问题）
  GET  /api/story-runs/{id}/artifact/{node} 某段产物原文（node = P0…P4）
  PUT  /api/story-runs/{id}/artifact/{node} {text} 项目方改原文 → 重新校验，下游挪到 superseded/
  POST /api/story-runs/{id}/retry           {link?} 返修：重写这一段（默认第一个没过的段）并继续
  POST /api/story-runs/{id}/resume          {upto?} 继续 / 写到更后面的一段
  POST /api/story-runs/{id}/send-to-import  P4 通过后存为导入候选（导入仍要项目方确认）
"""
from __future__ import annotations

from ns_api import run_paths as _RP   # K-OPS-F24：按当前剧取路径（V1 已归档，不在网页显示）
import json
import re
import shutil
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

REPO = Path(__file__).resolve().parents[3]
RUNS = REPO / "data" / "pipeline" / "runs"
STATE = "ui_state.json"
LINKS = ("P0-P1", "P1-P2", "P2-P3", "P3-P4")
NODE_OF = {"P0-P1": "P1", "P1-P2": "P2", "P2-P3": "P3", "P3-P4": "P4"}
LINK_OF = {v: k for k, v in NODE_OF.items()}
NODE_LABEL = {"P0": "故事提纲", "P1": "全剧故事线", "P2": "单集大纲", "P3": "单集剧本", "P4": "剧本分镜"}
ACTIVE = ("queued", "running")

router = APIRouter(tags=["story-runs"])
_lock = threading.Lock()
_threads: dict[str, threading.Thread] = {}
_done: dict[str, threading.Event] = {}      # T-SR-01：每次写作一个完成事件（线程写完状态后才置位），等待方按事件同步，不靠线程超时


def _rc():
    """CHAINSPEC 的链条执行器（按需导入；chainlib 会补齐 packages / services 的 sys.path）"""
    p = str(REPO / "tools" / "pipeline")
    if p not in sys.path:
        sys.path.insert(0, p)
    import run_chain  # noqa: PLC0415
    return run_chain


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return str(p)


def _run_dir(run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,80}", run_id or ""):
        raise HTTPException(404, f"没有这个运行：{run_id}")
    d = RUNS / run_id
    if not d.is_dir():
        raise HTTPException(404, f"没有这个运行：{run_id}")
    return d


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_jsonl(p: Path) -> list[dict]:
    out = []
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def _write_state(d: Path, st: dict) -> None:
    st["updated_at"] = _now()
    tmp = d / (STATE + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / STATE)


def _episode_of(d: Path, st: dict | None) -> int | None:
    if st and st.get("episode"):
        return int(st["episode"])
    rj = _read(d / "run.json") or {}
    if rj.get("episode"):
        return int(rj["episode"])
    # V2-WALK 11-02：全自动链（script_autoflow / claude_agent）跑的剧没有 ui_state / run.json，P2 前推不出集号 →
    # 网页只显示 P0、看不到已交的 P1 故事线；按 autoflow.json 的当前集补上
    af = _read(d / "autoflow.json") or {}
    if af.get("episode") or af.get("latest_episode"):
        return int(af.get("episode") or af.get("latest_episode"))
    for f in d.glob("P2_ep*_outline.json"):
        m = re.search(r"ep(\d+)", f.name)
        if m:
            return int(m.group(1))
    return None


def _fname(link: str, ep: int) -> str:
    return dict(_rc().STAGES)[link].format(ep=ep)


def _fname_light(link: str, ep: int) -> str:
    """与 run_chain.STAGES 同名（列表里不为了文件名去导入 run_chain）"""
    return {"P0-P1": "P1_storyline.json", "P1-P2": f"P2_ep{ep:02d}_outline.json", "P2-P3": f"P3_ep{ep:02d}_screenplay.json",
            "P3-P4": f"P4_ep{ep:02d}.md"}[link]


def _ledger_usd(tag: str | None) -> float:
    if not tag:
        return 0.0
    led = RUNS.parent / "ledger.jsonl"
    tot = 0.0
    try:
        for ln in led.read_text(encoding="utf-8").splitlines():
            try:
                x = json.loads(ln)
            except ValueError:
                continue
            if x.get("tag") == tag:
                tot += float(x.get("usd") or 0)
    except OSError:
        pass
    return round(tot, 4)


def series_eps(d: Path) -> list[int]:
    """整季运行（SERIES agent，例 data/pipeline/runs/series10_v1/）：根目录放 P0 / P1，每集 epNN/ 子目录放 P2–P4"""
    out = []
    for c in d.iterdir() if d.is_dir() else []:
        m = re.fullmatch(r"ep(\d{2,3})", c.name)
        if m and c.is_dir():
            out.append(int(m.group(1)))
    return sorted(out)


def _node_path(d: Path, link: str, ep: int) -> Path:
    name = _fname_light(link, ep)
    if link != "P0-P1" and series_eps(d):
        return d / f"ep{ep:02d}" / name
    return d / name


def _alive(run_id: str) -> bool:
    t = _threads.get(run_id)
    return bool(t and t.is_alive())


def _stage_rows(d: Path, st: dict | None, ep: int | None) -> list[dict]:
    rows = [{"node": "P0", "label": NODE_LABEL["P0"], "link": None, "file": "P0_brief.json",
             "status": "ok" if (d / "P0_brief.json").exists() else "missing", "issues": []}]
    if ep is None:
        return rows
    cur = (st or {}).get("current")
    running = (st or {}).get("status") in ACTIVE and _alive(d.name)
    for link in LINKS:
        node = NODE_OF[link]
        name = _fname_light(link, ep)
        out = _node_path(d, link, ep)
        rep = _read(out.parent / f"{name}.report.json")
        row = {"node": node, "label": NODE_LABEL[node], "link": link, "file": name, "exists": out.exists()}
        if running and cur == link:
            row["status"] = "running"
            row["rounds_done"] = len(list((d / "raw").glob(f"{link}.r*.txt"))) if (d / "raw").is_dir() else 0
        elif rep:
            row["status"] = rep.get("status") or ("ok" if (rep.get("report") or {}).get("ok") else "needs_writer")
            r = rep.get("report") or {}
            row["blocking"], row["warnings"] = r.get("blocking", 0), r.get("warnings", 0)
            iss = r.get("issues") or []
            row["issues"] = sorted(iss, key=lambda i: i.get("level") != "block")[:300]
            hist = rep.get("rounds") or []
            row["rounds"] = len(hist)
            row["usd"] = round(sum(float(h.get("usd") or 0) for h in hist), 4)
            row["edited_by"] = rep.get("edited_by")
        elif out.exists():
            row["status"] = "unchecked"   # 命令行旧 runs：有产物、没有报告
        else:
            row["status"] = "pending"
        row.setdefault("issues", [])
        rows.append(row)
    return rows


def _autoflow_brief(d: Path) -> dict | None:
    """列表里带上写作流程状态（前端 p1Status 要用：verdict、P1G 段、P1 闸门、评审最新一轮和轮数上限），不另写一套；没走写作流程 = None"""
    if not (d / "autoflow.json").is_file():
        return None
    try:
        from ns_api import script_autoflow as SA
        st = SA.status(d.name)
    except Exception:  # noqa: BLE001  列表不因某部剧的状态读不出而整个挂掉
        return None
    rv = st.get("p1_review") or {}
    latest = rv.get("latest") or {}
    return {"verdict": st.get("verdict"), "stages": [{"id": x.get("id"), "status": x.get("status")} for x in (st.get("stages") or []) if x.get("id") == "P1G"],
            "owner_gates": {"enabled": (st.get("owner_gates") or {}).get("enabled"), "gates": {"P1": ((st.get("owner_gates") or {}).get("gates") or {}).get("P1")}},
            "p1_review": {"latest": {"n": latest.get("n"), "passed": latest.get("passed"), "mean": latest.get("mean")} if latest else None, "threshold": rv.get("threshold")}}


def _registry_status(run_id: str) -> str | None:
    """config/pipeline/runs.json 里这部剧的状态（producing / paused / archived …）；没登记 = None（测试 run / 旧稿）"""
    from ns_api.script_library import _registry
    return ((_registry().get("runs") or {}).get(run_id) or {}).get("status")


def _title_of(d: Path) -> str:

    from ns_api.script_library import run_title_of   # 剧名只有一个来源（和剧本库同一个函数）

    return run_title_of(d)





def _summary(d: Path, full: bool = False, ep_sel: int | None = None) -> dict:
    st = _read(d / STATE)
    eps = series_eps(d)
    ep = ep_sel if (ep_sel and ep_sel in eps) else (eps[0] if eps else _episode_of(d, st))
    stages = _stage_rows(d, st, ep)
    status = (st or {}).get("status")
    if status in ACTIVE and not _alive(d.name):
        status = "interrupted"   # API 重启打断：已通过的产物都在，点“继续”接着写
    if not st:
        rj = _read(d / "run.json") or {}
        last = (rj.get("stages") or [{}])[-1]
        status = last.get("status") or "cli"
    brief = _read(d / "P0_brief.json") or {}
    out = {"id": d.name, "ui": bool(st), "episode": ep, "status": status, "current": (st or {}).get("current"),
           "upto": (st or {}).get("upto", "P4"), "created_at": (st or {}).get("created_at") or time.strftime(
               "%Y-%m-%dT%H:%M:%S", time.localtime(d.stat().st_mtime)), "updated_at": (st or {}).get("updated_at"),
           "title": _title_of(d), "outline_head": (brief.get("outline") or "")[:80],
           "registry_status": _registry_status(d.name), "autoflow": _autoflow_brief(d), "episodes": brief.get("episodes"), "error": (st or {}).get("error"), "budget_usd": (st or {}).get("budget_usd"),
           "spent_usd": max(_ledger_usd((st or {}).get("tag")), round(sum(float(s.get("usd") or 0) for s in stages), 4)),
           "sent_to_import": ((st or {}).get("sent_by_ep") or {}).get(str(ep)) if eps else (st or {}).get("sent_to_import"),
           "series": bool(eps), "readonly": bool(eps),
           "stages": [{k: v for k, v in s.items() if k != "issues"} | {"n_issues": len(s.get("issues") or [])} for s in stages]}
    if eps:   # 整季：每集一行 P2–P4 状态（矩阵）+ 整季花费
        out["series_eps"] = [{"ep": e, "stages": {r["node"]: r["status"] for r in _stage_rows(d, st, e)[2:]}} for e in eps]
        p4 = [x["stages"].get("P4") for x in out["series_eps"]]
        out["status"] = "ok" if all(v == "ok" for v in p4) else "needs_writer" if any(v in ("needs_writer", "budget_stop") for v in p4) else "running"
        out["ui"] = False
        led = [x for x in (_read_jsonl(d / "drive_log.jsonl")) if x.get("spent") is not None]
        if led:
            out["spent_usd"] = round(float(led[-1]["spent"]), 4)
    if full:
        out["stages"] = stages
        out["brief"] = brief
        out["model"] = (st or {}).get("model")
        out["history"] = (st or {}).get("history", [])[-30:]
    return out


# ----------------------------------------------------------------------------- 后台执行
def _worker(run_id: str) -> None:
    d = RUNS / run_id
    st = _read(d / STATE) or {}
    try:
        RC = _rc()
        st.update(status="running", error=None)
        _write_state(d, st)
        target = st.get("upto", "P4")
        nodes = ["P1", "P2", "P3", "P4"]
        for node in nodes[: nodes.index(target) + 1]:
            link = LINK_OF[node]
            st["current"] = link
            _write_state(d, st)
            s = RC.run(d / "P0_brief.json", int(st["episode"]), d, upto=node, tag=st["tag"],
                       budget=float(st["budget_usd"]), reasoning=bool(st.get("reasoning")))
            if s.get("status") == "bad_brief":
                st.update(status="bad_brief", error="提纲格式不对：" + "；".join(
                    i["message"] for i in (s.get("report") or {}).get("issues", [])[:5]))
                break
            last = (s.get("stages") or [{}])[-1]
            st.setdefault("history", []).append({"at": _now(), "link": last.get("link"), "status": last.get("status"),
                                                  "rounds": last.get("rounds"), "usd": last.get("usd")})
            if last.get("status") not in ("ok", "reused"):
                st["status"] = last.get("status") or "needs_writer"
                if last.get("error"):
                    st["error"] = last["error"]
                break
        else:
            st["status"] = "ok"
        st["current"] = None
    except Exception as e:  # noqa: BLE001  写作网关不通、超时等：写明原因，已通过的产物保留
        st.update(status="error", current=None, error=f"{type(e).__name__}: {e}"[:600])
    finally:
        _write_state(d, st)
        ev = _done.get(run_id)
        if ev is not None:
            ev.set()                          # 状态已落盘才通知（T-SR-01）


def writer_backend() -> str:
    """L-109：config/llm_providers.json writer_backend（claude_agent = 测试期剧本写作交 Claude agent，不花外部写作 API 的钱；api = 上线）。
    文件缺 = api（上线默认）；文件坏 = 抛错（不静默当 api 花钱）"""
    p = REPO / "config" / "llm_providers.json"
    if not p.is_file():
        return "api"
    return json.loads(p.read_text(encoding="utf-8")).get("writer_backend") or "api"


AGENT_REFUSE = ("测试期剧本只走“新建剧本”页的写作流程（写手收包，花费 $0），这里不再单独起写作；"
                "提纲在新建剧本页填，点“开始写作”。")   # V2-WALK W-01：不另造写作包格式，写手只收 writer_tasks/*.json（nsfs.writer_task/1）


def _start(run_id: str) -> None:
    if writer_backend() == "claude_agent":       # W-01 / W-02：不调外部写作 API，也不另发写作包；推进只走 /api/script-autoflow
        raise HTTPException(409, AGENT_REFUSE)
    with _lock:
        busy = [k for k in _threads if _alive(k)]
        if busy:
            raise HTTPException(409, f"已有一个剧本在写（{busy[0]}）：写完或停下后再开新的")
        t = threading.Thread(target=_worker, args=(run_id,), name=f"story-run-{run_id}", daemon=True)
        _threads[run_id] = t
        _done[run_id] = threading.Event()
        t.start()


def wait(run_id: str, timeout: float = 180) -> None:
    """测试用：等后台线程结束。
    UIRSI r43（总调度：test_needs_writer_then_retry 并行偶发失败、两次挡住 sv 发版）：原来 join(30) 超时后静默返回，
    -n 12 并行压测时一次 3 轮重写可能超过 30 s → 测试读到 running / 下一步 retry 撞 409，且线程带着测试的假写作网关继续跑、
    测试结束 monkeypatch 撤掉后改用真网关 → 后面的测试读到 error。现在超时直接报错（不再静默），默认等 180 s"""
    ev, t = _done.get(run_id), _threads.get(run_id)
    if ev is not None:                        # T-SR-01：按完成事件同步（写完状态才置位），再收线程
        if not ev.wait(timeout):
            raise TimeoutError(f"story-run {run_id} 还在跑（等了 {timeout:.0f} 秒）")
        if t:
            t.join(5)
    elif t:
        t.join(timeout)
        if t.is_alive():
            raise TimeoutError(f"story-run {run_id} 还在跑（等了 {timeout:.0f} 秒）")


def join_all(timeout: float = 180) -> None:
    """测试用：等所有后台写作线程结束（fixture 收尾时调，防止线程漏到下一个测试 / monkeypatch 撤掉之后）"""
    for t in list(_threads.values()):
        t.join(timeout)


def _model_label() -> str | None:
    try:
        from ns_api import llm_config as LC
        rv = LC.resolve("script_write", {})
        return f"{rv.get('id')} · {rv.get('model')}"
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------------------- 接口
class StartBody(BaseModel):
    brief: dict
    episode: int = Field(ge=1, le=999)
    upto: str = "P4"
    budget_usd: float = Field(3.0, gt=0, le=20)
    reasoning: bool = False


@router.get("/api/story-runs")
def list_runs(limit: int = 30):
    if not RUNS.is_dir():
        return {"runs": [], "busy": None}
    ds = sorted((p for p in RUNS.iterdir() if p.is_dir() and not p.name.startswith("_")), key=lambda p: -p.stat().st_mtime)
    runs = [_summary(d) for d in ds[: max(1, min(limit, 200))]]
    busy = next((k for k in _threads if _alive(k)), None)
    return {"runs": runs, "busy": busy, "dir": _rel(RUNS)}


@router.post("/api/story-runs")
def start_run(body: StartBody):
    if writer_backend() == "claude_agent":
        raise HTTPException(409, AGENT_REFUSE)
    RC = _rc()
    from ns_schema import storyline as SL
    if body.upto not in ("P1", "P2", "P3", "P4"):
        raise HTTPException(422, "upto 只能是 P1 / P2 / P3 / P4")
    brief = {"schema": "nsfs.brief/1", **body.brief, "source": body.brief.get("source") or "#/script-create"}
    rep = SL.check_brief(brief)
    if not rep.ok:
        raise HTTPException(422, {"message": "提纲格式没过校验", "issues": rep.as_dict()["issues"]})
    b = rep.obj
    if not b.episodes.first <= body.episode <= b.episodes.last:
        raise HTTPException(422, {"message": f"要写的第 {body.episode} 集不在提纲的集数范围 {b.episodes.first}–{b.episodes.last} 里",
                                  "issues": [{"rule": "BR-03", "level": "block", "field": "episodes",
                                              "message": "要写的集不在范围内"}]})
    with _lock:
        busy = next((k for k in _threads if _alive(k)), None)
    if busy:
        raise HTTPException(409, f"已有一个剧本在写（{busy}）：写完或停下后再开新的")
    run_id = f"ui_{time.strftime('%Y%m%d_%H%M%S')}_ep{body.episode:02d}"
    d = RUNS / run_id
    d.mkdir(parents=True, exist_ok=False)
    (d / "P0_brief.json").write_text(json.dumps(b.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    st = {"id": run_id, "episode": body.episode, "upto": body.upto, "status": "queued", "current": None,
          "budget_usd": body.budget_usd, "reasoning": body.reasoning, "tag": f"ui-story-{run_id}", "created_at": _now(),
          "model": _model_label(), "history": []}
    _write_state(d, st)
    del RC
    _start(run_id)
    return _summary(d, full=True)


@router.get("/api/story-runs/{run_id}")
def get_run(run_id: str, ep: int | None = None):
    return _summary(_run_dir(run_id), full=True, ep_sel=ep)


def _artifact_path(d: Path, node: str, ep: int | None = None) -> Path:
    if node == "P0":
        return d / "P0_brief.json"
    if node not in LINK_OF:
        raise HTTPException(404, f"没有这个节点：{node}")
    eps = series_eps(d)
    ep = ep if (ep and (not eps or ep in eps)) else (eps[0] if eps else _episode_of(d, _read(d / STATE)))
    if ep is None:
        raise HTTPException(404, "这个运行还不知道写哪一集")
    return _node_path(d, LINK_OF[node], ep)


@router.get("/api/story-runs/{run_id}/artifact/{node}")
def get_artifact(run_id: str, node: str, ep: int | None = None):
    d = _run_dir(run_id)
    p = _artifact_path(d, node, ep)
    if not p.exists():
        raise HTTPException(404, f"{NODE_LABEL.get(node, node)} 还没有产物")
    text = p.read_text(encoding="utf-8")
    parsed = None
    if p.suffix == ".json":
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
    return {"node": node, "file": _rel(p), "text": text, "json": parsed,
            "kind": "json" if p.suffix == ".json" else "markdown"}


class EditBody(BaseModel):
    text: str


def _ctx_upto(d: Path, link: str) -> dict:
    """校验某段要用的上下文（brief + 它上游已通过的产物）"""
    RC = _rc()
    from ns_schema import storyline as SL
    st = _read(d / STATE)
    ep = _episode_of(d, st)
    brep = SL.check_brief(_read(d / "P0_brief.json") or {})
    if not brep.ok:
        raise HTTPException(409, "提纲本身没过校验，先改提纲")
    try:
        from ns_api import script_chat as SC
        rc, rs, _ = SC.registry_tables({"from": brep.obj.registry_from})
    except Exception:  # noqa: BLE001
        rc, rs = [], []
    ctx = {"brief": brep.obj, "episode": ep, "registry_chars": rc, "registry_scenes": rs}
    key = {"P0-P1": "storyline", "P1-P2": "outline", "P2-P3": "screenplay", "P3-P4": "p4"}
    for up in LINKS[: LINKS.index(link)]:
        obj = RC._load_ok(d / _fname(up, ep), up, ctx)
        if obj is None:
            raise HTTPException(409, f"上游「{NODE_LABEL[NODE_OF[up]]}」还没通过校验，先处理上游")
        ctx[key[up]] = obj
    return ctx


def _supersede(d: Path, links: list[str], why: str) -> list[str]:
    """把这些段的产物和报告挪进 superseded/<时间>/（不删，可找回）"""
    ep = _episode_of(d, _read(d / STATE))
    dst = d / "superseded" / f"{time.strftime('%Y%m%d_%H%M%S')}_{why}"
    moved = []
    for link in links:
        name = _fname_light(link, ep)
        for f in (d / name, d / f"{name}.report.json"):
            if f.exists():
                dst.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dst / f.name))
                moved.append(f.name)
    return moved


@router.put("/api/story-runs/{run_id}/artifact/{node}")
def edit_artifact(run_id: str, node: str, body: EditBody):
    d = _run_dir(run_id)
    if series_eps(d):
        raise HTTPException(409, "整季运行由 SERIES 写作线负责，这里只读（要返修请交给总调度）")
    if _alive(run_id):
        raise HTTPException(409, "正在写作，写完或停下后再改")
    if node == "P0":
        raise HTTPException(422, "提纲请新建一次运行（提纲是这次运行的起点）")
    if node not in LINK_OF:
        raise HTTPException(404, f"没有这个节点：{node}")
    if not body.text.strip():
        raise HTTPException(422, "内容是空的")
    link = LINK_OF[node]
    ctx = _ctx_upto(d, link)
    RC = _rc()
    rep, obj, _ = RC.validate(link, body.text, ctx)
    p = _artifact_path(d, node)
    if p.exists():   # 旧版留底
        bk = d / "edits"
        bk.mkdir(exist_ok=True)
        shutil.copy2(p, bk / f"{time.strftime('%Y%m%d_%H%M%S')}_{p.name}")
    moved = _supersede(d, list(LINKS[LINKS.index(link) + 1:]), f"after_edit_{node}")
    p.write_text(body.text.replace("\r\n", "\n"), encoding="utf-8")   # 原样存项目方的文字，不改写
    status = "ok" if rep.ok else "needs_writer"
    (d / f"{p.name}.report.json").write_text(json.dumps({"link": link, "status": status, "edited_by": "owner",
                                                         "edited_at": _now(), "rounds": [], "report": rep.as_dict()},
                                                        ensure_ascii=False, indent=1), encoding="utf-8")
    st = _read(d / STATE)
    if st is not None:
        st["status"] = "ok" if rep.ok and not moved and node == st.get("upto", "P4") else ("paused" if rep.ok else "needs_writer")
        st.setdefault("history", []).append({"at": _now(), "link": link, "status": f"edited:{status}"})
        st["sent_to_import"] = None if node == "P4" else st.get("sent_to_import")
        _write_state(d, st)
    return {"report": rep.as_dict(), "status": status, "superseded": moved, "run": _summary(d, full=True)}


class RetryBody(BaseModel):
    link: str | None = None
    upto: str | None = None


def _ensure_state(d: Path) -> dict:
    st = _read(d / STATE)
    if st is None:   # 命令行旧 runs：补一份界面状态，才能接着写（不动已有产物）
        ep = _episode_of(d, None)
        if ep is None or not (d / "P0_brief.json").exists():
            raise HTTPException(409, "这个运行缺提纲或集号，不能在界面里继续")
        st = {"id": d.name, "episode": ep, "upto": "P4", "status": "paused", "budget_usd": 3.0, "reasoning": False,
              "tag": f"ui-story-{d.name}", "created_at": _now(), "model": _model_label(), "history": [], "adopted": True}
        _write_state(d, st)
    return st


@router.post("/api/story-runs/{run_id}/retry")
def retry(run_id: str, body: RetryBody | None = None):
    d = _run_dir(run_id)
    if series_eps(d):
        raise HTTPException(409, "整季运行由 SERIES 写作线负责，这里只读（要返修请交给总调度）")
    if _alive(run_id):
        raise HTTPException(409, "正在写作中")
    st = _ensure_state(d)
    body = body or RetryBody()
    rows = _stage_rows(d, st, st.get("episode"))
    link = body.link or next((r["link"] for r in rows[1:] if r["status"] not in ("ok", "unchecked")), None)
    if link not in LINKS:
        raise HTTPException(422, "没有需要返修的段；要重写某段请指明 link")
    moved = _supersede(d, list(LINKS[LINKS.index(link):]), f"retry_{NODE_OF[link]}")
    if body.upto in ("P1", "P2", "P3", "P4"):
        st["upto"] = body.upto
    if LINKS.index(link) > ["P1", "P2", "P3", "P4"].index(st.get("upto", "P4")):
        st["upto"] = NODE_OF[link]
    st.update(status="queued", error=None)
    st.setdefault("history", []).append({"at": _now(), "link": link, "status": "retry", "superseded": moved})
    _write_state(d, st)
    _start(run_id)
    return _summary(d, full=True)


@router.post("/api/story-runs/{run_id}/resume")
def resume(run_id: str, body: RetryBody | None = None):
    d = _run_dir(run_id)
    if series_eps(d):
        raise HTTPException(409, "整季运行由 SERIES 写作线负责，这里只读（要返修请交给总调度）")
    if _alive(run_id):
        raise HTTPException(409, "正在写作中")
    st = _ensure_state(d)
    if body and body.upto in ("P1", "P2", "P3", "P4"):
        st["upto"] = body.upto
    st.update(status="queued", error=None)
    _write_state(d, st)
    _start(run_id)
    return _summary(d, full=True)


@router.post("/api/story-runs/{run_id}/send-to-import")
def send_to_import(run_id: str, ep: int | None = None):
    d = _run_dir(run_id)
    st = _read(d / STATE) or {}
    eps = series_eps(d)
    ep = ep if (ep and ep in eps) else (eps[0] if eps and not ep else _episode_of(d, st))
    if ep is None:
        raise HTTPException(409, "还不知道是哪一集")
    p = _node_path(d, "P3-P4", ep)
    rep = _read(p.parent / f"{p.name}.report.json") or {}
    if not p.exists():
        raise HTTPException(409, "剧本分镜（P4）还没写出来")
    if rep.get("status") != "ok":
        raise HTTPException(409, "剧本分镜（P4）还没通过校验：先返修或改原文")
    from ns_api import script_input as SINPUT
    info = SINPUT._write_draft(f"story_{run_id}" + (f"_ep{ep:02d}" if eps else ""), p.read_text(encoding="utf-8"), True)
    rec = {"at": _now(), "path": info["path"]}
    if eps:   # 整季：记在界面自己的状态文件里（不改 SERIES 的 run.json）
        st = st or {"id": d.name, "series": True}
        st.setdefault("sent_by_ep", {})[str(ep)] = rec
        _write_state(d, st)
    elif st:
        st["sent_to_import"] = rec
        _write_state(d, st)
    return {"draft": info, "import_href": "#/script-create?tab=import",
            "note": "已存为导入候选；导入仍要你在导入页勾选确认"}


# ----------------------------------------------------------------------------- 新图接入（IMGGEN：runs/<id>/images/）
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def _img_kind(name: str) -> str:
    n = name.lower()
    if re.search(r"sheet|设定|turnaround|char", n):
        return "sheet"
    if re.search(r"last|尾帧|_end", n):
        return "last"
    if re.search(r"first|首帧|_ff|frame", n):
        return "first"
    return "other"


@router.get("/api/story-images")
def story_images(run: str | None = None):
    """最新一份带 images/ 的写作运行里的图（只读）。按镜头号（epNN-SK）和人物归组，给画布 / 资产中心在
    出图还没登记成 take 之前先显示新图。路径里认 epNN、S<数字>；人物认 images/chars|characters/<id>/ 或文件名前缀。"""
    if not run:
        # DATAALIGN（K-DATA-001）：没指定运行 = 当前画布剧本自己的运行（config/recipes/asset_refs.json 登记的项目），
        # 不再取“最近有图的任一运行”（别的剧出了图，画布 / 阅读页就会显示别的剧的同号镜头图）
        run = _RP.current_run()     # K-OPS-F24（L-125）：没给 run = 当前 primary 剧；V1 已归档，网页不再显示它的图
    return _story_images_cached(run)


_SI_CACHE: dict = {}


def _story_images_cached(run: str | None):
    """DATAALIGN（UIAUDIT r14g 首屏慢）：整份结果按“图片目录树里每个目录的 mtime”缓存——加 / 删 / 改名图片都会改目录 mtime；
    同名覆盖写不改目录 mtime，靠 15 s TTL 兜底"""
    import os as _os
    d = (RUNS / run) if run else None
    sig = None
    if d is not None and (d / "images").is_dir():
        sig = tuple(sorted((dp, _os.stat(dp).st_mtime_ns) for dp, _dn, _fn in _os.walk(d / "images")))
        sig = (sig, _read_mtime(d / PICKS))
    hit = _SI_CACHE.get(run)
    if sig is not None and hit and hit[0] == sig and time.time() - hit[1] < 15.0:
        return hit[2]
    v = _story_images(run)
    if sig is not None:
        _SI_CACHE[run] = (sig, time.time(), v)
    return v


def _read_mtime(p: Path):
    try:
        return p.stat().st_mtime_ns
    except OSError:
        return None


def _story_images(run: str | None):
    # K-OPS-W20：没传 run 时用当前主剧（runs.json primary）在前，不按 images 目录修改时间猜
    from ns_api.current_run import order_runs
    cands = [RUNS / run] if run else order_runs([d for d in RUNS.iterdir() if (d / "images").is_dir()]) if RUNS.is_dir() else []
    d = next((c for c in cands if (c / "images").is_dir()), None)
    if d is None:
        return {"run": None, "by_shot": {}, "chars": {}, "count": 0}
    root = d / "images"
    by_shot: dict[str, list[dict]] = {}
    chars: dict[str, list[dict]] = {}
    n = 0
    data = (REPO / "data").resolve()
    for f in sorted(root.rglob("*")):
        if f.suffix.lower() not in IMG_EXT or not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        if rel.split("/")[0].startswith("_"):     # _thumbs / _qc 是缩略图和质检图，不单独算
            continue
        url = f"/files/{f.resolve().relative_to(data).as_posix()}?v={int(f.stat().st_mtime)}"
        item = {"url": url, "path": rel, "kind": _img_kind(rel), "mtime": int(f.stat().st_mtime)}
        th = root / "_thumbs" / f"{f.stem}.jpg"   # IMGGEN 的缩略图：列表里先用它（图片懒加载 + 小图）
        if th.is_file():
            item["thumb"] = f"/files/{th.resolve().relative_to(data).as_posix()}?v={int(th.stat().st_mtime)}"
        ml, mseed = re.search(r"look([A-Z])", f.stem), re.search(r"_s(\d+)$", f.stem)
        if ml:
            item["look"] = ml.group(1)
        if mseed:
            item["seed"] = int(mseed.group(1))
        n += 1
        mc = re.search(r"(?:^|/)(?:chars?|characters?|people|sheets?)/([^/]+)/", rel)
        me, ms = re.search(r"ep(\d{1,3})", rel, re.I), re.search(r"(?:^|[/_\-])S(\d{1,3})(?![\d])", rel)
        if mc or (item["kind"] == "sheet" and not ms):
            cid = mc.group(1) if mc else re.split(r"[_\-.]", f.stem)[0]
            chars.setdefault(cid, []).append(item)
        elif me and ms:
            by_shot.setdefault(f"ep{int(me.group(1)):02d}-S{int(ms.group(1))}", []).append(item)
    # UIAUDIT r38–r41 P0-2（UIRSI r43）：出图目录里的草图也要跟剧本版本走——早于本集最后一次导入的是旧剧本的草图
    # （剧本重导后镜头重新编号，旧草图对不上新镜头），不给画布当兜底显示（文件不动，只是不返回）
    old_drafts = 0
    try:
        from ns_api import takes_ui as _TU  # noqa: PLC0415
        for sid in list(by_shot):
            cut = _TU.cutoff_for(int(sid[2:4]))
            if not cut:
                continue
            cut_t = time.mktime(time.strptime(cut[:19], "%Y-%m-%dT%H:%M:%S"))
            keep = [x for x in by_shot[sid] if x["mtime"] >= cut_t]
            old_drafts += len(by_shot[sid]) - len(keep)
            if keep:
                by_shot[sid] = keep
            else:
                del by_shot[sid]
    except Exception:  # noqa: BLE001 — 判不了就照旧返回
        pass
    for v in list(by_shot.values()):
        v.sort(key=lambda x: -x["mtime"])
    for v in chars.values():
        v.sort(key=lambda x: (x.get("look") or "", x.get("seed") or 0, x["path"]))
    return {"run": d.name, "by_shot": by_shot, "chars": chars, "count": n, "picks": _read(d / PICKS) or {}, "old_drafts_hidden": old_drafts}


PICKS = "ui_sheet_picks.json"


class PickBody(BaseModel):
    run: str
    char: str
    path: str
    by: str = ""
    owner_quote: str = ""
    note: str = ""
    look: str | None = None      # 撤销：path 为空 + look = 取消这套造型的选择


@router.post("/api/story-images/pick")
def pick_sheet(body: PickBody):
    """项目方挑设定图（每个角色、每套造型挑一张），点选即生效。身份来自登录会话（ns_api.auth：登录的项目方发 by=owner；
    没登录 / 不是项目方声称 by=owner 会被中间件改掉）→ by 不是 owner 一律 403。不再要求原话（项目方 2026-10-31：
    “我选这个图按一下就可以了”）。只记到 runs/<id>/ui_sheet_picks.json，历史全留（可撤销 = 再选回上一张）。"""
    if body.by != "owner":
        raise HTTPException(403, "挑设定图要登录的项目方本人操作")
    d = _run_dir(body.run)
    if not body.path and body.look:   # 撤销：取消这套造型的选择（记历史）
        with _lock:
            cur = _read(d / PICKS) or {}
            old = (cur.get(body.char) or {}).pop(body.look, None)
            cur.setdefault("_history", []).append({"char": body.char, "look": body.look, "path": None, "at": _now(), "by": "owner", "undo_of": (old or {}).get("path")})
            tmp = d / (PICKS + ".tmp")
            tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(d / PICKS)
        return {"ok": True, "char": body.char, "look": body.look, "pick": None}
    f = (d / "images" / body.path).resolve()
    if not f.is_file() or (d / "images").resolve() not in f.parents or f.suffix.lower() not in IMG_EXT:
        raise HTTPException(404, f"没有这张图：{body.path}")
    look = (re.search(r"look([A-Z])", f.stem) or [None, "_"])[1]
    with _lock:
        cur = _read(d / PICKS) or {}
        hist = cur.setdefault("_history", [])
        prev = (cur.get(body.char) or {}).get(look)
        rec = {"path": body.path, "at": _now(), "by": "owner", "owner_quote": body.owner_quote.strip(), "note": body.note,
               "prev": prev.get("path") if isinstance(prev, dict) else None}
        cur.setdefault(body.char, {})[look] = rec
        hist.append({"char": body.char, "look": look, **rec})
        tmp = d / (PICKS + ".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(d / PICKS)
    return {"ok": True, "char": body.char, "look": look, "pick": rec}


# ----------------------------------------------------------------------------- 每镜出图参考（REFLOCK：ns_agent.asset_refs）
@router.get("/api/shots/{shot_id}/asset-refs")
def shot_asset_refs(shot_id: str):
    """这一镜出首帧会用哪些参考图（按槽位，含写进提示词的“图N是…”原句）、缺什么图、哪些只有设定图。
    先读出图线作业表（runs/<最新整季>/assets/first_frame_jobs.json 里的 asset_refs）；没有就现算（ns_agent.asset_refs）。只读。"""
    m = re.fullmatch(r"ep(\d{2,3})-S(\d{1,3})", shot_id)
    if not m:
        raise HTTPException(404, f"镜头号不对：{shot_id}")
    from ns_api.current_run import order_runs   # K-OPS-W20：主剧在前，不按修改时间
    runs = order_runs([d for d in RUNS.iterdir() if (d / "assets" / "first_frame_jobs.json").is_file()]) if RUNS.is_dir() else []
    # DATAALIGN（K-UI-D01）：当前画布剧本自己的运行排第一（以前取最新一份作业表：别的剧同号镜头会串过来）
    try:
        from ns_api.shot_cast import import_project
        pj = import_project()
    except Exception:  # noqa: BLE001
        pj = None
    if pj:
        runs = [d for d in runs if d.name == pj]
    for d in runs:
        jobs = (_read(d / "assets" / "first_frame_jobs.json") or {}).get("jobs") or []
        j = next((x for x in jobs if x.get("shot") == shot_id), None)
        if j and j.get("asset_refs"):
            return {"source": "jobs", "run": d.name, **j["asset_refs"], "preflight": j.get("preflight")}
    if not runs and not pj:
        raise HTTPException(404, "还没有出图作业")
    proj = pj or runs[0].name
    try:
        p = str(REPO / "services" / "agent")
        if p not in sys.path:
            sys.path.insert(0, p)
        from ns_agent import asset_refs as AR  # noqa: PLC0415
        sc = _read(REPO / "data" / "import" / "script_v2.json") or {}
        ep = next((e for e in sc.get("episodes", []) if int(e.get("number") or 0) == int(m.group(1))), None)
        sh = next((x for x in (ep or {}).get("shots", []) if int(x.get("index") or 0) == int(m.group(2))), None)
        if not sh:
            raise HTTPException(404, f"当前剧本里没有 {shot_id}")
        sr, plan = AR.plan_for(proj, ep, sh)
        return {"source": "computed", "run": proj, **AR.record(sr, plan)}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"这一镜的参考图现在算不出来：{type(e).__name__}: {e}"[:300])
