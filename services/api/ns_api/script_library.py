"""剧本库（FOCUS_PLAN 第 9 条，项目方 11-02：“剧本页太 empty，很多剧本内容应该在这里管理，特别是已经做完的历史剧本”）。

只读聚合，不改任何剧本内容；数据全部来自文件：
  config/pipeline/runs.json                      有哪几部剧、状态（producing / paused / done …）
  data/pipeline/runs/<run>/                      P0 提纲、P1 故事线、P2 大纲（根目录或 epNN/ 下）、writer_out（r1..rN / 补丁 / 事实核查）、judge_out（盲评）、autoflow_epNN.json
  data/autopilot/coverage.json                   写作流水线 live_runs
GET /api/script-library                          剧集卡片 + 历史区 + 写作流水线
GET /api/script-library/{run}                    一部剧的集列表（梗概 / 场景 / 亲密 / 版本 / 核查 / 盲评 / 版本时间线）
GET /api/script-library/{run}/brief              提纲字段（给“复制为新剧模板”预填表单）

场景归类（造型卡“使用场景”共用）：只按地点关键词做客观归类——室内 / 户外、私密 / 公开 / 社交；是否亲密戏取大纲里的 intimate 标记。不评价内容。
"""
from __future__ import annotations

from ns_api import run_paths as _RP   # K-OPS-F24：渲染根目录按当前剧（V1 已归档，不在网页显示）
import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["script-library"])

_RUN_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_DONE_STATES = {"done", "finished", "archived", "completed", "delivered"}


# ----------------------------------------------------------------------------- 读文件
def _rj(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _registry() -> dict:
    return _rj(REPO / "config" / "pipeline" / "runs.json", {}) or {}


def _run_dir(run: str) -> Path:
    if not _RUN_RE.match(run):
        raise HTTPException(404, "没有这部剧")
    return REPO / "data" / "pipeline" / "runs" / run


def _mt(p: Path) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(p.stat().st_mtime))


def run_title_of(d: Path) -> str:
    """剧名的唯一来源（剧本库卡片、/api/story-runs 列表、下拉、页头都用它）：提纲里的名字 → P1 定稿的剧名 →
    P1 返修期间正式文件被改名留档（P1_storyline.v*.json）时取最新一份的剧名；都没有 = 空串"""
    t = (_rj(d / "P0_brief.json", {}) or {}).get("title")
    if t:
        return t
    st = _rj(d / "P1_storyline.json", {}) or {}
    if st.get("title"):
        return st["title"]
    # OVERSIGHT-F 第 4 轮（arch_scan mtime_latest）：按文件名里的版本号取最新，不按修改时间猜
    import re as _re
    old = sorted(d.glob("P1_storyline.v*.json"), key=lambda q: int((_re.search(r"\.v(\d+)\.json$", q.name) or [0, 0])[1]), reverse=True)
    for f in old:
        t = (_rj(f, {}) or {}).get("title")
        if t:
            return t
    return ""


# ----------------------------------------------------------------------------- 场景归类（客观：地点关键词）
# 顺序有意义：先匹配先得。每条 = (关键词, 室内/户外, 私密/公开/社交)
_SCENE_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("ballroom", "酒会", "宴会", "舞会", "派对", "party", "club", "_bar", "酒吧", "餐厅", "dining", "咖啡"), "室内", "社交"),
    (("alley", "street", "街巷", "街道", "road", "park", "公园", "天台", "rooftop", "garden", "花园", "taxi", "出租车", "停车场"), "户外", "公开"),
    (("bedroom", "卧室", "bath", "浴室", "closet", "衣帽间", "kitchen", "厨房", "apartment", "公寓", "home", "家", "rental", "出租屋", "entry", "玄关", "living", "客厅", "hotel", "酒店房"), "室内", "私密"),
    (("office", "办公", "elevator", "电梯", "楼道", "studio", "工作室", "meeting", "会议", "lobby", "大堂", "公司", "school", "学校", "hospital", "医院"), "室内", "公开"),
]


def classify_scene(scene_id: str, name: str = "") -> dict:
    """{place_kind: 室内/户外/室内外, privacy: 私密/公开/社交, matched: 命中的关键词}；关键词对不上就不猜，全给 None"""
    text = f"{scene_id} {name}".lower()
    hits = []
    for kws, io, pv in _SCENE_RULES:
        k = next((w for w in kws if w in text), None)
        if k:
            hits.append((io, pv, k))
    if not hits:
        return {"place_kind": None, "privacy": None, "matched": None}
    io, pv, k = hits[0]
    # 同时命中户外和室内（如“街巷与酒会厅”）= 室内外；隐私/社交取先命中的
    if len({h[0] for h in hits}) > 1 and not any(h[1] == "私密" for h in hits):
        io = "室内外"
    return {"place_kind": io, "privacy": pv, "matched": k}


# ----------------------------------------------------------------------------- 大纲
def _outline_path(run: str, ep: int) -> Path | None:
    d = _run_dir(run)
    for p in (d / f"P2_ep{ep:02d}_outline.json", d / f"ep{ep:02d}" / f"P2_ep{ep:02d}_outline.json"):
        if p.is_file():
            return p
    return None


def outlines(run: str) -> dict[int, dict]:
    out: dict[int, dict] = {}
    d = _run_dir(run)
    if not d.is_dir():
        return out
    for n in range(1, 61):
        p = _outline_path(run, n)
        if p:
            o = _rj(p)
            if isinstance(o, dict):
                out[n] = o
    return out


def scene_catalog(run: str) -> dict[str, dict]:
    """scene_id → {name, time}：P1 故事线 scenes 表；缺的用 data/scenes.json"""
    cat: dict[str, dict] = {}
    for s in (_rj(_run_dir(run) / "P1_storyline.json", {}) or {}).get("scenes") or []:
        if isinstance(s, dict) and s.get("scene_id"):
            cat[s["scene_id"]] = {"name": s.get("name") or s["scene_id"], "time": s.get("time_of_day")}
    for s in (_rj(REPO / "data" / "scenes.json", {}) or {}).get("scenes") or []:
        if isinstance(s, dict) and s.get("scene_id") and s["scene_id"] not in cat:
            cat[s["scene_id"]] = {"name": s.get("place") or s["scene_id"], "time": None}
    return cat


def episode_scenes(run: str, ep: int, outline: dict | None = None, cat: dict | None = None) -> list[dict]:
    """一集里的场景：地点、归类、在场人物、占几个节拍 / 约几秒、是否亲密戏（本集 intimate 且私密场景且两人以上在场）"""
    o = outline if outline is not None else (outlines(run).get(ep) or {})
    cat = cat if cat is not None else scene_catalog(run)
    intimate_ep = bool(o.get("intimate"))
    rows: dict[str, dict] = {}
    order = list(o.get("scenes") or [])
    for b in o.get("beats") or []:
        sid = b.get("scene_id")
        if sid and sid not in order:
            order.append(sid)
    for sid in order:
        rows[sid] = {"scene_id": sid, "beats": 0, "est_s": 0, "characters": [], "purposes": []}
    for b in o.get("beats") or []:
        r = rows.get(b.get("scene_id"))
        if not r:
            continue
        r["beats"] += 1
        r["est_s"] += int(b.get("est_s") or 0)
        for c in b.get("characters") or []:
            if c not in r["characters"]:
                r["characters"].append(c)
        if b.get("purpose") and b["purpose"] not in r["purposes"]:
            r["purposes"].append(b["purpose"])
    out = []
    for sid, r in rows.items():
        name = (cat.get(sid) or {}).get("name") or sid
        cl = classify_scene(sid, name)
        out.append({**r, "scene_type": next((b.get("scene_type") for b in (o.get("beats") or []) if b.get("scene_id") == sid and b.get("scene_type")), None) or (o.get("scene_types") or {}).get(sid), "name": name, "time": (cat.get(sid) or {}).get("time"), **cl,
                    "intimate": bool(intimate_ep and cl["privacy"] == "私密" and len(r["characters"]) >= 2)})
    return out


def character_usage(project: str, name: str) -> list[dict]:
    """造型卡“使用场景”：某人物在这部剧每一集出现的场景（地点 + 归类 + 是否亲密戏）。没写大纲的集不出现"""
    cat = scene_catalog(project)
    res = []
    for n, o in sorted(outlines(project).items()):
        scs = [s for s in episode_scenes(project, n, o, cat) if name in s["characters"]]
        if scs:
            res.append({"ep": n, "title": o.get("title") or "", "intimate_ep": bool(o.get("intimate")), "scenes": scs})
    return res


# ----------------------------------------------------------------------------- 核查 / 盲评 / 版本
def _factcheck(run: str, ep: int) -> dict | None:
    wo = _run_dir(run) / "writer_out"
    fs = sorted(wo.glob(f"factcheck_ep{ep:02d}_a*.json"), key=lambda p: int(re.search(r"_a(\d+)\.json$", p.name).group(1))) if wo.is_dir() else []
    if not fs:
        return None
    f = fs[-1]
    txt = f.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:   # arch-ok: 核查稿不是合法 JSON → ok=None（界面显示“核查中”），不当通过
        d = {}
    devs = d.get("deviations") or []
    return {"ok": bool(d.get("ok")) if "ok" in d else None, "deviations": len(devs), "attempt": int(re.search(r"_a(\d+)\.json$", f.name).group(1)),
            "rounds": len(fs), "at": _mt(f), "items": [str(x)[:120] if not isinstance(x, dict) else str(x.get("what") or x.get("note") or x)[:120] for x in devs[:3]]}


def _judge(run: str, ep: int) -> dict | None:
    d = _rj(_run_dir(run) / "judge_out" / f"judge_ep{ep:02d}.result.json")
    if not isinstance(d, dict):
        return None
    return {"mean": d.get("mean"), "sigma": d.get("sigma"), "stable": d.get("stable"), "verdict": d.get("verdict"), "n": d.get("n"),
            "problems": len(d.get("problems") or []), "at": d.get("at")}


def _autoflow(run: str, ep: int) -> dict | None:
    return _rj(_run_dir(run) / f"autoflow_ep{ep:02d}.json")


def _reason(p: Path) -> str:
    """版本改动原因：稿头的写作说明注释（<!-- ... -->，跳过 rules_version 行）；补丁文件写“补丁 N 处”"""
    try:
        if p.suffix == ".json":
            return f"补丁 {len((_rj(p, {}) or {}).get('patches') or [])} 处"
        head = p.read_text(encoding="utf-8", errors="replace")[:1500]
    except OSError:   # arch-ok: 读不到稿头只是不显示改动原因，版本本身照列
        return ""
    for m in re.finditer(r"<!--(.*?)-->", head, re.S):
        t = " ".join(m.group(1).split())
        t = re.sub(r"^[A-Za-z]+（[^）]*）\s*(ep\d+\s*)?", "", t)   # 去掉“SCRIPTWRITER（…）ep01”这类内部署名
        if t and not t.startswith("rules_version"):
            return t[:140]
    return ""


def versions(run: str, ep: int) -> list[dict]:
    """版本时间线：writer_out 的整集重写 rN 和补丁 aN（按时间），再加根目录的定稿快照"""
    d = _run_dir(run)
    wo = d / "writer_out"
    out = []
    if wo.is_dir():
        for p in wo.glob(f"P4_ep{ep:02d}_r*.md"):
            m = re.search(r"_r(\d+)\.md$", p.name)
            if m:
                out.append({"label": f"r{m.group(1)}", "kind": "重写", "n": int(m.group(1)), "at": _mt(p), "reason": _reason(p)})
        for p in wo.glob(f"patch_ep{ep:02d}_a*.json"):
            m = re.search(r"_a(\d+)\.json$", p.name)
            if m:
                out.append({"label": f"补丁 {m.group(1)}", "kind": "补丁", "n": int(m.group(1)), "at": _mt(p), "reason": _reason(p)})
    out.sort(key=lambda x: x["at"])
    return out


def _ep_state(run: str, ep: int, has_outline: bool) -> tuple[str, str]:
    """(key, 文字)：writing 写作中 / checking 核查中 / imported 已导入 / outline 只有大纲"""
    a = _autoflow(run, ep)
    if a:
        role = ((a.get("awaiting") or {}).get("role") or "")
        if role == "reviewer":
            return "checking", "核查中"
        if role == "writer":
            return "writing", "写作中"
        if a.get("verdict") in ("imported", "reimported"):
            return "imported", "已导入"
        return "writing", "写作中"
    return ("imported", "已导入") if has_outline else ("writing", "写作中")


# ----------------------------------------------------------------------------- 封面 / 成片
def _file_url(rel: str | None) -> str | None:
    if not rel:
        return None
    p = REPO / rel
    if not p.is_file():
        return None
    rel = rel.replace("\\", "/")
    return f"/files/{rel[5:]}?v={int(p.stat().st_mtime)}" if rel.startswith("data/") else None


def _shot_first_frame(ep: int, shot: int = 1) -> str | None:
    d = _RP.renders_root(REPO) / f"ep{ep:02d}" / f"S{shot}"
    t = _rj(d / "takes.json", {}) or {}
    n = (t.get("locked") or {}).get("image")
    if n is None:
        n = (t.get("active") or {}).get("image")
    take = next((x for x in t.get("takes") or [] if x.get("stage") == "image" and x.get("n") == n), None)
    if not take or not take.get("file"):
        return None
    f = str(take["file"]).replace("\\", "/")
    return _file_url(f if f.startswith("data/") else f"data/{f}")


def _sheet_cover(run: str) -> str | None:
    sc = _rj(_run_dir(run) / "assets" / "sheets_chosen.json", {}) or {}
    for k in sorted(sc):
        u = _file_url((sc[k] or {}).get("file"))
        if u:
            return u
    return None


def _finished_cuts(primary: bool) -> int:
    if not primary:
        return 0
    d = REPO / "data" / "episodes"
    eps = set()
    for p in d.glob("ep[0-9][0-9]*.mp4") if d.is_dir() else []:
        if any(w in p.name for w in ("PREVIEW", "未完成", "勿用", "预览", "待补")):
            continue
        eps.add(int(p.name[2:4]))
    return len(eps)


def _ep_video_progress(ep: int) -> tuple[float, float]:
    """本集“视频已定稿 / 镜数”（镜 = data/renders/epNN/S* 下有 takes.json 的目录；定稿 = takes.json 的 locked.video 有值）"""
    d = _RP.renders_root(REPO) / f"ep{ep:02d}"
    total = done = have = 0
    for sd in d.glob("S[0-9]*") if d.is_dir() else []:
        t = _rj(sd / "takes.json")
        if not isinstance(t, dict):
            continue
        total += 1
        if (t.get("locked") or {}).get("video") is not None:
            done += 1
        if (t.get("locked") or {}).get("video") is not None or (t.get("active") or {}).get("video") is not None:
            have += 1
    return (round(done / total, 3), round(have / total, 3)) if total else (0.0, 0.0)


def _poster_cover(run: str) -> str | None:
    """海报模块（tools/poster）：data/posters/<run>/manifest.json 里标 current 的那张（竖版 2:3 中文版）优先做卡片封面"""
    m = _rj(REPO / "data" / "posters" / run / "manifest.json", {}) or {}
    cur = m.get("current") or {}
    return _file_url(cur.get("file"))


def _cover(run: str, primary: bool, n: int) -> str | None:
    pc = _poster_cover(run)
    if pc:
        return pc
    if primary:
        for e in range(1, n + 1):
            u = _shot_first_frame(e)
            if u:
                return u
    return _sheet_cover(run)


# ----------------------------------------------------------------------------- 卡片
def _card(run: str, meta: dict, primary: bool) -> dict:
    d = _run_dir(run)
    ols = outlines(run)
    brief = _rj(d / "P0_brief.json", {}) or {}
    story = _rj(d / "P1_storyline.json", {}) or {}
    title = run_title_of(d) or "新剧（未定名）"
    total_eps = int(((brief.get("episodes") or {}).get("to") or (max(ols) if ols else 0)) or 0)
    states = {n: _ep_state(run, n, n in ols)[0] for n in range(1, total_eps + 1)}
    n_imp = sum(1 for v in states.values() if v == "imported")
    cuts = _finished_cuts(primary)
    st = (meta or {}).get("status") or ""
    if st in _DONE_STATES:
        state, text = "done", f"成片 {cuts or total_eps}/{total_eps}"
    elif n_imp < total_eps:
        state, text = "writing", f"写作中 {n_imp}/{total_eps}" + (" · 出图暂停" if st == "paused" else "")
    elif st == "paused":
        state, text = "paused", "出图暂停"
    else:
        state, text = "producing", f"出图中 · 成片 {cuts}/{total_eps}"
    season = 2 if run.endswith("_s2") or "第二季" in str(title) else 1
    m = re.search(r"_s(\d+)$", run)
    if m:
        season = int(m.group(1))
    return {"run": run, "title": title, "season": season, "episodes": total_eps, "written": len(ols), "imported": n_imp,
            "state": state, "state_text": text, "cuts": cuts, "primary": primary, "paused_note": (meta or {}).get("paused_note"),
            "duration_s": sum(int(o.get("target_duration_s") or 0) for o in ols.values()),
            "cover": _cover(run, primary, total_eps),
            "ep_progress": [(_ep_video_progress(n)[0] if primary else (1.0 if states.get(n) == "imported" else 0.0)) for n in range(1, total_eps + 1)],
            "ep_video_have": [(_ep_video_progress(n)[1] if primary else (1.0 if states.get(n) == "imported" else 0.0)) for n in range(1, total_eps + 1)], "intimate_eps": sum(1 for o in ols.values() if o.get("intimate")),
            "updated_at": max([_mt(p) for p in [*d.glob("P2_ep*_outline.json"), *d.glob("autoflow_ep*.json")]] or [""]) or None}


def _pipeline(run_ids: list[str]) -> list[dict]:
    """写作流水线：每部剧每集在哪一步——在写 / 在核查 / 待导入（coverage.json 的 live_runs 另给“卡住”的）"""
    cov = _rj(REPO / "data" / "autopilot" / "coverage.json", {}) or {}
    live = ((cov.get("live_runs") or {}).get("now")) or []
    rows = []
    for run in run_ids:
        for n in range(1, 61):
            a = _autoflow(run, n)
            if not a:
                continue
            key, text = _ep_state(run, n, True)
            if key == "imported":
                continue
            lv = next((x for x in live if x.get("run") == run and x.get("episode") == n), None)
            rows.append({"run": run, "ep": n, "state": key, "text": text, "step": ((a.get("awaiting") or {}).get("step")),
                         "note": a.get("next_action"), "stuck": (lv or {}).get("what"), "at": a.get("started")})
    for x in live:
        if not any(r["run"] == x.get("run") and r["ep"] == x.get("episode") for r in rows):
            rows.append({"run": x.get("run"), "ep": x.get("episode"), "state": "writing", "text": "写作中", "step": x.get("stage"),
                         "note": None, "stuck": x.get("what"), "at": None})
    return rows


@router.get("/api/script-library")
def library():
    reg = _registry()
    prim = reg.get("primary")
    runs = (reg.get("runs") or {})
    cards = []
    for run, meta in runs.items():
        if not _RUN_RE.match(run) or not (REPO / "data" / "pipeline" / "runs" / run).is_dir():
            continue
        if (meta or {}).get("status") in ("deleted", "trashed"):
            continue
        cards.append(_card(run, meta, run == prim))
    cards.sort(key=lambda c: (c["season"], c["run"]))
    return {"current": [c for c in cards if c["state"] != "done"], "history": [c for c in cards if c["state"] == "done"],
            "pipeline": _pipeline([c["run"] for c in cards])}


@router.get("/api/script-library/{run}")
def detail(run: str):
    reg = _registry()
    meta = (reg.get("runs") or {}).get(run)
    if meta is None or not (_run_dir(run)).is_dir() or meta.get("status") in ("deleted", "trashed"):
        raise HTTPException(404, "没有这部剧")
    prim = reg.get("primary") == run
    card = _card(run, meta, prim)
    cat = scene_catalog(run)
    ols = outlines(run)
    eps = []
    for n in range(1, max(card["episodes"], max(ols or [0])) + 1):
        o = ols.get(n) or {}
        key, text = _ep_state(run, n, bool(o))
        vs = versions(run, n)
        a = _autoflow(run, n) or {}
        eps.append({"ep": n, "title": o.get("title") or "", "logline": o.get("logline") or "", "intimate": bool(o.get("intimate")),
                    "duration_s": o.get("target_duration_s"), "scenes": episode_scenes(run, n, o, cat) if o else [],
                    "state": key, "state_text": text, "version": (vs[-1]["label"] if vs else ("定稿" if o else None)), "versions": vs,
                    "factcheck": _factcheck(run, n), "judge": _judge(run, n),
                    "cover": _shot_first_frame(n) if prim else None, "next_action": a.get("next_action")})
    return {"card": card, "episodes": eps}


@router.get("/api/script-library/{run}/brief")
def brief(run: str):
    if (_registry().get("runs") or {}).get(run) is None:
        raise HTTPException(404, "没有这部剧")
    b = _rj(_run_dir(run) / "P0_brief.json")
    if not isinstance(b, dict):
        raise HTTPException(404, "这部剧没有提纲")
    return {"title": b.get("title") or "", "outline": b.get("outline") or "", "episodes": b.get("episodes") or {"from": 1, "to": 1},
            "episode_lines": b.get("episode_lines") or {}, "seconds_per_episode": b.get("seconds_per_episode") or [50, 75],
            "shots_per_ep": b.get("shots_per_ep")}
