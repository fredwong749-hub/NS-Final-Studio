"""真机冒烟（W-E2E，L-214）：一部 3 镜合成小剧 smoke_e2e 走完整条正常路径——导入 → 资产就绪 → 首帧 → 尾帧 → 视频，
跑在真服务器上、走正常的 producer / night 通道，硬预算 30 分钟。每段记过 / 不过 + 用时。

**只由总调度手动跑**（会在服务器上建状态）；发版闸门不跑它。
  python tools/qa/e2e_smoke.py plan              # 只打印会做什么（不写任何东西）
  python tools/qa/e2e_smoke.py run               # 真跑（结束无论成败都收尾：隔离不删）
  python tools/qa/e2e_smoke.py cleanup           # 上次中断时单独收尾

夹具：eval/smoke/P4_smoke.md（W26 冒烟门的固定 3 镜迷你剧，人物 / 场景借 series10_v2 已登记的祁念 / 唐瑶 / 影棚白幕
sk_white_cyc，只读）。非成人：导入后逐镜核 shot.adult，有任何一镜带成人标记 → 立即中止收尾（成人镜只由项目方触发，冒烟不碰）。

会建的（全部带 smoke_e2e 前缀，收尾时隔离）：
  笔记本  config/pipeline/runs.json 加一条 smoke_e2e（priority 90，非主剧；先 preparing，资产就绪后 producing，收尾改 archived——
          producer 见 archived 自己退）；config/pipeline/video_policy.json scope_runs 临时加 smoke_e2e、config/compile/run_style.json
          runs.smoke_e2e 照抄主剧（两者收尾按备份恢复）；
          data/looks/hub_episode_looks.json 的 smoke_e2e 键；data/pipeline/runs|import/runs|sop_gate|asset_jobs|renders|producer/runs|
          episodes|autopilot/runs 下的 smoke_e2e 目录
  服务器  两台 runs.json / video_policy.json / run_style.json 经资产推送通道（tools/factory/sync verified_install：先备份再原子替换）推新版；
          resident_sync.ensure_runs 按 runs.json 起 producer serve --run smoke_e2e（pid 在 data/producer/runs/smoke_e2e/serve.pid）；
          本脚本在两台起 night.py --run smoke_e2e（pid 记 data/producer/runs/smoke_e2e/night_e2e.pid）；同上 smoke_e2e 数据目录
收尾（cleanup，总在 finally 里跑）：runs.json smoke_e2e → archived 并推两台；只停本脚本记录的 night pid、serve.pid（不 pkill）；
  video_policy.json / run_style.json 按备份恢复并推两台；两台和笔记本的 smoke_e2e 目录整目录 mv 进 data/_quarantine/smoke_e2e/<时间>/（不删）。
不碰：主剧 series10_v2 的任何状态、gpu33:2、功耗、成人镜。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = "smoke_e2e"
EP = 1
BUDGET_S = 30 * 60
POLL_S = 30
HOSTS = ("gpu33", "gpu36")
TEMPLATE_RUN = "smoke_v2"                       # eval/smoke 模板里写的剧名，拷贝时换成 RUN
SMOKE = ROOT / "eval/smoke"
CFG_RUNS, CFG_VIDEO, CFG_STYLE = "config/pipeline/runs.json", "config/pipeline/video_policy.json", "config/compile/run_style.json"
CFG_PUSH = [CFG_RUNS, CFG_VIDEO, CFG_STYLE]          # 推两台的配置（收尾时 video_policy / run_style 按备份恢复后再推一次）
STATE_REL = f"data/qa/e2e_smoke/{RUN}_state.json"      # 本次建了什么 / 起了哪些 pid（收尾按它来，中断后 cleanup 也读它）
OUT_DIR = "data/qa/e2e_smoke"
STAGES = ["preflight", "setup", "import", "assets", "first", "last", "video"]
STAGE_WORD = {"preflight": "预检", "setup": "建剧", "import": "导入", "assets": "资产就绪 + 提示词", "first": "首帧", "last": "尾帧", "video": "视频"}
DONE = {"passed", "done"}
FAILED = {"best_effort", "failed", "exhausted", "blocked"}


class SmokeAbort(Exception):
    """这一段过不去：原因写给总调度看"""


# ================================================================== 环境（真机；测试用 Fake 子类）
class Env:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)

    def now(self) -> float:
        return time.time()

    def sleep(self, s: float) -> None:
        time.sleep(s)

    def py(self) -> str:
        p = self.root / ".venv/Scripts/python.exe"
        return str(p) if p.is_file() else sys.executable

    def sh(self, cmd: list[str], timeout: float) -> tuple[int, str]:
        e = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        try:
            p = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, env=e, stdin=subprocess.DEVNULL)
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired:
            return 124, f"超时 {timeout:.0f}s"

    def rssh(self, host: str, cmd: str, timeout: float = 120) -> tuple[int, str]:
        rs = _mod("rssh_for_smoke", "tools/netfix/rssh.py", self.root)
        H = _mod("hosts_for_smoke", "tools/factory/hosts.py", self.root)
        r = rs.run_retry(host, f"cd {H.server_root(host)} && {cmd}", timeout=timeout, tries=2, text=True)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def push_files(self, rels: list[str]) -> dict:
        """资产推送通道（asset_jobs.push_files → tools/factory/sync verified_install：先备份再核 sha 原子替换）"""
        AJ = _mod("asset_jobs_for_smoke", "tools/pipeline/asset_jobs.py", self.root)
        return AJ.push_files(self.root, rels, hosts=HOSTS)

    def rs(self):
        return _mod("resident_sync_for_smoke", "tools/autopilot/resident_sync.py", self.root)

    def runs(self):
        return _mod("runs_for_smoke", "tools/autopilot/runs.py", self.root)


def _mod(name: str, rel: str, _data_root: Path = ROOT):
    """代码永远从本仓库取（数据根可以是测试的临时目录，按参数传给各函数）"""
    import importlib.util
    if str(ROOT / "tools/autopilot") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools/autopilot"))
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _j(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 没有 / 坏 = 默认（调用方按“还没有”处理）
        return default


def _jw(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _rel(p) -> str:
    return Path(p).resolve().relative_to(ROOT.resolve()).as_posix()


def run_dirs() -> list[str]:
    """smoke_e2e 的全部数据目录（按剧取路径一律走 runs.py；与笔记本 / 服务器同一相对路径）"""
    RUNS = _mod("runs_for_smoke_dirs", "tools/autopilot/runs.py")
    return [_rel(RUNS.run_dir(RUN, ROOT)), _rel(Path(RUNS.import_path(RUN, ROOT)).parent), f"data/pipeline/sop_gate/{RUN}",
            f"data/pipeline/asset_jobs/{RUN}", _rel(RUNS.renders_dir(RUN, ROOT)), _rel(RUNS.producer_dir(RUN, ROOT)),
            f"data/episodes/{RUN}", f"data/autopilot/runs/{RUN}"]


def hub_looks_rel() -> str:
    """本集造型排期文件（全局，按剧一个键）= ns_agent.asset_refs.HUB_EP_LOOKS"""
    if str(ROOT / "services/agent") not in sys.path:
        sys.path.insert(0, str(ROOT / "services/agent"))
    from ns_agent import asset_refs as AR  # noqa: PLC0415
    return _rel(AR.HUB_EP_LOOKS)


def stamp(t: float) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(t + 9 * 3600))      # JST


# ================================================================== 纯函数（可测）
def registry_progress(reg: dict | None, kind: str) -> dict:
    """服务器 producer 登记表 → 这一阶段 {shots, done, failed, why}"""
    out = {"shots": 0, "done": 0, "failed": [], "running": 0}
    for E in (reg or {}).get("episodes") or []:
        if int(E.get("ep") or 0) != EP:
            continue
        for S in E.get("shots") or []:
            o = (S.get("objects") or {}).get(kind) or {}
            out["shots"] += 1
            st = str(o.get("status") or "")
            if st in DONE:
                out["done"] += 1
            elif st in FAILED:
                out["failed"].append(f"{S.get('shot')}：{st} {str(o.get('last_error') or o.get('reason') or '')[:60]}")
            elif st == "running":
                out["running"] += 1
    return out


def video_progress(states: list[dict | None], shots: int) -> dict:
    done, failed = set(), []
    for st in states:
        for sid, r in ((st or {}).get("shots") or {}).items():
            if not str(sid).startswith(f"ep{EP:02d}-"):
                continue
            if r.get("status") == "done":
                done.add(sid)
            elif r.get("status") in ("best_effort", "failed"):
                failed.append(f"{sid}：{r.get('status')}")
    return {"shots": shots, "done": len(done), "failed": sorted(set(failed) - {f"{s}：best_effort" for s in done})}


def adult_shots(doc: dict) -> list[str]:
    return [f"ep{EP:02d}-S{s.get('index')}" for e in doc.get("episodes") or [] for s in e.get("shots") or [] if s.get("adult")]


def night_env(host: str) -> str:
    """服务器常驻进程的环境（与 ops/offline/ensure_runs.sh 同口径）"""
    other = "gpu33" if host == "gpu36" else ""
    return (f"TZ=Asia/Tokyo OFFLINE_SELF={host} OFFLINE_ALIASES={other} PATH=$PWD/../bin:$PATH PYTHONUTF8=1 PYTHONIOENCODING=utf-8 "
            f"NS_QC_VISION_DIR=$PWD/models_cache/vision")


def seed_text(text: str) -> str:
    return text.replace(TEMPLATE_RUN, RUN)


# ================================================================== 冒烟
class Smoke:
    def __init__(self, env: Env, budget_s: float = BUDGET_S, poll_s: float = POLL_S, dry: bool = False):
        self.env, self.budget_s, self.poll_s, self.dry = env, budget_s, poll_s, dry
        self.root = env.root
        self.rows: list[dict] = []
        self.t0 = env.now()
        self.deadline = self.t0 + budget_s
        self.state = _j(self.root / STATE_REL, {}) or {}
        self.plan: list[str] = []

    # ---------------------------------------------------------------- 小工具
    def do(self, what: str, fn, *a, **k):
        """dry = 只记计划；否则执行"""
        self.plan.append(what)
        return None if self.dry else fn(*a, **k)

    def save_state(self) -> None:
        if not self.dry:
            _jw(self.root / STATE_REL, self.state)

    def left(self) -> float:
        return self.deadline - self.env.now()

    def wait(self, what: str, probe, ok, failed=None) -> dict:
        """轮询到 ok(结果) / failed(结果) 给原因 / 预算用完"""
        last = None
        while True:
            last = probe()
            if ok(last):
                return last
            why = failed(last) if failed else None
            if why:
                raise SmokeAbort(f"{what}：{why}")
            if self.left() <= 0:
                raise SmokeAbort(f"{what}：30 分钟预算用完（最后状态 {json.dumps(last, ensure_ascii=False)[:160]}）")
            self.env.sleep(min(self.poll_s, max(1.0, self.left())))

    # ---------------------------------------------------------------- 各段
    def preflight(self) -> str:
        RUNS = self.env.runs()
        reg = RUNS.registry(self.root)
        if reg.get("primary") == RUN:
            raise SmokeAbort(f"{RUN} 是主剧，不能拿来冒烟")
        cur = ((reg.get("runs") or {}).get(RUN) or {}).get("status")
        if cur in ("producing", "preparing"):
            raise SmokeAbort(f"{RUN} 已在 {cur}（上次没收尾？先跑 cleanup）")
        for h in HOSTS:
            rc, out = self.env.rssh(h, "echo ok", timeout=60)
            if rc != 0 or "ok" not in out:
                raise SmokeAbort(f"{h} 连不上（rc={rc}）")
        if not (SMOKE / "P4_smoke.md").is_file():
            raise SmokeAbort("夹具 eval/smoke/P4_smoke.md 不在")
        return f"两台可连；{RUN} 现状 {cur or '没登记'}"

    def setup(self) -> str:
        st = stamp(self.env.now())
        self.state = {"stamp": st, "started": self.t0, "created": [], "pids": {}, "backups": {}}
        moved = self.do(f"隔离笔记本上次残留的 {RUN} 目录 → data/_quarantine/{RUN}/{st}/", quarantine_local, self.root, st) or []
        rd = self.root / f"data/pipeline/runs/{RUN}"

        def seed():
            tpl = SMOKE / "template/pipeline_run"
            for p in tpl.rglob("*"):
                if p.is_file():
                    dst = rd / p.relative_to(tpl)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_text(seed_text(p.read_text(encoding="utf-8")), encoding="utf-8")
            (rd / f"P4_ep{EP:02d}.md").write_text(seed_text((SMOKE / "P4_smoke.md").read_text(encoding="utf-8")), encoding="utf-8")
            hub = _j(SMOKE / "template/hub_episode_looks.json", {}) or {}
            want = hub.get(TEMPLATE_RUN)
            if isinstance(want, dict):
                d = _j(self.root / hub_looks_rel(), {}) or {}
                d[RUN] = json.loads(seed_text(json.dumps(want, ensure_ascii=False)))
                _jw(self.root / hub_looks_rel(), d)
        self.do(f"按 eval/smoke 模板建 {rd.relative_to(self.root).as_posix()}（剧名换成 {RUN}）+ {hub_looks_rel()} 的 {RUN} 键", seed)

        def register():
            RUNS = self.env.runs()
            RUNS.register_run(RUN, source="e2e-smoke", episode=EP, priority=90, root=self.root)
            d = _j(self.root / CFG_RUNS, {})
            d["runs"][RUN]["assets_manifest"] = (d["runs"].get(RUNS.primary_run(self.root)) or {}).get("assets_manifest") or "assets_v2/manifest.json"
            d["runs"][RUN]["note"] = "W-E2E 真机冒烟（tools/qa/e2e_smoke.py）：非主剧、借主剧资产清单只读；收尾改 archived"
            _jw(self.root / CFG_RUNS, d)
            vp = _j(self.root / CFG_VIDEO, {}) or {}
            rs = _j(self.root / CFG_STYLE, {}) or {}
            self.state["backups"] = {CFG_VIDEO: json.loads(json.dumps(vp)), CFG_STYLE: json.loads(json.dumps(rs))}
            self.save_state()                                # 先落备份再改
            scope = list(vp.get("scope_runs") or [])
            if RUN not in scope:
                vp["scope_runs"] = scope + [RUN]
                _jw(self.root / CFG_VIDEO, vp)
            prim = RUNS.primary_run(self.root)
            if (rs.get("runs") or {}).get(prim) is not None:   # 编译规则按剧取（bible.py：资产包剧没有自己的 bible 就拒绝）→ 照抄主剧那份
                rs["runs"][RUN] = json.loads(json.dumps(rs["runs"][prim]))
                _jw(self.root / CFG_STYLE, rs)
        self.do(f"{CFG_RUNS} 登记 {RUN}（priority 90、preparing、非主剧）；{CFG_VIDEO} scope_runs 临时加 {RUN}、{CFG_STYLE} runs.{RUN} 照抄主剧（都先备份）", register)
        self.state["created"] = run_dirs() + [CFG_RUNS + f"#{RUN}", CFG_VIDEO + "#scope_runs", CFG_STYLE + f"#runs.{RUN}", hub_looks_rel() + f"#{RUN}"]
        self.save_state()
        return f"隔离旧目录 {moved or '无'}"

    def import_(self) -> str:
        RUNS = self.env.runs()
        md = self.root / f"data/pipeline/runs/{RUN}/P4_ep{EP:02d}.md"
        out = self.root / _rel(RUNS.import_path(RUN, ROOT))

        def imp():
            out.parent.mkdir(parents=True, exist_ok=True)
            rc, txt = self.env.sh([self.env.py(), "-X", "utf8", str(self.root / "tools/import_script.py"), "--script", str(md), "-o", str(out),
                                   "--no-timeline"], 900)
            if rc != 0:
                raise SmokeAbort(f"导入失败 rc={rc}：{txt.strip()[-160:]}")
            doc = _j(out, {}) or {}
            bad = adult_shots(doc)
            if bad:
                raise SmokeAbort(f"夹具里有带成人标记的镜 {bad}：冒烟不碰成人镜，中止")
            shots = sum(len(e.get("shots") or []) for e in doc.get("episodes") or [])
            if not 2 <= shots <= 3:
                raise SmokeAbort(f"导入后 {shots} 镜（夹具应是 2–3 镜）")
            self.state["shots"] = shots
            self.save_state()
            return shots
        n = self.do(f"tools/import_script.py 导入 {md.relative_to(self.root).as_posix()} → {RUN} 导入稿；核每镜 shot.adult 为假", imp)
        return f"{n or '?'} 镜，全部非成人"

    def assets(self) -> str:
        def ready():
            rc, txt = self.env.sh([self.env.py(), "-X", "utf8", str(self.root / "tools/master/episode_ready.py"), "--run", RUN, "--episode", str(EP),
                                   "--json"], 900)
            try:
                res = json.loads(txt[txt.index("{"):])
            except ValueError:
                raise SmokeAbort(f"episode_ready 没给 JSON（rc={rc}）") from None
            if not res.get("ready") or res.get("gaps"):
                raise SmokeAbort(f"资产没就绪：{[g.get('what') for g in res.get('gaps') or []][:3]}")
            AJ = _mod("asset_jobs_for_smoke_g", "tools/pipeline/asset_jobs.py", self.root)
            AJ.generate(RUN, EP, root=self.root, res=res)
            rc, txt = self.env.sh([self.env.py(), "-X", "utf8", str(self.root / "tools/master/sop_gate.py"), "probe-prompts", "--run", RUN,
                                   "--episode", str(EP)], 1200)
            SG = _mod("sop_gate_for_smoke", "tools/master/sop_gate.py", self.root)
            j = SG.judge(RUN, EP, "出图", root=self.root)
            if not j.get("ok"):
                raise SmokeAbort(f"出图闸门不放：{'；'.join(j.get('missing') or [])[:200]}")
            self.env.runs().set_status(RUN, "producing", by="W-E2E e2e_smoke", why="冒烟：资产就绪 + 提示词证据齐", root=self.root)
        self.do(f"episode_ready → asset_jobs.generate → sop_gate probe-prompts → sop_gate.judge 出图；runs.json {RUN} → producing", ready)

        def to_servers():
            res = self.env.push_files(CFG_PUSH)
            bad = [h for h, v in (res or {}).items() if not (isinstance(v, dict) and v.get("ok"))]
            if bad:
                raise SmokeAbort(f"runs.json / video_policy.json / run_style.json 推不上 {bad}")
            RS = self.env.rs()
            for h in HOSTS:
                RS.run_sync_tick(h, runs=[RUN])              # 本剧的导入稿 / 提示词证据 / 资产就绪 / 资产清单
                RS.push_control(h, force=True)               # 本剧的 ready 清单（control_files 按在产剧算）
                out = RS.ensure_runs(h)                      # 按 runs.json 起 producer serve --run smoke_e2e
                self.state["pids"][f"{h}:serve"] = f"data/producer/runs/{RUN}/serve.pid"
                self.state.setdefault("ensure_out", {})[h] = str(out)[-200:]
            self.save_state()
        self.do(f"推 {' / '.join(CFG_PUSH)} 到两台；resident_sync.run_sync_tick(runs=[{RUN}]) + push_control + ensure_runs（起 producer serve --run {RUN}）",
                to_servers)
        return "资产就绪、出图闸门放行、两台 producer 已按 runs.json 起"

    def server_registry(self, host: str) -> dict | None:
        rc, out = self.env.rssh(host, f"cat data/producer/runs/{RUN}/registry.json", timeout=60)
        if rc != 0:
            return None
        try:
            return json.loads(out[out.index("{"):])
        except ValueError:   # arch-ok: 写了一半 / 还没有 = 本轮当没进度，下一轮再读
            return None

    def frames(self, kind: str) -> str:
        if self.dry:
            self.plan.append(f"每 {self.poll_s:.0f}s 读两台 data/producer/runs/{RUN}/registry.json，等 {kind} 全部 passed（尽力 / 失败 = 不过）")
            return "dry"
        shots = int(self.state.get("shots") or 0)

        def probe():
            best = {"shots": 0, "done": 0, "failed": [], "running": 0}
            for h in HOSTS:
                p = registry_progress(self.server_registry(h), kind)
                if (p["done"], p["shots"]) > (best["done"], best["shots"]):
                    best = {**p, "host": h}
            return best
        got = self.wait(STAGE_WORD[kind], probe, lambda p: p["shots"] >= shots > 0 and p["done"] >= shots,
                        lambda p: ("、".join(p["failed"][:3]) if p["failed"] else None))
        return f"{got['done']}/{shots} 过（{got.get('host')}）"

    def video(self) -> str:
        cmd = (f"mkdir -p data/producer/runs/{RUN} data/pipeline/runs/{RUN}/video && "
               f"(export {night_env('$SELF')}; setsid nohup ../venv/bin/python -u tools/series10_video/night.py --run {RUN} </dev/null "
               f">>data/pipeline/runs/{RUN}/video/night_e2e.out 2>&1 & echo $! > data/producer/runs/{RUN}/night_e2e.pid) && "
               f"cat data/producer/runs/{RUN}/night_e2e.pid")
        if self.dry:
            self.plan.append(f"两台起 night.py --run {RUN}（pid 记 data/producer/runs/{RUN}/night_e2e.pid）；"
                             f"每 {self.poll_s:.0f}s 读 data/pipeline/runs/{RUN}/video/state_<台>.json，等每镜 done")
            return "dry"
        for h in HOSTS:
            rc, out = self.env.rssh(h, cmd.replace("$SELF", h), timeout=60)
            if rc != 0:
                raise SmokeAbort(f"{h} 起不了 night.py --run {RUN}：{out.strip()[-120:]}")
            self.state["pids"][f"{h}:night"] = f"data/producer/runs/{RUN}/night_e2e.pid"
        self.save_state()
        shots = int(self.state.get("shots") or 0)

        def probe():
            sts = []
            for h in HOSTS:
                rc, out = self.env.rssh(h, f"cat data/pipeline/runs/{RUN}/video/state_{h}.json 2>/dev/null || echo '{{}}'", timeout=60)
                try:
                    sts.append(json.loads(out[out.index("{"):]) if rc == 0 else None)
                except ValueError:   # arch-ok: 没有 / 写了一半 = 这台本轮没进度
                    sts.append(None)
            return video_progress(sts, shots)
        got = self.wait("视频", probe, lambda p: p["done"] >= shots > 0, lambda p: ("、".join(p["failed"][:3]) if p["failed"] else None))
        return f"{got['done']}/{shots} 出完并过打分"

    # ---------------------------------------------------------------- 收尾（隔离不删；只停自己记录的进程）
    def cleanup(self) -> list[str]:
        notes: list[str] = []
        st = self.state.get("stamp") or stamp(self.env.now())

        def archive():
            try:
                self.env.runs().set_status(RUN, "archived", by="W-E2E e2e_smoke", why="冒烟收尾", root=self.root)
            except Exception as e:  # noqa: BLE001  # arch-ok: 没登记 = 不用改（记一句）
                notes.append(f"runs.json 改 archived 没成：{e}")
            for rel, d in (self.state.get("backups") or {}).items():
                if isinstance(d, dict) and d:
                    _jw(self.root / rel, d)
            res = self.env.push_files(CFG_PUSH)
            notes.append(f"runs.json（{RUN}=archived）/ video_policy / run_style 恢复 推两台：{ {h: bool((v or {}).get('ok')) for h, v in (res or {}).items()} }")
        self.do(f"{CFG_RUNS} {RUN} → archived（producer 自己退）；{CFG_VIDEO} / {CFG_STYLE} 按备份恢复；两台推新版", archive)
        for h in HOSTS:
            kill = " ; ".join(
                f"[ -f {pf} ] && p=$(cat {pf}) && grep -q '{pat}' /proc/$p/cmdline 2>/dev/null && grep -q '{RUN}' /proc/$p/cmdline 2>/dev/null"
                f" && kill $p && echo killed:{pf}:$p"
                for pf, pat in ((f"data/producer/runs/{RUN}/night_e2e.pid", f"night.py"), (f"data/producer/runs/{RUN}/serve.pid", "producer.py")))
            mv = (f"d=data/_quarantine/{RUN}/{st}; mkdir -p $d && for x in " + " ".join(run_dirs())
                  + "; do [ -e $x ] && mkdir -p $d/$(dirname $x) && mv $x $d/$x && echo moved:$x; done; true")

            def remote(h=h, kill=kill, mv=mv):
                rc, out = self.env.rssh(h, f"sleep 5; {kill}; true", timeout=120)
                notes.append(f"{h} 停本脚本记的进程：{' '.join(x for x in out.split() if x.startswith('killed:')) or '无（已自己退）'}")
                rc, out = self.env.rssh(h, mv, timeout=300)
                notes.append(f"{h} 隔离：{' '.join(x for x in out.split() if x.startswith('moved:')) or '无'}")
            self.do(f"{h}：只停 night_e2e.pid / serve.pid 记的进程（核命令行）；{RUN} 目录 mv → data/_quarantine/{RUN}/{st}/", remote)
        moved = self.do(f"笔记本：{RUN} 目录 mv → data/_quarantine/{RUN}/{st}/；{hub_looks_rel()} 的 {RUN} 键挪进隔离清单", quarantine_local, self.root, st, True)
        if moved is not None:
            notes.append(f"笔记本隔离：{moved or '无'}")
        self.state["cleaned"] = stamp(self.env.now())
        self.save_state()
        return notes

    # ---------------------------------------------------------------- 主流程
    def run(self) -> dict:
        steps = {"preflight": self.preflight, "setup": self.setup, "import": self.import_, "assets": self.assets,
                 "first": lambda: self.frames("first"), "last": lambda: self.frames("last"), "video": self.video}
        failed = None
        started = False
        try:
            for sid in STAGES:
                if failed:
                    self.rows.append({"stage": sid, "name": STAGE_WORD[sid], "ok": False, "secs": 0, "why": "前一段没过，没跑"})
                    continue
                t = self.env.now()
                try:
                    if sid == "setup":
                        started = True
                    why = steps[sid]()
                    self.rows.append({"stage": sid, "name": STAGE_WORD[sid], "ok": True, "secs": round(self.env.now() - t, 1), "why": why})
                except SmokeAbort as e:
                    failed = sid
                    self.rows.append({"stage": sid, "name": STAGE_WORD[sid], "ok": False, "secs": round(self.env.now() - t, 1), "why": str(e)})
                except Exception as e:  # noqa: BLE001  任何崩溃都记成这一段不过（带原因），照样收尾
                    failed = sid
                    self.rows.append({"stage": sid, "name": STAGE_WORD[sid], "ok": False, "secs": round(self.env.now() - t, 1),
                                      "why": f"{type(e).__name__}: {str(e)[:200]}"})
        finally:
            notes = self.cleanup() if started else ["预检没过，什么都没建，不用收尾"]
        total = round(self.env.now() - self.t0, 1)
        rep = {"schema": "nsfs.e2e_smoke/1", "run": RUN, "dry": self.dry, "ok": failed is None and not self.dry, "failed_stage": failed,
               "secs": total, "budget_s": self.budget_s, "within_budget": total <= self.budget_s, "stages": self.rows, "cleanup": notes,
               "plan": self.plan}
        if not self.dry:
            _jw(self.root / OUT_DIR / f"{RUN}_{self.state.get('stamp') or stamp(self.t0)}.json", rep)
        return rep


def quarantine_local(root: Path, st: str, hub_key: bool = False) -> list[str]:
    """笔记本上 smoke_e2e 目录整目录 mv 进 data/_quarantine/smoke_e2e/<st>/（不删）；hub_key=True 时把排期文件的 smoke_e2e 键
    挪进隔离目录的 hub_episode_looks.smoke_e2e.json 再从排期里拿掉"""
    moved = []
    base = root / "data/_quarantine" / RUN / st
    for d in run_dirs():
        src = root / d
        if src.exists():
            dst = base / d
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append(d)
    if hub_key:
        d = _j(root / hub_looks_rel(), None)
        if isinstance(d, dict) and RUN in d:
            _jw(base / "hub_episode_looks.smoke_e2e.json", {RUN: d.pop(RUN)})
            _jw(root / hub_looks_rel(), d)
            moved.append(hub_looks_rel() + f"#{RUN}")
    return moved


def table(rep: dict) -> str:
    L = [f"真机冒烟 {RUN}：{'过' if rep['ok'] else ('计划（dry）' if rep['dry'] else '不过：' + str(rep['failed_stage']))}，"
         f"总用时 {rep['secs']} s / 预算 {rep['budget_s']:.0f} s"]
    L += [f"  {'✅' if r['ok'] else '❌'} {r['name']:<10} {r['secs']:>7.1f} s  {r['why']}" for r in rep["stages"]]
    if rep["plan"] and rep["dry"]:
        L.append("会做的事：")
        L += [f"  {i + 1}. {x}" for i, x in enumerate(rep["plan"])]
    L += [f"  收尾：{x}" for x in rep["cleanup"]]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="真机冒烟（只由总调度手动跑）")
    ap.add_argument("cmd", choices=["plan", "run", "cleanup"])
    ap.add_argument("--budget-min", type=float, default=BUDGET_S / 60)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    env = Env()
    if a.cmd == "cleanup":
        s = Smoke(env)
        print("\n".join(s.cleanup()))
        return 0
    s = Smoke(env, budget_s=a.budget_min * 60, dry=(a.cmd == "plan"))
    if a.cmd == "plan":
        s.preflight = lambda: "（plan 不连服务器）"
    rep = s.run()
    print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else table(rep))
    return 0 if rep["ok"] or rep["dry"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
