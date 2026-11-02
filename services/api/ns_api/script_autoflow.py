"""HOLLYWOOD r8（总调度 fredw-2b 派，11-02）：新建剧本页的“全自动写到可导入”接口。执行者 = tools/script_rsi/autoflow.py（子进程），
本模块只启动 / 读状态，不写剧本、不判内容。运行目录与 /api/story-runs 同一个（data/pipeline/runs/<id>，P0_brief.json 由新建页写入）。

  POST /api/script-autoflow/{run_id}/start    {episode, budget_usd?, import_mode: dry|live}   一键：P1→P4 + 代码判定补丁 + 新尺子 + 导入闸门
  POST /api/script-autoflow/{run_id}/repair   同 start（已通过的段复用，从卡住处续跑）                             一键返修
  POST /api/script-autoflow/{run_id}/import   项目方一次点选导入（L-098 闸门范围）：live + --owner-ok
  GET  /api/script-autoflow/{run_id}          状态 autoflow.json（每段 status / decider / 花费 / 失败项 / 分数轨迹）+ 项目方闸门
  GET  /api/script-autoflow/{run_id}/tasks    写作包列表（每步：包、回稿有没有、校验 / 闸门状态）——网页逐步展示（总调度 11-02）
  GET  /api/script-autoflow/{run_id}/tasks/{name}   单个写作包 + 回稿原文
  POST /api/script-autoflow/{run_id}/gate     项目方闸门：{key: P1|epNN, action: approve|revise, note}（L-123：“用这版” / “修改”，没有“不要”）；先收下，异步推进
  POST /api/script-autoflow/{run_id}/brief    新建剧本：写 P0_brief.json（字段：theme / assets / constraints / style / episodes…，或整份 brief 导入），并开项目方闸门
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
RUNS = REPO / "data" / "pipeline" / "runs"
router = APIRouter(tags=["script-autoflow"])
_procs: dict[str, subprocess.Popen] = {}


class StartBody(BaseModel):
    episode: int = 1
    budget_usd: float | None = None
    import_mode: str = "dry"


def _dir(run_id: str) -> Path:
    if not run_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "运行编号不合法")
    d = RUNS / run_id
    if not (d / "P0_brief.json").exists():
        raise HTTPException(404, "这个运行还没有提纲（P0_brief.json）")
    return d


CLOSED = ("archived", "frozen", "paused")


def run_status(run_id: str) -> str | None:
    """runs.json 里这部剧的状态（不在登记表 = None）"""
    import sys as _s
    _s.path.insert(0, str(REPO / "tools" / "autopilot"))
    import runs as RN
    return ((RN.registry(REPO).get("runs") or {}).get(run_id) or {}).get("status")


def _refuse_closed(run_id: str, what: str) -> None:
    """W-37：已归档 / 冻结 / 暂停的剧不能再开写、续写或推进（409 大白话原因）"""
    s = run_status(run_id)
    if s in CLOSED:
        word = {"archived": "已归档", "frozen": "已冻结", "paused": "已暂停"}[s]
        raise HTTPException(409, f"{run_id} {word}（{s}），不能{what}；要恢复请找总调度")


def _spawn(run_id: str, body: StartBody, owner_ok: bool = False) -> dict:
    _refuse_closed(run_id, "开写或推进")
    p = _procs.get(run_id)
    if p is not None and p.poll() is None:
        raise HTTPException(409, "这个剧本正在自动写，等它停下再点")
    d = _dir(run_id)
    if body.import_mode not in ("dry", "live"):
        raise HTTPException(400, "import_mode 只能是 dry 或 live")
    cmd = [sys.executable, str(REPO / "tools/script_rsi/autoflow.py"), "run", "--run-dir", str(d), "--episode", str(body.episode),
           "--import", body.import_mode, "--source", "web"]
    if body.budget_usd is not None:
        cmd += ["--budget", str(body.budget_usd)]
    if owner_ok:
        cmd.append("--owner-ok")
    log = open(d / "autoflow.stdout.log", "a", encoding="utf-8")      # 子进程输出另存；autoflow.log 只放推进记录 JSON 行（OVERSIGHT-F P1-d）
    _procs[run_id] = subprocess.Popen(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                                      env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    return {"started": True, "run": run_id, "cmd": " ".join(cmd[1:])}


@router.post("/api/script-autoflow/{run_id}/start")
def start(run_id: str, body: StartBody):
    return _spawn(run_id, body)


@router.post("/api/script-autoflow/{run_id}/repair")
def repair(run_id: str, body: StartBody):
    return _spawn(run_id, body)


@router.post("/api/script-autoflow/{run_id}/import")
def owner_import(run_id: str, body: StartBody):
    st = status(run_id)
    if st.get("verdict") not in ("importable", "imported"):         # imported = 已导入、补丁后可再覆盖导入（总调度 11-02）
        raise HTTPException(409, f"还不能导入：{st.get('verdict')}（{st.get('next_action') or ''}）")
    return _spawn(run_id, StartBody(episode=body.episode, budget_usd=body.budget_usd, import_mode="live"), owner_ok=True)


@router.get("/api/script-autoflow/{run_id}")
def status(run_id: str):
    d = _dir(run_id)
    p = d / "autoflow.json"
    st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"verdict": "not_started"}
    proc = _procs.get(run_id)
    st["running"] = bool(proc is not None and proc.poll() is None)
    st["owner_gates"] = _og().summary(d)
    st["p1_review"] = p1_review(d)
    return st


def p1_review(d: Path) -> dict | None:
    """P1 三评委（V2-WALK W-18）：各轮 {n, 各家总分 totals, 均分 mean, σ, 逐条均分 item_mean, 逐条分歧 item_split, judge_ids, top_fixes, problems,
    passed, why}；门槛见 config/prompts/hollywood_p1_review.yaml。没有评审 = None"""
    sp = d / "judge_p1" / "STATE.json"
    if not sp.exists():
        rp = d / "judge_p1" / "RESULT.json"
        return {"rounds": [], "latest": json.loads(rp.read_text(encoding="utf-8"))} if rp.exists() else None
    state = json.loads(sp.read_text(encoding="utf-8"))
    rounds = []
    for r in state.get("rounds") or []:
        rp = REPO / (r.get("dir") or "_no_dir_") / "RESULT.json"
        res = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
        rounds.append({"n": r.get("n"), "dir": r.get("dir"), "passed": r.get("passed"), "why": r.get("why"),
                       **{k: res.get(k) for k in ("totals", "mean", "sigma", "item_mean", "item_split", "judge_ids", "top_fixes", "problems")}})
    import yaml
    cfg = yaml.safe_load((REPO / "config/prompts/hollywood_p1_review.yaml").read_text(encoding="utf-8")) or {}
    od = state.get("owner_direction")
    return {"rounds": rounds, "latest": rounds[-1] if rounds else None,
            "threshold": {k: cfg.get(k) for k in ("min_mean", "min_item_mean", "max_rounds", "judges")},
            "owner_direction": ({**{k: od.get(k) for k in ("at", "round", "mean", "totals", "sha")}, "by": "总调度", "why": _og().owner_direction_text(d)}      # W-39：给项目方看的不带内部编号（审计原文在 STATE.json）
                                if (od and _og().owner_direction(d)) else None),          # 总调度转项目方定方向（只对当时那一稿有效）
            "revise_options": list(_og().REVISE_OPTIONS)}


def _load(name: str, rel: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _og():
    return _load("owner_gate", "tools/script_rsi/owner_gate.py")


def _task_row(d: Path, f: Path) -> dict:
    pk = json.loads(f.read_text(encoding="utf-8"))
    out = REPO / ((pk.get("output") or {}).get("path") or "")
    done = Path(str(out) + ".done")
    return {"name": f.stem, "step": pk.get("step"), "role": pk.get("role"), "episode": pk.get("episode"), "attempt": pk.get("attempt"),
            "link": pk.get("link"), "created_at": pk.get("created_at"), "output": (pk.get("output") or {}).get("path"),
            "answered": out.exists() and done.exists(), "targets": pk.get("targets")}


@router.get("/api/script-autoflow/{run_id}/tasks")
def tasks(run_id: str):
    """网页逐步展示：每个写作包 + 回稿有没有 + 当前推进状态（stages）和闸门"""
    d = _dir(run_id)
    rows = [_task_row(d, f) for f in sorted((d / "writer_tasks").glob("*.json"), key=lambda q: q.stat().st_ctime)]
    sts = {}
    for f in sorted(d.glob("autoflow_ep*.json")):
        x = json.loads(f.read_text(encoding="utf-8"))
        sts[f.stem] = {"verdict": x.get("verdict"), "next_action": x.get("next_action"), "stages": x.get("stages"), "awaiting": x.get("awaiting")}
    return {"run": run_id, "tasks": rows, "episodes": sts, "owner_gates": _og().summary(d), "p1_review": p1_review(d)}


@router.get("/api/script-autoflow/{run_id}/tasks/{name}")
def task(run_id: str, name: str):
    d = _dir(run_id)
    if not name.replace("_", "").isalnum():
        raise HTTPException(400, "包名不合法")
    f = d / "writer_tasks" / f"{name}.json"
    if not f.exists():
        raise HTTPException(404, "没有这个写作包")
    pk = json.loads(f.read_text(encoding="utf-8"))
    out = REPO / ((pk.get("output") or {}).get("path") or "")
    return {"packet": pk, "row": _task_row(d, f), "output_text": out.read_text(encoding="utf-8") if out.exists() else None}


def _actor(request: Request) -> str:
    try:
        from ns_api import auth as AU
        u = AU.user_of(request)
        if u:
            return u.get("name") or "owner"
    except Exception:  # noqa: BLE001
        pass
    return "未登录"


class GateBody(BaseModel):
    key: str
    action: str                     # approve =“用这版”；revise =“修改”；redirect =“换方向”（只在 owner_direction 状态）
    note: str = ""
    options: list[str] = []         # “修改”的一键选项（owner_gate.REVISE_OPTIONS）
    by: str = "项目方"


@router.post("/api/script-autoflow/{run_id}/gate")
def gate(run_id: str, body: GateBody, request: Request):
    """“用这版” / “修改”：先记下（原位显示状态），再异步推进；正在跑时只记下，下一次推进会处理"""
    d = _dir(run_id)
    actor = _actor(request)
    if actor == "未登录":                       # OVERSIGHT-F 第 3 轮 P1-3a：未登录不能替项目方点闸门
        raise HTTPException(403, "请先登录再点“用这版 / 修改”")
    try:
        g = _og().act(d, body.key, body.action, body.note, actor, body.options)   # by 一律取登录会话，不信前端传的值
    except PermissionError as e:              # W-25：P1 没过三评委门槛不收“用这版”（“修改”照常收）
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    ep = 1 if body.key == "P1" else int(body.key[2:])
    p = _procs.get(run_id)
    started = None
    if p is None or p.poll() is not None:
        started = _spawn(run_id, StartBody(episode=ep))
    return {"accepted": True, "gate": g, "started": started, "note": None if started else "正在推进中，已记下，下一次推进会处理"}


def _reject_archived(run_id: str, brief: dict | None) -> None:
    reg = json.loads((REPO / "config" / "pipeline" / "runs.json").read_text(encoding="utf-8")).get("runs") or {}
    arch = {k for k, v in reg.items() if (v or {}).get("status") == "archived"}
    if run_id in arch:
        raise HTTPException(409, "这部剧已归档，不能再往里写；请新建一部剧")
    bad = [x for x in ((brief or {}).get("registry_from") or []) if x in arch]
    if bad:
        raise HTTPException(409, "不能拿已归档的剧做续写来源：" + "、".join(bad))


class BriefBody(BaseModel):
    brief: dict | None = None             # 整份 nsfs.brief/1 导入
    title: str = ""
    theme: str = ""                        # 主题 / 故事方向（项目方原话）
    assets: list[str] = []                 # 资产清单引用（如 assets_v2/owner_inputs.json）
    constraints: str = ""                  # 约束
    style: str = ""                        # 风格方向
    episodes: int = 10
    seconds_min: int = 60
    seconds_max: int = 120
    clean_cut: bool = True                 # 完全切割（不带旧剧内容进写作包，L-126）；OVERSIGHT-F 11-02：新剧默认 True，自动写 CLEAN_CUT.json
    source_run: str = ""                   # clean_cut=false 续写时的源剧（不能是已归档 / 冻结 / 暂停的剧，W-37）


@router.post("/api/script-autoflow/{run_id}/brief")
def brief(run_id: str, body: BriefBody):
    if not run_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "运行编号不合法")
    _refuse_closed(run_id, "写新的 Brief")
    _reject_archived(run_id, body.brief)   # 旧实现（只认 archived）保留：已归档剧再挡一道
    if not body.clean_cut:                 # 续写：源剧（source_run，或 brief.registry_from 里登记过的剧）不能是已归档的剧
        srcs = [body.source_run] if body.source_run else []
        srcs += [x for x in ((body.brief or {}).get("registry_from") or []) if run_status(str(x)) is not None]
        for src in srcs:
            if run_status(src) in CLOSED:
                raise HTTPException(409, f"续写的源剧 {src} 状态是 {run_status(src)}（已归档 / 冻结 / 暂停），不能从它续写；V2 请用完全切割（clean_cut）")
    import sys as _s
    _s.path.insert(0, str(REPO / "packages" / "schema"))
    from ns_schema import storyline as SL
    if body.brief is not None:
        b = dict(body.brief)
    else:
        if not body.theme.strip():
            raise HTTPException(400, "主题不能为空")
        outline = "\n".join(x for x in ("【主题 / 故事方向】" + body.theme.strip(),
                                          ("【资产清单】" + "；".join(body.assets)) if body.assets else "",
                                          ("【风格方向】" + body.style.strip()) if body.style.strip() else "") if x)
        b = {"schema": "nsfs.brief/1", "title": body.title, "outline": outline, "episodes": {"from": 1, "to": max(1, body.episodes)},
             "episode_lines": {}, "seconds_per_episode": [body.seconds_min, body.seconds_max], "shots_per_ep": None, "registry_from": [],
             "notes": body.constraints, "source": "新建剧本页（/api/script-autoflow/brief）"}
    rep = SL.check_brief(b)
    if not rep.ok:
        raise HTTPException(400, "Brief 不合格：" + "；".join(i.message for i in rep.issues)[:500])
    d = RUNS / run_id
    d.mkdir(parents=True, exist_ok=True)
    if (d / "P0_brief.json").exists() and (d / "autoflow.json").exists():
        raise HTTPException(409, "这个运行已经开始写了；换一个运行编号，或先在页面上点“修改”")
    tmp = d / "P0_brief.json.tmp"
    tmp.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / "P0_brief.json")
    _og().enable(d, by="新建剧本页")
    if body.clean_cut and not (d / "CLEAN_CUT.json").exists():
        (d / "CLEAN_CUT.json").write_text(json.dumps({"rule": "L-126", "by": "新建剧本页"}, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "run": run_id, "brief": "P0_brief.json", "owner_gates": True, "clean_cut": (d / "CLEAN_CUT.json").exists()}
