"""PRODUCER：制作监督（常驻服务）——一部剧从剧本到成片按依赖自动推进，人类只处理闸门（项目方 11-01）。

项目方原话：“http://localhost:5173/#/script-create?run=series10_v1 自动执行对应制作,人类不应该点,坏了,系统自动做”
（11-01 选方案 A：常驻监督服务 + 阶段推进不再让他点；删除 / 花钱 / 推翻旧决定仍问他。规则 K-OPS-A01。）

一、状态（每个对象一条链，状态全部从真实记录现推，不另存一份）
    剧本 P0–P4（story_runs 摘要 / P4 校验报告）→ 导入（系统剧本 data/import/script_v2.json）→ 资产（生成契约 preflight）
    → 每镜：首帧 → 尾帧（takes.json 当前版本 + postflight）→ 视频片段（video/state_<host>.json、takes.json video）
    → 每集：声音（config/voices.json 演员表 + TTS 缓存）→ BGM（data/music/series10/epNN.wav）→ 合成（data/episodes/series10）
    → 审片页（data/review_pages/series10_video/epNN）
    状态：pending（依赖没过）/ ready（可以派）/ running / passed / failed / best_effort（尽力，不进合成）。
    每个对象另记 attempts（内容尝试次数，≤3）/ last_error / reason（人话）/ waiting_for / where（哪条道 / 哪个会话）。
    尝试账本 data/producer/attempts.json 只记本服务自己派过的尝试（不是状态副本）。
二、触发：依赖都过了的对象自动派：首帧 / 尾帧走唯一出图路径（K-REN-134：ns_agent.frame_job + ns_render.unified_frame，
    preflight 不过不提交），每条空闲道一个（道上有别人的任务就让道），每个任务带 comfy_tag（K-OPS-G01，agent=PRODUCER）。
    视频：VIDEO10 的 night.py 在跑时由它按集派；本服务在“一集每镜首尾帧都定下（通过 / 尽力）”时写 night_control.json
    force_eps 放行该集（不再等人点）；night.py 退役后本服务直接调它的 loop_once（cutover 见 docs/AUTOPILOT.md §7）。
三、自修阶梯（内容失败）：第 1 次 → 第 2 次换 seed → 第 3 次换参考（双人镜两张脸各占一槽，否则再换 seed）→ 仍不过 = 尽力
    （取契约分最好的一版设为当前，标 best_effort，写人话原因，不进合成）。preflight 不过：不提交，记原因；缺身份参考 = 项目方闸门。
    基础设施错误（隧道断、502、OOM、缓存文件缺失、超时）：退避（30 s × 2^k，≤10 min）+ 换道，不算内容尝试。
四、租约：data/producer/leases/<对象>.json（O_EXCL 创建；过期 / 进程没了即失效）。别的会话正在做的对象（ASSETMASTER frames_v2
    在跑的集、VIDEO10 已派的集、画布任务队列里该镜的任务）当外部租约，不重复提交。
五、服务：serve 常驻（每 20 s 一轮），心跳 data/producer/heartbeat.json，日志 data/producer/log.jsonl（只追加），
    登记表 data/producer/registry.json（与 GPUVIEW /api/render-tasks 共用这一份），控制 data/producer/control.json
    （paused = 项目方暂停；hold_lanes；workers.frames = producer|off；workers.video = VIDEO10|producer）。
    ns_api：GET /api/producer/status、POST /api/producer/pause|resume（services/api/ns_api/producer.py）。

    .venv/Scripts/python.exe tools/autopilot/producer.py serve            # 常驻（ops/autostart/laptop_autostart.ps1 拉起）
    .venv/Scripts/python.exe tools/autopilot/producer.py once [--only ep02-S1,ep02-S2] [--wait]
    .venv/Scripts/python.exe tools/autopilot/producer.py status
    .venv/Scripts/python.exe tools/autopilot/producer.py pause|resume [--by owner]
    .venv/Scripts/python.exe tools/autopilot/producer.py dryrun [--inject-fail]   # 临时目录演练：首帧 → 尾帧 → 视频，零点击

不做内容检测：本服务只看契约结果和文件是否存在，不看图、不评价剧本。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# K-OPS-E18（DEBUG-RSI 11-02 04:3x）：项目时间一律 Asia/Tokyo。服务器常驻 producer 由 resident_restart.sh 设了 TZ，
# 但经 ssh 调的 CLI（restart_queue 排空 pause、reject、server-control…）没设 → 写出 EST 时间戳（早 14 h）：
# 暂停时长算错（SENTINEL“pause 占 54.5%”大半是假象）、master_rejects 按时间合并时新条目被笔记本旧值盖回。这里在进程内强制统一
if os.environ.get("TZ") != "Asia/Tokyo" and hasattr(time, "tzset"):
    os.environ["TZ"] = "Asia/Tokyo"
    time.tzset()
for _p in ("services/render_router", "services/agent", "packages/schema", "tools/pipeline", "tools/gen_contract",
           "tools/series10_video", "services/api", "services/recipes"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

AGENT = "PRODUCER"
def _run_id_from_config(default: str = "series10_v1") -> str:
    """K-OPS-W15 / DISTILL 冷启动 ①：现行运行 ID 只从 config/pipeline/run.json 读（换一部剧只改一处）。
    读不到时这里仍给默认值（只为模块能导入），但 K-OPS-F09 decisions_guard 会在派单前拒派并报警，不再静默按 series10_v1 生产"""
    try:
        v = json.loads((Path(__file__).resolve().parents[2] / "config" / "pipeline" / "run.json").read_text(encoding="utf-8")).get("run_id")
        return str(v).strip() or default
    except (OSError, ValueError, AttributeError):
        return default


RUN_ID = _run_id_from_config()
MAX_TRIES = 3                       # GEN_CONTRACT：每镜每阶段内容尝试 ≤3
TICK_S = 20
LEASE_S = 45 * 60                   # 一次出图 + 取回的上限；过期视为失效
INFRA_BACKOFF = (30, 60, 120, 300, 600)
PREFLIGHT_RETRY_S = 30 * 60
CODE_RETRY_S = 5 * 60               # 系统代码 / 接口不匹配：5 分钟后再试（多半已热修），不再停 30 分钟         # preflight 不过：资料可能被别的会话补上，30 分钟后再查
# 出图道（gpu36:2 是长镜头视频专用道，不派出图；gpu33 GPU2 永不使用）
IMAGE_LANES = {"gpu33:0": "http://127.0.0.1:18188", "gpu33:1": "http://127.0.0.1:18189", "gpu33:3": "http://127.0.0.1:18191",
               "gpu36:0": "http://127.0.0.1:18288", "gpu36:1": "http://127.0.0.1:18289"}
DEFAULT_CTRL = {"paused": False, "run": RUN_ID, "hold_lanes": [], "only": [],
                "workers": {"frames": "producer", "video": "VIDEO10"}, "auto_force_eps": True}
STATUSES = ("pending", "ready", "running", "passed", "failed", "best_effort")
KIND_WORD = {"script": "剧本", "import": "导入", "assets": "资产", "first": "首帧", "last": "尾帧", "video": "视频",
             "voice": "声音", "bgm": "配乐", "assembly": "合成", "preview": "审片页"}


def vlm_instances() -> int:
    """K-OPS-E05：看图（VLM）并发实例数——config/vqa.json model.instances（VQAGATE 加多实例时填），环境变量 NS_VQA_INSTANCES 优先；
    打分积压上限 = 2 × 道数 × 实例数（总调度 01:0x：阈值跟着看图并发数自动算）"""
    try:
        v = os.environ.get("NS_VQA_INSTANCES") or (json.loads((ROOT / "config" / "vqa.json").read_text(encoding="utf-8")).get("model") or {}).get("instances")
        return max(1, int(v or 1))
    except (OSError, ValueError, TypeError):
        return 1


def redo_ladder_policy() -> dict:
    """config/policies/retry.yaml redo_ladder（单一来源）；读不到按默认"""
    d = {"heavy_plan": ["frame_v9_heavy", "frame_v9_heavy"]}
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import policy as POL
        it = POL.item("retry.redo_ladder", ROOT)
        d.update({k: v for k, v in (it.get("value") or {}).items() if k in d})
    except Exception:  # noqa: BLE001
        pass
    return d


def job_sig(paths, sid: str) -> str | None:
    """本镜现在编译出的作业签名：提示词 + compiler_inputs_sha + 参考图（路径 + 修改时间）的哈希；作业表里没有 → None"""
    import hashlib
    jobs = (jl(paths.run / "assets" / "first_frame_jobs.json", {}) or {}).get("jobs") or []
    job = next((j for j in jobs if j.get("shot") == sid or j.get("id") == sid), None)
    if not job:
        return None
    parts = [job.get("prompt") or "", str(job.get("compiler_inputs_sha") or "")]
    for r in job.get("refs") or []:
        try:
            parts.append(f"{r}@{round((paths.root / str(r)).stat().st_mtime)}")
        except OSError:
            parts.append(str(r))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def redo_inputs_changed_v2(paths, sid: str, kind: str, led: dict) -> str | None:
    """K-OPS-E09 修订（11-02 08:4x，ep05-S3 出到第 82 版的根因）：只拿“现在的作业签名”和“上次重置 / 升级时记下的签名”比；
    第一次（没记过）才退回比参考图修改时间 / 编译输入哈希。绝不拿出图后的提示词比（出图时会追加朝向句 / 看图修正，永远不同）"""
    sig = job_sig(paths, sid)
    if not sig:
        return None
    last = led.get("ladder_sig")
    if last:
        return "作业输入变了" if sig != last else None
    why = redo_inputs_changed(paths, sid, kind, led)
    return why if why and why != "提示词变了" else None


def redo_inputs_changed(paths, sid: str, kind: str, led: dict) -> str | None:
    """最后一次驳回重出那一版的输入 vs 现在编译出的作业：提示词 / 编译输入哈希 / 参考图集合 / 参考图文件比那一版新 → 说明；没变 None"""
    try:
        from ns_render import pipeline as P
        hist = [h for h in led.get("redo_history") or [] if h.get("take")]
        if not hist:
            return None
        n = hist[-1]["take"]
        stage = "image" if kind == "first" else "last"
        t = next((x for x in P.load_takes(sid).get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None)
        if not t:
            return None
        jobs = (jl(paths.run / "assets" / "first_frame_jobs.json", {}) or {}).get("jobs") or []
        job = next((j for j in jobs if j.get("shot") == sid or j.get("id") == sid), None)
        if not job:
            return None
        if kind == "first" and (job.get("prompt") or "").strip() != (t.get("prompt") or "").strip():
            return "提示词变了"
        if job.get("compiler_inputs_sha") and t.get("inputs_sha") and job["compiler_inputs_sha"] != t["inputs_sha"]:
            return "编译输入哈希变了"
        old = t.get("refs") or t.get("references") or []
        old = {Path(str(x if isinstance(x, str) else (x.get("file") or x.get("path") or ""))).name for x in old} - {""}
        new = {Path(str(r)).name for r in job.get("refs") or []}
        if old and new and old != new:
            return "参考图换了：" + "、".join(sorted(new - old))[:80]
        t0 = time.mktime(time.strptime(str(t.get("created_at"))[:19], "%Y-%m-%dT%H:%M:%S"))
        for r in job.get("refs") or []:
            f = paths.root / str(r)
            if f.exists() and f.stat().st_mtime > t0:
                return "参考图更新了：" + f.name
    except Exception:  # noqa: BLE001
        return None
    return None


BE_RULE_FILES = ("config/gen_contract.json", "config/render_quality.json", "config/vqa.json")


def be_rule_sig(root: Path = ROOT) -> str:
    """尽力版判定依据的“规则版本”：契约门槛 / 出图预设 / 看图闸门三份配置的内容哈希（知识库每次 compile 都变，不用它，免得反复重置）"""
    import hashlib
    h = hashlib.sha256()
    for f in BE_RULE_FILES:
        try:
            h.update((root / f).read_bytes())
        except OSError:
            h.update(b"-")
    return h.hexdigest()[:16]


def shot_inputs_sig(paths, sid: str) -> dict:
    """本镜现在编译出的作业：{inputs: compiler_inputs_sha, refs_mtime: 参考图最新修改时间, prompt_sha}；作业表里没有 → {}"""
    import hashlib
    jobs = (jl(paths.run / "assets" / "first_frame_jobs.json", {}) or {}).get("jobs") or []
    job = next((j for j in jobs if j.get("shot") == sid or j.get("id") == sid), None)
    if not job:
        return {}
    mt = 0.0
    for r in job.get("refs") or []:
        try:
            mt = max(mt, (paths.root / str(r)).stat().st_mtime)
        except OSError:
            pass
    return {"inputs": job.get("compiler_inputs_sha"), "refs_mtime": round(mt, 1),
            "prompt_sha": hashlib.sha256((job.get("prompt") or "").encode()).hexdigest()[:16]}


def first_input_changed(paths, sid: str, fo: dict, led: dict) -> dict:
    """K-OPS-E24（总调度 11:3x：第二季等非主剧重新导入后，按 E09 的 job_sig 自动重编、自动重出）：
    首帧 passed 时记过 passed_sig、现在编译出的作业签名不同了 → 回到 ready（不计次，原因“作业输入变了”）。
    没记过 passed_sig（旧数据）不动；项目方定稿锁不动"""
    if fo.get("status") != "passed" or fo.get("owner_locked") or not led.get("passed_sig"):
        return fo
    sig = job_sig(paths, sid)
    if not sig or sig == led["passed_sig"]:
        return fo
    return {**fo, "status": "ready", "attempts": 0, "stale": True, "waiting_for": "空闲道",
            "reason": f"v{fo.get('take')} 之后作业输入变了（重新导入 / 重编），自动重出，不算之前的次数"}


def last_consistent(td: dict, fo: dict, lo: dict) -> dict:
    """K-OPS-E13（总调度 11-02 02:2x：以 takes.json 当前版本和契约结果为准，不反过来改 takes）：
    尾帧 passed 但①首帧不是 passed，或②当前尾帧比当前首帧旧（首帧换过）→ 尾帧作废，回到 ready（首帧过了）/ pending（首帧没过），不计次"""
    if lo.get("status") != "passed" or lo.get("na"):
        return lo
    fa, la = active_take(td, "image"), active_take(td, "last")
    stale = bool(fa and la and str(la.get("created_at") or "") < str(fa.get("created_at") or ""))
    if fo.get("status") == "passed" and not stale:
        return lo
    why = ("首帧换过（当前首帧 v{} 比尾帧 v{} 新），尾帧作废，跟着重出，不计次".format(fa.get("n"), la.get("n")) if stale
           else "首帧现在不是“已通过”（{}），尾帧作废，等首帧过契约后重出".format(fo.get("status")))
    return {**lo, "status": "ready" if fo.get("status") == "passed" else "pending", "attempts": 0, "reason": why,
            "waiting_for": "空闲道" if fo.get("status") == "passed" else "首帧过契约", "voided": True}


def registry_consistency(reg: dict) -> list[dict]:
    """登记表自检：passed 却没有 take / 尾帧 passed 首帧没过 / 视频 passed 首尾帧没过 → 问题清单（写 data/producer/consistency.json）"""
    probs = []
    for E in reg.get("episodes") or []:
        for S in E.get("shots") or []:
            ob = S.get("objects") or {}
            f, l, v = (ob.get(k) or {} for k in ("first", "last", "video"))
            if f.get("status") == "passed" and not f.get("take"):
                probs.append({"shot": S["shot"], "kind": "first", "why": "首帧 passed 但没有当前版本"})
            if l.get("status") == "passed" and not l.get("na") and f.get("status") != "passed":
                probs.append({"shot": S["shot"], "kind": "last", "why": "尾帧 passed 但首帧不是 passed"})
            if v.get("status") == "passed" and (f.get("status") != "passed" or (l.get("status") != "passed")):
                probs.append({"shot": S["shot"], "kind": "video", "why": "视频 passed 但首 / 尾帧不是 passed（只记录，视频不自动作废）"})
    return probs


def fail_stats(led: dict) -> dict:
    """驳回重出 / 普通尝试历史里的不过项计数（Q1 身份、Q9 看图……）"""
    from collections import Counter
    c = Counter()
    for h in (led.get("redo_history") or []) + (led.get("history") or []):
        for b in h.get("blocking") or []:
            c[str(b)] += 1
    return dict(c.most_common())


def sentinel_ticket(paths, oid: str, why: str, stats: dict, led: dict) -> None:
    """K-OPS-E09：阶梯走完 → 给 SENTINEL 开工单（data/sentinel/tickets.jsonl，追加一行）"""
    f = paths.data / "sentinel" / "tickets.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    rec = {"at": iso(), "kind": "redo_ladder_exhausted", "obj": oid, "why": why, "fail_stats": stats,
           "tries": len(led.get("redo_history") or []), "by": "producer.escalate_exhausted", "rule": "K-OPS-E09",
           "route": "VQAGATE / IMGFIX（按失败项修根因）"}
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + chr(10))


def run_priority(run: str, root: Path = ROOT) -> int:
    reg = jl(root / "config" / "pipeline" / "runs.json", {}) or {}
    return int(((reg.get("runs") or {}).get(run) or {}).get("priority", 0 if run == RUN_ID else 10))


def higher_priority_busy(paths) -> dict:
    """K-OPS-E15：比本剧优先级高（数字小）且 producing 的剧，登记表里还有 ready 的首帧 / 尾帧 → {run: 个数}；没有 → {}"""
    reg = jl(paths.root / "config" / "pipeline" / "runs.json", {}) or {}
    mine = run_priority(paths.run_id, paths.root)
    out = {}
    for run, e in (reg.get("runs") or {}).items():
        if run == paths.run_id or e.get("status", "producing") != "producing" or int(e.get("priority", 10)) >= mine:
            continue
        rp = Paths(root=paths.root, run_id=run)
        r = jl(rp.registry, {}) or {}
        n = sum(1 for E in r.get("episodes") or [] for S in E.get("shots") or []
                for k in ("first", "last") if ((S.get("objects") or {}).get(k) or {}).get("status") == "ready")
        if n:
            out[run] = n
    return out


def run_env(run: str, root: Path = ROOT) -> dict:
    """非主剧 producer 进程要设的环境变量（在 import ns_render 之前）"""
    if run == RUN_ID:
        return {}
    return {"NS_RENDERS_DIR": str(root / "data" / "renders" / run),
            "NS_SCRIPT_JSON": str(root / "data" / "import" / "runs" / run / "script_v2.json")}


def prefetch_depth() -> int:
    """K-OPS-E17：每道 ComfyUI 队列保持“1 单在跑 + (depth-1) 单排队”，派单 / 传图和渲染并行。
    NS_PRODUCER_PREFETCH 优先，其次 config/policies/resources.yaml resources.prefetch_depth，默认 2"""
    try:
        v = os.environ.get("NS_PRODUCER_PREFETCH")
        if not v:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import policy as POL
            v = POL.item("resources.prefetch_depth", ROOT).get("value")
        return max(1, min(4, int(v or 2)))
    except Exception:  # noqa: BLE001
        return 2


def dynamic_backlog(done_times: list, t: float, lanes: int, depth: int, window_s: float = 900, horizon_min: float = 15) -> int:
    """K-OPS-E17：积压上限按打分（契约 + 看图）实测吞吐定——最近 window_s 完成数折算每分钟，允许积压约 horizon_min 分钟的打分量；
    下限 = 道数 × 预取深度（保证每道至少能把预取填满）。不再写死 2×道数×实例数"""
    recent = [x for x in done_times if t - x <= window_s]
    rate = len(recent) / (window_s / 60.0)
    return max(lanes * depth, int(round(rate * horizon_min)))


LOCAL_ONLY_MARKS = ("本地生成", "占位", "暂缓")


def local_only_shots(script) -> set:
    """K-OPS-E22（项目方 11-02 点选导入第二季时的硬约束）：剧本 **H3校验** 写了“本地生成 / 占位 / 暂缓”的镜（亲密镜、露骨暂缓），
    服务器一律不派单——派单层代码检查，不靠人记。→ 镜号集合"""
    out = set()
    for ep in getattr(script, "episodes", None) or []:
        for sh in getattr(ep, "shots", None) or []:
            if any(m in str(getattr(sh, "h3_check", "") or "") for m in LOCAL_ONLY_MARKS):
                out.add(sh.id)
    return out


def is_server_lane(lane: str) -> bool:
    return str(lane).split(":", 1)[0] in ("gpu33", "gpu36") or str(lane).isdigit()


def asset_hold_objects(data: Path) -> set:
    """IMGFIX r5（总调度 fredw-2b 11-02）：data/autopilot/*_hold.json（active=true）列出的首帧 / 尾帧对象暂缓派单——
    资产（例：林晚造型 A 设定图缺袖）修复后等项目方点选，点选前不出图。不在 = 没有 hold；
    文件坏 → K-OPS-F09 decisions_guard 在派单前整体拒派（⤴ 取代“文件坏 = 不挡”）"""
    out: set = set()
    for f in (data / "autopilot").glob("*_hold.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("active"):
            t_now = time.strftime("%Y-%m-%dT%H:%M:%S")
            out |= {o for it in d.get("shots") or [] if not (it.get("expires_at") and str(it["expires_at"])[:19] < t_now)
                    for o in it.get("objects") or []}           # K-OPS-E19：带 expires_at 的条目到期自动失效
    return out


class Paths:
    """全部路径集中在这里；dryrun 指向临时目录"""

    def __init__(self, root: Path = ROOT, pd: Path | None = None, run_id: str = RUN_ID):
        self.root = root
        self.data = root / "data"
        self.run_id = run_id
        self.primary = run_id == RUN_ID                      # K-OPS-E15：主剧沿用旧路径（在途单 / 账本不失效）
        self.pd = pd or (self.data / "producer" if self.primary else self.data / "producer" / "runs" / run_id)
        self.run = self.data / "pipeline" / "runs" / run_id
        self.renders = self.data / "renders" if self.primary else self.data / "renders" / run_id
        self.vid = self.run / "video"
        self.frames_v2 = self.data / "assetmaster" / "frames_v2" / "state.json"
        self.voices = root / "config" / "voices.json"
        self.music = self.data / "music" / "series10"
        self.eps_out = self.data / "episodes" / "series10"
        self.review = self.data / "review_pages" / "series10_video"
        self.morning = root / "docs" / "overnight" / "morning_decisions.md"

    @property
    def log(self):
        return self.pd / "log.jsonl"

    @property
    def registry(self):
        return self.pd / "registry.json"

    @property
    def ctrl(self):
        return self.pd / "control.json"

    @property
    def heartbeat(self):
        return self.pd / "heartbeat.json"

    @property
    def leases(self):
        return self.pd / "leases"

    @property
    def ledger(self):
        return self.pd / "attempts.json"

    @property
    def rejects(self):
        return self.pd / "master_rejects.json"

    @property
    def gates(self):
        return self.pd / "gates.json"

    @property
    def mirror(self):
        """SSE 挂钩：live.py 的 Watcher 扫 runs/<run>/**，这个小文件一变就推 {type: stage, run, field: _producer.json}"""
        return self.run / "_producer.json"


# ---------------------------------------------------------------------------------------------- 小工具
def now() -> float:
    return time.time()


def iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t or now()))


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def js(p, d) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    for i in range(5):                     # K-OPS-I06：Windows os.replace 会撞上读者，带重试
        try:
            tmp.replace(p)
            return
        except PermissionError:
            time.sleep(0.2 * (i + 1))
    tmp.replace(p)


_log_lock = threading.Lock()


def log_event(paths: Paths, ev: str, **kw) -> dict:
    rec = {"ts": iso(), "t": round(now(), 2), "ev": ev, **kw}
    with _log_lock:
        paths.pd.mkdir(parents=True, exist_ok=True)
        with paths.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(rec["ts"], ev, json.dumps(kw, ensure_ascii=False)[:300], flush=True)
    return rec


def sid_parts(sid: str) -> tuple[int, int]:
    m = re.fullmatch(r"ep(\d+)-S(\d+)", sid)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


# ---------------------------------------------------------------------------------------------- 错误分类
INFRA_PAT = re.compile(r"ComfyUnavailable|URLError|Connection(Refused|Reset|Aborted)?Error|connection refused|timed out|"
                       r"Timeout|超时|HTTP 50[0-9]|Bad Gateway|Service Unavailable|out of memory|OOM|CUDA error|"
                       r"No such file|FileNotFoundError|找不到文件|scp |ssh: |Broken pipe|RemoteDisconnected|隧道|训练锁", re.I)
PREFLIGHT_PAT = re.compile(r"preflight 不通过|生成契约 preflight", re.I)
GATE_PAT = re.compile(r"身份参考|identity|没有挑定|未挑定|设定图未选|look 未确认", re.I)


CODE_PAT = re.compile(r"^(TypeError|AttributeError|NameError|ImportError|ModuleNotFoundError|KeyError|IndexError|"
                      r"UnboundLocalError):|^ValueError: (too many|not enough) values to unpack", re.I)


def classify(err: str) -> str:
    """→ "preflight" | "infra" | "code" | "content"。基础设施错误和系统代码错误都不算内容尝试"""
    if CODE_PAT.search(err or ""):
        return "code"
    if PREFLIGHT_PAT.search(err or ""):
        return "preflight"
    if INFRA_PAT.search(err or ""):
        return "infra"
    return "content"


def plain_reason(kind: str, err: str) -> str:
    """给项目方看的一句人话（不评价内容，只说哪道关没过）"""
    e = err or ""
    if kind == "infra":
        if "训练锁" in e:
            return "这张卡上有人在训练（train.lock），没提交，换一条道，不算一次尝试"
        if re.search(r"out of memory|OOM", e, re.I):
            return "显卡显存不够（OOM），换一条道重来，不算一次尝试"
        if re.search(r"No such file|FileNotFoundError|找不到文件", e, re.I):
            return "缓存文件缺失，重新规划参考后重来，不算一次尝试"
        if re.search(r"50[0-9]|Bad Gateway|Unavailable|refused|timed out|超时|Timeout|隧道|URLError|ssh|scp", e, re.I):
            return "到 GPU 的隧道 / 服务暂时连不上，稍后换道重来，不算一次尝试"
        return "基础设施出错，稍后换道重来，不算一次尝试"
    if kind == "preflight":
        return "出图前契约检查没过，没有提交：" + e.split("：", 1)[-1][:160]
    return e[:200]


Q_WORD = {"Q1": "身份（脸像不像定的人）", "Q2": "服装 / 单品对不上参考", "Q3": "人数 / 在画人物不对", "Q4": "画面不够清晰",
          "Q5": "手 / 肢体有问题", "Q6": "景别 / 构图不对", "Q7": "场景对不上", "Q8": "发色不对"}


def pf_reason(pf: dict) -> str:
    blk = pf.get("blocking") or [i.get("id") for i in pf.get("items") or [] if i.get("status") == "fail"]
    if blk:
        return "契约没过：" + "、".join(Q_WORD.get(str(b), str(b)) for b in blk)
    if pf.get("error") or pf.get("remote_error"):
        return "契约打分出错：" + str(pf.get("error") or pf.get("remote_error"))[:120]
    return "契约没过"


# ---------------------------------------------------------------------------------------------- 租约
class Leases:
    def __init__(self, paths: Paths, holder: str = AGENT):
        self.dir, self.holder = paths.leases, holder

    def _p(self, obj: str) -> Path:
        return self.dir / (re.sub(r"[^A-Za-z0-9_.-]", "_", obj) + ".json")

    def get(self, obj: str) -> dict | None:
        d = jl(self._p(obj))
        if not d:
            return None
        if d.get("until", 0) < now() or (d.get("host") == os.environ.get("COMPUTERNAME") and not pid_alive(d.get("pid"))):
            try:
                self._p(obj).unlink()
            except OSError:
                pass
            return None
        return d

    def acquire(self, obj: str, **info) -> bool:
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.get(obj):
            return False
        rec = {"obj": obj, "holder": self.holder, "pid": os.getpid(), "host": os.environ.get("COMPUTERNAME"),
               "since": now(), "until": now() + LEASE_S, **info}
        try:
            fd = os.open(self._p(obj), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        return True

    def release(self, obj: str) -> None:
        try:
            self._p(obj).unlink()
        except OSError:
            pass

    def all(self) -> dict:
        out = {}
        if self.dir.is_dir():
            for p in self.dir.glob("*.json"):
                d = jl(p)
                if d and d.get("obj") and self.get(d["obj"]):
                    out[d["obj"]] = d
        return out


# 让道模式的会话（道上只有它们的任务时，出图照样排进去）：VIDEO10 / BAKEOFF（client_id 前缀 video10- / bakeoff- 也算）
YIELDING_AGENTS = ("VIDEO10", "BAKEOFF")

# gpu33 各道 ComfyUI 的输出目录（与 tools/series10_imggen/imggen.py OUTDIR 一致）；契约在 gpu33 上原地读
GPU33_OUTDIR = {"gpu33:0": "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu0",
                "gpu33:1": "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu1",
                "gpu33:3": "/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu3"}


def _replan(project, ep, shot, job: dict, plan_kw: dict, make_slots):
    import dataclasses
    from ns_agent import asset_refs as AR
    sr, plan = AR.plan_for(project, ep, shot, "qwen_image_2.1", **plan_kw)
    if not job["prompt"].startswith(plan.prompt_prefix):
        return job
    slots = make_slots(AR, plan)
    if slots is None:
        return job
    for i, sl in enumerate(slots, 1):
        sl.index = i
        sl.line = AR._line(project, sl)
    plan2 = dataclasses.replace(plan, slots=slots, prompt_prefix="".join(x.line for x in slots))
    body = job["prompt"][len(plan.prompt_prefix):]
    return {**job, "prompt": plan2.prompt_prefix + body, "refs": plan2.files, "asset_refs": AR.record(sr, plan2),
            "face_files": [x.file for x in slots if x.kind == "face"]}


def faces_only_variant(project, ep, shot, job: dict, plan_kw: dict) -> dict:
    """策略 A：只留脸槽（双人镜两张脸），设定图 / 参考板 / 单品都不挂；服装由正文外层单品句点名（Q2 与外套检查照判）"""
    import copy

    def mk(AR, plan):
        faces = [copy.copy(x) for x in plan.slots if x.kind == "face"]
        return faces or None
    return _replan(project, ep, shot, job, plan_kw, mk)


def double_face_variant(project, ep, shot, job: dict, plan_kw: dict) -> dict:
    """策略 B：主角身份脸放两槽（图1、图2 同一张），其余参考顺延，超出槽位的丢掉"""
    import copy

    def mk(AR, plan):
        faces = [x for x in plan.slots if x.kind == "face"]
        if not faces:
            return None
        dup = copy.copy(faces[0])
        rest = [copy.copy(x) for x in plan.slots if x is not faces[0]]
        return ([copy.copy(faces[0]), dup] + rest)[:plan.capacity]
    out = _replan(project, ep, shot, job, plan_kw, mk)
    if out is not job:
        # 第二槽的标注改成“也是同一人的脸”，免得模型以为画面里有两个人
        lines = out["prompt"]
        first_line_end = lines.find("。") + 1
        second_end = lines.find("。", first_line_end) + 1
        if first_line_end > 0 and second_end > first_line_end:
            out["prompt"] = lines[:first_line_end] + "图2是同一人的脸部参考（与图1同一张，加强身份，只取脸和发型）。" + lines[second_end:]
    return out


def linwan_sheet_variant(project, ep, shot, job: dict, plan_kw: dict) -> dict:
    """双人镜 A 版：两张脸各占一槽 + 第 3 槽固定为林晚本镜造型设定图（去头）；槽位标注用 asset_refs._line 原样生成"""
    import dataclasses
    from ns_agent import asset_refs as AR
    sr, plan = AR.plan_for(project, ep, shot, "qwen_image_2.1", **plan_kw)
    if not job["prompt"].startswith(plan.prompt_prefix):
        return job
    faces = [sl for sl in plan.slots if sl.kind == "face"]
    ref = next((r for r in sr.refs if r.role == "sheet" and r.character == "lin_wan" and r.file), None)
    if ref is None or len(faces) + 1 > plan.capacity:
        return {**job, "variant_note": "林晚造型设定图不在参考里，按默认槽位"}
    if any(sl.kind == "sheet" and sl.character == "lin_wan" for sl in plan.slots):
        return job
    n = len(faces) + 1
    sl = AR.Slot(n, "sheet", ref.file, "lin_wan", ["造型" + (ref.look_id or "") + "设定图"],
                 [{"file": ref.file, "label": ref.label, "role": "sheet", "source": ref.source, "character": "lin_wan",
                   "look_id": ref.look_id or next((c.get("look") for c in sr.characters if c.get("character") == "lin_wan"), None)}])
    sl.line = AR._line(project, sl)
    plan2 = dataclasses.replace(plan, slots=[*faces, sl], prompt_prefix="".join(x.line for x in faces) + sl.line)
    body = job["prompt"][len(plan.prompt_prefix):]
    return {**job, "prompt": plan2.prompt_prefix + body, "refs": plan2.files, "asset_refs": AR.record(sr, plan2),
            "face_files": [x.file for x in faces]}


def vqa_gate(sid: str, stage: str, file_rel: str, job: dict, pf: dict) -> dict | None:
    """VQAGATE（项目方 11-01 16:10 / 16:3x：“image 做出来后用本地图像模型检测是否达标……再跑视频”）：
    契约之后、设为当前之前，gpu36 本地 Qwen3-VL 按 config/vqa.json 检查（含跨镜连贯：同场上一镜首帧 / 本镜首帧作参考），
    结果并进 postflight（Q9；ns_agent.vqa.contract.apply）。enforce 期 Q9 fail / 没看成 → pf.ok=False → 不设为当前、
    按下一轮 prompt_delta 自动重出。只因看图服务没跑成而不过 → score_infra（只重打分，不重出、不计次）"""
    try:
        from ns_agent.vqa import contract as VQ
        from ns_render import pipeline as P
        if not VQ.enforced():
            return None
        other = [b for b in (pf.get("blocking") or []) if b not in ("Q9", "Q1")]
        q1a = next((i for i in pf.get("items") or [] if i.get("id") == "Q1a"), None)
        if q1a and q1a.get("status") == "untested" and (q1a.get("evidence") or {}).get("q1a_mode") == "unavailable":
            other = [b for b in other if b != "Q1a"]   # K-REV-V19：分割不可用的 Q1a 要靠看图逐人问答判，不能因此跳过看图
        if pf.get("ok") is False and "Q1" in (pf.get("blocking") or []) and not VQ.q1_needs_vlm(pf):
            other.append("Q1")                   # Q1 不过、又不是转角放宽 / 后脑复核能救的（11-02 服务器上大头是“身份”不过）→ 也不排队看图
        if pf.get("ok") is False and other:
            # 总调度 11-02 P0（看图是整条出图线的吞吐上限）：Q2–Q8 已经不过的图反正要重出，不再排队看图（11-01 08–16 时 214 张里 151 张
            # 属于这种情况）。Q1 例外：Q1 的转角放宽 / 后脑复核要看图结果
            VQ.apply(pf, {"error": "前置契约不过（" + "、".join(other) + "），未看图"})
            return None
        refs = [str(ROOT / r) if not Path(r).is_absolute() else r for r in (job.get("refs") or [])] \
            or VQ.ref_files(job.get("asset_refs") or {})
        v = VQ.inspect_for(sid, "first" if stage == "image" else "last", str(P.DATA / file_rel), job.get("prompt") or "",
                           refs, wait_s=1200)
        VQ.recheck_strangers(pf, str(P.DATA / file_rel))   # K-REV-V14：背影人物的后脑被认成“多出的脸” → 本地看图复核
        VQ.q1_band_review(pf, str(P.DATA / file_rel))      # K-REV-V18 修订：Q1 复核带 → 和 L-086 左右并排的本地看图复核
        VQ.q1a_vlm(pf, str(P.DATA / file_rel))             # K-REV-V19：Q1a 逐人头发——确定性过了再由本地看图逐人问答复核
        VQ.hair_primary(pf, v)                              # 发色：Q1a 分割主判、VLM 辅助（开关 gate.hair_primary）
        VQ.apply(pf, v)
        if v.get("error") and pf.get("ok") is False and pf.get("blocking") == ["Q9"]:
            pf["score_infra"] = True
            pf["remote_error"] = pf.get("remote_error") or ("本地看图服务：" + str(v["error"])[:200])
        return v
    except Exception as e:  # noqa: BLE001
        try:
            log_event(Paths(), "vqa_gate_err", obj=f"{stage}:{sid}", error=repr(e)[:200])
        except Exception:  # noqa: BLE001
            pass
        return None


def outbox_emit(sid: str, stage: str, n: int, file_rel: str) -> None:
    """K-OPS-F05（FACTORY D7）：服务器工厂打分完成 → 写 outbox 结果目录（takes.json + 成图 + 512px 缩略图，.done 最后写），
    由 NETFIX puller 取回并 merge_file。只在服务器（OFFLINE_SELF / NS_FACTORY_HOST）写；失败只留痕，不影响生产"""
    host = os.environ.get("NS_FACTORY_HOST") or os.environ.get("OFFLINE_SELF")
    if not host:
        return
    try:
        if str(ROOT / "tools" / "factory") not in sys.path:
            sys.path.insert(0, str(ROOT / "tools" / "factory"))
        import outbox as OB
        ep, s = sid.split("-", 1)
        OB.write(f"{'first' if stage == 'image' else 'last'}:{sid}", "take",
                 [f"data/renders/{ep}/{s}/takes.json", f"data/{file_rel}"], host=host, root=ROOT)
    except Exception as e:  # noqa: BLE001
        try:
            log_event(Paths(), "outbox_err", obj=f"{stage}:{sid}", take=n, error=repr(e)[:200])
        except Exception:  # noqa: BLE001
            pass


def decision_file_problems() -> list[str]:
    """K-OPS-F09：tools/factory/decisions_guard.problems()；校验器自身出错也算问题（失败关闭）"""
    try:
        if str(ROOT / "tools" / "factory") not in sys.path:
            sys.path.insert(0, str(ROOT / "tools" / "factory"))
        import decisions_guard as DG
        return DG.problems(ROOT)
    except Exception as e:  # noqa: BLE001
        return [f"决策文件校验器出错：{e!r}"[:200]]


def refs_guard(paths: "Paths", sid: str, job: dict) -> list[str]:
    """K-OPS-F03（FACTORY D4，总调度 01:3x）：派单前把这单 refs 的路径 + sha 和目标状态 data/factory/inbox/expected_refs.json 比对；
    不一致 → 返回问题列表（调用方拒派、不计次）并写报警事件 refs_mismatch。没有期望表 / 这镜不在表里 → 不拦（[]）"""
    try:
        if str(ROOT / "tools" / "factory") not in sys.path:
            sys.path.insert(0, str(ROOT / "tools" / "factory"))
        import inbox as IB
        probs = IB.check_refs(sid, list(job.get("refs") or []), root=ROOT, run=getattr(paths, "run_id", None))   # 多剧：按剧查
    except Exception as e:  # noqa: BLE001  校验器自身出错不挡生产，但留痕
        log_event(paths, "refs_unchecked", obj=f"first:{sid}", error=repr(e)[:200])
        return []
    if probs:
        log_event(paths, "refs_mismatch", obj=f"first:{sid}", problems=probs[:6], alarm=True, counted=False)
    return probs or []


def vqa_delta(sid: str, stage: str) -> dict | None:
    """上一版没过时写作网关给的 prompt_delta（take.params.vqa_rounds[-1]，outcome=rerun），下一次出图套用（一次只改一个维度）"""
    try:
        from ns_render import pipeline as P
        ts = [t for t in P.load_takes(sid).get("takes") or [] if t.get("stage") == stage]
        if not ts:
            return None
        t = max(ts, key=lambda x: x.get("n") or 0)
        if take_pf(t).get("ok"):
            return None
        r = ((t.get("params") or {}).get("vqa_rounds") or [None])[-1] or {}
        return r.get("prompt_delta") if r.get("outcome") == "rerun" else None
    except Exception:  # noqa: BLE001
        return None


def vqa_record(sid: str, stage: str, n: int, file_rel: str, job: dict, pf: dict, vlm: dict | None = None) -> None:
    """R11-10（VQA 11-01）：契约之后让 gpu36 本地看图模型写文字、写作网关判，结果追加到 take.params.vqa_rounds[]。
    只记录期：不改通过判定、不触发重跑（config/vqa.json judge.enforce=true 之后再接重跑，见 VQA 说明）。任何错误都吞掉"""
    try:
        from ns_agent.vqa import judge as VJ
        from ns_render import pipeline as P
        from ns_render import frame_edit as FE
        if vlm is None and (pf.get("vqa_gate") or {}).get("enforce"):
            return                       # 闸门期没看图（前置契约不过 / 服务没跑成）：不在这里再排一次看图（P0 吞吐）
        t = next((x for x in P.load_takes(sid)["takes"] if x["stage"] == stage and x["n"] == n), None)
        if t is None:
            return
        params = dict(t.get("params") or {})
        hist = list(params.get("vqa_rounds") or [])
        rec = VJ.review_round(sid, "first" if stage == "image" else "last", str(P.DATA / file_rel), job.get("prompt") or "",
                              list(job.get("refs") or []), contract=pf, history=hist, vlm=vlm)
        rec = {**rec, "recorded_by": AGENT, "mode": "enforce" if (pf.get("vqa_gate") or {}).get("enforce") else "record_only",
               "at": iso()}
        params["vqa_rounds"] = hist + [rec]
        FE.annotate(sid, stage, n, params=params)
    except Exception as e:  # noqa: BLE001
        try:
            log_event(Paths(), "vqa_skip", obj=f"{stage}:{sid}", take=n, error=repr(e)[:160])
        except Exception:  # noqa: BLE001
            pass


def score_unmeasured(pf: dict) -> bool:
    """契约结果是“没量成”而不是“不过”：带远端错误，且阻断项全是 untested"""
    if not (pf.get("remote_error") or pf.get("measure_error") or pf.get("error")):
        return False
    st = {i.get("id"): i.get("status") for i in pf.get("items") or []}
    blk = pf.get("blocking") or [k for k, v in st.items() if v in ("fail", "untested")]
    return bool(blk) and all(st.get(b) == "untested" for b in blk) or not pf.get("items")


def render_image_only_lanes() -> dict:
    """LOCALGPU（11-01）：config/render_endpoints.json lanes 里 image_only 的道（laptop:0 笔记本本机 ComfyUI）并入出图道表"""
    try:
        from ns_render import endpoints as EP
        return EP.image_lanes()
    except Exception:  # noqa: BLE001
        return {}


def lane_held(lane: str) -> bool:
    """LOCALGPU：render_endpoints 里 hold=true 的道（就绪、等总调度开派）按 hold_lanes 处理"""
    try:
        from ns_render import endpoints as EP
        return EP.held(lane)
    except Exception:  # noqa: BLE001
        return False


def lane_split(lane: str) -> tuple[str, int]:
    srv, _, i = str(lane).partition(":")
    return srv, int(i or 0)


def train_locks_cached(server: str) -> set | None:
    """ns_api.jobs.train_locks(server, wait=False)：后台 ssh 读 train.lock.gpuN、30 s 缓存；从没读到过 → None（调用方按“锁着”处理）"""
    from ns_api import jobs as J
    locks = J.train_locks(server, wait=False)
    with J._train_guard:
        known = server in J._train_cache
    return set(locks) if known else None


def lane_locked_now(lane: str) -> bool:
    """ns_api.jobs.lane_train_locked_now：出发前现读（ssh，读不到沿用上次；从没读到过按无锁——所以前面 probe 先要求读到过）"""
    from ns_api import jobs as J
    srv, idx = lane_split(lane)
    return J.lane_train_locked_now(idx if srv == "gpu33" else lane)


def pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True, timeout=10)
            return str(int(pid)) in (r.stdout or "")
        os.kill(int(pid), 0)
        return True
    except Exception:  # noqa: BLE001
        return False


_proc_cache: dict = {"at": 0.0, "val": []}


def python_procs() -> list[str]:
    """本机 python 进程命令行（缓存 60 s）：认出 ASSETMASTER frames_v2 / VIDEO10 night.py 还在不在跑"""
    if now() - _proc_cache["at"] < 60:
        return _proc_cache["val"]
    out: list[str] = []
    try:
        if os.name == "nt":
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | ForEach-Object { $_.CommandLine }"],
                               capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
            out = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    except Exception:  # noqa: BLE001
        out = []
    _proc_cache.update(at=now(), val=out)
    return out


def parse_eps(s: str) -> list[int]:
    out = []
    for part in (s or "").split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part.strip():
            out.append(int(part))
    return out


# ---------------------------------------------------------------------------------------------- 道
_lane_cache: dict = {}


def lane_queue(url: str) -> dict:
    """ComfyUI /queue → {ok, n, agents}；连不上 ok=False"""
    try:
        with urllib.request.urlopen(url + "/queue", timeout=6) as r:
            d = json.loads(r.read())
        items = (d.get("queue_running") or []) + (d.get("queue_pending") or [])
        agents = []
        for it in items:
            ex = it[3] if len(it) > 3 and isinstance(it[3], dict) else {}
            tag = (ex.get("ns_tag") or {}) if isinstance(ex.get("ns_tag"), dict) else {}
            agents.append(tag.get("agent") or str(ex.get("client_id") or "?")[:12])
        return {"ok": True, "n": len(items), "agents": agents}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "n": None, "agents": [], "error": repr(e)[:120]}


# ---------------------------------------------------------------------------------------------- 契约结果
def take_pf(t: dict | None) -> dict:
    """这一版的出图后契约：take.postflight（register_takes / 本服务）或 take.contract（ok / postflight，画布 unified 路径）"""
    if not t:
        return {}
    p = t.get("postflight")
    if isinstance(p, dict) and (p.get("ok") is not None or p.get("state")):
        return p
    c = t.get("contract") or {}
    if isinstance(c, dict):
        if c.get("ok") is not None:
            return c
        if isinstance(c.get("postflight"), dict):
            return c["postflight"]
    return {}


def active_take(td: dict, stage: str) -> dict | None:
    n = (td.get("active") or {}).get(stage)
    return next((t for t in td.get("takes") or [] if t.get("stage") == stage and t.get("n") == n), None) if n else None


def score_key(pf: dict) -> tuple:
    items = {i.get("id"): i for i in pf.get("items") or []}
    q1 = (items.get("Q1") or {}).get("evidence") or {}
    v = next((q1[k] for k in ("value", "min", "score") if isinstance(q1.get(k), (int, float))), 0.0)
    return (bool(pf.get("ok")), -len(pf.get("blocking") or []), v)


# ---------------------------------------------------------------------------------------------- 状态推导
class World:
    """一次快照：把各处真实记录读进来（每轮重读）"""

    def __init__(self, paths: Paths, script=None, shots_filter: set | None = None):
        self.p = paths
        self.script = script
        self.filter = shots_filter
        self.procs = python_procs() if paths.root == ROOT else []
        self.fv2 = jl(paths.frames_v2, {}) or {}
        self.vstate = {}
        for h in ("gpu33", "gpu36"):
            self.vstate[h] = (jl(paths.vid / f"state_{h}.json", {}) or {}).get("shots") or {}
        self.night = jl(paths.vid / "night_state.json", {}) or {}
        self.nctrl = jl(paths.vid / "night_control.json", {}) or {}
        self.voices = jl(paths.voices, {}) or {}
        self.api_jobs = self._api_jobs() if paths.root == ROOT else []
        self.summary = self._summary() if paths.root == ROOT else {}

    def _summary(self) -> dict:
        """总调度 11-01（PW-011）：“当前帧 / 视频”统一读集摘要 first_frame / last_frame_target / video（与 /api/shots frames 同源）"""
        try:
            with urllib.request.urlopen("http://127.0.0.1:8800/api/episodes/summary", timeout=20) as r:
                d = json.loads(r.read())
            return {s.get("id"): s for e in d.get("episodes") or [] for s in e.get("shots") or []}
        except Exception:  # noqa: BLE001
            return {}

    def _api_jobs(self) -> list[dict]:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8800/api/jobs", timeout=5) as r:
                return [j for j in json.loads(r.read()) if j.get("state") in ("queued", "running")]
        except Exception:  # noqa: BLE001
            return []

    # 外部在做的：ASSETMASTER frames_v2 / VIDEO10 night / 画布任务
    def fv2_eps(self) -> set[int]:
        out: set[int] = set()
        for c in self.procs:          # run（出图）和 rescore（重打分，可能改当前版本）都算 ASSETMASTER 占着这几集
            if "frames_v2.py" in c and re.search(r"\s(run|rescore)\b", c):
                m = re.search(r"--eps\s+(\S+)", c)
                out |= set(parse_eps(m.group(1))) if m else set(range(1, 11))
        return out

    def night_alive(self) -> bool:
        return any("series10_video/night.py" in c.replace("\\", "/") for c in self.procs)

    def episodes(self) -> list:
        eps = list(self.script.episodes) if self.script is not None else []
        return eps

    def takes(self, sid: str) -> dict:
        ep, s = sid.split("-")
        return jl(self.p.renders / ep / s / "takes.json", {"takes": [], "active": {}}) or {"takes": [], "active": {}}


def obj(kind: str, key: str, **kw) -> dict:
    o = {"id": f"{kind}:{key}", "kind": kind, "label": KIND_WORD.get(kind, kind), "status": "pending", "attempts": 0,
         "max_attempts": MAX_TRIES if kind in ("first", "last", "video") else None, "last_error": None, "reason": None,
         "waiting_for": None, "where": None, "since": None}
    o.update(kw)
    return o


def derive(w: World, ledger: dict, leases: dict, run_summary: dict | None = None) -> dict:
    """→ registry（不写盘）。状态全部从 w 里的真实记录推出来；ledger 只提供本服务自己的尝试次数 / 错误"""
    p = w.p
    fv2_eps = w.fv2_eps()
    night_alive = w.night_alive()
    canvas = {}
    for j in w.api_jobs:
        st = "first" if j.get("stage") in ("image", "first") else j.get("stage") or ("video" if j.get("kind") == "video" else "")
        canvas[f"{st}:{j.get('shot_id')}"] = j
    script_eps = {}
    for x in (run_summary or {}).get("series_eps") or []:
        script_eps[int(x["ep"])] = x.get("stages") or {}
    sys_titles = {}
    episodes = []
    for ep in w.episodes():
        n = int(ep.number)
        sys_titles[n] = getattr(ep, "title", None)
        E = {"ep": n, "title": getattr(ep, "title", None), "objects": {}, "shots": []}
        # 剧本 / 导入
        st = script_eps.get(n) or {}
        p4 = st.get("P4")
        so = obj("script", f"ep{n:02d}", ep=n)
        if p4 in ("ok", "unchecked", "reused") or (not st and ep.shots):
            so.update(status="passed", reason="剧本分镜 P4 已通过校验" if p4 else "剧本已在画布里")
        elif p4 in ("needs_writer", "budget_stop", "error"):
            so.update(status="failed", reason={"needs_writer": "分镜格式要写作方返修（已自动转写作方）", "budget_stop": "写作到预算上限（花钱闸门，问项目方）",
                                               "error": "写作出错，自动重试"}[p4], waiting_for="写作方" if p4 != "budget_stop" else "项目方（花钱闸门）")
        else:
            so.update(status="running" if p4 == "running" else "ready", waiting_for="写作模型写 P4")
        io_ = obj("import", f"ep{n:02d}", ep=n)
        if ep.shots:
            io_.update(status="passed", reason=f"已在系统剧本里（{len(ep.shots)} 镜）")
        else:
            io_.update(status="ready" if so["status"] == "passed" else "pending", waiting_for="自动导入")
        E["objects"]["script"], E["objects"]["import"] = so, io_
        shot_objs = []
        for s in ep.shots:
            sid = s.id
            if w.filter and sid not in w.filter:
                continue
            td = w.takes(sid)
            fv = w.fv2.get(sid) or {}
            act = td.get("active") or {}
            sm = w.summary.get(sid)
            # “有当前版本”= 集摘要 first_frame / last_frame_target / video（与 /api/progress、/api/shots frames 同源）；
            # 摘要读不到（API 重启中 / 演练）才退回 takes.json active。“过契约”是监督自己的口径
            has = ({"first": bool(sm.get("first_frame")), "last": bool(sm.get("last_frame_target")), "video": bool(sm.get("video"))}
                   if sm is not None else {"first": bool(act.get("image")), "last": bool(act.get("last")), "video": bool(act.get("video"))})
            S = {"shot": sid, "index": sid_parts(sid)[1], "objects": {}, "has": has, "has_src": "summary" if sm is not None else "takes"}
            # 资产（preflight）
            ao = obj("assets", sid, ep=n, shot=sid)
            pfb = ((fv.get("image") or {}).get("job") or {}).get("preflight") or {}
            led_a = ledger.get(f"assets:{sid}") or {}
            if led_a.get("blocked") and now() - led_a.get("at", 0) < PREFLIGHT_RETRY_S:
                gate = bool(GATE_PAT.search(" ".join(led_a.get("reasons") or [])))
                ao.update(status="failed", reason="出图前契约没过：" + "；".join(led_a.get("reasons") or [])[:200],
                          waiting_for="项目方挑定身份参考（characters 闸门）" if gate else "资料补齐后 30 分钟内自动重查",
                          gate="characters" if gate else None)
            elif pfb and not pfb.get("ok"):
                ao.update(status="failed", reason="出图前契约没过：" + "；".join(pfb.get("reasons") or [])[:200], waiting_for="资料补齐后自动重查")
            else:
                ao.update(status="passed" if io_["status"] == "passed" else "pending",
                          reason="参考槽位齐（出图前再查一次 preflight）" if io_["status"] == "passed" else None)
            # 首帧 / 尾帧
            stl = (sm or {}).get("stale") or {}                  # 剧本 / 输入改了：画布摘要的过期标记（与 /api/shots 同源）
            fo = _frame_obj("first", "image", sid, n, td, fv, ledger, leases, canvas, n in fv2_eps, deps_ok=ao["status"] == "passed",
                            stale=stl.get("image"))
            lo = _frame_obj("last", "last", sid, n, td, fv, ledger, leases, canvas, n in fv2_eps, deps_ok=fo["status"] == "passed",
                            first=fo, stale=stl.get("last"))
            fo = first_input_changed(w.p, sid, fo, ledger.get(f"first:{sid}") or {})   # K-OPS-E24：重新导入后作业变了 → 重出
            lo = last_consistent(td, fo, lo)          # K-OPS-E13：尾帧不能比首帧旧、首帧没过尾帧不能算过
            vo = _video_obj(w, sid, n, td, fo, lo, ledger, leases, night_alive)
            S["objects"] = {"assets": ao, "first": fo, "last": lo, "video": vo}
            shot_objs.append(S)
        E["shots"] = shot_objs
        # 每集：声音 / BGM / 合成 / 审片页
        resolved = [S for S in shot_objs if S["objects"]["video"]["status"] in ("passed", "best_effort")]
        cast_ok = w.voices.get("series") == p.run_id
        vo_ = obj("voice", f"ep{n:02d}", ep=n)
        if cast_ok:
            vo_.update(status="passed", reason="series10 演员表已定（对白在合成时按演员表合成）")
        else:
            vo_.update(status="pending", waiting_for="VOICE10 定 series10 演员表（config/voices.json series=series10_v1）",
                       where="VOICE10")
        bo = obj("bgm", f"ep{n:02d}", ep=n)
        if (p.music / f"ep{n:02d}.wav").exists():
            bo.update(status="passed", reason=f"data/music/series10/ep{n:02d}.wav")
        else:
            bo.update(status="pending", waiting_for="BGM10 出本集配乐（缺时合成用 --no-bgm，不挡成片）", where="BGM10", optional=True)
        ao_ = obj("assembly", f"ep{n:02d}", ep=n)
        night_ep = (w.night.get("eps") or {}).get(str(n)) or {}
        final = p.eps_out / f"ep{n:02d}_v1.mp4"
        if final.exists():
            ao_.update(status="passed", reason=str(final.relative_to(p.root)).replace("\\", "/"))
        elif night_ep.get("status") == "assemble_failed":
            ao_.update(status="failed", reason="合成失败，下一轮自动重试", where="VIDEO10 night.py")
        elif night_ep.get("status") == "hold_voices":
            ao_.update(status="pending", waiting_for="声音（series10 演员表）", where="VIDEO10 night.py")
        else:
            left = len(shot_objs) - len(resolved)
            waits = []
            if left:
                waits.append(f"{left} 镜视频没定下")
            if not cast_ok:
                waits.append("声音演员表")
            ao_.update(status="ready" if not waits and shot_objs else "pending", waiting_for="、".join(waits) or None,
                       where="VIDEO10 night.py" if night_alive else AGENT)
        po = obj("preview", f"ep{n:02d}", ep=n)
        if (p.review / f"ep{n:02d}" / "index.html").exists():
            po.update(status="passed", reason=f"data/review_pages/series10_video/ep{n:02d}/index.html")
        else:
            po.update(status="pending", waiting_for="合成后自动生成")
        E["objects"].update(voice=vo_, bgm=bo, assembly=ao_, preview=po)
        E["counts"] = _counts([o for S in shot_objs for o in S["objects"].values()] + list(E["objects"].values()))
        E["headline"] = _headline(E)
        episodes.append(E)
    # 新一季：写作运行里有、系统剧本里还没有的集 → 只有 剧本 / 导入 两个对象（导入由监督自动做，见 ImportExec）
    have = {E["ep"] for E in episodes}
    for n, st in sorted(script_eps.items()):
        if n in have:
            continue
        p4 = st.get("P4")
        so = obj("script", f"ep{n:02d}", ep=n)
        io_ = obj("import", f"ep{n:02d}", ep=n)
        if p4 in ("ok", "unchecked", "reused"):
            so.update(status="passed", reason="剧本分镜 P4 已通过校验")
            led = ledger.get(io_["id"]) or {}
            if led.get("blocked_until", 0) > now():
                io_.update(status="failed", reason=led.get("reason"), waiting_for=led.get("waiting_for") or "30 分钟后自动重试",
                           gate=led.get("gate"))
            else:
                io_.update(status="ready", waiting_for="自动导入（PRODUCER，项目方 11-01 选A授权）", reason=led.get("reason"))
        else:
            so.update(status="running" if p4 == "running" else ("failed" if p4 in ("needs_writer", "budget_stop", "error") else "pending"),
                      waiting_for="写作模型写 P4")
            io_.update(status="pending", waiting_for="P4 通过校验")
        episodes.append({"ep": n, "title": None, "objects": {"script": so, "import": io_}, "shots": [],
                         "counts": _counts([so, io_]), "headline": "导入：" + ({"ready": "排队自动导入", "failed": "没导成"}.get(
                             io_["status"], io_.get("waiting_for") or io_["status"]))})
    episodes.sort(key=lambda E: E["ep"])
    flat = [o for E in episodes for o in list(E["objects"].values()) + [x for S in E["shots"] for x in S["objects"].values()]]
    return {"schema": "nsfs.producer/1", "run": p.run_id, "episodes": episodes, "counts": _counts(flat),
            "external": {"ASSETMASTER frames_v2": sorted(fv2_eps), "VIDEO10 night.py": night_alive,
                         "画布任务": len(w.api_jobs)}}


ORPHAN_SCORE_S = 120          # 打分中的版本，没有活租约且创建超过这么久 = 打分被打断（K-OPS-F12）


def _age_s(ts) -> float:
    try:
        return now() - time.mktime(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0.0


def _frame_obj(kind, stage, sid, n, td, fv, ledger, leases, canvas, fv2_owned, deps_ok, first=None, stale=None) -> dict:
    rj = (ledger.get("_master_rejects") or {}).get(f"{kind}:{sid}")
    if rj and not rj.get("cleared") and not (ledger.get(f"{kind}:{sid}") or {}).get("redo_exhausted"):
        return _redo_obj(kind, sid, n, td, ledger, leases, rj, first)
    o = obj(kind, sid, ep=n, shot=sid)
    led = ledger.get(o["id"]) or {}
    o["attempts"] = int(led.get("tries") or 0)
    o["last_error"] = led.get("last_error")
    o["infra_errors"] = int(led.get("infra") or 0)
    t = active_take(td, stage)
    pf = take_pf(t)
    fvs = (fv.get(stage) or {})
    fvf = fvs.get("final") or {}
    fv_tries = len(fvs.get("attempts") or [])
    o["attempts"] = max(o["attempts"], fv_tries) if not led.get("tries") and not led.get("demoted_at") else o["attempts"]
    lease = leases.get(o["id"])
    try:                                       # K-OPS-E23：项目方定稿锁（非 auto）的阶段一律算定稿，不自动重出
        from ns_render import auto_current as AC  # （ep01-S1 尾帧锁在 v11：新版设不成当前 → 撤回 → 重出，10:30 起每 45 s 空转一轮）
        lock_n = AC.owner_lock(td, stage)
    except Exception:  # noqa: BLE001
        lock_n = None
    if lock_n is not None and not lease:
        return {**o, "status": "passed", "reason": f"项目方定稿 v{lock_n}（定稿锁），不自动重出", "take": lock_n, "owner_locked": True}
    if t and pf.get("ok") and stale:
        return {**o, "status": "ready", "stale": True, "attempts": 0, "waiting_for": "空闲道",
                "reason": f"v{t['n']} 过期（{stale if isinstance(stale, str) else '剧本 / 输入改了'}），自动重出，不算之前的次数"}
    if t and pf.get("ok"):
        # REFLOCK 11-01：Q2 鞋 0.70–0.78 只记录（evidence.review =“鞋待目检”）→ 面板标出来，留给总调度看印样
        rv = [f"{i.get('id')} {(i.get('evidence') or {}).get('review')}" for i in pf.get("items") or []
              if isinstance(i.get("evidence"), dict) and (i["evidence"].get("review"))]
        return {**o, "status": "passed", "reason": f"v{t['n']} 过契约并设为当前", "take": t["n"], "review": "；".join(rv) or None}
    if t and pf.get("state") == "running":
        # K-OPS-F12（FACTORY sv-09）：打分进行到一半进程重启了（租约随进程失效）→ 这张图只重打分，不重出、不计次；
        # 否则对象永远停在“契约质检中”。重启队列因此可以只等出图道排空、不必等打分积压清空
        if not leases.get(f"{kind}:{sid}") and _age_s(t.get("created_at")) > ORPHAN_SCORE_S:
            return {**o, "status": "ready", "rescore_take": t["n"], "take": t["n"],
                    "reason": f"v{t['n']} 打分被进程重启打断", "waiting_for": "只重打分（不占道、不重出、不计次）"}
        return {**o, "status": "running", "reason": f"v{t['n']} 契约质检中", "where": "postflight（CPU，不占道）", "take": t["n"]}
    if kind == "last" and (led.get("na") or fvf.get("status") == "不适用"):
        return {**o, "status": "passed", "reason": "剧本这一镜没有结束状态，不需要尾帧", "na": True}
    if not deps_ok:
        if kind == "last" and first and first["status"] == "best_effort":
            return {**o, "status": "best_effort", "reason": "首帧没过契约（尽力），不出尾帧"}
        return {**o, "status": "pending", "waiting_for": "资产 / 导入" if kind == "first" else "首帧过契约"}
    if lease:
        return {**o, "status": "running", "where": lease.get("lane") or lease.get("holder"), "since": lease.get("since"),
                "reason": f"第 {lease.get('try', o['attempts'] + 1)}/{MAX_TRIES} 次" + (f"：{lease.get('rung')}" if lease.get("rung") else "")}
    cj = canvas.get(f"{kind}:{sid}") or (canvas.get(f"image:{sid}") if kind == "first" else None)
    if cj:
        return {**o, "status": "running", "where": f"画布任务 {cj.get('id')}（{cj.get('state')}，道 {cj.get('gpu')}）",
                "reason": "画布上有这一镜的任务在排 / 在跑，不重复提交"}
    if fv2_owned and not fvf:
        return {**o, "status": "running", "where": "ASSETMASTER frames_v2", "reason": f"ASSETMASTER 在做（已试 {fv_tries} 次）"}
    if led.get("final") == "best_effort" and led.get("reason"):
        return {**o, "status": "best_effort", "reason": led["reason"]}
    if led.get("final") == "best_effort" or (fvf.get("status") == "不合格" and not led.get("demoted_at")) or o["attempts"] >= MAX_TRIES:
        why =led.get("reason") or ("；".join(fvf.get("why") or [])[:160] if fvf.get("why") else None) or (pf_reason(pf) if pf else None)
        return {**o, "status": "best_effort", "reason": f"试了 {max(o['attempts'], fv_tries)} 次仍没过契约，取最好一版标“尽力”，不进合成。"
                                                         + (f"原因：{why}" if why else "")}
    if led.get("backoff_until", 0) > now():
        return {**o, "status": "ready", "waiting_for": f"基础设施退避到 {iso(led['backoff_until'])[11:]}",
                "reason": led.get("reason")}
    if led.get("blocked_until", 0) > now():
        return {**o, "status": "failed", "reason": led.get("reason"), "waiting_for": "资料补齐后自动重查"}
    r = None
    if t and pf.get("ok") is False:
        r = "当前版本" + pf_reason(pf) + "，自动重出"
    elif led.get("reason"):
        r = led["reason"]
    return {**o, "status": "ready", "reason": r, "waiting_for": "空闲道"}


def _redo_obj(kind, sid, n, td, ledger, leases, rj, first=None) -> dict:
    """总调度驳回（master_reject）：被驳回的当前版本立即撤下（总调度 11-01 G0，⤴ 取代“当前版本留着”），按驳回计划重出；替换版过契约 + 看图闸门（或总调度复核）后换上；不计入 3 次上限"""
    o = obj(kind, sid, ep=n, shot=sid)
    oid = o["id"]
    led = ledger.get(oid) or {}
    plan = (rj.get("plan") or []) + list(led.get("ladder_plan") or [])      # K-OPS-E09：阶梯追加的计划记在本机账本
    k = int(led.get("redo_tries") or 0)
    o.update(redo=True, attempts=k, max_attempts=len(plan) or None, master_reject=rj.get("reason"),
             reason=("总调度驳回 v{}：{}".format(rj.get("reject_n"), rj.get("reason")) if rj.get("reject_n") else "总调度插队：" + str(rj.get("reason"))))
    lease = leases.get(oid)
    if lease:
        return {**o, "status": "running", "where": lease.get("lane"), "reason": o["reason"] + "；" + str(lease.get("rung"))}
    if led.get("redo_candidate"):
        return {**o, "status": "pending",
                "waiting_for": "总调度复核替换版 v{}（已过契约；驳回版 v{} 已撤下，这一镜暂无当前版本）".format(led["redo_candidate"], rj.get("reject_n"))}
    if rj.get("wait"):
        return {**o, "status": "pending", "waiting_for": rj["wait"]}
    if kind == "last" and first and first.get("redo"):
        return {**o, "status": "pending", "waiting_for": "首帧被驳回、替换版复核后再重做尾帧"}
    if k >= len(plan):
        # K-OPS-E09（总调度 02:4x，G1）：取消“等总调度定”——阶梯用完交给 Producer.escalate_exhausted 自动定下一步
        return {**o, "status": "pending", "escalate": True,
                "waiting_for": "驳回重出 {} 次都没换上 → 阶梯自动处理（输入变了重置 / 换重档 / 尽力 + 工单）".format(k)}
    if led.get("backoff_until", 0) > now():
        return {**o, "status": "ready", "waiting_for": "基础设施退避到 " + iso(led["backoff_until"])[11:]}
    return {**o, "status": "ready", "waiting_for": "空闲道（驳回重出，第 {}/{} 次：{}）".format(k + 1, len(plan), plan[k].get("name"))}


def _video_obj(w: World, sid, n, td, fo, lo, ledger, leases, night_alive) -> dict:
    o = obj("video", sid, ep=n, shot=sid)
    t = active_take(td, "video")
    rec = None
    host = None
    for h, shots in w.vstate.items():
        if sid in shots:
            rec, host = shots[sid], h
    if t and (take_pf(t).get("ok") or (t.get("qc") or {}).get("ok")):
        return {**o, "status": "passed", "reason": f"v{t['n']} 视频已设为当前"}
    if rec:
        st = rec.get("status")
        tries = len([x for x in rec.get("renders") or [] if x.get("state") not in ("cancelled",)])
        o["attempts"] = tries
        if st in ("done", "best_effort") and fo["status"] != "passed":
            return {**o, "status": "pending", "where": host, "waiting_for": "首帧过契约（现有视频是用旧首帧出的，新首帧定下后重出）"}
        if st == "done":
            return {**o, "status": "passed", "reason": f"{rec.get('chosen')} 过审片打分", "where": host}
        if st == "best_effort":
            return {**o, "status": "best_effort", "reason": f"试了 {tries} 次没全过，取罚分最小的一版（{rec.get('chosen')}）标“尽力”", "where": host}
        if st == "blocked":
            return {**o, "status": "failed", "reason": rec.get("why") or "资料不全，没出", "where": host}
        busy = [x for x in rec.get("renders") or [] if x.get("state") in ("submitted", "fetched", "scoring")]
        if busy:
            b = busy[-1]
            return {**o, "status": "running", "where": f"{host} {b.get('lane', '')}".strip(),
                    "reason": f"第 {tries}/{MAX_TRIES + 1} 版 {b.get('variant', '')}（{b.get('state')}）"}
    if fo["status"] != "passed" or lo["status"] not in ("passed", "best_effort"):
        why = "首帧过契约" if fo["status"] != "passed" else "尾帧定下"
        if fo["status"] == "best_effort":
            return {**o, "status": "pending", "waiting_for": "首帧尽力：本集放行后走纯 Ref2VA（K-REN-301）"}
        return {**o, "status": "pending", "waiting_for": why}
    ep_disp = (w.night.get("eps") or {}).get(str(n))
    if ep_disp:
        return {**o, "status": "running", "where": f"VIDEO10 {ep_disp.get('host')}", "reason": "已随本集派出，等编排器排到"}
    return {**o, "status": "ready", "where": "VIDEO10 night.py" if night_alive else AGENT,
            "waiting_for": "本集每镜首尾帧都定下后整集派出（VIDEO10 按集出片、整集合成）"}


def _counts(objs: list[dict]) -> dict:
    c = {s: 0 for s in STATUSES}
    for o in objs:
        c[o["status"]] = c.get(o["status"], 0) + 1
    c["total"] = len(objs)
    return c


def _headline(E: dict) -> str:
    """每集一句：现在在干什么 / 在等什么"""
    shots = E["shots"]
    k = {kind: sum(1 for S in shots if S["objects"][kind]["status"] == "passed") for kind in ("first", "last", "video")}
    run = [S["objects"][kind] for S in shots for kind in ("first", "last", "video") if S["objects"][kind]["status"] == "running"]
    be = sum(1 for S in shots for kind in ("first", "last", "video") if S["objects"][kind]["status"] == "best_effort")
    h = {kind: sum(1 for S in shots if (S.get("has") or {}).get(kind)) for kind in ("first", "last", "video")}
    E["have"] = {**h, "passed": k, "total": len(shots)}
    # PW-011：分子 = takes.json 当前版本（与 /api/progress 同口径）；括号里是监督口径（帧 = 当前版本过契约；视频 = VIDEO10 审片打分定下）
    parts = [f"{w} {h[kind]}/{len(shots)}（{q} {k[kind]}）" for kind, w, q in
             (("first", "首帧", "过契约"), ("last", "尾帧", "过契约"), ("video", "视频", "已定下"))]
    if run:
        parts.append(f"{len(run)} 项在做")
    if be:
        parts.append(f"{be} 项尽力")
    a = E["objects"]["assembly"]
    if a["status"] == "passed":
        parts.append("已合成")
    elif a.get("waiting_for"):
        parts.append("合成等：" + a["waiting_for"])
    return " · ".join(parts)


# ---------------------------------------------------------------------------------------------- 出图执行
class FrameExec:
    """真出图：唯一出图路径（K-REN-134）。一次占一条道；postflight 放 CPU 线程池（不占道，K-OPS-I06）"""

    def __init__(self, paths: Paths, script):
        self.p, self.script = paths, script
        self.post_pool = cf.ThreadPoolExecutor(max_workers=3, thread_name_prefix="producer-postflight")

    def render(self, kind: str, sid: str, lane: str, url: str, attempt: int, rung: dict, tag: dict) -> dict:
        """→ {"take": n, "file": data 相对路径, "job": 作业, "pf_future": Future|None} ；出错抛异常（调用方分类）"""
        from ns_agent import frame_job as FJ
        from ns_render import pipeline as P
        from ns_render import unified_frame as UF
        from ns_render.comfy_client import ComfyClient, ComfyError
        class _Cap(ComfyClient):              # 记下 ComfyUI 输出项：契约在 gpu33 上直接读原始输出（不用再上传）
            def run(self, workflow, timeout_s):
                entry, secs = super().run(workflow, timeout_s)
                self.last_entry = entry
                return entry, secs

        client = _Cap(url)
        client.ns_tag = tag
        host = "gpu36" if lane.startswith("gpu36") else "local" if lane in render_image_only_lanes() else "gpu33"   # LOCALGPU：本机道 → 本机打分
        project = UF.project_for(self.script) or self.p.run_id
        ep, shot = P.find_shot(self.script, sid)
        first_job = FJ.build_first(project, ep, shot, self.script.globals, **(rung.get("plan_kw") or {}))
        if rung.get("preset"):
            first_job = {**first_job, "preset": rung["preset"]}
        if rung.get("variant") == "faces_only" and kind == "first":    # 策略 A：只挂脸，服装靠正文外层单品句（总调度 11-01 09:5x）
            first_job = faces_only_variant(project, ep, shot, first_job, rung.get("plan_kw") or {})
        if rung.get("variant") == "double_face" and kind == "first":   # 策略 B：同一张身份脸放两槽，加身份权重
            first_job = double_face_variant(project, ep, shot, first_job, rung.get("plan_kw") or {})
        if rung.get("variant") == "faces_look" and kind == "first":   # 双人镜 A 版：两张脸 + 林晚本镜造型设定图（第 3 槽）
            first_job = linwan_sheet_variant(project, ep, shot, first_job, rung.get("plan_kw") or {})
        if rung.get("board") and kind == "first":       # 双人镜 B 版：两张脸 + 参考板（与 ASSETMASTER frames_v2 同一函数）
            from ns_agent import asset_refs as AR
            if str(ROOT / "tools" / "assetmaster") not in sys.path:
                sys.path.insert(0, str(ROOT / "tools" / "assetmaster"))
            import frames_v2 as F2
            sr, plan = AR.plan_for(project, ep, shot, "qwen_image_2.1", **(rung.get("plan_kw") or {}))
            plan2 = F2.two_person_board(sr, plan)
            if first_job["prompt"].startswith(plan.prompt_prefix) and plan2 is not plan:
                body = first_job["prompt"][len(plan.prompt_prefix):]
                first_job = {**first_job, "prompt": plan2.prompt_prefix + body, "refs": plan2.files,
                             "asset_refs": AR.record(sr, plan2), "face_files": [x.file for x in plan2.slots if x.kind == "face"]}
        if kind == "first":
            job = first_job
            dl = vqa_delta(sid, "image")        # VQAGATE：上一版看图没过 → 套用写作网关给的一维修正（K-REN-V05）
            if dl:
                from ns_agent.vqa import judge as VJ
                job = {**job, "prompt": VJ.apply_delta(job["prompt"], dl), "vqa_delta": dl}
            pf = UF._contract(job)
            if not pf.ok:
                raise ComfyError(f"{sid} 生成契约 preflight 不通过，未提交：" + "；".join(pf.reasons()))
            bad_refs = refs_guard(self.p, sid, job)
            if bad_refs:
                raise ComfyError(f"{sid} 生成契约 preflight 不通过，未提交：K-OPS-F03 refs 与目标状态不一致：" + "；".join(bad_refs)[:400])
            stage = "image"
        else:
            td = P.load_takes(sid)
            ft = active_take(td, "image")
            if not ft or not take_pf(ft).get("ok"):
                raise ComfyError(f"{sid} 首帧没有过契约的当前版本，不能做尾帧（preflight 不通过）")
            if not first_job.get("last_prompt"):
                return {"na": True}
            job = FJ.build_last(first_job, f"data/{ft['file']}")
            if rung.get("preset"):
                job["preset"] = rung["preset"]
            if rung.get("variant") == "double_face" and job.get("face_files"):     # 策略 B（尾帧）：身份脸再放一槽
                f0 = job["face_files"][0]
                k = len(job["refs"]) + 1
                job = {**job, "refs": [*job["refs"], f0],
                       "prompt": f"图{k}是同一人的脸部参考（与图2同一张，加强身份，只取脸和发型）。" + job["prompt"]}
            stage = "last"
        take = UF._run(client, sid, stage, job, rung["seed"])[0]       # REFLOCK 11-01 起返回 (take, eff, post_rec)
        P._add_take(sid, take, activate=False)        # G3：过了契约才由 auto_current.on_contract 设为当前
        bad = next((t.get("bad") for t in P.load_takes(sid).get("takes") or [] if t.get("stage") == stage and t.get("n") == take.n), None)
        if bad:                                   # 坏图只记版本、不设为当前（pipeline._add_take）→ 算一次内容失败
            raise ComfyError(f"{sid} {stage} v{take.n} {bad}")
        from ns_render import frame_edit as FE
        FE.annotate(sid, stage, take.n, path="unified_frame（K-REN-134）· PRODUCER",
                    producer={"attempt": attempt, "rung": rung.get("name"), "lane": lane, "seed": rung["seed"], "tag": tag},
                    postflight={"state": "running", "ok": None})
        asset_refs = first_job.get("asset_refs")
        host_path = None
        try:
            item = next(f for f in client.output_files(client.last_entry) if f["filename"].endswith(".png"))
            if lane in GPU33_OUTDIR:
                host_path = "/".join(x for x in (GPU33_OUTDIR[lane], item.get("subfolder") or "", item["filename"]) if x)
        except Exception:  # noqa: BLE001
            host_path = None
        fut = self.post_pool.submit(self._postflight, sid, stage, take.n, take.file, {**job, "asset_refs": asset_refs}, host,
                                    host_path)
        gpu_s = None
        try:                                   # IMGPERF：GPU 实际执行秒数（/history execution_start → success），不含排队
            from ns_api import jobs as J
            gpu_s = J.gpu_seconds(client.last_entry)
        except Exception:  # noqa: BLE001
            pass
        return {"take": take.n, "file": take.file, "pf_future": fut, "gpu_s": gpu_s}

    def _postflight(self, sid, stage, n, file_rel, job, host, host_path=None) -> dict:
        """契约打分（总调度 11-01 切到 GPU）：gpu33 道出的图 → remote_score.postflight_full 一次 ssh 在 gpu33 GPU 上读原始输出、
        按 frame_v9 交付后处理复现后打分（实测 30–61 s / 张，与 CPU 路径差 ≤0.0036，data/review_pages/asset_reflock/gpu_parity.json）；
        gpu36 道的图 / 远端失败 → UF._postflight（交付图上传到 gpu33 GPU 打分，再不行退回笔记本 CPU，不冒充通过）"""
        from ns_render import frame_edit as FE
        from ns_render import unified_frame as UF
        pf = None
        for k in range(3 if host_path else 0):    # gpu33 打分偶发 OOM / ssh 抖：退避重试，不当成内容不过
            try:
                if str(ROOT / "tools" / "gen_contract") not in sys.path:
                    sys.path.insert(0, str(ROOT / "tools" / "gen_contract"))
                import remote_score as RS
                from ns_render import image_params as IP
                req = {"cast": job.get("cast"), "asset_refs": job.get("asset_refs") or {}}
                d = RS.postflight_full("gpu33", [{"id": "x", "host_path": host_path,
                                                   "post": RS.post_of(IP.resolve(job.get("preset") or UF.preset_id(), {"style_suffix": ""})),
                                                   "request": req}])["x"]
                if not d.get("measure_error"):
                    pf = d
                    pf["scored_from"] = "gpu33 原始输出 " + host_path
                    break
                err = d["measure_error"]
            except Exception as e:  # noqa: BLE001
                err = repr(e)[:200]
            log_event(self.p, "score_retry", obj=f"{stage}:{sid}", error=str(err)[:200], k=k + 1)
            time.sleep(30 * (k + 1))
        if pf is None:
            try:
                pf = UF._postflight(file_rel, job, host)
            except Exception as e:  # noqa: BLE001
                pf = {"ok": None, "error": repr(e)[:300]}
        if score_unmeasured(pf):                 # 远端打分失败、退回本机后关键项“未测”：是基础设施问题，不是内容不过
            pf["score_infra"] = True
        pf.setdefault("reasons", [])
        vlm = vqa_gate(sid, stage, file_rel, job, pf)   # VQAGATE：本地看图闸门（enforce 期不过 = 不设为当前、自动重出）
        try:                                     # canary_after_redo：换版后前 6 镜同一阻断项失败 > 34% → 暂停派单（kind=canary，不自动恢复）
            from ns_agent.vqa import canary as CN
            hit = CN.observe(sid, stage, pf)
            if hit:
                set_paused(Paths(), True, by="POLICY_CANARY", kind="canary",
                           note=f"换版首批复核：前 {hit['n']} 镜 {hit['item']} 不过占 {hit['frac']:.0%}（{'、'.join(hit['shots'])}），版本 {hit['version']}")
        except Exception as e:  # noqa: BLE001 — canary 出错不挡出图，但要记
            log_event(Paths(), "canary_err", obj=f"{stage}:{sid}", error=repr(e)[:200])
        try:
            FE.annotate(sid, stage, n, postflight=pf)
            from ns_render import auto_current as AC
            pf["current"] = AC.on_contract(sid, stage, n)
        except Exception:  # noqa: BLE001
            pass
        vqa_record(sid, stage, n, file_rel, job, pf, vlm=vlm)
        outbox_emit(sid, stage, n, file_rel)
        return pf

    def activate(self, sid: str, stage: str, n: int) -> None:
        from ns_render import pipeline as P
        P.set_active(sid, stage, n)


class FakeFrameExec:
    """dryrun：不碰 GPU。写一张 768×1344 占位图登记成版本；fail_plan = {对象 id: ["content"|"infra"|"ok", ...]}"""

    def __init__(self, paths: Paths, fail_plan: dict | None = None):
        self.p = paths
        self.plan = {k: list(v) for k, v in (fail_plan or {}).items()}
        self.post_pool = cf.ThreadPoolExecutor(max_workers=2)

    def render(self, kind, sid, lane, url, attempt, rung, tag) -> dict:
        from ns_render import pipeline as P
        from ns_schema.edits import Take
        from PIL import Image
        oid = f"{kind}:{sid}"
        step = self.plan.get(oid, ["ok"]).pop(0) if self.plan.get(oid) else "ok"
        if step == "infra":
            raise ConnectionError(f"/prompt: HTTP 502 Bad Gateway（注入：{lane} 隧道断）")
        stage = "image" if kind == "first" else "last"
        n = P._next_n(sid, stage)
        rel = f"renders/{sid.split('-')[0]}/{sid.split('-')[1]}/takes/{stage}_{n:03d}.png"
        f = P.DATA / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        Image.effect_noise((768, 1344), 60 + 10 * attempt).convert("RGB").save(f)   # 纯色图会被坏图检查（<10 KB）拦下
        take = Take(n=n, stage=stage, file=rel, seed=rung["seed"], prompt=f"[dryrun] {oid} {rung.get('name')}", negative="",
                    seconds=0.1, created_at=P.now(), workflow="dryrun")
        P._add_take(sid, take, activate=False)
        ok = step == "ok"
        # 演练要走完整闸门：看图闸门 enforce 时 auto_current 要求 Q9 pass（11-02 DEBUG-RSI：原来缺 Q9 → 过契约却设不成当前 →
        # reconcile_demoted 撤回 → 无限循环、退出码仍是 0）
        pf = {"ok": ok, "blocking": [] if ok else ["Q1"], "items": [{"id": "Q1", "status": "pass" if ok else "fail",
                                                                     "evidence": {"value": 0.5 + 0.05 * attempt}},
                                                                    {"id": "Q9", "status": "pass", "evidence": {"dryrun": True}}],
              "reasons": [] if ok else ["Q1 身份相似度 0.31 < 0.40（注入）"]}
        from ns_render import frame_edit as FE
        FE.annotate(sid, stage, n, postflight=pf, producer={"attempt": attempt, "rung": rung.get("name"), "lane": lane, "tag": tag})
        from ns_render import auto_current as AC
        pf = {**pf, "current": AC.on_contract(sid, stage, n)}
        fut: cf.Future = cf.Future()
        fut.set_result(pf)
        return {"take": n, "file": rel, "pf_future": fut}

    def activate(self, sid, stage, n):
        from ns_render import pipeline as P
        P.set_active(sid, stage, n)


# ---------------------------------------------------------------------------------------------- 视频桥
class VideoBridge:
    """VIDEO10 night.py 在跑：只在“本集每镜首尾帧都定下”时写 force_eps 放行（night 下一轮自己派）；
    workers.video = producer（night 退役后）：本服务每轮直接调 night.loop_once"""

    def __init__(self, paths: Paths):
        self.p = paths
        self._night_state = None
        self._warned: set = set()

    def tick(self, reg: dict, ctrl: dict, night_alive: bool, logf) -> None:
        if ctrl.get("auto_force_eps", True):
            cpath = self.p.vid / "night_control.json"
            c = jl(cpath, {}) or {}
            forced = set(c.get("force_eps") or [])
            for E in reg["episodes"]:
                shots = E["shots"]
                if not shots or E["ep"] in forced or str(E["ep"]) in (jl(self.p.vid / "night_state.json", {}) or {}).get("eps", {}):
                    continue
                fs = [S["objects"]["first"]["status"] for S in shots]
                ls = [S["objects"]["last"]["status"] for S in shots]
                if all(x in ("passed", "best_effort") for x in fs) and all(x in ("passed", "best_effort") for x in ls) \
                        and any(x == "best_effort" for x in fs) and E["ep"] not in self._warned:
                    # 总调度 11-02 02:2x（ITERATION_PROTOCOL §3 不合格不进合成；DISTILL gates.best_effort_policy）：
                    # ⤴ 取代“含尽力镜的集自动写 force_eps 放行”。force_eps 是整集放行，会把尽力镜带进视频 / 合成，所以不再写；
                    # 过了契约的镜 night 本来就逐镜派（first_ready），尽力镜等规则 / 资产变化后自动 reset 重做（K-OPS-E11）
                    self._warned.add(E["ep"])
                    logf("video_release_skipped", ep=E["ep"], counted=False,
                         why="本集有尽力镜：不整集放行（尽力镜不进合成）；过了契约的镜照常逐镜出视频")
        if (ctrl.get("workers") or {}).get("video") == "producer" and not night_alive:
            import night as NT  # noqa: PLC0415
            if self._night_state is None:
                self._night_state = jl(NT.STATE, None) or {"eps": {}, "pending_shots": {}, "started": time.time()}
            try:
                NT.loop_once(self._night_state)
            except Exception as e:  # noqa: BLE001
                logf("video_err", error=repr(e)[:300], kind=classify(repr(e)))


class FakeVideo:
    """dryrun：首尾帧都定下的镜，下一轮写 state_gpu33.json shots[镜] = done（模拟 VIDEO10 编排器）"""

    def __init__(self, paths: Paths):
        self.p = paths

    def tick(self, reg, ctrl, night_alive, logf):
        sp = self.p.vid / "state_gpu33.json"
        st = jl(sp, {"shots": {}}) or {"shots": {}}
        changed = False
        for E in reg["episodes"]:
            for S in E["shots"]:
                v = S["objects"]["video"]
                rec = st["shots"].get(S["shot"])
                if v["status"] == "ready" and not rec:
                    st["shots"][S["shot"]] = {"status": "pending", "renders": [{"variant": "v1", "state": "submitted", "lane": "gpu33:1"}]}
                    changed = True
                    logf("video_dispatch", obj=v["id"], lane="gpu33:1", dry=True)
                elif rec and rec["status"] == "pending":
                    rec.update(status="done", chosen="v1")
                    rec["renders"][0]["state"] = "done"
                    changed = True
                    logf("video_done", obj=v["id"], dry=True)
        if changed:
            js(sp, st)


# ---------------------------------------------------------------------------------------------- 监督
class Producer:
    def __init__(self, paths: Paths | None = None, *, script=None, frames=None, video=None, lanes: dict | None = None,
                 lane_probe=None, only: set | None = None, run_summary_fn=None, train_locks_fn=None, lock_now_fn=None):
        self.p = paths or Paths()
        self.p.pd.mkdir(parents=True, exist_ok=True)
        self.leases = Leases(self.p)
        self._script = script
        self.frames = frames
        self.video = video or VideoBridge(self.p)
        self.lanes = lanes if lanes is not None else {**IMAGE_LANES, **render_image_only_lanes()}
        self.lane_probe = lane_probe or lane_queue
        # 训练锁（K-OPS-A02，IMGPERF 11-01 报：10-31 OOM 就是往训练中的卡派了活）：与 ns_api.jobs.pick_lane 同一来源
        self.train_locks_fn = train_locks_fn or train_locks_cached
        self.lock_now_fn = lock_now_fn or lane_locked_now
        self.only = only
        self._dispatch_only = only
        self.run_summary_fn = run_summary_fn or self._run_summary
        self.inflight: dict[str, dict] = {}        # 对象 → {lane, future}
        self.lane_busy: dict[str, list] = {}       # 道 → 在这条道上的对象（预取：最多 prefetch_depth 个）
        self.depth = prefetch_depth()
        self.score_done: list = []                 # 打分完成时刻（动态积压上限用）
        self.lane_cool: dict[str, float] = {}      # 道 → 冷却到
        # DEBUG-RSI K-OPS-E05（11-02）：出完图后 _run_one 还要在本线程里等契约打分 + 看图（实测 8–25 分钟）。
        # 原来线程数 = 道数 → 6 张图都在等打分时，新派的单只能在线程池里排队，道被标“在做”、GPU 实际空着
        # （00:46 派出的 ep01-S10 / ep02-S1 / S2 / S3 到 01:03 一直没交给 ComfyUI，四个队列都是空的）。
        # 线程数放大到道数 × 3；同时用 SCORE_BACKLOG 限制“出好但还没打完分”的数量，打分跟不上时停派（背压），不堆积。
        self.scoring: set[str] = set()             # 出好、正在等契约打分 / 看图的对象
        self._backlog_env = int(os.environ.get("NS_PRODUCER_SCORE_BACKLOG", "0"))
        self.score_backlog_max = self._backlog_env or 2 * (len(self.lanes) or 1) * vlm_instances()     # 启动值；之后按实测吞吐动态更新
        # 11-02 02:2x 复核：gpu33 线程池 18 < 积压上限 48，等打分的线程占满后新单在池里排 50–100 s 才开始（dispatch 02:08:30 → rendered
        # 02:10:04，render_s 只记 39.9）。线程数必须 ≥ 积压上限 + 道数，让积压闸而不是线程池来限流
        self.pool = cf.ThreadPoolExecutor(max_workers=max(8, max(self.score_backlog_max, 96) + 2 * self.depth * (len(self.lanes) or 1)),
                                          thread_name_prefix="producer-lane")
        self.mu = threading.RLock()
        self.last_sig = None
        self.reg: dict = {}
        self.backoff = INFRA_BACKOFF

    # -- 输入 --
    def script(self):
        if self._script is None or self._script_mtime != self._mtime():
            from ns_render import pipeline as P
            self._script = P.load_script()
            self._script_mtime = self._mtime()
        return self._script

    _script_mtime = None

    def _mtime(self):
        from ns_render import pipeline as P
        try:
            return P.SCRIPT_JSON.stat().st_mtime
        except OSError:
            return None

    def _run_summary(self):
        try:
            from ns_api import story_runs as SR  # noqa: PLC0415
            return SR._summary(SR._run_dir(self.p.run_id))
        except Exception:  # noqa: BLE001
            return None

    def ctrl(self) -> dict:
        c = {**DEFAULT_CTRL, **(jl(self.p.ctrl, {}) or {})}
        c["workers"] = {**DEFAULT_CTRL["workers"], **(c.get("workers") or {})}
        return c

    def ledger(self) -> dict:
        return jl(self.p.ledger, {}) or {}

    def led_update(self, oid: str, **kw) -> dict:
        with self.mu:
            L = self.ledger()
            r = L.setdefault(oid, {})
            r.update(kw)
            js(self.p.ledger, L)
            return r

    def logf(self, ev, **kw):
        return log_event(self.p, ev, **kw)

    # -- 一轮 --
    def tick(self, dispatch: bool = True) -> dict:
        try:
            pause_tick(self.p)                     # K-OPS-E08：运维暂停到点自动恢复；显式暂停超时只报警
        except Exception as e:  # noqa: BLE001
            self.logf("pause_tick_err", error=repr(e)[:200])
        ctrl = self.ctrl()
        only = self.only or (set(ctrl.get("only") or []) or None)
        # PW-005：共享登记表永远是整季（分母 = 每集镜数）；--only / control.only 只限制派单。演练（临时目录）才按 only 推导
        self._dispatch_only = only
        w = World(self.p, script=self._script if getattr(self, "_fixed_script", False) else self.script(),
                  shots_filter=only if getattr(self, "derive_only", False) else None)
        leases = self.leases.all()
        self.reconcile_demoted(w)
        led_all = {**self.ledger(), "_master_rejects": jl(self.p.rejects, {}) or {}}
        reg = derive(w, led_all, leases, self.run_summary_fn())
        lanes = self.probe_lanes(ctrl)
        reg.update(updated=iso(), heartbeat=now(), pid=os.getpid(), paused=bool(ctrl.get("paused")),
                   paused_by=ctrl.get("paused_by"), lanes=lanes, workers=ctrl["workers"],
                   gates=jl(self.p.gates, []) or [], tasks=self._tasks(reg))
        self.reg = reg
        if dispatch and not ctrl.get("paused"):
            if ctrl["workers"].get("frames") == "producer" and self.frames is not None:
                try:
                    if self.adopt_fv2(reg):          # 接手前先收 ASSETMASTER 已出、已打分、没登记的图（不重出）
                        return self.tick(dispatch)
                except Exception as e:  # noqa: BLE001
                    self.logf("adopt_err", error=repr(e)[:300])
                try:
                    self.auto_reset_best_effort(reg)   # K-OPS-E11：尽力版在规则 / 资产版本变化时自动重置
                except Exception as e:  # noqa: BLE001
                    self.logf("be_reset_err", error=repr(e)[:300])
                try:
                    self.escalate_exhausted(reg)  # K-OPS-E09：驳回阶梯用完的对象自动定下一步（不停下等人）
                except Exception as e:  # noqa: BLE001
                    self.logf("escalate_err", error=repr(e)[:300])
                self.dispatch_frames(reg, lanes, ctrl)
            try:
                self.video.tick(reg, ctrl, w.night_alive(), self.logf)
            except Exception as e:  # noqa: BLE001
                self.logf("video_err", error=repr(e)[:300])
            if ctrl.get("auto_import", True):
                try:
                    self.auto_import(reg)
                except Exception as e:  # noqa: BLE001
                    self.logf("import_err", error=repr(e)[:300])
            self.raise_gates(reg)
        try:                                         # K-OPS-E13 登记表自检（data_parity 读同一份文件）
            probs = registry_consistency(reg)
            js(self.p.pd / "consistency.json", {"at": iso(), "n": len(probs), "problems": probs[:200], "rule": "K-OPS-E13"})
        except Exception as e:  # noqa: BLE001
            self.logf("consistency_err", error=repr(e)[:200])
        js(self.p.registry, reg)
        with self.mu:
            scoring_n = len(self.scoring)
        js(self.p.heartbeat, {"ts": iso(), "t": now(), "pid": os.getpid(), "paused": reg["paused"], "inflight": len(self.inflight),
                              "scoring": scoring_n, "rendering": max(0, len(self.inflight) - scoring_n)})   # K-OPS-F12：重启队列只等 rendering=0
        sig = json.dumps([[(o["id"], o["status"], o.get("attempts")) for S in E["shots"] for o in S["objects"].values()]
                          for E in reg["episodes"]] + [reg["paused"]], ensure_ascii=False)
        if sig != self.last_sig:
            self.last_sig = sig
            js(self.p.mirror, {"updated": reg["updated"], "counts": reg["counts"], "paused": reg["paused"],
                               "note": "PRODUCER 状态变了（live.py 据此推 stage 事件，界面重取 /api/producer/status）"})
        return reg

    def auto_reset_best_effort(self, reg, every_s: float = 300) -> dict:
        """K-OPS-E11（总调度 11-02 02:2x / DISTILL gates.best_effort_policy）：尽力版（不进合成）在规则或资产版本变化时自动重置、
        重新进正常流程，不计次。第一次见到尽力版只记下当时的依据（be_basis），之后依据变了才重置。资产暂缓清单里的不动。每 5 分钟查一次"""
        if now() - getattr(self, "_be_check_t", 0) < every_s:
            return {}
        self._be_check_t = now()
        rule = be_rule_sig(self.p.root)
        held = asset_hold_objects(self.p.data)
        out = {"basis": 0, "reset": 0}
        for E in reg.get("episodes") or []:
            for S in E["shots"]:
                for k in ("first", "last"):
                    o = S["objects"][k]
                    if o.get("status") != "best_effort" or o["id"] in held:
                        continue
                    led = self.ledger().get(o["id"]) or {}
                    sig = {"rule": rule, **shot_inputs_sig(self.p, S["shot"])}
                    base = led.get("be_basis")
                    if not base:
                        self.led_update(o["id"], be_basis=sig)
                        out["basis"] += 1
                        continue
                    changed = [x for x in ("rule", "inputs", "prompt_sha") if sig.get(x) and base.get(x) and sig[x] != base[x]]
                    if sig.get("refs_mtime") and base.get("refs_mtime") and sig["refs_mtime"] > base["refs_mtime"]:
                        changed.append("refs")
                    if not changed:
                        continue
                    word = {"rule": "契约 / 预设 / 看图规则", "inputs": "编译输入", "prompt_sha": "提示词", "refs": "参考图"}
                    why = "尽力版的" + "、".join(word[c] for c in changed) + "变了 → 自动重置，重新给 3 次，不计次（K-OPS-E11）"
                    self.led_update(o["id"], tries=0, final=None, redo_exhausted=None, ladder_plan=[], redo_tries=0, be_basis=None,
                                    demoted_at=iso(), reason=why,
                                    history=[dict(h, before_gate_change=True) for h in led.get("history") or []])
                    self.logf("best_effort_reset", obj=o["id"], counted=False, why=why, changed=changed)
                    out["reset"] += 1
        return out

    def obj_rate_exceeded(self, o: dict, cap: int = 8) -> bool:
        """K-OPS-E21（总调度 08:0x P0：ep05-S3 出到第 82 版、S7 46 次，计次没拦住）：同一对象最近 1 小时派单 ≥ cap →
        写 data/autopilot/runaway_hold.json（按镜暂停，reason_kind=runaway，6 小时到期）+ SENTINEL 工单，这一单不派"""
        t = now()
        hist = self.__dict__.setdefault("_obj_disp", {})
        recent = [x for x in hist.get(o["id"], []) if t - x <= 3600]
        hist[o["id"]] = recent
        if len(recent) < cap:
            return False
        f = self.p.data / "autopilot" / "runaway_hold.json"
        d = jl(f, {}) or {}
        items = {it.get("shot"): it for it in d.get("shots") or []}
        if o["shot"] not in items:
            exp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t + 6 * 3600))
            items[o["shot"]] = {"shot": o["shot"], "objects": [f"first:{o['shot']}", f"last:{o['shot']}"], "expires_at": exp,
                                "why": f"1 小时内派了 {len(recent)} 次（上限 {cap}）", "at": iso()}
            d.update(active=True, reason_kind=d.get("reason_kind") or "runaway", shots=list(items.values()),
                     rule="K-OPS-E21 单对象出图速率超限自动暂停；到期（expires_at）自动失效")
            f.parent.mkdir(parents=True, exist_ok=True)
            js(f, d)
            sentinel_ticket(self.p, o["id"], f"单对象出图速率超限：1 小时 {len(recent)} 次（上限 {cap}），已自动按镜暂停",
                            {"per_hour": len(recent), "cap": cap}, self.ledger().get(o["id"]) or {})
            self.logf("runaway_hold", obj=o["id"], per_hour=len(recent), cap=cap, counted=False)
        return True

    def escalate_exhausted(self, reg) -> dict:
        """K-OPS-E09 驳回阶梯（config/policies/retry.yaml redo_ladder，decider=code）：
          ① 还在资产暂缓清单（*_hold.json）→ 继续等；
          ② 最后一次失败之后输入变了（提示词 / 参考图集合 / 参考图文件更新 / 编译输入哈希）→ 重置驳回次数，counted=false，原因“输入已更新”；
          ③ 输入没变 → 下一级：追加 frame_v9_heavy 换 seed ×2（只追加一次）；
          ④ 再不过 → 标尽力版（不进合成）+ 给 SENTINEL 开工单（附失败原因统计）。"""
        held = asset_hold_objects(self.p.data)
        lad = redo_ladder_policy()
        out = {"held": 0, "reset": 0, "heavy": 0, "best_effort": 0}
        for E in reg.get("episodes") or []:
            for S in E["shots"]:
                for k in ("first", "last"):
                    o = S["objects"][k]
                    if not o.get("escalate"):
                        continue
                    oid = o["id"]
                    if oid in held:
                        out["held"] += 1
                        continue
                    led = self.ledger().get(oid) or {}
                    changed = redo_inputs_changed_v2(self.p, o["shot"], k, led)
                    sig = job_sig(self.p, o["shot"])
                    if changed:
                        self.led_update(oid, redo_tries=0, ladder_plan=[], redo_exhausted=None, ladder_sig=sig,
                                        redo_resets=(led.get("redo_resets") or []) + [{"at": iso(), "why": "输入已更新：" + changed}],
                                        reason="输入已更新（" + changed + "），驳回重出重新给，不计次")
                        self.logf("redo_reset", obj=oid, counted=False, why="输入已更新：" + changed)
                        out["reset"] += 1
                    elif not led.get("ladder_plan"):
                        plan = [plan_item(x) for x in lad["heavy_plan"]]
                        self.led_update(oid, ladder_plan=plan, ladder_sig=sig, reason="驳回重出用完、输入没变 → 下一级：" + "、".join(lad["heavy_plan"]))
                        self.logf("redo_escalate", obj=oid, counted=False, plan=lad["heavy_plan"])
                        out["heavy"] += 1
                    else:
                        stats = fail_stats(led)
                        why = "驳回阶梯走完仍没过（" + "、".join(f"{a}×{b}" for a, b in stats.items()) + "），标尽力版，不进合成"
                        self.led_update(oid, redo_exhausted=True, final="best_effort", reason=why)
                        sentinel_ticket(self.p, oid, why, stats, led)
                        self.logf("best_effort", obj=oid, reason=why, via="redo_ladder", counted=False)
                        out["best_effort"] += 1
        if any(out[x] for x in ("reset", "heavy", "best_effort")):
            self.logf("ladder_tick", **out)
        return out

    def _tasks(self, reg) -> list[dict]:
        """给 GPUVIEW /api/render-tasks：在做 / 要做 / 失败 / 尽力的出图视频对象（扁平）"""
        out = []
        for E in reg["episodes"]:
            for S in E["shots"]:
                for k in ("first", "last", "video"):
                    o = S["objects"][k]
                    if o["status"] in ("running", "ready", "failed", "best_effort"):
                        out.append({k2: o.get(k2) for k2 in ("id", "kind", "label", "ep", "shot", "status", "attempts", "max_attempts",
                                                             "last_error", "reason", "waiting_for", "where", "since")})
        return out

    def probe_lanes(self, ctrl) -> dict:
        hold = set(ctrl.get("hold_lanes") or []) | {ln for ln in self.lanes if lane_held(ln)}
        out = {}
        for ln, url in self.lanes.items():
            q = self.lane_probe(url)
            mine = list(self.lane_busy.get(ln) or [])
            cool = self.lane_cool.get(ln, 0)
            srv, idx = lane_split(ln)
            locks = self.train_locks_fn(srv)          # None = 这台的锁还没读到过 → 当作不可用（宁可不派）
            locked = locks is None or idx in locks
            # 道上只有“让道模式”的任务（VIDEO10 视频、BAKEOFF 对比；夜间道归属：gpu33 三道出图优先、gpu36:0/1 BAKEOFF 让道）
            # → 出图照样排进去（队列深度 ≤ 1 个别人的任务，K-OPS-I06），对方按让道规则停交新活
            agents = [str(x) for x in q.get("agents") or []]
            foreign = [a for a in agents if not a.upper().startswith(AGENT.upper())]
            yielding_only = bool(foreign) and all(a.upper().startswith(YIELDING_AGENTS) for a in foreign) and len(foreign) <= 1
            # K-OPS-E17 预取：队列里只有自己的单（或至多 1 个让道任务）且总数 < 预取深度 → 还能再交一单
            qfree = q.get("ok") and (not foreign or yielding_only) and (q.get("n") or 0) < self.depth + (1 if yielding_only else 0)
            free = qfree and len(mine) < self.depth and ln not in hold and cool <= now() and not locked
            why = None
            if free and yielding_only:
                why = "排在让道任务后面（出图优先）：" + "、".join(sorted(set(agents)))
            elif locks is None:
                why = "训练锁还没读到（后台读取中），先不派"
            elif locked:
                why = f"训练锁 train.lock.gpu{idx}（有人在训练）"
            elif ln in hold:
                why = "render_endpoints hold（道就绪，等总调度开派）" if lane_held(ln) else "control.json hold_lanes"
            elif not q.get("ok"):
                why = "连不上（隧道 / 服务）"
            elif len(mine) >= self.depth:
                why = f"PRODUCER 在做 {'、'.join(mine)}"
            elif foreign and not yielding_only:
                why = "让道：" + "、".join(sorted(set(q.get("agents") or [])))[:80]
            elif cool > now():
                why = f"出错冷却到 {iso(cool)[11:]}"
            out[ln] = {"free": bool(free), "why": why, "queue": q.get("n"), "agents": q.get("agents"), "mine": mine,
                       "prefetch": self.depth}
        return out

    # -- 派单 --
    def dispatch_frames(self, reg, lanes, ctrl) -> None:
        free = [ln for ln, s in lanes.items() if s["free"]]
        if not free:
            return
        hi = higher_priority_busy(self.p)
        if hi:                                     # K-OPS-E15：高优先级剧还有可派的活 → 低优先级剧不派（不打断在途）
            if getattr(self, "_last_prio_log", 0) < now() - 300:
                self._last_prio_log = now()
                self.logf("priority_yield", run=self.p.run_id, to=hi, counted=False)
            return
        dprobs = decision_file_problems()
        if dprobs:          # K-OPS-F09：决策 / 覆盖文件缺失或损坏 → 这一拍一单不派（失败关闭），5 分钟报一次警
            if getattr(self, "_last_dfb_log", 0) < now() - 300:
                self._last_dfb_log = now()
                self.logf("decision_files_block", problems=dprobs[:8], alarm=True, counted=False)
            return
        with self.mu:
            backlog = len(self.scoring)
            if not self._backlog_env and len(self.score_done) >= 3:
                self.score_backlog_max = dynamic_backlog(self.score_done, now(), len(self.lanes) or 1, self.depth)
        if backlog >= self.score_backlog_max:
            if getattr(self, "_last_s3_ticket", 0) < now() - 1800:       # K-OPS-E17：压到上限不悄悄停派——给 SENTINEL 开 S3 工单（30 分钟一张）
                self._last_s3_ticket = now()
                sentinel_ticket(self.p, "score_backlog", f"打分积压 {backlog} 达到上限 {self.score_backlog_max}（按最近 15 分钟打分吞吐算），出图停派等打分",
                                {"backlog": backlog, "max": self.score_backlog_max, "done_15min": len([x for x in self.score_done if now() - x <= 900])},
                                {"redo_history": []})     # K-OPS-E05：打分积压到上限就先不派（GPU 出得再快也只是排队等打分）
            if getattr(self, "_last_backlog_log", 0) < now() - 300:
                self._last_backlog_log = now()
                self.logf("score_backlog", n=backlog, max=self.score_backlog_max, counted=False,
                          note="出好的图在排队等契约打分 / 看图，先不派新单")
            return
        cands = []
        for E in reg["episodes"]:
            for S in E["shots"]:
                for k in ("last", "first"):            # 先把已有首帧的镜推到尾帧（链条往视频走）
                    o = S["objects"][k]
                    if o["status"] == "ready" and not str(o.get("waiting_for") or "").startswith("基础设施退避") and o["id"] not in self.inflight:
                        cands.append((E["ep"], 0 if k == "last" else 1, S["index"], o))
        cands.sort(key=lambda x: (0 if x[3].get("redo") else 1, *x[:3]))   # 总调度驳回 / 插队的先派
        held = asset_hold_objects(self.p.data)
        rate_cap = int(os.environ.get("NS_PRODUCER_OBJ_PER_HOUR", "8"))
        try:
            local_only = local_only_shots(self.script())
        except Exception:  # noqa: BLE001  读不到剧本 = 失败关闭：这一拍不派
            self.logf("local_only_unknown", counted=False)
            return
        for _ep, _k, _i, o in cands:
            if o["shot"] in local_only and all(is_server_lane(ln) for ln in free):   # K-OPS-E22：本地生成镜，服务器不派
                if o["id"] not in self.__dict__.setdefault("_local_only_logged", set()):
                    self._local_only_logged.add(o["id"])
                    self.logf("local_only_skip", obj=o["id"], counted=False, why="剧本 H3校验 标了本地生成 / 占位，服务器不派单")
                continue
            if self.obj_rate_exceeded(o, rate_cap):      # K-OPS-E21：同一对象 1 小时出图超过上限 → 自动按镜暂停 + 工单
                continue
            if self._dispatch_only and o["shot"] not in self._dispatch_only:
                continue
            if o["id"] in held:                  # IMGFIX r5：资产修复待点选的造型（data/autopilot/*_hold.json）暂缓派单
                continue
            if not free:
                break
            led = self.ledger().get(o["id"]) or {}
            rt = led.get("rescore_take") or o.get("rescore_take")     # K-OPS-F12：打分被重启打断的版本同样只重打分
            if rt:                               # 上次只是打分没打成：只重打分（不占道、不重出、不计次）
                if self.leases.acquire(o["id"], holder_note="rescore"):
                    with self.mu:
                        self.inflight[o["id"]] = {"lane": None, "since": now()}
                    self.pool.submit(self._rescore_one, o, int(rt))
                continue
            tried = set(led.get("lanes_failed") or [])
            lane = next((ln for ln in free if ln not in tried), free[0])
            if o.get("redo"):                    # 总调度驳回重出：按驳回计划，不计入 3 次上限
                rj = (jl(self.p.rejects, {}) or {}).get(o["id"]) or {}
                k = int(led.get("redo_tries") or 0)
                plan = (rj.get("plan") or []) + list(led.get("ladder_plan") or [])
                if k >= len(plan):
                    continue
                from ns_render import pipeline as P
                pk = plan[k]
                rung = {"name": "{} {}/{}：{}".format(rj.get("label") or "驳回重出", k + 1, len(plan), pk.get("name")),
                        "preset": pk.get("preset"), "seed": P.seed_for(f"{o['shot']}/producer/{o['kind']}/redo/{rj.get('at')}", k + 1), "redo": True}
                if pk.get("variant") == "faces_look":
                    rung.update(variant="faces_look", plan_kw={"two_person": "both_faces"})
                elif pk.get("variant") == "faces_only":
                    rung.update(variant="faces_only", plan_kw={"two_person": "both_faces"}, strategy="A" if pk.get("preset") != "frame_v9_heavy" else "C")
                elif pk.get("variant") == "faces_board":
                    rung.update(variant="faces_board", plan_kw={"two_person": "both_faces"}, board=True)
                if not self.leases.acquire(o["id"], lane=lane, attempt=k + 1, rung=rung["name"]):
                    continue
                free.remove(lane)
                from ns_agent import comfy_tag as CT
                tag = CT.make(AGENT, "first_frame" if o["kind"] == "first" else "last_frame", episode=o["ep"],
                              shot=o["shot"].split("-")[1], label=rung["name"], attempt=k + 1, max_attempts=len(plan),
                              obj=o["id"], job=o["id"])
                with self.mu:
                    self.lane_busy.setdefault(lane, []).append(o["id"])
                    self.inflight[o["id"]] = {"lane": lane, "since": now()}
                    self.__dict__.setdefault("_obj_disp", {}).setdefault(o["id"], []).append(now())
                self.logf("dispatch", obj=o["id"], lane=lane, attempt=k + 1, rung=rung["name"], preset=rung.get("preset"),
                          seed=rung["seed"], redo=True, counted=False, comfy_tag=tag)
                self.pool.submit(self._run_one, o, lane, k + 1, rung, tag)
                continue
            # 总调度 11-01：ASSETMASTER frames_v2 已出的尝试计入 3 次上限（o["attempts"] 已含 frames_v2 的次数）
            attempt = max(int(led.get("tries") or 0), int(o.get("attempts") or 0)) + 1
            if attempt > MAX_TRIES:
                continue
            rung = self.rung_strategy(o, attempt, led) or self.rung_ab(o, attempt) or self.rung(o, attempt)
            if not self.leases.acquire(o["id"], lane=lane, attempt=attempt, rung=rung["name"], **{"try": attempt}):
                continue
            free.remove(lane)
            from ns_agent import comfy_tag as CT
            tag = CT.make(AGENT, "first_frame" if o["kind"] == "first" else "last_frame", episode=o["ep"],
                          shot=o["shot"].split("-")[1], label=f"自动制作 {rung['name']}", attempt=attempt, max_attempts=MAX_TRIES,
                          obj=o["id"], job=o["id"])
            with self.mu:
                self.lane_busy.setdefault(lane, []).append(o["id"])
                self.inflight[o["id"]] = {"lane": lane, "since": now()}
                self.__dict__.setdefault("_obj_disp", {}).setdefault(o["id"], []).append(now())
            self.logf("dispatch", obj=o["id"], lane=lane, attempt=attempt, rung=rung["name"], variant=rung.get("variant"),
                      strategy=rung.get("strategy"),
                      seed=rung["seed"], comfy_tag=tag)
            self.pool.submit(self._run_one, o, lane, attempt, rung, tag)

    def rung(self, o: dict, attempt: int) -> dict:
        """自修阶梯：1 默认 → 2 换 seed → 3 换参考（双人镜两张脸各占一槽；单人镜再换 seed）"""
        from ns_render import pipeline as P
        seed = P.seed_for(f"{o['shot']}/producer/{o['kind']}", attempt)
        if attempt == 1:
            return {"name": "第 1 次（frame_v9 默认）", "seed": seed}
        if attempt == 2:
            return {"name": "第 2 次：换 seed", "seed": seed}
        plan_kw = {}
        name = "第 3 次：再换 seed"
        try:
            _ep, shot = P.find_shot(self.script(), o["shot"])
            if sum(1 for c in shot.cast if getattr(c, "presence", None) == "在画") >= 2:
                plan_kw = {"two_person": "both_faces"}
                name = "第 3 次：换参考（两张脸各占一槽）"
        except Exception:  # noqa: BLE001
            pass
        return {"name": name, "seed": seed, "plan_kw": plan_kw}

    def two_person(self, sid: str) -> bool:
        try:
            from ns_render import pipeline as P
            _ep, shot = P.find_shot(self.script(), sid)
            return sum(1 for c in shot.cast if getattr(c, "presence", None) == "在画") >= 2
        except Exception:  # noqa: BLE001
            return False

    def rung_strategy(self, o: dict, attempt: int, led: dict) -> dict | None:
        """总调度 11-01 09:5x 批：第二轮 Q1 自修——账本 strategy = "A"（双人：只挂脸）/ "B"（单人、尾帧：双份脸）；
        第 1、2 次用 A / B，第 3 次 C（frame_v9_heavy，同一挂法）。每次记 variant 统计胜率"""
        stg = led.get("strategy")
        if stg not in ("A", "B"):
            return None
        from ns_render import pipeline as P
        seed = P.seed_for(f"{o['shot']}/producer/{o['kind']}/strategy{stg}", attempt)
        var = "faces_only" if stg == "A" else "double_face"
        word = "只挂脸（服装靠正文点名）" if stg == "A" else "双份身份脸"
        kw = {"two_person": "both_faces"} if stg == "A" else {}
        if attempt < 3:
            return {"name": f"第 {attempt} 次：策略 {stg} {word}", "seed": seed, "plan_kw": kw, "variant": var, "strategy": stg}
        return {"name": f"第 {attempt} 次：策略 C 重档 frame_v9_heavy + {word}", "seed": seed, "plan_kw": kw,
                "variant": var, "preset": "frame_v9_heavy", "strategy": "C"}

    def rung_ab(self, o: dict, attempt: int) -> dict | None:
        """双人镜首帧（总调度 11-01 06:16 定默认，依据 A/B：A 4/12 过、B 0/8 过）：第 1、2 次 两张脸 + 林晚造型设定图（A，
        第 2 次换 seed），第 3 次才退到 两张脸 + 参考板（B）；每次都记 variant"""
        if o["kind"] != "first" or not self.two_person(o["shot"]):
            return None
        from ns_render import pipeline as P
        seed = P.seed_for(f"{o['shot']}/producer/{o['kind']}", attempt)
        if attempt < 3:
            return {"name": f"第 {attempt} 次：两张脸 + 林晚造型设定图（A）" + ("，换 seed" if attempt == 2 else ""), "seed": seed,
                    "plan_kw": {"two_person": "both_faces"}, "variant": "faces_look"}
        return {"name": f"第 {attempt} 次：退到 两张脸 + 参考板（B）", "seed": seed, "plan_kw": {"two_person": "both_faces"},
                "board": True, "variant": "faces_board"}

    def _run_one(self, o, lane, attempt, rung, tag) -> None:
        oid, sid, kind = o["id"], o["shot"], o["kind"]
        url = self.lanes[lane]
        t0 = now()
        try:
            if self.lock_now_fn(lane):            # 出发前现读一次训练锁（不走缓存，在派单线程里读，不卡主循环）
                raise RuntimeError(f"训练锁：{lane} 上锁了（train.lock），未提交，换道")
            res = self.frames.render(kind, sid, lane, url, attempt, rung, tag)
            if res.get("na"):
                self.led_update(oid, na=True, final="na", reason="剧本这一镜没有结束状态，不需要尾帧")
                self.logf("na", obj=oid)
                return
            with self.mu:
                if oid in (self.lane_busy.get(lane) or []):     # 出图完成即放道（只放自己这一单，别动同道预取的后来者）
                    self.lane_busy[lane].remove(oid)
            render_s = round(now() - t0, 1)
            self.logf("rendered", obj=oid, lane=lane, take=res["take"], secs=render_s, render_s=render_s, gpu_s=res.get("gpu_s"))
            with self.mu:
                self.scoring.add(oid)
            t1 = now()
            pf = res["pf_future"].result(timeout=1800)
            contract_s = round(now() - t1, 1)
            if pf.get("score_infra"):
                self.led_update(oid, rescore_take=res["take"], backoff_until=now() + 300,
                                reason="契约打分时 gpu33 出错（显存 / 连接），5 分钟后只重打分、不重出，不算一次尝试")
                self.logf("score_infra", obj=oid, take=res["take"], error=str(pf.get("remote_error") or pf.get("error"))[:200],
                          counted=False, render_s=render_s, contract_s=contract_s, gpu_s=res.get("gpu_s"))
                return
            L = self.ledger().get(oid) or {}
            if rung.get("redo"):
                rh = list(L.get("redo_history") or []) + [{"try": attempt, "take": res["take"], "ok": bool(pf.get("ok")),
                                                          "blocking": pf.get("blocking"), "rung": rung["name"],
                                                          "preset": rung.get("preset"), "at": iso()}]
                if pf.get("ok"):
                    self.led_update(oid, redo_tries=attempt, redo_history=rh, redo_candidate=res["take"])
                    if auto_review_redo(self.p, oid, res["take"], pf):   # G0：替换版过了本地看图闸门 → 自动换上（总调度改抽查）
                        self.logf("redo_auto_approved", obj=oid, take=res["take"], counted=False, render_s=render_s,
                                  contract_s=contract_s)
                        return
                    self.logf("redo_candidate", obj=oid, take=res["take"], preset=rung.get("preset"), counted=False,
                              note="替换版过了契约，等总调度复核（驳回版已撤下，复核通过后设为当前）", render_s=render_s, contract_s=contract_s)
                else:
                    self.led_update(oid, redo_tries=attempt, redo_history=rh, last_error=pf_reason(pf))
                    note_auto_reject(self.p, oid, res["take"], pf)        # G0：原因写进驳回记录，按计划接着重出
                    self.logf("redo_fail", obj=oid, take=res["take"], preset=rung.get("preset"), why=pf_reason(pf), counted=False)
                return
            hist = list(L.get("history") or []) + [{"try": attempt, "lane": lane, "take": res["take"], "ok": bool(pf.get("ok")),
                                                     "variant": rung.get("variant"),
                                                     "blocking": pf.get("blocking"), "rung": rung["name"], "at": iso()}]
            if pf.get("ok"):
                self.led_update(oid, tries=attempt, history=hist, final="passed", reason=None, last_error=None,
                                passed_sig=job_sig(self.p, sid) if kind == "first" else None)
                self.logf("passed", obj=oid, take=res["take"], attempt=attempt, variant=rung.get("variant"), strategy=rung.get("strategy"),
                          render_s=render_s, contract_s=contract_s,
                          gpu_s=res.get("gpu_s"), scored_from=pf.get("scored_from") or pf.get("measured_on"))
                return
            why = pf_reason(pf)
            if attempt >= MAX_TRIES:
                best = self._best(sid, "image" if kind == "first" else "last", hist)
                # G3：没过契约的版本绝不设为当前；契约分最好的一版只记下来给人看
                reason = (f"试了 {attempt} 次（{' → '.join(str(h.get('rung') or h.get('source') or '?') for h in hist)}）仍没过：{why}；契约分最好的是 v{best}"
                          f"（没过契约，不设为当前），标“尽力”，不进合成")
                self.led_update(oid, tries=attempt, history=hist, final="best_effort", reason=reason, last_error=why)
                self.logf("best_effort", obj=oid, reason=reason, strategy=rung.get("strategy"), variant=rung.get("variant"),
                          blocking=pf.get("blocking"), render_s=render_s, contract_s=contract_s, gpu_s=res.get("gpu_s"))
            else:
                nxt = (self.rung_strategy(o, attempt + 1, self.ledger().get(oid) or {}) or self.rung_ab(o, attempt + 1)
                       or self.rung(o, attempt + 1))["name"]
                self.led_update(oid, tries=attempt, history=hist, reason=f"第 {attempt} 次{why}；自动重出（{nxt}）", last_error=why)
                self.logf("content_fail", obj=oid, attempt=attempt, variant=rung.get("variant"), strategy=rung.get("strategy"),
                          blocking=pf.get("blocking"), why=why, next=nxt, render_s=render_s, contract_s=contract_s,
                          gpu_s=res.get("gpu_s"), scored_from=pf.get("scored_from") or pf.get("measured_on"))
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            k = classify(err)
            L = self.ledger().get(oid) or {}
            if k == "code":            # 系统代码 / 接口不匹配：不算内容尝试，30 分钟后再试，日志带 traceback 给负责会话修
                self.led_update(oid, backoff_until=now() + CODE_RETRY_S, last_error=err[:300],
                                reason="系统代码出错（不算一次尝试），已记日志等修：" + err[:120])
                self.logf("code_error", obj=oid, lane=lane, error=err[:300], counted=False, tb=traceback.format_exc()[-600:])
            elif k == "infra":
                ni = int(L.get("infra") or 0) + 1
                back = self.backoff[min(ni - 1, len(self.backoff) - 1)]
                lf = sorted(set(L.get("lanes_failed") or []) | {lane})
                self.lane_cool[lane] = now() + back
                self.led_update(oid, infra=ni, backoff_until=now() + back, lanes_failed=lf[-4:], last_error=err[:300],
                                reason=plain_reason(k, err))
                self.logf("infra_error", obj=oid, lane=lane, error=err[:300], backoff_s=back, counted=False,
                          reason=plain_reason(k, err))
            elif k == "preflight":
                reasons = [x for x in re.split(r"[；;]", err.split("：", 1)[-1]) if x.strip()]
                gate = bool(GATE_PAT.search(err))
                self.led_update(oid, blocked_until=now() + PREFLIGHT_RETRY_S, last_error=err[:300], reason=plain_reason(k, err))
                self.led_update(f"assets:{sid}", blocked=True, at=now(), reasons=reasons[:6], gate="characters" if gate else None)
                self.logf("preflight_block", obj=oid, reasons=reasons[:6], owner_gate=gate)
            else:
                hist = list(L.get("history") or []) + [{"try": attempt, "lane": lane, "error": err[:200], "rung": rung["name"], "at": iso()}]
                fin = attempt >= MAX_TRIES
                self.led_update(oid, tries=attempt, history=hist, last_error=err[:300],
                                final="best_effort" if fin else None,
                                reason=(f"试了 {attempt} 次都出错：{err[:120]}；标“尽力”" if fin else f"第 {attempt} 次出错：{err[:120]}；自动重出"))
                self.logf("content_error", obj=oid, attempt=attempt, error=err[:300], tb=traceback.format_exc()[-300:])
        finally:
            with self.mu:
                if oid in (self.lane_busy.get(lane) or []):     # 11-01 08:38：只放自己这一单
                    self.lane_busy[lane].remove(oid)
                self.inflight.pop(oid, None)
                if oid in self.scoring:
                    self.score_done.append(now())
                    self.score_done = self.score_done[-500:]
                self.scoring.discard(oid)
            self.leases.release(oid)

    def _rescore_one(self, o, n) -> None:
        oid, sid = o["id"], o["shot"]
        stage = "image" if o["kind"] == "first" else "last"
        try:
            from ns_render import pipeline as P
            from ns_render import unified_frame as UF
            from ns_agent import frame_job as FJ
            script = self.script()
            ep, shot = P.find_shot(script, sid)
            job = FJ.build_first(UF.project_for(script), ep, shot, script.globals)
            t = next(x for x in P.load_takes(sid)["takes"] if x["stage"] == stage and x["n"] == n)
            pf = self.frames._postflight(sid, stage, n, t["file"], {"cast": job.get("cast"), "asset_refs": job.get("asset_refs")},
                                         "gpu33", None)
            if pf.get("score_infra"):
                self.led_update(oid, backoff_until=now() + 600, reason="契约打分仍没打成，10 分钟后再试（不重出、不计次）")
                self.logf("score_infra", obj=oid, take=n, counted=False)
                return
            L = self.ledger().get(oid) or {}
            hist = [dict(h, ok=bool(pf.get("ok")), blocking=pf.get("blocking")) if h.get("take") == n else h
                    for h in L.get("history") or []]
            self.led_update(oid, rescore_take=None, history=hist,
                            **({"final": "passed", "reason": None} if pf.get("ok") else {"reason": "重打分后：" + pf_reason(pf)}))
            self.logf("rescore", obj=oid, take=n, ok=pf.get("ok"), blocking=pf.get("blocking"), counted=False)
        except Exception as e:  # noqa: BLE001
            self.led_update(oid, backoff_until=now() + 600, last_error=repr(e)[:200])
            self.logf("rescore_err", obj=oid, take=n, error=repr(e)[:200])
        finally:
            with self.mu:
                self.inflight.pop(oid, None)
            self.leases.release(oid)

    def reconcile_demoted(self, w) -> None:
        """每轮都让账本跟上 takes.json（DATAALIGN D-LEDGER）：
        ① 账本记“已通过”、但这一版后来被重打分判不过（门槛改了，如 REFLOCK 11-01 Q1 全脸识别）、当前已被 G3 撤下 →
           这是门槛变化，不是又失败了一次：清掉旧次数，重新给 3 次（总调度：重打分不计尝试）；
        ② 当前版本过契约但换了一版（总调度 approve 替换版 / 驳回 / 别的会话设的）→ 账本追加一条 ok 记录指向当前版本"""
        L = self.ledger()
        changed = False
        for oid, r in list(L.items()):
            if oid.startswith("_") or ":" not in oid:
                continue
            if r.get("final") != "passed":
                # ③ 账本不是“已通过”，但这一阶段有版本被别的会话重打分从“过”改成“不过”（门槛变了，REFLOCK rescore_takes.py
                #    写 postflight.rescored.was_ok=True）→ 也算门槛变化：在那次重打分之前用掉的次数清零（只清一次）
                kind, sid = oid.split(":", 1)
                stage = "image" if kind == "first" else "last"
                try:
                    td = w.takes(sid)
                except Exception:  # noqa: BLE001
                    continue
                flips = [((t.get("postflight") or {}).get("rescored") or {}) for t in td.get("takes") or [] if t.get("stage") == stage]
                flips = [x for x in flips if x.get("was_ok") and (t_ok := x.get("at")) and t_ok > (r.get("demoted_at") or "")]
                if flips:
                    at = max(x["at"] for x in flips)
                    keep = [h for h in r.get("history") or [] if str(h.get("at") or "") > at]
                    n_now = len([h for h in keep if "take" in h or "error" in h])
                    if n_now < MAX_TRIES and r.get("final") == "best_effort":
                        r["final"] = None                       # 门槛变化后还没用满 3 次：撤掉“尽力”，接着出
                    r.update(tries=n_now, demoted_at=at,
                             history=[dict(h, before_gate_change=True) if h not in keep else h for h in r.get("history") or []],
                             reason="之前通过的版本在契约门槛更新后重打分没过，门槛变化前的次数不算")
                    changed = True
                    self.logf("demoted", obj=oid, counted=False, note=r["reason"], tries_now=r["tries"])
                continue
            kind, sid = oid.split(":", 1)
            stage = "image" if kind == "first" else "last"
            td = w.takes(sid)
            t = active_take(td, stage)
            sm = (getattr(w, "summary", None) or {}).get(sid) or {}
            if t and take_pf(t).get("ok") and ((sm.get("stale") or {}).get(stage)):
                r.update(final=None, tries=0, demoted_at=iso(), reason="剧本 / 输入改了，当前版本过期，自动重出，不算之前的次数")
                changed = True
                self.logf("stale_requeue", obj=oid, take=t["n"], counted=False, why=str((sm.get("stale") or {}).get(stage))[:120])
                continue
            if t and t.get("master_reject"):
                # K-OPS-Q23 / 总调度 11-01：当前版本带总调度驳回 → 不能当“已通过”同步进账本（驳回即撤当前，这里只是兜底：
                # 别处还没撤下时也不记通过，交 master_reject 流程重出）
                continue
            if t and take_pf(t).get("ok"):
                # 当前版本过契约，但不是账本里最后一次“通过”的那版（总调度 approve 换上、驳回、别的会话设的）→ 账本跟上 takes.json
                okh = [h for h in r.get("history") or [] if h.get("ok")]
                if not okh or okh[-1].get("take") != t["n"]:
                    old = okh[-1].get("take") if okh else None
                    ot = next((x for x in td.get("takes") or [] if x.get("stage") == stage and x.get("n") == old), None) if old else None
                    note = (f"当前换成 v{t['n']}" + (f"（原 v{old}" + ("，总调度驳回" if (ot or {}).get("master_reject") else "") + "）" if old else "")
                            + ("；总调度复核通过" if (t.get("master_review") or {}).get("ok") else ""))
                    hist = [dict(h, superseded_by=t["n"]) if h.get("ok") and h.get("take") != t["n"] else h for h in r.get("history") or []]
                    hist.append({"take": t["n"], "ok": True, "source": "reconcile（跟 takes.json 当前版本）", "note": note, "at": iso()})
                    r.update(history=hist, current_take=t["n"], reason=None)
                    changed = True
                    self.logf("ledger_sync", obj=oid, take=t["n"], old=old, note=note, counted=False)
                continue
            r.update(final=None, tries=0, demoted_at=iso(), history=[dict(h, before_gate_change=True) for h in r.get("history") or []],
                     reason="之前通过的版本在契约门槛更新后重打分没过（当前已撤下），重新给 3 次，不算之前的次数")
            changed = True
            self.logf("demoted", obj=oid, counted=False, note=r["reason"])
        if changed:
            js(self.p.ledger, L)

    def adopt_fv2(self, reg) -> int:
        """ASSETMASTER 交接（总调度 11-01）：frames_v2 不再占着的集里，还没有过契约当前版本的镜，
        若 frames_v2 已出过、且契约已打过分的尝试还没登记进 takes.json → 走 register_takes 登记（带原契约结果，
        由 auto_current.on_contract 决定是否设为当前），不重出。过契约的优先（只登最好的一张），没过的也登记成可查的候选"""
        fv = jl(self.p.frames_v2, {}) or {}
        owned = set((reg.get("external") or {}).get("ASSETMASTER frames_v2") or [])
        n_new = 0
        import register_takes as RT
        for E in reg["episodes"]:
            if E["ep"] in owned:
                continue
            for S in E["shots"]:
                for kind, stage in (("first", "image"), ("last", "last")):
                    o = S["objects"][kind]
                    if o["status"] in ("passed", "running"):
                        continue
                    atts = [a for a in ((fv.get(S["shot"]) or {}).get(stage) or {}).get("attempts") or []
                            if a.get("file") and isinstance(a.get("postflight"), dict) and a["postflight"].get("ok") is not None
                            and (self.p.root / a["file"]).is_file()]
                    for a in sorted(atts, key=lambda a: score_key(a["postflight"]), reverse=True):
                        pf = a["postflight"]
                        it = {"shot": S["shot"], "stage": stage, "file": a["file"], "seed": a.get("seed"),
                              "prompt": a.get("sent_prompt") or "", "refs": a.get("refs"), "workflow": "frame_v9_unified",
                              "label": "ASSETMASTER 已出（PRODUCER 接手登记）",
                              "postflight": {"ok": bool(pf.get("ok")), "items": pf.get("items") or [], "reasons": pf.get("reasons") or []},
                              "origin": {"run": "assetmaster/frames_v2", "adopted_by": AGENT, "seed": a.get("seed"),
                                         "lane": a.get("lane"), "contract_ok": bool(pf.get("ok"))}}
                        r = RT.register(it, label=it["label"])
                        if r.get("status") == "registered":
                            n_new += 1
                            self.logf("adopt", obj=o["id"], take=r.get("n"), ok=bool(pf.get("ok")), seed=a.get("seed"),
                                      current=r.get("current"), rerendered=False)
        return n_new

    def _best(self, sid, stage, hist) -> int | None:
        from ns_render import pipeline as P
        td = P.load_takes(sid)
        ns = {h.get("take") for h in hist if h.get("take")}
        cands = [t for t in td.get("takes") or [] if t.get("stage") == stage and t.get("n") in ns and not t.get("bad")]
        if not cands:
            return None
        return max(cands, key=lambda t: score_key(take_pf(t)))["n"]

    # -- 自动导入（总调度 11-01：项目方选 A 授权；/api/script-inbox/import 的 PRODUCER 系统身份）--
    API = "http://127.0.0.1:8800"

    def _http(self, method: str, path: str, body=None, timeout=900):
        data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
        req = urllib.request.Request(self.API + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}

    def auto_import(self, reg) -> None:
        import hashlib
        import urllib.error  # noqa: F401
        tok = ensure_token(self.p)
        for E in reg["episodes"]:
            io_ = E["objects"].get("import") or {}
            if io_.get("status") != "ready" or E["shots"]:
                continue
            n, oid = E["ep"], io_["id"]
            st, d = self._http("POST", f"/api/story-runs/{self.p.run_id}/send-to-import?ep={n}")
            if st != 200:
                self.led_update(oid, blocked_until=now() + PREFLIGHT_RETRY_S, reason=f"存导入候选没成：{d.get('detail') or st}")
                self.logf("import_blocked", obj=oid, step="send-to-import", status=st, detail=str(d.get("detail"))[:200])
                continue
            path = d["draft"]["path"]
            f = self.p.root / path
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            st, v = self._http("POST", "/api/script-inbox/validate", {"path": path})
            if st != 200 or not v.get("ok") or v.get("blocking"):
                why = f"格式校验 {v.get('blocking')} 个阻断（或没跑成：{str(v.get('error') or v.get('detail') or '')[:100]}），转写作方返修"
                self.led_update(oid, blocked_until=now() + PREFLIGHT_RETRY_S, reason=why, waiting_for="写作方返修")
                self.logf("import_blocked", obj=oid, step="validate", why=why)
                continue
            st, r = self._http("POST", "/api/script-inbox/import", {
                "path": path, "sha256": sha, "by": "PRODUCER", "run": self.p.run_id, "token": tok, "mode": "merge",
                "note": f"PRODUCER 自动导入第 {n} 集（项目方 11-01 选A授权）"})
            if st == 200:
                self.led_update(oid, final="passed", reason=f"已自动导入（备份 {r.get('backup')}）", blocked_until=0)
                self.logf("imported", obj=oid, path=path, backup=r.get("backup"))
            else:
                det = str(r.get("detail") or st)
                gate = "推翻旧决定" in det
                self.led_update(oid, blocked_until=now() + PREFLIGHT_RETRY_S, reason="导入没成：" + det[:200],
                                gate="import_replace" if gate else None, waiting_for="项目方闸门" if gate else "30 分钟后自动重试")
                self.logf("import_blocked", obj=oid, step="import", status=st, detail=det[:200], owner_gate=gate)

    # -- 闸门：只有项目方的事才停 --
    def raise_gates(self, reg) -> None:
        gates = jl(self.p.gates, []) or []
        have = {g["id"] for g in gates}
        new = []
        for E in reg["episodes"]:
            for S in E["shots"]:
                a = S["objects"]["assets"]
                if a.get("gate") == "characters":
                    gid = f"characters:{S['shot']}"
                    if gid not in have:
                        new.append({"id": gid, "gate": "characters", "ep": E["ep"], "shot": S["shot"], "status": "open",
                                    "what": f"{S['shot']} 缺项目方挑定的身份参考：{a.get('reason', '')[:160]}",
                                    "where": "资产中心 → 挑设定图（点“选这张”即生效）", "at": iso()})
            so = E["objects"]["script"]
            if so.get("waiting_for") == "项目方（花钱闸门）":
                gid = f"budget:ep{E['ep']:02d}"
                if gid not in have:
                    new.append({"id": gid, "gate": "budget", "ep": E["ep"], "status": "open", "what": f"第 {E['ep']} 集写作到预算上限",
                                "where": "加预算或停写", "at": iso()})
        if not new:
            return
        js(self.p.gates, gates + new)
        for g in new:
            self.logf("owner_gate", **g)
        self._morning(new)

    def _morning(self, new: list[dict]) -> None:
        f = self.p.morning
        try:
            txt = f.read_text(encoding="utf-8") if f.exists() else "# 早上留给项目方的决定\n"
        except OSError:
            return
        mark = "<!-- PRODUCER gates -->"
        if mark not in txt:
            txt += f"\n\n## 自动制作停在项目方闸门的事（PRODUCER 自动追加）\n{mark}\n\n| 闸门 | 事项 | 在哪点 | 时间 |\n|---|---|---|---|\n"
        for g in new:
            txt += f"| {g['gate']} | {g['what']} | {g['where']} | {g['at']} |\n"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(txt, encoding="utf-8")

    def wait_idle(self, timeout: float = 3600) -> None:
        t0 = now()
        while self.inflight and now() - t0 < timeout:
            time.sleep(2)


# ---------------------------------------------------------------------------------------------- 控制
def rubric_gate(paths: Paths, path: str) -> dict:
    """HOLLYWOOD r7 导入闸门（总调度 fredw-2b 11-02 批复，L-098 / L-102，CONSENT 总调度 -> HOLLYWOOD）：
    暂存稿每集 rubric_code 代码判定失败项 = 0 才放行（tools/script_rsi/rubric_audit.gate，只读）。只拦新导入，不碰已导入的现行稿"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("rubric_audit", paths.root / "tools" / "script_rsi" / "rubric_audit.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.gate(paths.root / path)


def import_staged(paths: Paths, path: str, sha: str, note: str, by: str = "PRODUCER", skip_rubric_gate: bool = False,
                  run: str | None = None) -> int:
    """总调度派的整稿导入（D-SCR-07，项目方 11-01 选 A：“自动执行对应制作,人类不应该点,坏了,系统自动做”）：
    走与 auto_import 相同的通道——先核 sha256、rubric 导入闸门（HOLLYWOOD r7）、/api/script-inbox/validate 阻断 = 0，再带 PRODUCER 令牌 POST
    /api/script-inbox/import（merge，导入接口自己备份）；审计进 log.jsonl（imported_staged / import_blocked / rubric_gate_skipped）"""
    import hashlib
    f = paths.root / path
    got = hashlib.sha256(f.read_bytes()).hexdigest()
    if got != sha:
        log_event(paths, "import_blocked", path=path, step="sha", want=sha, got=got, by=by)
        print(json.dumps({"ok": False, "why": f"sha256 不符：{got}"}, ensure_ascii=False))
        return 1
    if skip_rubric_gate:
        if "总调度" not in (by or ""):
            log_event(paths, "import_blocked", path=path, step="rubric_skip_denied", by=by)
            print(json.dumps({"ok": False, "why": "--skip-rubric-gate 只有总调度能批（--by 须写总调度）"}, ensure_ascii=False))
            return 1
        log_event(paths, "rubric_gate_skipped", path=path, sha=sha, by=by, note=note)
    else:
        try:
            rg = rubric_gate(paths, path)
        except Exception as e:  # noqa: BLE001  闸门自身出错 = 不放行
            rg = {"ok": False, "eps": {}, "error": repr(e)[:300]}
        if not rg.get("ok"):
            fails = {e: x.get("fails", [])[:5] for e, x in (rg.get("eps") or {}).items() if x.get("fails")}
            log_event(paths, "import_blocked", path=path, step="rubric", fails=fails, error=rg.get("error"), by=by)
            print(json.dumps({"ok": False, "why": "rubric 导入闸门：代码判定失败项 ≠ 0", "fails": fails, "error": rg.get("error")},
                             ensure_ascii=False)[:2000])
            return 1
    pr = Producer.__new__(Producer)
    st, v = Producer._http(pr, "POST", "/api/script-inbox/validate", {"path": path})
    if run and not _runs().is_primary(run, paths.root):         # 第二季等非主剧：写 data/import/runs/<run>/script_v2.json，不碰主导入稿
        if st == 404:                                           # 收件箱接口只认收件箱目录；非主剧稿直接跑同一个校验器（失败关闭）
            import subprocess
            r = subprocess.run([sys.executable, str(paths.root / "tools" / "validate_qwen_script.py"), str(paths.root / path), "--json"],
                               capture_output=True, cwd=paths.root, timeout=900, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            try:
                d = json.loads(r.stdout.decode("utf-8"))
                st, v = 200, {"ok": d.get("blocking", 1) == 0, "blocking": d.get("blocking")}
            except ValueError:
                st, v = 500, {"ok": False, "blocking": None}
        if st != 200 or not v.get("ok") or v.get("blocking"):
            log_event(paths, "import_blocked", path=path, step="validate", status=st, blocking=v.get("blocking"), by=by, run=run)
            print(json.dumps({"ok": False, "why": "validate", "status": st, "blocking": v.get("blocking"), "run": run}, ensure_ascii=False))
            return 1
        return import_staged_run(paths, path, sha, note, by, run)
    if st != 200 or not v.get("ok") or v.get("blocking"):
        log_event(paths, "import_blocked", path=path, step="validate", status=st, blocking=v.get("blocking"), by=by)
        print(json.dumps({"ok": False, "why": "validate", "status": st, "blocking": v.get("blocking"),
                          "detail": str(v.get("detail") or v.get("error") or "")[:300]}, ensure_ascii=False))
        return 1
    st, r = Producer._http(pr, "POST", "/api/script-inbox/import", {
        "path": path, "sha256": sha, "by": "PRODUCER", "run": paths.run_id, "token": ensure_token(paths), "mode": "merge",
        "note": note})
    log_event(paths, "imported_staged" if st == 200 else "import_blocked", path=path, sha=sha, status=st, by=by, note=note,
              backup=r.get("backup"), detail=None if st == 200 else str(r.get("detail") or "")[:300])
    if st == 200:                                  # K-OPS-W15（WORKFLOW）：导入事件给 episode_pipeline 等下游
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import import_events as IE
            IE.append_import(imported_episodes(paths, path, r), by=f"PRODUCER import_staged（{by}）", source=path, note=note)
        except Exception as e:  # noqa: BLE001  事件没写上不影响导入本身，记日志
            log_event(paths, "import_event_err", path=path, error=repr(e)[:200])
    print(json.dumps({"ok": st == 200, "status": st, **({k: r.get(k) for k in ("backup", "episodes", "detail") if k in r})},
                     ensure_ascii=False))
    return 0 if st == 200 else 1


def _runs():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import runs as RN
    return RN


def import_staged_run(paths: Paths, path: str, sha: str, note: str, by: str, run: str) -> int:
    """多剧并行（DISTILL §0.1，总调度 02:4x / r3 ③）：非主剧导入 = tools/import_script.py -o data/import/runs/<run>/script_v2.json
    （同 run 已有稿则先备份、按集合并；不重建全局 state_timeline）→ runs.register_run → import_events.append_import(run_id=run)"""
    import subprocess
    RN = _runs()
    out = RN.import_path(run, paths.root)
    out.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if out.exists():
        bdir = out.parent / "backups"
        bdir.mkdir(parents=True, exist_ok=True)
        backup = bdir / f"script_v2.{time.strftime('%Y%m%d-%H%M%S')}.json"
        shutil.copy2(out, backup)
    cmd = [sys.executable, str(paths.root / "tools" / "import_script.py"), "--script", str(paths.root / path), "-o", str(out),
           "--no-timeline"]
    if backup:
        cmd += ["--merge-base", str(backup)]
    r = subprocess.run(cmd, capture_output=True, cwd=paths.root, timeout=900,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0:
        if backup:
            shutil.copy2(backup, out)
        log_event(paths, "import_blocked", path=path, step="import_script", run=run, by=by,
                  detail=(r.stderr or b"").decode("utf-8", "replace")[-300:])
        print(json.dumps({"ok": False, "why": "import_script 失败", "run": run}, ensure_ascii=False))
        return 1
    eps = imported_episodes(paths, path, None)
    RN.register_run(run, source="import", episode=min(eps) if eps else None, root=paths.root)
    try:
        import import_events as IE
        IE.append_import(eps, by=f"PRODUCER import_staged（{by}）", source=path, note=note, run_id=run)
    except Exception as e:  # noqa: BLE001
        log_event(paths, "import_event_err", path=path, run=run, error=repr(e)[:200])
    log_event(paths, "imported_staged", path=path, sha=sha, status=200, by=by, note=note, run=run, out=str(out.relative_to(paths.root)),
              backup=str(backup.relative_to(paths.root)) if backup else None, episodes=eps)
    print(json.dumps({"ok": True, "run": run, "out": str(out.relative_to(paths.root)), "episodes": eps}, ensure_ascii=False))
    return 0


def imported_episodes(paths: Paths, path: str, resp: dict | None = None) -> list[int]:
    """这次导入替换的集号：导入接口回的 episodes 优先；否则从暂存稿文件名（…_epNN_…）或稿内集头（第 N 集 / EP N）取"""
    eps = (resp or {}).get("episodes")
    out: set[int] = set()
    if isinstance(eps, list):
        for e in eps:
            m = re.search(r"\d+", str(e.get("n") if isinstance(e, dict) else e))
            if m:
                out.add(int(m.group()))
    if not out:
        out |= {int(m) for m in re.findall(r"ep(\d{1,2})(?!\d)", Path(path).name, re.I)}
    if not out:
        try:
            txt = (paths.root / path).read_text(encoding="utf-8")
            out |= {int(m) for m in re.findall(r"^#+\s*(?:第\s*(\d+)\s*集)", txt, re.M)}
        except OSError:
            pass
    return sorted(out)


def ensure_token(paths: Paths) -> str:
    """自动导入的系统身份令牌（只有本服务和 :8800 读；data/producer/import_token）"""
    import secrets
    f = paths.pd / "import_token"
    try:
        t = f.read_text(encoding="utf-8").strip()
    except OSError:
        t = ""
    if not t:
        t = secrets.token_hex(16)
        paths.pd.mkdir(parents=True, exist_ok=True)
        f.write_text(t, encoding="utf-8")
    return t


# ---- K-OPS-E08 暂停口径（总调度 11-02 D5）：判定只有一份实现 = tools/autopilot/policy.py:pause_decision（DISTILL）。
# 这里只负责：写暂停时强制带 reason_kind + expires_at；每拍（producer.tick / infra_watchdog）按判定执行 resume 或报警。
#   运维暂停 reason_kind ∈ resources.pause_max_s.ops_kinds（line_switch / restart / deploy）：到 expires_at（≤ paused_at+180 s）自动恢复
#   显式暂停 reason_kind ∈ explicit_kinds（master / owner）：不自动恢复，超过 180 s 写报警 A-PAUSE-OVERDUE（每 10 分钟最多一条）
OPS_HINTS = (("line_switch", ("netfix", "切线路", "线路")), ("deploy", ("deploy", "部署", "system_version")),
             ("restart", ("restart", "drain", "重启", "排空")))


def _pol():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import policy as POL
    return POL


def pause_ops_max_s() -> int:
    """单一来源：config/policies/resources.yaml resources.pause_max_s；读不到按 180"""
    try:
        return int(_pol().item("resources.pause_max_s", ROOT)["value"])
    except Exception:  # noqa: BLE001
        return 180


def infer_pause_kind(by: str) -> str:
    """没写 reason_kind 时按 --by 推断：运维类 → line_switch / deploy / restart；项目方 → owner；其余（总调度 / agent 显式）→ master"""
    b = str(by or "").lower()
    for kind, hints in OPS_HINTS:
        if any(h in b for h in hints):
            return kind
    return "owner" if (b.strip() in ("owner", "fred") or "项目方" in b) else "master"


def is_ops_kind(kind: str) -> bool:
    try:
        return kind in set(_pol().item("resources.pause_max_s", ROOT).get("ops_kinds") or [])
    except Exception:  # noqa: BLE001
        return kind in ("line_switch", "restart", "deploy")


def set_paused(paths: Paths, paused: bool, by: str = "owner", note: str = "", kind: str | None = None,
               expires_s: float | None = None) -> dict:
    """暂停一律带 reason_kind + expires_at（D5 require_fields）。运维暂停 expires ≤ 180 s；显式暂停 expires 只作提示（不自动恢复）"""
    c = jl(paths.ctrl, {}) or {}
    if paused:
        kind = kind or infer_pause_kind(by)
        if kind == "ops":
            kind = infer_pause_kind(by) if is_ops_kind(infer_pause_kind(by)) else "restart"
        cap = pause_ops_max_s()
        exp = now() + (min(float(expires_s or cap), cap) if is_ops_kind(kind) else float(expires_s or cap))
        c.update(paused=True, paused_by=by, paused_at=iso(), note=note or None, reason_kind=kind,
                 expires_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(exp)), overdue_alert_t=None)
    else:
        c.update(paused=False, paused_by=None, paused_at=None, note=note or None, reason_kind=None,
                 expires_at=None, overdue_alert_t=None)
    c.pop("expires_t", None)
    js(paths.ctrl, c)
    log_event(paths, "pause" if paused else "resume", by=by, note=note,
              **({"reason_kind": c.get("reason_kind"), "expires_at": c.get("expires_at")} if paused else {}))
    return c


def pause_shots(paths: Paths, shots: list, by: str, note: str, minutes: float = 60) -> dict:
    """K-OPS-E19：按镜暂停（默认做法）——写 data/autopilot/pause_hold.json（*_hold.json 机制，producer 每拍跳过），
    不停整条道；带 expires_at（默认 60 分钟）和 release_when，到期自动失效"""
    f = paths.data / "autopilot" / "pause_hold.json"
    d = jl(f, {}) or {}
    items = {it["shot"]: it for it in d.get("shots") or [] if it.get("shot")}
    exp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now() + minutes * 60))
    for sid in shots:
        items[sid] = {"shot": sid, "objects": [f"first:{sid}", f"last:{sid}"], "by": by, "note": note, "at": iso(), "expires_at": exp}
    d.update(active=True, rule="K-OPS-E19 按镜暂停；到期（expires_at）自动失效", shots=list(items.values()))
    f.parent.mkdir(parents=True, exist_ok=True)
    js(f, d)
    log_event(paths, "pause_shots", shots=shots, by=by, note=note, expires_at=exp, counted=False)
    return d


def pause_tick(paths: Paths, t: float | None = None, apply: bool = True, alerts: Path | None = None) -> dict:
    """按 policy.pause_decision 执行（幂等）→ {"action": None|resume|alert, ...}"""
    t = now() if t is None else t
    c = jl(paths.ctrl, {}) or {}
    d = _pol().pause_decision(c, t, ROOT)
    try:                                       # K-OPS-E19：全道暂停超过 30 分钟 → 给 SENTINEL 开工单（每次暂停一张）
        t0 = time.mktime(time.strptime(str(c.get("paused_at"))[:19], "%Y-%m-%dT%H:%M:%S")) if c.get("paused") else None
        if apply and t0 and t - t0 > 1800 and c.get("ticket_for") != c.get("paused_at"):
            sentinel_ticket(paths, "global_pause", f"整条道全局暂停已 {round((t - t0) / 60)} 分钟（{c.get('paused_by')}，"
                            f"{c.get('reason_kind') or '没写类型'}）：能不能改成只停受影响的镜（producer.py pause --shots）",
                            {"paused_s": round(t - t0), "by": c.get("paused_by"), "kind": c.get("reason_kind")}, {"redo_history": []})
            c["ticket_for"] = c.get("paused_at")
            js(paths.ctrl, c)
    except (TypeError, ValueError):
        pass
    if not d:
        return {"action": None}
    if d["action"] == "resume" and apply:
        set_paused(paths, False, by="PAUSE_EXPIRY", note=f"运维暂停（{d.get('by')}，{d.get('kind')}）到点自动恢复：{d.get('why')}（K-OPS-E08）")
    elif d["action"] == "alert" and apply and t - float(c.get("overdue_alert_t") or 0) >= 600:
        ap = alerts or (ROOT / "data/qa/alerts.jsonl")
        ap.parent.mkdir(parents=True, exist_ok=True)
        with open(ap, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": iso(), "t": t, "id": "A-PAUSE-OVERDUE", "state": "open", "level": "warn", "by": "producer.pause_tick",
                                "msg": f"暂停（{d.get('by')}，{d.get('kind') or '没写类型'}：{c.get('note') or '无说明'}）已 "
                                       f"{round((d.get('paused_s') or 0) / 60)} 分钟，不自动恢复：{d.get('why')}", "rule": "K-OPS-E08"},
                               ensure_ascii=False) + chr(10))
        c["overdue_alert_t"] = t
        js(paths.ctrl, c)
    return d

def serve(paths: Paths) -> int:
    pidf = paths.pd / "producer.pid"
    old = jl(pidf, {}) or {}
    if old.get("pid") and old.get("pid") != os.getpid() and pid_alive(old["pid"]):
        print("PRODUCER 已在运行 pid", old["pid"])
        return 0
    js(pidf, {"pid": os.getpid(), "started": iso()})
    pr = Producer(paths)
    pr.frames = FrameExec(paths, pr.script())
    log_event(paths, "start", pid=os.getpid(), lanes=list(pr.lanes))
    while True:
        try:
            pr.tick()
        except Exception as e:  # noqa: BLE001
            log_event(paths, "tick_err", error=repr(e)[:300], tb=traceback.format_exc()[-600:])
        time.sleep(TICK_S)


# ---------------------------------------------------------------------------------------------- 演练
def dryrun(inject_fail: bool = False, keep: bool = False, dest: Path | None = None) -> int:
    """临时目录演练（不碰 GPU / 正式数据）：系统剧本 ep01 的 S1（+ 注入时 S2），零点击走完 首帧 → 尾帧 → 视频。
    注入：S2 首帧 第 1 次隧道 502（基础设施，不计次）→ 3 次内容不过 → 尽力；S1 尾帧第 1 次内容不过 → 第 2 次过"""
    from ns_render import pipeline as P
    tmp = Path(tempfile.mkdtemp(prefix="producer_dry_"))
    root = tmp / "repo"
    (root / "data" / "renders").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "docs" / "overnight").mkdir(parents=True)
    paths = Paths(root=root)
    paths.vid.mkdir(parents=True)
    old = (P.DATA, P.RENDERS)
    P.DATA, P.RENDERS = root / "data", root / "data" / "renders"
    script = P.load_script()
    only = {"ep01-S1", "ep01-S2"} if inject_fail else {"ep01-S1"}
    plan = {}
    if inject_fail:
        plan = {"first:ep01-S2": ["infra", "content", "content", "content"], "last:ep01-S1": ["content", "ok"]}
    fx = FakeFrameExec(paths, plan)
    lanes = {"gpu33:0": "fake://a", "gpu33:1": "fake://b"}
    pr = Producer(paths, script=script, frames=fx, video=FakeVideo(paths), lanes=lanes,
                  lane_probe=lambda url: {"ok": True, "n": 0, "agents": []}, only=only,
                  run_summary_fn=lambda: None, train_locks_fn=lambda srv: set(), lock_now_fn=lambda lane: False)
    pr._fixed_script = True
    pr.derive_only = True
    pr.backoff = (1, 1, 1)
    # 演练里尾帧要有 last_prompt：FakeFrameExec 不编译，直接出
    trail = []
    max_ticks = 30                                # 上限：到点没走完 = 失败（退出码 2），报卡在哪一步
    ok = False
    try:
        for i in range(max_ticks):
            reg = pr.tick()
            pr.wait_idle(60)
            row = {S["shot"]: {k: S["objects"][k]["status"] for k in ("first", "last", "video")}
                   for E in reg["episodes"] for S in E["shots"]}
            trail.append((i, row))
            print(f"tick {i:02d}", json.dumps(row, ensure_ascii=False))
            if all(v["video"] == "passed" or v["first"] == "best_effort" for v in row.values()):
                reg = pr.tick(dispatch=False)
                ok = True
                break
            time.sleep(1.2)
        out = {"tmp": str(tmp), "trail": trail, "final": {S["shot"]: {k: {f: S["objects"][k].get(f) for f in ("status", "attempts", "reason", "waiting_for")}
                                                                     for k in ("first", "last", "video")}
                                                          for E in reg["episodes"] for S in E["shots"]},
               "log": [json.loads(x) for x in paths.log.read_text(encoding="utf-8").splitlines()]}
        want_video = {"ep01-S1"}                  # 成功条件：S1 必须一路到视频 passed（注入时 S2 按设计落到“尽力”）
        final = out["final"]
        ok = ok and all((final.get(sid) or {}).get("video", {}).get("status") == "passed" for sid in want_video)
        stuck = {sid: next((f"{k}={v['status']}（{v.get('reason') or v.get('waiting_for') or ''}）" for k, v in st.items()
                            if v.get("status") != "passed"), None) for sid, st in final.items()}
        out.update(ok=ok, max_ticks=max_ticks, stuck=None if ok else stuck)
        dest = dest or ROOT / "data" / "producer" / ("dryrun_inject.json" if inject_fail else "dryrun.json")
        js(dest, out)
        print("演练记录：", dest)
        if not ok:
            print("演练失败：", json.dumps(stuck, ensure_ascii=False))
            return 2
        return 0
    finally:
        P.DATA, P.RENDERS = old
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


PRESET_WORD = {"frame_v9": "frame_v9 换 seed", "frame_v9_heavy": "frame_v9_heavy（写实·重，krea2 0.8）"}


VARIANT_WORD = {"faces_look": "两张脸 + 林晚造型设定图（A）", "faces_board": "两张脸 + 参考板（B）", "faces_only": "只挂脸（策略 A）",
                "double_face": "双份身份脸（策略 B）"}


def plan_item(x: str) -> dict:
    """"frame_v9" / "frame_v9_heavy" / "frame_v9:faces_look" → 计划项"""
    preset, _, variant = x.partition(":")
    name = PRESET_WORD.get(preset, preset) + (f" · {VARIANT_WORD.get(variant, variant)}" if variant else "")
    return {"preset": preset or None, "variant": variant or None, "name": name}


def master_reject(paths: Paths, oid: str, n: int, reason: str, presets: list, wait, by: str) -> int:
    """总调度驳回某镜某阶段的版本：版本上记 master_reject（原因）；**被驳回的版本若是当前版本，立即撤下**
    （总调度 11-01 按 G0 定：驳回版不能流进视频和成片；视频本来只派过了闸门的首帧，撤下后这一镜等替换版即可。
    ⤴ 取代旧口径“驳回版保留为当前，直到替换版通过”）；takes.json master_gate 挡住自动换当前；
    按 presets 重出（不计入 3 次上限）；替换版过契约 + 看图闸门（或总调度 approve）后换上"""
    from ns_render import pipeline as P
    from ns_render import frame_edit as FE
    kind, sid = oid.split(":", 1)
    stage = "image" if kind == "first" else "last"
    if n:
        FE.annotate(sid, stage, n, master_reject={"by": by, "reason": reason, "at": iso()})
        if (P.load_takes(sid).get("active") or {}).get(stage) == n:
            P.clear_active(sid, stage, f"总调度驳回 v{n}：{reason}（驳回即撤下当前，等替换版）", actor=f"producer.master_reject（{by}）")
    with P.shot_lock(sid):
        d = P.load_takes(sid)
        d.setdefault("master_gate", {})[stage] = {"reject_n": n, "reason": reason, "by": by, "at": iso()}
        P._save_takes(sid, d)
    rj = jl(paths.rejects, {}) or {}
    rj[oid] = {"reject_n": n, "reason": reason, "by": by, "at": iso(), "wait": wait,
               "label": "总调度插队" if not n else "驳回重出",
               "plan": [plan_item(x) for x in presets if x]}
    js(paths.rejects, rj)
    L = jl(paths.ledger, {}) or {}
    rec = L.setdefault(oid, {})
    rec.update(redo_tries=0, redo_candidate=None)
    if rec.get("final") == "passed":   # 驳回即撤下（L-089）：账本同步成待重出，不留 passed（CLEANUP D-LEDGER 19:2x；WORKFLOW 改，CONSENT PRODUCER -> AUTOPILOT）
        rec.update(final=None, demoted_at=iso(), reason=f"总调度驳回 v{n}：{reason}（驳回即撤下，等替换版）")
    js(paths.ledger, L)
    log_event(paths, "master_reject", obj=oid, take=n, reason=reason, plan=presets, wait=wait, by=by, counted=False)
    return 0


def auto_review_redo(paths: Paths, oid: str, n: int, pf: dict) -> bool:
    """G0（总调度 11-01 16:2x）：驳回重出的替换版过了契约 + 本地看图闸门（Q9 pass/na：景别、锁定发色、单品在对的人身上、
    跨镜连贯）→ 直接走 master_approve 换上（by = config/vqa.json gate.auto_review_by）；总调度改为交项目方前抽查。
    闸门没开 / 没看图结果 → False（回到等总调度复核）"""
    try:
        from ns_agent.vqa import contract as VQ
        g = VQ.gate_cfg()
        if not (VQ.enforced() and g.get("auto_review_redo")) or not VQ.q9_passed(pf):
            return False
        vg = pf.get("vqa_gate") or {}
        note = "本地看图闸门通过（Q9 {}；拿不准 {}）".format(vg.get("status"), "、".join(vg.get("unsure") or []) or "无")
        master_approve(paths, oid, n, g.get("auto_review_by") or "VQAGATE", note)
        return True
    except Exception as e:  # noqa: BLE001
        log_event(paths, "redo_auto_review_err", obj=oid, take=n, error=repr(e)[:200])
        return False


def note_auto_reject(paths: Paths, oid: str, n: int, pf: dict) -> None:
    """G0：替换版没过（契约或看图闸门）→ 原因追加到 master_rejects.json[oid].auto_reviews[]（驳回计划照常往下走）"""
    try:
        rj = jl(paths.rejects, {}) or {}
        if oid not in rj:
            return
        vg = pf.get("vqa_gate") or {}
        rj[oid].setdefault("auto_reviews", []).append({"take": n, "ok": False, "by": "VQAGATE 本地看图闸门", "at": iso(),
                                                      "why": pf_reason(pf)[:300], "vqa_defects": vg.get("defects") or []})
        js(paths.rejects, rj)
    except Exception:  # noqa: BLE001
        pass


def master_approve(paths: Paths, oid: str, n: int, by: str, note: str = "") -> int:
    """总调度复核通过替换版：设为当前、清掉 master_gate 和驳回记录；首帧换了 → 同镜在等首帧的尾帧开始重做"""
    from ns_render import pipeline as P
    from ns_render import frame_edit as FE
    kind, sid = oid.split(":", 1)
    stage = "image" if kind == "first" else "last"
    from ns_render import auto_current as AC
    FE.annotate(sid, stage, n, master_review={"ok": True, "by": by, "at": iso(), "note": note})
    with P.shot_lock(sid):
        d = P.load_takes(sid)
        (d.get("master_gate") or {}).pop(stage, None)
        P._save_takes(sid, d)
    # K-OPS-Q23：唯一入口 set_active（拒绝驳回版、自己记一条审计，传操作人；不再另记 AC.audit_change，免得重复）
    P.set_active(sid, stage, n, reason=f"总调度复核通过替换版 v{n}：{note}", actor=f"producer.master_approve（{by}）")
    L0 = jl(paths.ledger, {}) or {}
    if kind == "first":
        # 首帧换了 → 由旧首帧做的尾帧不再对得上：撤下当前尾帧（项目方定稿的不动），尾帧和视频照常往下自动做
        d = P.load_takes(sid)
        lt = (d.get("active") or {}).get("last")
        if lt is not None and AC.owner_lock(d, "last") is None:
            P.clear_active(sid, "last", f"首帧换成 v{n}，旧尾帧作废、自动重做", actor=f"producer.master_approve（{by}）")
            FE.annotate(sid, "last", lt, superseded={"why": f"首帧换成 v{n}（总调度复核），由旧首帧做的尾帧作废", "at": iso()})
            L0.setdefault(f"last:{sid}", {}).update(final=None, tries=0, demoted_at=iso(),
                                                    reason=f"首帧换成 v{n}（总调度复核），尾帧自动重做")
            js(paths.ledger, L0)
            log_event(paths, "last_requeued", obj=f"last:{sid}", old=lt, first=n)
    rj = jl(paths.rejects, {}) or {}
    if oid in rj:
        rj[oid]["cleared"] = {"by": by, "at": iso(), "n": n}
    lo = f"last:{sid}"
    if kind == "first" and lo in rj and not rj[lo].get("cleared"):
        # 尾帧是随首帧一起被驳回的：首帧替换版复核通过后，尾帧回到常规自动流程（过契约即设为当前，不再要总调度复核）
        rj[lo]["cleared"] = {"by": by, "at": iso(), "why": f"首帧换成 v{n}（总调度复核），尾帧走常规自动流程"}
        with P.shot_lock(sid):
            d = P.load_takes(sid)
            (d.get("master_gate") or {}).pop("last", None)
            P._save_takes(sid, d)
    js(paths.rejects, rj)
    L = jl(paths.ledger, {}) or {}
    L.setdefault(oid, {}).update(redo_candidate=None, final="passed")
    js(paths.ledger, L)
    log_event(paths, "master_approve", obj=oid, take=n, by=by)
    return 0


def reset_best_effort(paths: Paths, why: str, by: str) -> int:
    """总调度 11-01：门槛 / 编译器更新后，仍是“尽力”的首帧 / 尾帧重新给 3 次（旧次数标 before_gate_change，不算）。
    安全做法：先暂停、等手上的活做完（heartbeat inflight=0，最多 15 分钟），改账本，再恢复原来的暂停状态"""
    was = bool((jl(paths.ctrl, {}) or {}).get("paused"))
    set_paused(paths, True, by="reset-best-effort", kind="restart", expires_s=180)   # K-OPS-E08：运维暂停 ≤180 s
    t_end = now() + 170
    while now() < t_end and int((jl(paths.heartbeat, {}) or {}).get("inflight") or 0) > 0:
        time.sleep(10)
    reg = jl(paths.registry, {}) or {}
    objs = [o for E in reg.get("episodes") or [] for S in E.get("shots") or [] for k, o in (S.get("objects") or {}).items()
            if k in ("first", "last") and o.get("status") == "best_effort" and not o.get("redo")]
    L = jl(paths.ledger, {}) or {}
    for o in objs:
        r = L.setdefault(o["id"], {})
        r.update(tries=0, final=None, demoted_at=iso(), reason=why,
                 history=[dict(h, before_gate_change=True) for h in r.get("history") or []])
    js(paths.ledger, L)
    log_event(paths, "reset_best_effort", n=len(objs), objs=[o["id"] for o in objs], why=why, by=by, counted=False)
    if not was:
        set_paused(paths, False, by="reset-best-effort")
    print("重新给 3 次：", len(objs))
    return 0


def rescore(paths: Paths, items: set) -> int:
    """契约门槛改了（REFLOCK / 总调度 11-01：Q4 只记录、Q5 停“肢体比例”、Q8 只记录）→ 监督出过的、没过的项全在 items 里的版本，
    用新代码重打一次分：不重出、不计内容尝试；重打后过了 → on_contract 设为当前，账本把这次改记为通过"""
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    from ns_render import frame_edit as FE
    from ns_render import auto_current as AC
    from ns_agent import frame_job as FJ
    script = P.load_script()
    project = UF.project_for(script)
    led = jl(paths.ledger, {}) or {}
    n_done = 0
    for tj in sorted(paths.renders.glob("ep*/S*/takes.json")):
        sid = f"{tj.parent.parent.name}-{tj.parent.name}"
        for t in (jl(tj, {}) or {}).get("takes") or []:
            mine = t.get("producer") or (((t.get("params") or {}).get("origin") or {}).get("run") == "PRODUCER")
            pf = t.get("postflight") or {}
            if not mine or t.get("stage") not in ("image", "last") or pf.get("ok") is not False:
                continue
            fails = {i.get("id") for i in pf.get("items") or [] if i.get("status") == "fail"} or set(pf.get("blocking") or [])
            if not score_unmeasured(pf) and (not fails or not fails <= items):
                continue
            ep, shot = P.find_shot(script, sid)
            job = FJ.build_first(project, ep, shot, script.globals)
            new = UF._postflight(t["file"], {"cast": job.get("cast"), "asset_refs": job.get("asset_refs")}, "gpu33")
            if score_unmeasured(new):
                log_event(paths, "score_infra", obj=sid, take=t["n"], error=str(new.get("remote_error"))[:200], counted=False)
                continue
            new["rescored"] = {"at": iso(), "why": "契约门槛改了（Q4 / Q8 只记录、Q5 停肢体比例），用新代码重打，不重出、不计次",
                               "old_blocking": sorted(fails)}
            FE.annotate(sid, t["stage"], t["n"], postflight=new)
            cur = AC.on_contract(sid, t["stage"], t["n"])
            oid = f"{'first' if t['stage'] == 'image' else 'last'}:{sid}"
            r = led.setdefault(oid, {})
            for h in r.get("history") or []:
                if h.get("take") == t["n"]:
                    h.update(ok=bool(new.get("ok")), blocking=new.get("blocking"), rescored=True)
            if new.get("ok"):
                r.update(final="passed", reason=None, last_error=None)
            log_event(paths, "rescore", obj=oid, take=t["n"], old=sorted(fails), ok=new.get("ok"),
                      blocking=new.get("blocking"), current=cur, counted=False)
            n_done += 1
    js(paths.ledger, led)
    print("重打", n_done, "版")
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["serve", "once", "status", "pause", "resume", "dryrun", "rescore", "reject", "approve", "unwait", "reset-best-effort", "import-staged"])
    ap.add_argument("--obj", default="")
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--reason", default="")
    ap.add_argument("--plan", default="frame_v9,frame_v9", help="reject：驳回重出计划（预设，逗号分隔）")
    ap.add_argument("--wait-for", default="")
    ap.add_argument("--items", default="Q4,Q5,Q8", help="rescore：只重打“没过的项全在这里面”的版本")
    ap.add_argument("--only", default="")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--no-dispatch", action="store_true")
    ap.add_argument("--by", default="owner")
    ap.add_argument("--note", default="")
    ap.add_argument("--shots", default="", help="pause：只停这些镜（逗号分隔，默认做法）；不写 = 整条道全局暂停（必须带 --kind）")
    ap.add_argument("--minutes", type=float, default=60, help="pause --shots：多少分钟后自动失效")
    ap.add_argument("--run", default="", help="import-staged：目标剧（config/pipeline/runs.json）；不写 / 主剧 = 合并进主导入稿，其它 = data/import/runs/<run>/")
    ap.add_argument("--kind", default="", choices=["", "ops", "line_switch", "restart", "deploy", "master", "owner"],
                    help="pause 的 reason_kind：line_switch / restart / deploy = 运维暂停（≤180 s 到点恢复）；master / owner = 显式暂停（不自动恢复，超 180 s 报警）；不写按 --by 推断")
    ap.add_argument("--expires-s", type=float, default=0, help="pause：到点自动恢复的秒数（ops 上限 180）")
    ap.add_argument("--inject-fail", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--skip-rubric-gate", action="store_true", help="import-staged：跳过 rubric 导入闸门（只有总调度能批，--by 须写总调度，记审计）")
    a = ap.parse_args(argv)
    run = (a.run or "").strip() or RUN_ID
    if a.cmd != "import-staged":                    # 导入时还没有该剧的导入稿，不能把 ns_render 指过去（rubric 闸门要读主剧结构）
        os.environ.update(run_env(run))             # K-OPS-E15：非主剧进程的渲染 / 导入稿目录（ns_render 在函数里才 import）
    paths = Paths(run_id=run) if a.cmd != "import-staged" else Paths()
    if a.cmd == "serve":
        return serve(paths)
    if a.cmd == "reject":
        return master_reject(paths, a.obj, a.n, a.reason, a.plan.split(","), a.wait_for or None, a.by)
    if a.cmd == "reset-best-effort":
        return reset_best_effort(paths, a.note or "门槛 / 编译器更新后重新给 3 次（总调度 11-01）", a.by)
    if a.cmd == "import-staged":          # 总调度派的整稿导入（走 PRODUCER 令牌通道）：--obj <暂存稿路径> --reason <sha256> --note
        return import_staged(paths, a.obj, a.reason, a.note, a.by, skip_rubric_gate=a.skip_rubric_gate, run=a.run or None)
    if a.cmd == "unwait":                 # 驳回重出在等的前提（如 REFLOCK 修 Q1）满足了 → 放行
        rj = jl(paths.rejects, {}) or {}
        if a.obj in rj:
            rj[a.obj]["wait"] = None
            js(paths.rejects, rj)
            log_event(paths, "unwait", obj=a.obj, by=a.by)
        return 0
    if a.cmd == "approve":
        return master_approve(paths, a.obj, a.n, a.by, a.note)
    if a.cmd == "rescore":
        return rescore(paths, set(a.items.split(",")))
    if a.cmd == "dryrun":
        return dryrun(a.inject_fail, a.keep)
    if a.cmd == "pause" and a.shots:            # K-OPS-E19：默认按镜暂停，不停整条道
        print(json.dumps(pause_shots(paths, [x for x in a.shots.split(",") if x], a.by, a.note, a.minutes), ensure_ascii=False)[:500])
        return 0
    if a.cmd in ("pause", "resume"):
        print(json.dumps(set_paused(paths, a.cmd == "pause", a.by, a.note, kind=a.kind or None, expires_s=a.expires_s or None),
                         ensure_ascii=False))
        return 0
    if a.cmd == "status":
        reg = jl(paths.registry, {}) or {}
        hb = jl(paths.heartbeat, {}) or {}
        print("心跳", hb.get("ts"), "暂停" if reg.get("paused") else "运行中", reg.get("counts"))
        for E in reg.get("episodes") or []:
            print(f"ep{E['ep']:02d}", E.get("headline"))
        return 0
    only = set(x for x in a.only.split(",") if x) or None
    pr = Producer(paths, only=only)
    pr.frames = FrameExec(paths, pr.script())
    reg = pr.tick(dispatch=not a.no_dispatch)
    if a.wait:
        t_end = now() + 3 * 3600
        while now() < t_end:
            pr.wait_idle(3600)
            reg = pr.tick(dispatch=not a.no_dispatch)
            if not pr.inflight:
                busy = [o for E in reg["episodes"] for S in E["shots"] for k, o in S["objects"].items()
                        if k in ("first", "last") and o["status"] in ("ready", "running") and o.get("where") not in ("ASSETMASTER frames_v2",)
                        and (not only or S["shot"] in only)]
                if not busy or all(o["status"] == "ready" and str(o.get("waiting_for") or "").startswith("基础设施退避") for o in busy):
                    if not busy:
                        break
                time.sleep(TICK_S)
    print(json.dumps(reg["counts"], ensure_ascii=False))
    for E in reg["episodes"]:
        print(f"ep{E['ep']:02d}", E["headline"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
