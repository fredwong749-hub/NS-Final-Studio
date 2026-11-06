"""项目方路径验收（W-E2E，L-214）：按项目方实际怎么用、看到什么来验收，补上“单测全过、项目方却当了测试员”的那一层。

11-06 / 11-07 夜里项目方撞上的都是集成问题：点过的卡又冒出来、成人触发没人写、V2“修改”没推到服务器、视频页黑（文件没拉回）、
首尾帧看图走到忙着的本机卡、提示词证据静默过期……每一条单测都绿。这里两部分：

  get   只读，对着在跑的本机 API（:8800）和真实数据：每个页面 GET 能打开、不慢、跟真相一致。
        已有的检查直接复用 tools/brain/invariants.py（queue_done / kpi_page / media_missing / slow_api / api_tz / pick_stuck /
        ctrl_unpushed），这里只补它没有的：页面打不开、队列读取失败、待你看里出现没过检的候选、成人镜页面和触发清单对不上。
  post  沙箱：把最小状态拷进临时目录，按现有测试的做法起一个指向沙箱的 API（FastAPI + 同一批路由 + 登录换成项目方），
        把项目方会点的每条 POST 真走一遍——挑选（用这张）、首尾帧“修改”、成人镜触发、资产“修改描述”——
        断言效果落在消费方读的地方，并且“会送到服务器”：路径在 resident_sync.control_files() 里，或在资产推送清单里。
        沙箱里不推服务器、不调 producer（子进程换成记录器）、不写真实数据；成人镜只用合成夹具（没有任何画面描述）。

输出：一项一行，不过的用一句中文说清楚（项目方看得懂）。退出码 = 不过的项数。
  python tools/qa/e2e_owner.py                 # 两部分
  python tools/qa/e2e_owner.py --part get      # 只读页面部分
  python tools/qa/e2e_owner.py --json          # 机器读（发版闸门用）
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
API = "http://127.0.0.1:8800"
for _p in ("services/api", "services/agent", "tools/autopilot", "tools/pipeline", "tools/factory"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

# 项目方在网页上会打开的页面（hash 页 → 它读的 GET）。invariants.API_PAGES 那三个也在这里
PAGES = {
    "/api/owner/inbox": "待你看",
    "/api/owner/queue": "待你看（旧队列）",
    "/api/episodes/kpi": "KPI 面板",
    "/api/videos/overview": "视频页",
    "/api/owner/adult-trigger": "成人镜触发",
    "/api/frame-queue": "出图队列",
    "/api/frames-index": "首尾帧总览",
    "/api/producer/status": "生产状态",
    "/api/pipeline/status": "流水线状态",
    "/api/v2/assets": "资产页",
    "/api/progress": "进度",
    "/api/render/lanes": "GPU 道",
    "/api/sop/stepbar": "步骤条",
    "/api/owner/delegate": "代选",
    "/api/episodes/summary": "分集总览",
}
PAGE_TIMEOUT_S = 20.0
# 复用 invariants 的检查族 → 全过时给项目方看的一句
GET_FAMILIES = {"queue_done": "待你看没有已处理过的卡", "kpi_page": "KPI 面板的数和服务器登记表一致",
                "media_missing": "视频页的视频本机都有文件", "slow_api": "主要页面 2 秒内打开", "api_tz": "待你看时间是 JST",
                "pick_stuck": "点过的卡没有卡在处理中", "pick_failed_noreason": "失败的挑选都带原因", "tmp_orphan": "没有原子写残留",
                "ctrl_unpushed": "触发清单 / 修改清单已推到两台服务器"}
E2E_EP = 99          # 沙箱合成镜用的集号（真实剧本里没有第 99 集）


def _load(name: str, rel: str):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def R(rid: str, ok: bool, line: str, part: str, detail: str = "") -> dict:
    return {"id": rid, "ok": bool(ok), "line": line, "part": part, "detail": str(detail)[:400]}


def _j(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不到 = 默认（调用方按“没有”处理）
        return default


# ================================================================== get：只读页面
def check_inbox_extra(inbox) -> list[dict]:
    """invariants 没覆盖的：队列读取失败；待你看里出现没过检的候选（只给看通过的图）"""
    out = []
    if not isinstance(inbox, dict):
        return out
    errs = inbox.get("source_errors") or []
    if inbox.get("status") == "error" or errs:
        out.append(R("inbox_source", False, f"待你看读取失败（{len(errs)} 个来源读不了），页面可能显示成空队列", "get", "；".join(map(str, errs))[:300]))
    bad = []
    for it in inbox.get("items") or []:
        for c in it.get("candidates") or []:
            if isinstance(c, dict) and c.get("contract_ok") is False:
                bad.append(f"{it.get('id')}:{c.get('key')}")
    if bad:
        out.append(R("inbox_unpassed", False, f"待你看给你看了 {len(bad)} 张没过检查的候选图（只该给看通过的图）", "get", ", ".join(bad[:6])))
    return out


def check_adult_view(view, triggers: dict | None) -> list[dict]:
    """成人镜页面 vs producer 读的触发清单：页面说“已点”的，清单里必须有；清单里有的，页面不能还显示“等你点”"""
    if not isinstance(view, dict):
        return []
    objs = set((triggers or {}).get("objects") or [])
    shown_trig, shown_wait = [], []
    for e in view.get("episodes") or []:
        for s in e.get("shots") or []:
            sid = s.get("shot")
            has = bool({f"first:{sid}", f"last:{sid}"} & objs)
            if s.get("state") == "waiting" and has:
                shown_wait.append(sid)
            if s.get("state") != "waiting" and not has:
                shown_trig.append(sid)
    out = []
    if shown_trig:
        out.append(R("adult_view_ghost", False, f"成人镜页面说 {len(shown_trig)} 镜已点，但出图读的触发清单里没有（点了不会出）", "get", ", ".join(shown_trig[:8])))
    if shown_wait:
        out.append(R("adult_view_stale", False, f"成人镜页面还让你点 {len(shown_wait)} 镜，其实已经触发过了（会让你重复点）", "get", ", ".join(shown_wait[:8])))
    return out


def get_part(root: Path, base: str, now: float | None = None, timeout: float = PAGE_TIMEOUT_S) -> list[dict]:
    now = now or time.time()
    INV = _load("invariants_for_e2e", "tools/brain/invariants.py")
    out: list[dict] = []
    pages, timings = {}, {}
    for p, label in PAGES.items():
        body, dt = INV.api_get(base, p, timeout=timeout)
        pages[p], timings[p] = body, dt
        if body is None:
            out.append(R(f"page_open:{p}", False, f"{label}（{p}）打不开或不是 JSON（{dt:.1f} s）", "get"))
    if all(pages.get(p) is None for p in PAGES):
        return [R("api_down", False, f"本机 API {base} 连不上，页面全部打不开", "get")]
    snap = _j(root / "data/brain/snapshot.json", {}) or {}
    viol = INV.check_pages({p: pages.get(p) for p in INV.API_PAGES if pages.get(p) is not None},
                           {p: timings[p] for p in PAGES if pages.get(p) is not None}, root, snap, now)
    viol += INV.check_picks(root, now)
    if snap and not snap.get("probe_errors"):
        viol += INV.check_ctrl_push(snap, root, str(snap.get("run") or ""))
    for v in viol:
        out.append(R(f"inv:{v['key']}", False, v["title"], "get", v.get("evidence", "")))
    fams = {v["key"].split(":", 1)[0] for v in viol}
    ran = dict(GET_FAMILIES)
    if not (snap and not snap.get("probe_errors")):
        ran.pop("ctrl_unpushed")
    out += [R(f"inv:{k}", True, word, "get") for k, word in ran.items() if k not in fams]
    extra = check_inbox_extra(pages.get("/api/owner/inbox"))
    av = pages.get("/api/owner/adult-trigger")
    if isinstance(av, dict) and av.get("run"):
        RUNS = _load("runs_for_e2e", "tools/autopilot/runs.py")
        extra += check_adult_view(av, _j(Path(RUNS.producer_dir(av["run"], root)) / "owner_triggers.json", {}))
        if not any(x["id"].startswith("adult_view") for x in extra):
            extra.append(R("adult_view", True, "成人镜页面和出图读的触发清单一致", "get"))
    if isinstance(pages.get("/api/owner/inbox"), dict) and not any(x["id"].startswith("inbox_") for x in extra):
        extra.append(R("inbox", True, "待你看读取正常、只给看通过的图", "get"))
    out += extra
    ok_pages = [p for p in PAGES if pages.get(p) is not None]
    out.append(R("pages_open", len(ok_pages) == len(PAGES), f"页面能打开 {len(ok_pages)}/{len(PAGES)}", "get"))
    return out


# ================================================================== post：沙箱里把项目方会点的都点一遍
class Sandbox:
    """临时数据根：只拷消费方要读的最小状态（登记表、资产配置、资产清单），其余从空开始"""

    def __init__(self, real: Path = ROOT):
        self.real = Path(real)
        self.dir = Path(tempfile.mkdtemp(prefix="nsfs_e2e_owner_"))
        self.RUNS = _load("runs_for_e2e_sb", "tools/autopilot/runs.py")
        self.run = self.RUNS.primary_run(self.real)
        for rel in ("config/pipeline/runs.json", "config/pipeline/asset_worker.json"):
            self.copy(rel)
        mp = self.RUNS.asset_manifest(self.run, self.real)
        self.manifest_rel = Path(mp).relative_to(self.real).as_posix() if mp else None
        if self.manifest_rel:
            self.copy(self.manifest_rel)
        self.write("data/owner_queue/requests.json", [])
        self.write("data/sentinel/open.json", {})                       # owner_queue 必需来源（空 = 没有哨兵等待）
        (self.dir / "docs/master").mkdir(parents=True, exist_ok=True)
        (self.dir / "docs/master/MASTER_PICTURE.md").write_text("# 沙箱\n", encoding="utf-8")

    def copy(self, rel: str) -> None:
        src = self.real / rel
        if src.is_file():
            (self.dir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, self.dir / rel)

    def write(self, rel: str, obj) -> Path:
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        data = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        return p

    def rel_real(self, p: Path) -> str:
        """沙箱里的路径 → 真实仓库里同一个相对路径"""
        return Path(p).resolve().relative_to(self.dir.resolve()).as_posix()

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)     # 只删自己建的临时目录（不在仓库里）


OWNER = {"name": "项目方", "role": "owner"}


def _client(*routers):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    return TestClient(app)


def _control_files() -> list[str]:
    RS = _load("resident_sync_for_e2e", "tools/autopilot/resident_sync.py")
    return list(RS.control_files())


def _producer_paths(run: str | None):
    P = _load("producer_for_e2e", "tools/autopilot/producer.py")
    return P.Paths(root=ROOT, run_id=run or None)


class _Recorder:
    def __init__(self, ret=None):
        self.calls: list = []
        self.ret = ret

    def __call__(self, *a, **k):
        self.calls.append((a, k))
        return self.ret(*a, **k) if callable(self.ret) else self.ret


def scenario_pick(sb: Sandbox) -> list[dict]:
    """用这张：场景底图挑选 → pick_state done、清单登记、推送清单含资产清单、待你看不再出现"""
    from ns_api import auth, owner_pick as OP, owner_queue as OQ
    out = []
    if not sb.manifest_rel:
        return [R("pick:manifest", False, f"{sb.run} 没登记资产清单（runs.json assets_manifest），挑选无处登记", "post")]
    AJ = _load("asset_jobs_for_e2e", "tools/pipeline/asset_jobs.py")
    sid = "sk_e2e_probe"
    cands = []
    for k in ("a", "b"):
        b = f"e2e-{k}".encode()
        sb.write(f"data/review_pages/e2e/{k}.png", b)
        cands.append({"key": k, "label": k, "file": f"data/review_pages/e2e/{k}.png", "contract_ok": True,
                      "sha256": __import__("hashlib").sha256(b).hexdigest()})
    pid = f"pick:scene:{sid}"
    pushed = _Recorder(ret=lambda root, host, rels: {"ok": True, "sha": {r: "x" for r in rels}})
    ready = _Recorder()
    with contextlib.ExitStack() as st:
        st.enter_context(mock.patch.object(OP, "REPO", sb.dir))
        st.enter_context(mock.patch.object(OQ, "REPO", sb.dir))
        st.enter_context(mock.patch.object(OP, "_AJ", AJ))
        st.enter_context(mock.patch.object(AJ, "_push_one", pushed))
        st.enter_context(mock.patch.object(OP, "READY_HOOK", ready))
        st.enter_context(mock.patch.object(auth, "user_of", lambda request: OWNER))
        OP.enqueue_pick(sb.dir, {"id": pid, "title": "e2e 场景底图", "run": sb.run, "episode": E2E_EP, "candidates": cands})
        c = _client(OP.router, OQ.router)
        r = c.post("/api/owner/pick", json={"id": pid, "choice": "b"})
        if r.status_code != 202:
            return [R("pick:accept", False, f"点“用这张”没收下（HTTP {r.status_code}）", "post", r.text[:200])]
        stv = c.get(f"/api/owner/pick/{pid}").json()
        out.append(R("pick:done", stv.get("state") == "done", "点“用这张”后状态是“已生效”" if stv.get("state") == "done"
                     else f"点“用这张”后状态停在 {stv.get('state')}（{stv.get('error') or ''}）", "post"))
        d = _j(sb.dir / sb.manifest_rel, {}) or {}
        base = ((d.get("scenes") or {}).get(sid) or {}).get("base") or {}
        out.append(R("pick:manifest", base.get("sha256") == cands[1]["sha256"],
                     "选中的图登记进了出图读的资产清单" if base.get("sha256") == cands[1]["sha256"] else "选中的图没登记进出图读的资产清单", "post",
                     sb.manifest_rel))
        rels = sorted({r_ for (a, _k) in pushed.calls for r_ in a[2]})
        res = ((stv.get("result") or {}).get("push") or {})
        if not pushed.calls:
            out.append(R("pick:push", False, f"选中的图不会推到服务器（{json.dumps(res, ensure_ascii=False)[:80]}）", "post",
                         "config/pipeline/asset_worker.json push"))
        else:
            hosts = sorted({a[1] for (a, _k) in pushed.calls})
            ok = sb.manifest_rel in rels and len(hosts) >= 2
            out.append(R("pick:push", ok, f"资产清单推到 {hosts}" if ok else f"推送清单缺资产清单或只推了 {hosts}", "post", ", ".join(rels)))
        q = OQ.build(sb.dir)
        again = [it for it in q.get("items") or [] if it.get("id") == pid]
        out.append(R("pick:gone", not again, "点过的卡不再出现在待你看" if not again else "点过的卡又出现在待你看", "post"))
        out.append(R("pick:ready_hook", bool(ready.calls), "登记后接着重算资产就绪" if ready.calls else "登记后没触发资产就绪重算（流水线不会往下走）", "post"))
    return out


def scenario_frame_edit(sb: Sandbox) -> list[dict]:
    """首尾帧“修改”：收下 → 交 producer 插队通道 → master_rejects 写在服务器 producer 读的那份，且那份在推送清单里"""
    from ns_api import auth, frame_edit_queue as FEQ
    calls = []

    def fake_run(cmd, *a, **k):
        cmd = list(cmd)
        edit = None
        if "--edit-file" in cmd:
            edit = _j(Path(cmd[cmd.index("--edit-file") + 1]), {})
        calls.append({"cmd": cmd, "edit": edit})
        return __import__("subprocess").CompletedProcess(cmd, 0, "", "")
    shot = f"ep{E2E_EP:02d}-S1"
    with contextlib.ExitStack() as st:
        st.enter_context(mock.patch.object(FEQ, "STATE", sb.dir / "data/state/frame_edit_requests.json"))
        st.enter_context(mock.patch.object(FEQ, "_kick", lambda rid: None))
        st.enter_context(mock.patch.object(FEQ.subprocess, "run", fake_run))
        st.enter_context(mock.patch.object(auth, "user_of", lambda request: OWNER))
        c = _client(FEQ.router)
        r = c.post(f"/api/shots/{shot}/frame-edit", json={"stage": "first", "text": "e2e 验收：人往左一点", "n": 1})
        if r.status_code != 202:
            return [R("edit:accept", False, f"点“修改”没收下（HTTP {r.status_code}）", "post", r.text[:200])]
        rid = r.json()["id"]
        FEQ.process(rid, rewrite=lambda kind, text, ctx: {"prompt": "move left", "zh_summary": "人往左"},
                    check=lambda ctx, d: [], ctx_fn=lambda *a: {"prompt": "x"})
    return judge_reject_calls(calls, "edit", "首尾帧“修改”", "e2e 验收")


def judge_reject_calls(calls: list[dict], key: str, what: str, must_text: str = "") -> list[dict]:
    """producer.py reject 的调用 → 会写哪份 master_rejects（没带 --run = producer 默认剧）→ 那份在不在推送清单"""
    out = []
    rej = [c for c in calls if "reject" in c["cmd"]]
    if not rej:
        return [R(f"{key}:submit", False, f"{what}没交给 producer（出图队列收不到）", "post")]
    cmd = rej[-1]["cmd"]
    run = cmd[cmd.index("--run") + 1] if "--run" in cmd else None
    P = _producer_paths(run)
    rel = Path(P.rejects).relative_to(ROOT).as_posix()
    out.append(R(f"{key}:run", P.run_id == _load("runs_for_e2e_r", "tools/autopilot/runs.py").primary_run(ROOT),
                 f"{what}写进在产剧 {P.run_id} 的修改清单", "post", rel))
    cf = _control_files()
    out.append(R(f"{key}:push", rel in cf, f"{what}会推到服务器（{rel} 在推送清单）" if rel in cf
                 else f"{what}写在 {rel}，但它不在推送清单里——服务器 producer 永远看不到", "post", ", ".join(cf)))
    if must_text:
        e = rej[-1].get("edit") or {}
        ok = must_text in json.dumps(e, ensure_ascii=False)
        out.append(R(f"{key}:text", ok, f"{what}的原话带进了出图要求" if ok else f"{what}的原话没带进出图要求（只换种子）", "post"))
    return out


def scenario_adult(sb: Sandbox) -> list[dict]:
    """成人镜触发（合成夹具，没有任何画面描述）：写进 producer 读的触发清单，且清单在推送列表里"""
    from ns_api import adult_trigger as AT, auth
    sp = Path(AT._runs_mod().script_path(sb.run, sb.dir))
    sb.write(sb.rel_real(sp), {"episodes": [{"number": E2E_EP, "shots": [{"episode": E2E_EP, "index": 1, "duration": 5, "adult": True},
                                                                       {"episode": E2E_EP, "index": 2, "duration": 5, "adult": False}]}]})
    pushed = _Recorder()
    with contextlib.ExitStack() as st:
        st.enter_context(mock.patch.object(AT, "REPO", sb.dir))
        st.enter_context(mock.patch.object(AT, "push_now", pushed))
        st.enter_context(mock.patch.object(auth, "user_of", lambda request: OWNER))
        c = _client(AT.router)
        oid = f"first:ep{E2E_EP:02d}-S1"
        r = c.post("/api/owner/adult-trigger", json={"run": sb.run, "objects": [oid], "note": "e2e 合成夹具"})
        if r.status_code != 200:
            return [R("adult:accept", False, f"成人镜触发没收下（HTTP {r.status_code}）", "post", r.text[:200])]
        tp = AT.triggers_path(sb.run, sb.dir)
    out = []
    objs = set((_j(tp, {}) or {}).get("objects") or [])
    out.append(R("adult:file", oid in objs, "触发写进了触发清单" if oid in objs else "点了触发但触发清单里没有", "post"))
    rel = sb.rel_real(tp)
    prod_rel = (Path(_producer_paths(sb.run).pd) / "owner_triggers.json").relative_to(ROOT).as_posix()
    out.append(R("adult:consumer", rel == prod_rel, "触发清单就是服务器 producer 读的那份" if rel == prod_rel
                 else f"网页写 {rel}，producer 读 {prod_rel}——点了不会出", "post"))
    cf = _control_files()
    out.append(R("adult:push", rel in cf and bool(pushed.calls), "触发清单会马上推到服务器" if rel in cf and pushed.calls
                 else f"触发清单不会推到服务器（在推送清单：{rel in cf}；点完立即推：{bool(pushed.calls)}）", "post"))
    return out


def scenario_asset_revise(sb: Sandbox) -> list[dict]:
    """资产“需要修改描述”写一句：作业记下原话、重排，卡片消失；作业在资产工人读的位置，工人会把原话加进提示词"""
    from ns_api import auth, owner_pick as OP, owner_queue as OQ
    AJ = _load("asset_jobs_for_e2e_rv", "tools/pipeline/asset_jobs.py")
    jid = "e2e-revise-probe"
    job = {"id": jid, "run": sb.run, "kind": "scene", "episode": E2E_EP, "state": "failed", "final": True, "attempts": 2,
           "spec": {"label": "e2e 场景"}, "log": []}
    AJ.save_job(sb.dir, job)
    iid = f"asset_revise:{jid}"
    OQ.enqueue_asset_revise(sb.dir, {"id": iid, "run": sb.run, "job": jid, "name": "e2e", "what": "场景底图", "spec_text": "x", "reason": "x"})
    with contextlib.ExitStack() as st:
        st.enter_context(mock.patch.object(OQ, "REPO", sb.dir))
        st.enter_context(mock.patch.object(OP, "_AJ", AJ))
        st.enter_context(mock.patch.object(auth, "user_of", lambda request: OWNER))
        c = _client(OQ.router)
        r = c.post("/api/owner/decide", json={"id": iid, "choice": "revise", "reason": "e2e 验收：灯再暖一点", "by": "owner"})
        if r.status_code != 200:
            return [R("revise:accept", False, f"“修改描述”没收下（HTTP {r.status_code}）", "post", r.text[:200])]
        q = OQ.build(sb.dir)
    out = []
    j2 = AJ.load_job(AJ.job_path(sb.dir, sb.run, jid))
    ok = j2.get("state") == "pending" and any("灯再暖" in n for n in j2.get("owner_notes") or [])
    out.append(R("revise:job", ok, "原话记进作业并重新排队" if ok else f"原话没记进作业或没重排（state={j2.get('state')}）", "post"))
    real_dir = Path(AJ.jobs_dir(ROOT, sb.run)).relative_to(ROOT).as_posix()
    out.append(R("revise:consumer", sb.rel_real(AJ.jobs_dir(sb.dir, sb.run)) == real_dir, "作业写在资产工人读的目录", "post", real_dir))
    aw = (ROOT / "tools/pipeline/asset_worker.py").read_text(encoding="utf-8")
    out.append(R("revise:prompt", "owner_notes" in aw and "with_owner_notes" in aw, "资产工人会把原话加进提示词" if "with_owner_notes" in aw
                 else "资产工人不读 owner_notes：写了也不会进提示词", "post"))
    again = [it for it in q.get("items") or [] if it.get("id") == iid]
    out.append(R("revise:gone", not again, "写完的卡不再出现在待你看" if not again else "写完“修改”的卡又出现在待你看", "post"))
    return out


SCENARIOS = (("pick", scenario_pick), ("edit", scenario_frame_edit), ("adult", scenario_adult), ("revise", scenario_asset_revise))


def post_part(real: Path = ROOT, only: set | None = None) -> list[dict]:
    out = []
    for name, fn in SCENARIOS:
        if only and name not in only:
            continue
        sb = Sandbox(real)
        try:
            out += fn(sb)
        except Exception as e:  # noqa: BLE001  场景本身崩了 = 这条路径不通，记一条不过（带原因），不影响别的场景
            out.append(R(f"{name}:crash", False, f"{name} 这条项目方路径在沙箱里走不通：{type(e).__name__}: {str(e)[:120]}", "post",
                         traceback.format_exc()[-400:]))
        finally:
            sb.close()
    return out


# ================================================================== 入口
def run(parts: set, root: Path = ROOT, base: str = API, timeout: float = PAGE_TIMEOUT_S) -> dict:
    t0 = time.time()
    res: list[dict] = []
    if "get" in parts:
        res += get_part(root, base, timeout=timeout)
    if "post" in parts:
        res += post_part(root)
    fails = [r for r in res if not r["ok"]]
    return {"schema": "nsfs.e2e_owner/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "parts": sorted(parts), "secs": round(time.time() - t0, 1),
            "n": len(res), "failed": len(fails), "results": res}


def text(rep: dict) -> str:
    L = [f"项目方路径验收：{rep['n'] - rep['failed']}/{rep['n']} 过（{rep['secs']} s）"]
    for r in rep["results"]:
        if not r["ok"]:
            L.append(f"  ❌ {r['line']}" + (f"  〔{r['detail'][:140]}〕" if r.get("detail") else ""))
    L += [f"  ✅ {r['line']}" for r in rep["results"] if r["ok"]]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="项目方路径验收（只读真实数据 + 沙箱 POST）")
    ap.add_argument("--part", default="get,post", help="get / post / get,post")
    ap.add_argument("--api", default=API)
    ap.add_argument("--root", default=str(ROOT), help="真实数据根（只读）")
    ap.add_argument("--timeout", type=float, default=PAGE_TIMEOUT_S)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="", help="结果另存一份 JSON（发版闸门用）")
    a = ap.parse_args(argv)
    rep = run({x.strip() for x in a.part.split(",") if x.strip()}, Path(a.root), a.api, a.timeout)
    if a.out:
        p = Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    print(json.dumps(rep, ensure_ascii=False) if a.json else text(rep))
    return min(rep["failed"], 100)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
