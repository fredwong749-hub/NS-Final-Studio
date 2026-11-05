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

from ns_agent import video_mode as _VM  # noqa: E402  L-197 A：按剧 / 集的“无尾帧（I2VA）”开关

AGENT = "PRODUCER"


def _runs():   # W1 11-03：须在模块级 RUN_ID 求值前定义（_run_id_from_config 用它）
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import runs as RN
    return RN


def _run_id_from_config(default: str = "", root: Path | None = None) -> str:
    """现行主剧。PRODMERGE-O 11-03（PLAN_V2_MASTER v4 1-3）：“当前剧”只认 config/pipeline/runs.json 的 primary
    （tools/autopilot/runs.primary_run）；config/pipeline/run.json 是 runs.sync_run_ptr 派生的指针，只在没有 runs.json 的
    演练目录里兜底读。读不到时给默认值（只为模块能导入），K-OPS-F09 decisions_guard 会在派单前拒派并报警。
    ISS-1103-033310-5833：serve 每拍用 root 参数重读（模块级 RUN_ID 只是导入时的兼容名，不能当“现在该跑哪部剧”）"""
    base = root or Path(__file__).resolve().parents[2]
    try:
        if (base / "config" / "pipeline" / "runs.json").is_file():
            return str(_runs().registry(base).get("primary") or "").strip() or default
        v = json.loads((base / "config" / "pipeline" / "run.json").read_text(encoding="utf-8")).get("run_id")
        return str(v).strip() or default
    except (OSError, ValueError, AttributeError):
        return default


def default_run(root: Path | None = None) -> str:
    """本进程没指定 --run 时做的剧：现读 runs.json（不用导入时的 RUN_ID 缓存）"""
    return _run_id_from_config(root=root)


RUN_ID = _run_id_from_config()
MAX_TRIES = 3                       # GEN_CONTRACT：每镜每阶段内容尝试 ≤3
TICK_S = 20
LEASE_S = 45 * 60                   # 一次出图 + 取回的上限；过期视为失效
INFRA_BACKOFF = (30, 60, 120, 300, 600)
PREFLIGHT_RETRY_S = 30 * 60
# W20（11-03 15:19 受控重启后 7 个“只重打分”单在隧道断时占着 inflight、心跳记成 rendering=7）：
# 只重打分走独立通道——不占道、算 scoring 不算 rendering、有硬时限、打分链路不可用时整体退避（熔断），不无限占位
RESCORE_TIMEOUT_S = int(os.environ.get("NS_PRODUCER_RESCORE_TIMEOUT_S", "900"))   # 一次只重打分最多占位这么久
RESCORE_MAX = int(os.environ.get("NS_PRODUCER_RESCORE_MAX", "3"))                  # 同时在跑的只重打分（含超时后还没回来的）上限
RESCORE_BACKOFF = (300, 600, 1200, 1800, 3600)    # 同一对象连续只重打分没拿到结论：逐级退避
SCORE_CHAIN_COOL_S = 300                          # 打分链路（gpu33 ssh / 共用验收）刚出过错：这么久内不再派只重打分
# W44（11-04 项目方“ep01 都做不出来”→ 无人介入）：② 只重打分每镜每小时 ≤3 次，超了退避 30 分钟（ev=rescore_cap）；
# 看图 health 恢复 loaded 后自动清零（ev=rescore_cap_reset）
RESCORE_HOURLY_MAX = int(os.environ.get("NS_PRODUCER_RESCORE_HOURLY_MAX", "3"))
RESCORE_CAP_BACKOFF_S = 1800
# W44 ①：canary 暂停按“谁、用哪份代码判的”失效：每条结论记 code_sha（本进程启动时 ns_agent + autopilot 的内容 sha）；
# 暂停后 pid / code_sha 变了 → 旧 canary 自动失效并恢复（ev=canary_auto_resume）；到 expires_at → 重评估（ev=canary_reeval）
CODE_SHA_DIRS = ("services/agent/ns_agent", "tools/autopilot")
CANARY_EXPIRE_S = 1800                           # 第一次 canary 暂停 30 分钟后重评估；同一份代码再触发逐次翻倍
CANARY_EXPIRE_MAX_S = 4 * 3600
# W44 ④：坏卡永远 hold（CLAUDE.md 红线）；本机道只在分区登记（退役 / 未到期借道 / 未到期临时 hold）或 lane_notes 显式 held_by 时 hold
BAD_LANES = ("gpu33:2",)      # L-194（11-05）：gpu36:2 归 NS 出图 / 视频，只剩 gpu33:2 坏卡
CODE_RETRY_S = 5 * 60               # 系统代码 / 接口不匹配：5 分钟后再试（多半已热修），不再停 30 分钟         # preflight 不过：资料可能被别的会话补上，30 分钟后再查
# 出图道（gpu36:2 是长镜头视频专用道，不派出图；gpu33 GPU2 永不使用）
IMAGE_LANES = {"gpu33:0": "http://127.0.0.1:18188", "gpu33:1": "http://127.0.0.1:18189", "gpu33:3": "http://127.0.0.1:18191",
               "gpu36:0": "http://127.0.0.1:18288", "gpu36:1": "http://127.0.0.1:18289"}
DEFAULT_CTRL = {"paused": False, "run": None, "hold_lanes": [], "only": [],          # run：ctrl() 按 Paths.run_id 填（不读导入时缓存）
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
    d = {"heavy_plan": ["frame_v9_heavy", "frame_v9_heavy"], "skip_heavy_on": []}
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import policy as POL
        it = POL.item("retry.redo_ladder", ROOT)
        d.update({k: v for k, v in (it.get("value") or {}).items() if k in d})
    except Exception:  # noqa: BLE001
        pass
    return d


def heavy_cannot_fix(led: dict, lad: dict) -> list | None:
    """AUDIT-PERF 11-05：驳回阶梯的重档（frame_v9_heavy = 换 krea2 写实预设）只改画风、不改脸参考约束——日志 11-04/05 重档 26 单只过 1 单
    （10 705 s 出图 + ~26×140 s 打分白耗），其中上次不过项含 Q1（身份）的 11 单全败。retry.yaml redo_ladder.skip_heavy_on = ["Q1", ...]
    时：最后一次失败的不过项与之有交集 → 不排重档、直接标尽力版；返回交集（空 / 开关没开 → None）"""
    skip = {str(x) for x in (lad.get("skip_heavy_on") or [])}
    if not skip:
        return None
    hist = (led.get("redo_history") or []) + (led.get("history") or [])
    last = next((h for h in reversed(hist) if h.get("ok") is False or h.get("blocking")), None)
    hit = sorted(skip & {str(b) for b in (last or {}).get("blocking") or []})
    return hit or None


def job_sig(paths, sid: str) -> str | None:
    """本镜现在编译出的作业签名：提示词 + compiler_inputs_sha + 参考图（路径 + 修改时间）的哈希；作业表里没有 → None"""
    import hashlib
    jobs = (jl(paths.run / "assets" / "first_frame_jobs.json", {}) or {}).get("jobs") or []
    job = next((j for j in jobs if j.get("shot") == sid or j.get("id") == sid), None)
    if not job:
        return None
    parts = [job.get("prompt") or "", str(job.get("compiler_inputs_sha") or "")]
    if job.get("tier_overrides"):        # L-191：首帧档（35 步 base）进签名，缓存的 8 步版不算同一作业；preview 不加段，旧签名不变
        parts.append("tier=" + json.dumps(job["tier_overrides"], sort_keys=True))
    if job.get("prompt_template"):       # 阶段 2.1：提示词模板（v2）进签名；v1 不加段，旧签名不变
        parts.append("template=" + str(job["prompt_template"]))
    if job.get("previz"):                # L-197 B：previz 控制图（深度图 sha）+ 强度 / 结束段进签名；没开 previz 不加段，旧签名不变
        pv = job["previz"]
        parts.append("previz=" + json.dumps({k: pv.get(k) for k in ("sha", "strength", "start_percent", "end_percent")}, sort_keys=True))
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
        if kind == "first" and ((job.get("tier_overrides") or None) != (((t.get("params") or {}).get("tier") or {}).get("overrides") or None)):
            return "出图档变了（预览 8 步 ↔ 35 步 base）"
        if kind == "first" and ((job.get("previz") or {}).get("sha") != (((t.get("params") or {}).get("previz") or {}).get("sha"))):
            return "previz 控制图变了（L-197 B）"
        if kind == "first" and ((job.get("prompt_template") or None) != ((t.get("params") or {}).get("prompt_template") or None)):
            return "提示词模板变了（v1 ↔ v2，阶段 2.1）"
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
    out = {"inputs": job.get("compiler_inputs_sha"), "refs_mtime": round(mt, 1),
           "prompt_sha": hashlib.sha256((job.get("prompt") or "").encode()).hexdigest()[:16]}
    if job.get("tier_overrides"):        # L-191
        out["tier"] = job.get("tier")
    if job.get("prompt_template"):       # 阶段 2.1：模板 v2
        out["template"] = job.get("prompt_template")
    if job.get("previz"):                # L-197 B
        out["previz"] = job["previz"].get("sha")
    return out


_INPUT_SIG_CACHE: dict = {}
INPUT_FIELDS = ("img_prompt", "motion_prompt", "cast_raw", "cast", "scene_id", "scene_detail", "decor_state", "duration")


def input_sig(paths, sid: str) -> str | None:
    """K-REN-956：本镜“剧本输入”签名（导入稿 data/import/script_v2.json 里这一镜的 img / motion / cast / 场景 / 时长）——
    不含编译产物（提示词、参考图列表）。编译规则变了它不变；剧本重新导入、本镜改了它才变"""
    import hashlib
    f = paths.root / "data" / "import" / "script_v2.json"
    try:
        mt = f.stat().st_mtime
    except OSError:   # arch-ok: 读不到导入稿 → None，E24 判“没变”、不重出已通过的帧（保守方向，护栏 17:3x）
        return None
    hit = _INPUT_SIG_CACHE.get(str(f))
    if not hit or hit[0] != mt:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):   # arch-ok: 同上，读坏 → None = 不重出（保守方向）
            return None
        sigs = {}
        for ep in d.get("episodes") or []:
            for sh in ep.get("shots") or []:
                k = f"ep{int(ep.get('number') or 0):02d}-S{sh.get('index')}"
                sigs[k] = hashlib.sha256(json.dumps({x: sh.get(x) for x in INPUT_FIELDS}, ensure_ascii=False,
                                                    sort_keys=True).encode()).hexdigest()[:16]
        hit = _INPUT_SIG_CACHE[str(f)] = (mt, sigs)
    return hit[1].get(sid)


def first_input_changed(paths, sid: str, fo: dict, led: dict) -> dict:
    """K-OPS-E24（总调度 11:3x：第二季等非主剧重新导入后，按 E09 的 job_sig 自动重编、自动重出）：
    首帧 passed 时记过 passed_sig、现在编译出的作业签名不同了 → 回到 ready（不计次，原因“作业输入变了”）。
    没记过 passed_sig（旧数据）不动；项目方定稿锁不动。
    ⤴ K-REN-956（总调度 11-02 17:3x“先验收、后重出”）：只认剧本输入签名（input_sig，passed_input_sig）。编译规则变了
    （提示词 / 参考槽变、作业签名变）不作废已通过的版本——已通过的帧交出图后验收查，查出问题才重出。没记过 passed_input_sig 的旧数据不动
    （剧本真改了由画布摘要的本镜过期标记兜底）"""
    if fo.get("status") != "passed" or fo.get("owner_locked") or not led.get("passed_sig"):
        return fo
    if not led.get("passed_input_sig"):
        return fo
    sig = input_sig(paths, sid)
    if not sig or sig == led["passed_input_sig"]:
        return fo
    return {**fo, "status": "ready", "attempts": 0, "stale": True, "waiting_for": "空闲道",
            "reason": f"v{fo.get('take')} 之后作业输入变了（重新导入 / 重编），自动重出，不算之前的次数"}


def last_consistent(td: dict, fo: dict, lo: dict) -> dict:
    """K-OPS-E13（总调度 11-02 02:2x：以 takes.json 当前版本和契约结果为准，不反过来改 takes）：
    尾帧 passed 但①首帧不是 passed，或②当前尾帧比当前首帧旧（首帧换过）→ 尾帧作废，回到 ready（首帧过了）/ pending（首帧没过），不计次"""
    if lo.get("status") != "passed" or lo.get("na") or lo.get("owner_locked"):
        return lo                    # K-OPS-E23 优先：项目方定稿锁的尾帧不因首帧换版作废（ep01-S1：E13 无视定稿锁 → 新尾帧设不成当前 → 撤回 → 重出，24 小时 108 版）
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
    return int(((reg.get("runs") or {}).get(run) or {}).get("priority", 0 if run == reg.get("primary") else 10))


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


def legacy_run_id(root: Path = ROOT) -> str:
    """K-OPS-F24：统一调 runs.legacy_run（缺 legacy_unprefixed_run 字段 → 抛错，失败关闭；没有登记表的演练目录 = 主剧旧路径）"""
    return _runs().legacy_run(root)


def run_env(run: str, root: Path = ROOT) -> dict:
    """非 legacy 剧的 producer 进程要设的环境变量（在 import ns_render 之前）——K-OPS-F24：primary 切到 V2 也一律带前缀路径。
    PRODMERGE-O：唯一派生处是 tools/autopilot/runs.run_env（没登记的剧 → RunNotRegistered）"""
    return _runs().run_env(run, root)


def apply_owner_edit(job: dict, edit: dict | None) -> dict:
    """L-123：项目方的修改要求（edit.prompt，已改写成中文修改要求并过了禁用词检查）追加到这一单的提示词后面；
    原编译提示词、参考图、槽位一律不动（图N 的对应关系不能乱）。没有 edit → 原样返回"""
    p = str((edit or {}).get("prompt") or "").strip()
    if not p:
        return job
    base = str(job.get("prompt") or "")
    if p in base:
        return job
    return {**job, "prompt": base + "\n项目方要求修改（只改这一点，其余保持不变）：" + p, "owner_edit": (edit or {}).get("id"), "owner_edit_prompt": p}


def episode_order_key(c: tuple) -> tuple:
    """K-OPS-E30（项目方 L-124：每集按 sequence 把图到视频做完，最小的未完成集优先）：派单候选 (集, 0=尾帧/1=首帧, 镜序, 对象) 的排序键
    = (集, 驳回 / 插队优先, 尾帧先, 镜序)。以前驳回 / 插队排在最前面，会跨集插队（后面集的驳回单挤掉 ep01 的活）"""
    ep, k, idx, o = c
    return (ep, 0 if o.get("redo") else 1, k, idx)


def hard_cap_per_stage() -> int:
    """K-OPS-E28：每镜每阶段 24 小时内自动出图的硬上限（config/policies/retry.yaml hard_cap.value.per_stage_24h，默认 10）。
    NS_PRODUCER_HARD_CAP 优先（测试 / 临时）"""
    try:
        v = os.environ.get("NS_PRODUCER_HARD_CAP")
        if not v:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import policy as POL
            v = (POL.item("retry.hard_cap", ROOT).get("value") or {}).get("per_stage_24h")
        return max(1, int(v or 10))
    except Exception:  # noqa: BLE001  # arch-ok: 政策读不到用默认 10（仍然有上限，失败关闭方向）
        return 10


def ts_epoch(s) -> float | None:
    """A-09（V2_READINESS）：时间串 → epoch 秒。带时区（+09:00 / Z / -05:00）按时区换算；不带时区的按项目时区 Asia/Tokyo
    （K-OPS-E18）。以前 E28 直接拿字符串比大小：服务器旧数据有 EST 串、新数据有 +09:00 串，比出来不对"""
    from datetime import datetime, timedelta, timezone
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:   # arch-ok: 格式不认识 = 没有时间，调用方按“不在窗口内”处理
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone(timedelta(hours=9)))
    return d.timestamp()


def stage_renders_24h(takes: dict, stage: str, t: float | None = None) -> int:
    """takes.json 里这一阶段最近 24 小时自动出的版本数（手工编辑 origin=manual_edit 不算）。
    以 takes.json 为准：不受 E09 / E11 / E24 / 驳回各条重置路径影响，进程重启也不丢（E21 的计数在内存里，重启就清零）。
    时间按 ts_epoch 带时区比较（A-09）"""
    since = (t or now()) - 24 * 3600
    return sum(1 for x in takes.get("takes") or [] if x.get("stage") == stage and x.get("origin") != "manual_edit"
               and (ts_epoch(x.get("created_at")) or 0) >= since)


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


def render_timeout_s() -> float:
    """一单出图（含同道前面排队的单）最长等多久。AUDIT-PERF 11-05：unified_frame._run 缺省 900 s 是按 8 步档定的；
    L-191 base35 实测 gpu_s 300–461 s、每道预取 2 单 → 墙钟 600–854 s，再慢一点就超时 → cancel + 整张白算、道冷却。
    NS_PRODUCER_RENDER_TIMEOUT_S 优先；否则 900 × 预取深度（深度 2 = 1800 s，仍小于租约 45 min）"""
    try:
        v = os.environ.get("NS_PRODUCER_RENDER_TIMEOUT_S")
        if v:
            return max(60.0, float(v))
    except ValueError:
        pass
    return 900.0 * max(1, prefetch_depth())


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


def adult_shot_ids(script) -> set:
    """L-128 不变项：剧本里 adult=true 的镜（导入时编译器分类写入）——系统 / agent 不自动派，只由项目方在界面触发"""
    return {sh.id for ep in getattr(script, "episodes", []) or [] for sh in ep.shots if getattr(sh, "adult", None)}


def owner_trigger_ids(paths) -> set:
    """项目方在界面上点了“出这一镜”的对象 id（data/producer[/runs/<run>]/owner_triggers.json {"objects": [...]}）；读不到 = 空（不放行成人镜）"""
    try:
        return set((json.loads((paths.pd / "owner_triggers.json").read_text(encoding="utf-8")) or {}).get("objects") or [])
    except (OSError, ValueError):   # arch-ok: 没有触发记录 = 一个都不放（失败关闭）
        return set()


def is_server_lane(lane: str) -> bool:
    return str(lane).split(":", 1)[0] in ("gpu33", "gpu36") or str(lane).isdigit()


def owner_lane(lane: str) -> bool:
    """L-128（项目方 19:1x）：route=local_only / 剧本标了本地生成的作业只许项目方自有机器的道（笔记本 + gpu33 + gpu36，
    config/factory/hosts.json owner_controlled）；不是自有机器 / 认不出 = False（失败关闭）。取代“服务器一律拦”"""
    import importlib.util as _u
    sp = _u.spec_from_file_location("factory_hosts_prod", ROOT / "tools" / "factory" / "hosts.py")
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m.owner_lane(str(lane))


WAIT_ASSET_MAX_S = 6 * 3600          # 等资产的兜底上限（正常靠签名变化放回，不靠时间）


def asset_sig(paths) -> str:
    """K-OPS-E26：资产登记的签名——preflight（services/agent/ns_agent/asset_refs.py）真正读的登记源：
    config/recipes/asset_refs.json 本身、data/looks/wardrobe.json（单品图），以及配置里每个项目（含继承的父季）登记的
    *_file（P1_looks / assets/sheets_chosen / assets/shot_looks）。设定图 / 单品 / 身份脸一登记，签名就变。只 stat 不读内容"""
    import hashlib
    root = getattr(paths, "root", ROOT)
    cfg_p = root / "config" / "recipes" / "asset_refs.json"
    files = [cfg_p, root / "data" / "looks" / "wardrobe.json"]
    try:
        projs = (json.loads(cfg_p.read_text(encoding="utf-8")).get("projects") or {})
    except (OSError, ValueError):
        projs = {}
    for name in sorted(projs):
        for k, v in sorted((projs.get(name) or {}).items()):
            if k.endswith("_file") and isinstance(v, str):
                files.append(root / v)
    run = getattr(paths, "run", None)                   # 配置里没登记的本 run 资产文件也算上（新剧还没写进配置时）
    if run is not None:
        files += [run / "P1_looks.json", run / "assets" / "sheets_chosen.json", run / "assets" / "shot_looks.json"]
    h = hashlib.sha256()
    for f in dict.fromkeys(files):
        try:
            st = f.stat()
            h.update(f"{f.as_posix()}:{st.st_size}:{st.st_mtime_ns}".encode())
        except OSError:
            h.update(f"{f.as_posix()}:-".encode())
    return h.hexdigest()[:16]


def refs_table_sig(root: Path = ROOT) -> str:
    """期望 refs 表（FACTORY data/factory/inbox/expected_refs.json）的签名：表一重建就变"""
    f = root / "data" / "factory" / "inbox" / "expected_refs.json"
    try:
        st = f.stat()
        return f"{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        return "-"


def wait_kind(err: str) -> str | None:
    """preflight 挡的原因 → 等什么：asset（I3 / I4 缺设定图 / 单品）/ refs（K-OPS-F03 期望表不一致）/ None（别的原因，照旧退避）"""
    if "K-OPS-F03" in err or "refs 与目标状态不一致" in err or "期望 refs 表" in err:
        return "refs"
    if any(k in err for k in ("没有设定图", "没有图", "资产缺图", "I3 ", "I4 ")):
        return "asset"
    return None


def asset_hold_objects(data: Path, run: str | None = None, primary: str | None = None) -> set:
    """IMGFIX r5（总调度 fredw-2b 11-02）：data/autopilot/*_hold.json（active=true）列出的首帧 / 尾帧对象暂缓派单——
    资产（例：V1 女主造型 A 设定图缺袖）修复后等项目方点选，点选前不出图。不在 = 没有 hold；
    文件坏 → K-OPS-F09 decisions_guard 在派单前整体拒派（⤴ 取代“文件坏 = 不挡”）"""
    out: set = set()
    for f in (data / "autopilot").glob("*_hold.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("active"):
            t_now = now()

            def mine(it: dict) -> bool:
                # A-09（V2_READINESS）：hold 按 run 隔离——条目 / 文件写了 run 就只管那部剧；旧条目没写 run 的只管主剧
                # （以前 runaway_hold 全局共用：对象 id 不分季，第一季的暂停把第二季同号镜也挡了；V2 不能继承 V1 的遗留 hold）
                r = it.get("run") or d.get("run")
                return run is None or r == run or (not r and run == primary)
            out |= {o for it in d.get("shots") or [] if mine(it) and not it.get("released")     # B2：释放过的条目（resume / unhold / retry）不再挡
                    and not (it.get("expires_at") and (ts_epoch(it["expires_at"]) or 0) < t_now)
                    and (it.get("expires_at") or hold_alive(None, it.get("at") or it.get("paused_at"), t_now)[0])   # K-OPS-I15：没带 expires_at 的条目挂满 6 h 失效
                    for o in it.get("objects") or []}           # K-OPS-E19：带 expires_at 的条目到期自动失效（A-09：带时区比较）
    return out


class Paths:
    """全部路径集中在这里；dryrun 指向临时目录"""

    def __init__(self, root: Path = ROOT, pd: Path | None = None, run_id: str | None = None):
        self.root = root
        self.data = root / "data"
        self.run_id = run_id or default_run(root)
        run_id = self.run_id                                  # W1 11-03：下面几行用补了默认值的 run_id（原来拿到 None → TypeError）
        self.primary = run_id == legacy_run_id(root)         # K-OPS-F24：只有 legacy_unprefixed_run（series10_v1）用不带前缀的旧路径
        self.pd = pd or (self.data / "producer" if self.primary else self.data / "producer" / "runs" / run_id)
        self.run = self.data / "pipeline" / "runs" / run_id
        self.renders = self.data / "renders" if self.primary else self.data / "renders" / run_id
        self.vid = self.run / "video"
        self.frames_v2 = self.data / "assetmaster" / "frames_v2" / "state.json"
        # C-8（REVIEW_GLOBAL_OPUS）：V2 的声音 / BGM / 合成 / 审片页按剧，不指向 V1 目录（与 series10_video/run_ctx、bgm.deliver 同口径）
        self.voices = root / "config" / ("voices.json" if self.primary else "voices_v2.json")
        self.music = self.data / "music" / ("series10" if self.primary else self.run_id)
        self.eps_out = self.data / "episodes" / ("series10" if self.primary else self.run_id)
        self.review = self.data / "review_pages" / ("series10_video" if self.primary else f"{self.run_id}_video")
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


PROJECT_TZ_H = 9      # K-OPS-E18 / K-OPS-I10：项目时间一律 Asia/Tokyo


def iso(t: float | None = None) -> str:
    """无时区串一律按项目时区（+09:00）写——ts_epoch 把无时区串按 +09:00 读，两边必须同口径。
    AUDIT-PERF 11-05：以前用 time.localtime，Windows 没有 tzset（上面的 TZ 强制只在 Linux 生效）→ 笔记本（美东）写出的
    pause / canary expires_at 早 14 h，ts_epoch 一读就“已过期”（test_producer_b2 / w44 在本机时钟下红的根因）"""
    from datetime import datetime, timedelta, timezone
    return datetime.fromtimestamp(t or now(), timezone(timedelta(hours=PROJECT_TZ_H))).strftime("%Y-%m-%dT%H:%M:%S")


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
            "face_files": face_files_of(slots)}


FACE_KINDS = ("face", "faceboard")    # W20：三人镜三张脸合成一个 faceboard 槽——同样是身份脸槽（preflight I2 口径）


def face_files_of(slots) -> list:
    """槽位里的身份脸文件：face 槽本身 + faceboard 槽的成员（与 preflight I2 files 口径一致）"""
    return [x.file for x in slots if x.kind == "face"] + [m.get("file") for x in slots if x.kind == "faceboard"
                                                          for m in (x.members or []) if m.get("file")]


def faces_only_variant(project, ep, shot, job: dict, plan_kw: dict) -> dict:
    """策略 A：只留脸槽（双人镜两张脸），设定图 / 参考板 / 单品都不挂；服装由正文外层单品句点名（Q2 与外套检查照判）"""
    import copy

    def mk(AR, plan):
        faces = [copy.copy(x) for x in plan.slots if x.kind in FACE_KINDS]
        return faces or None
    return _replan(project, ep, shot, job, plan_kw, mk)


def double_face_variant(project, ep, shot, job: dict, plan_kw: dict) -> dict:
    """策略 B：主角身份脸放两槽（图1、图2 同一张），其余参考顺延，超出槽位的丢掉"""
    import copy

    def mk(AR, plan):
        faces = [x for x in plan.slots if x.kind == "face"]
        if not faces:                      # 只有脸板（三人镜）：不复制脸板，保持默认槽位
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


def lead_char(run_id: str | None) -> str | None:
    """当前剧的主角 char_id（MASTER-WSL 14:14 派 CODER-PS：双人镜 A 版原来写死 V1 女主的 id 与名字）。
    单一来源 = data/pipeline/runs/<run>/P1_storyline.json characters[].role == "主角"（项目方过闸的 P1）；读不到 → None（调用方按默认槽位）"""
    if not run_id:
        return None
    p = ROOT / "data" / "pipeline" / "runs" / str(run_id) / "P1_storyline.json"
    try:
        chars = json.loads(p.read_text(encoding="utf-8")).get("characters") or []
    except (OSError, ValueError):   # arch-ok: 没有 P1（V1 / 演练）= 不认主角，A 版退默认槽位并写 variant_note
        return None
    return next((c.get("char_id") for c in chars if c.get("role") == "主角" and c.get("char_id")), None)


def lead_sheet_variant(project, ep, shot, job: dict, plan_kw: dict, lead: str | None = None) -> dict:
    """双人镜 A 版：两张脸各占一槽 + 第 3 槽固定为主角（lead_char，按 run 的 P1 取）本镜造型设定图（去头）；槽位标注用 asset_refs._line 原样生成"""
    if not lead:
        return {**job, "variant_note": "认不出本剧主角（P1 没有 role=主角），按默认槽位"}
    import dataclasses
    from ns_agent import asset_refs as AR
    sr, plan = AR.plan_for(project, ep, shot, "qwen_image_2.1", **plan_kw)
    if not job["prompt"].startswith(plan.prompt_prefix):
        return job
    # ISS-1103-141532（ep01-S1 三人镜）：三张脸会被 asset_refs 合成一个 faceboard 槽；原来只认 kind=="face"，
    # 脸板被当成非脸丢掉 → 只剩设定图一槽 → preflight I2“露脸的人没有身份脸参考槽”。脸板同样是脸槽，必须保留
    faces = [sl for sl in plan.slots if sl.kind in FACE_KINDS]
    ref = next((r for r in sr.refs if r.role == "sheet" and r.character == lead and r.file), None)
    if ref is None:
        return {**job, "variant_note": "主角造型设定图不在参考里，按默认槽位"}
    if not faces or len(faces) + 1 > plan.capacity:      # K-AST-263 槽位上限：放不下设定图 → 不挤掉脸，保持默认槽位（参考板 B 档），不阻断
        return {**job, "variant_note": f"脸槽 {len(faces)} 个 + 设定图超过 {plan.capacity} 槽上限（或没有脸槽），按默认槽位"}
    if any(sl.kind == "sheet" and sl.character == lead for sl in plan.slots):
        return job
    n = len(faces) + 1
    sl = AR.Slot(n, "sheet", ref.file, lead, ["造型" + (ref.look_id or "") + "设定图"],
                 [{"file": ref.file, "label": ref.label, "role": "sheet", "source": ref.source, "character": lead,
                   "look_id": ref.look_id or next((c.get("look") for c in sr.characters if c.get("character") == lead), None)}])
    sl.line = AR._line(project, sl)
    plan2 = dataclasses.replace(plan, slots=[*faces, sl], prompt_prefix="".join(x.line for x in faces) + sl.line)
    body = job["prompt"][len(plan.prompt_prefix):]
    return {**job, "prompt": plan2.prompt_prefix + body, "refs": plan2.files, "asset_refs": AR.record(sr, plan2),
            "face_files": face_files_of(faces)}


linwan_sheet_variant = lead_sheet_variant      # 旧名兼容（外部脚本 / 旧测试）


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
        VQ.sanitize(v) if v and not v.get("error") else None
        VQ.reask_eye(v, str(P.DATA / file_rel))              # 看镜头结论与证据矛盾 → 只问视线重问一次（总调度 11-02 21:xx）
        VQ.recheck_strangers(pf, str(P.DATA / file_rel))   # K-REV-V14：背影人物的后脑被认成“多出的脸” → 本地看图复核
        VQ.q1_band_review(pf, str(P.DATA / file_rel))      # K-REV-V18 修订：Q1 复核带 → 和 L-086 左右并排的本地看图复核
        VQ.q1a_vlm(pf, str(P.DATA / file_rel))             # K-REV-V19：Q1a 逐人头发——确定性过了再由本地看图逐人问答复核
        VQ.hair_primary(pf, v)                              # 发色：Q1a 分割主判、VLM 辅助（开关 gate.hair_primary）
        VQ.q1x(sid, stage, str(P.DATA / file_rel), pf)      # Q1x 同场跨镜身份一致（开关 Q1x_scene.enabled）
        VQ.q1d(sid, stage, str(P.DATA / file_rel), pf)      # Q1d 本地图片异常检测（记日志、不拦；开关 Q1d_anomaly.enabled，默认关）
        VQ.accept_gate(sid, stage, str(P.DATA / file_rel), pf)   # Q10 出图后验收：身份 / 服装 / 提示词 / 人数四项全过（ALIGNMENT 第 8 步）
        VQ.apply(pf, v)
        if v.get("contradiction") and not v.get("error") and pf.get("ok") is False and pf.get("blocking") == ["Q9"]:
            pf["score_infra"] = True       # 11-04：判词自相矛盾、重问仍未定 = untested，不算 fail、不计重出次数（只重打分）
            pf["remote_error"] = pf.get("remote_error") or "本地看图判词自相矛盾、重问仍未定：" + "、".join(v["contradiction"])
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
        # NETFIX 11-02 18:2x（CONSENT PRODUCER → NETFIX）：takes.json 跟成图在同一镜目录下取——非主剧在 data/renders/<run>/epNN/SN/，
        # 原来写死 data/renders/epNN/SN/takes.json，第二季的 takes 从没进过 outbox（笔记本 98 镜没有 takes.json）
        import re as _re
        mdir = _re.match(r"(renders/(?:[^/]+/)?ep\d{2}/S\d+)/", file_rel or "")
        if mdir:
            takes_rel = f"data/{mdir.group(1)}/takes.json"
        else:                                         # W33：兜底也按本进程的剧取目录，不写死 V1 的 data/renders/epNN/SN
            from ns_render import pipeline as _P, render_paths as _RP
            takes_rel = f"data/{_RP.shot_rel_dir(_P.shot_dir(sid), _P.DATA, _P.RENDERS)}/takes.json"
        OB.write(f"{'first' if stage == 'image' else 'last'}:{sid}", "take",
                 [takes_rel, f"data/{file_rel}"], host=host, root=ROOT)
    except Exception as e:  # noqa: BLE001
        try:
            log_event(Paths(), "outbox_err", obj=f"{stage}:{sid}", take=n, error=repr(e)[:200])
        except Exception:  # noqa: BLE001
            pass


def decision_file_problems(run: str | None = None) -> list[str]:
    """K-OPS-F09：tools/factory/decisions_guard.problems()；校验器自身出错也算问题（失败关闭）"""
    try:
        if str(ROOT / "tools" / "factory") not in sys.path:
            sys.path.insert(0, str(ROOT / "tools" / "factory"))
        import decisions_guard as DG
        return DG.problems(ROOT, run=run)
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


def vlm_health() -> dict:
    """W44 ②：看图服务 health（与 ns_agent.vqa.client 路由同一来源：服务器上先内网 lan_url，再本机 8870）→ {loaded, url}"""
    try:
        from ns_agent.vqa import client as VC
        for u in [x for x in (VC._lan_url(), VC._url()) if x]:
            if VC._local_up(u):
                h = VC._HEALTH.get(u) or {}
                if h.get("loaded"):
                    return {"loaded": True, "url": u, "queue": h.get("queue")}
        return {"loaded": False}
    except Exception as e:  # noqa: BLE001  # arch-ok: 探不到 = 不清零（保持退避），原因带回
        return {"loaded": False, "error": repr(e)[:160]}


def lane_held(lane: str) -> bool:
    """LOCALGPU：render_endpoints 里 hold=true 的道（就绪、等总调度开派）按 hold_lanes 处理"""
    try:
        from ns_render import endpoints as EP
        return EP.held(lane)
    except Exception:  # noqa: BLE001
        return False


_CODE_SHA: dict = {}


def code_sha(root: Path = ROOT, dirs=CODE_SHA_DIRS, fresh: bool = False) -> str:
    """W44 ①：本进程代码的内容 sha（*.py 相对路径 + 内容，排序后 sha256 前 16 位）。按 root 缓存 = 进程启动时算一次：
    之后磁盘上热推了新文件，这个值不变（进程没加载就不算新代码），重启后才变"""
    import hashlib
    key = str(root)
    if key in _CODE_SHA and not fresh:
        return _CODE_SHA[key]
    h = hashlib.sha256()
    for d in dirs:
        base = Path(root) / d
        for f in sorted(base.rglob("*.py")) if base.is_dir() else []:
            if "__pycache__" in f.parts:
                continue
            try:
                h.update(f.relative_to(root).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
            except OSError:
                h.update(f.as_posix().encode() + b"\0?\0")
    _CODE_SHA[key] = h.hexdigest()[:16]
    return _CODE_SHA[key]


def canary_key(paths: "Paths", version: str | None = None, pid: int | None = None, sha: str | None = None) -> str:
    """W44 ①：canary 计数的版本键 = 规则 / 资产版本 + 本进程 code_sha + pid + 重评估轮次（control.canary_epoch）。
    旧进程 / 旧代码判的结论不进新进程的计数；到点重评估换一轮，从头数 6 镜"""
    if version is None:
        from ns_agent.vqa import canary as CN
        version = CN.version_key()
    ep = int((jl(paths.ctrl, {}) or {}).get("canary_epoch") or 0)
    return f"{version}+{sha or code_sha()}+p{pid or os.getpid()}+e{ep}"


def canary_tick(paths: "Paths", pid: int | None = None, sha: str | None = None, t: float | None = None) -> dict | None:
    """W44 ①：producer 每拍（在 pause_tick 之前）处理 kind=canary 的暂停 → None 或 {action, why}。
    · 暂停记录没有 pid / code_sha（W44 前的旧 canary），或与本进程不同 → 结论出自旧进程 / 旧代码：自动恢复（canary_auto_resume）
    · 同一进程同一份代码、到 expires_at → 重评估：canary_epoch+1（新一轮 6 镜从头数）并恢复（canary_reeval）；
      再触发时暂停时长翻倍（canary_strikes），最多 4 小时——不会永久停着等人"""
    c = jl(paths.ctrl, {}) or {}
    if not c.get("paused") or c.get("reason_kind") != "canary":
        return None
    pid, sha, t = pid or os.getpid(), sha or code_sha(), now() if t is None else t
    meta = c.get("canary") or {}
    why = None
    if not meta.get("pid") or not meta.get("code_sha"):
        why = "暂停记录没有 pid / code_sha（W44 之前的 canary，判定代码无法核对），按旧代码结论失效"
    elif str(meta.get("code_sha")) != sha:
        why = f"判定时代码 {meta.get('code_sha')} ≠ 现在加载的 {sha}（热修 / 换代后重启），旧结论失效"
    elif int(meta.get("pid")) != int(pid):
        why = f"判定进程 pid {meta.get('pid')} 已不是本进程 {pid}（重启过），旧结论失效，新进程重新数"
    if why:
        set_paused(paths, False, by="CANARY_AUTO_RESUME", note=why)
        c2 = jl(paths.ctrl, {}) or {}
        c2.update(canary_epoch=int(c2.get("canary_epoch") or 0) + 1, canary_strikes=0)
        js(paths.ctrl, c2)
        log_event(paths, "canary_auto_resume", why=why, was=meta or None, pid=pid, code_sha=sha, counted=False)
        return {"action": "canary_auto_resume", "why": why}
    exp = ts_epoch(c.get("expires_at"))
    if exp is not None and t >= exp:
        why = f"canary 暂停到点（{c.get('expires_at')}）：换一轮重新数 {meta.get('n') or 6} 镜再判（同一份代码再触发会暂停更久）"
        set_paused(paths, False, by="CANARY_REEVAL", note=why)
        c2 = jl(paths.ctrl, {}) or {}
        c2.update(canary_epoch=int(c2.get("canary_epoch") or 0) + 1, canary_strikes=int(c.get("canary_strikes") or 0) + 1)
        js(paths.ctrl, c2)
        log_event(paths, "canary_reeval", why=why, was=meta, strikes=c2["canary_strikes"], counted=False)
        return {"action": "canary_reeval", "why": why}
    return None


def canary_pause(paths: "Paths", hit: dict, pid: int | None = None, sha: str | None = None) -> dict:
    """W44 ①：canary 触发 → 暂停（kind=canary）并记下判定进程 pid / code_sha；暂停时长 30 分钟 × 2^strikes（≤4 小时）"""
    pid, sha = pid or os.getpid(), sha or code_sha()
    strikes = int((jl(paths.ctrl, {}) or {}).get("canary_strikes") or 0)
    exp_s = min(CANARY_EXPIRE_S * (2 ** strikes), CANARY_EXPIRE_MAX_S)
    c = set_paused(paths, True, by="POLICY_CANARY", kind="canary", expires_s=exp_s,
                   note=f"换版首批复核：前 {hit['n']} 镜 {hit['item']} 不过占 {hit['frac']:.0%}（{'、'.join(hit['shots'])}），"
                        f"版本 {hit['version']}；判定 pid {pid} code_sha {sha}，{int(exp_s // 60)} 分钟后重评估")
    c["canary"] = {"pid": pid, "code_sha": sha, "version": hit.get("version"), "item": hit.get("item"), "n": hit.get("n"),
                   "shots": hit.get("shots"), "at": iso()}
    js(paths.ctrl, c)
    return c


def partition_held(part: dict, t: float | None = None) -> set:
    """W44 ④：分区里真正该 hold 的道（与 tools/netfix/dispatch.held_lanes 同口径，含其修正）：
    retired_lanes 里有对应借道 / 临时 hold 记录的，以记录的到期时间为准（tools/debug/lanes.py hold() 两处都写，
    到期后 sweep 没跑，retired_lanes 里那条就永远 hold——11-04 02:40 ASSET-WORKER 的 gpu33:0 就是这样）；
    没有记录的 retired_lanes = 真退役；坏卡永远 hold"""
    t = now() if t is None else t

    def alive(v) -> bool:
        u = (v or {}).get("until") or (v or {}).get("expires_at")
        e = ts_epoch(u) if u else None
        return True if not u or e is None else e > t      # 没写 / 写坏到期时间 = 还在（失败关闭）
    rec = {}
    for f in ("_lent_lanes", "_temp_holds"):
        for k, v in (part.get(f) or {}).items():
            rec[k] = rec.get(k, False) or alive(v)
    out = {ln for ln in part.get("retired_lanes") or [] if ln not in rec}
    out |= {k for k, a in rec.items() if a}
    return out | set(BAD_LANES)


def hold_alive(expires_at, since, t: float | None = None) -> tuple[bool, str]:
    """K-OPS-I15：hold 带 expires_at → 到点失效；没带 → 写入时刻起超 6 h 失效；写入时刻也没有 = 有效（失败关闭）。实现在 hold_expiry.py"""
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hold_expiry as HX
    return HX.alive(expires_at, since, now() if t is None else t)


def effective_holds(ctrl: dict, lanes, part: dict | None, t: float | None = None) -> tuple[set, dict]:
    """W44 ④（K-OPS-N04“hold = 别的机器的道”）：control.json hold_lanes 是 dispatch.py 某一刻的快照（02:25 写的 gpu33:0 临时 hold
    02:40 到期后没人重算，ep01 一度只剩 1 条道）。本机（dispatch_by.host）的道只在分区仍登记 hold、或 lane_notes 写了 held_by
    （人工显式 hold）时才 hold；别的机器的道照 hold；坏卡永远 hold。读不到分区 / 不知道本机 = 原样照 hold（失败关闭）。
    → (hold 集合, {放开的道: 原因})"""
    hold = set(ctrl.get("hold_lanes") or []) | set(BAD_LANES)
    host = ((ctrl.get("dispatch_by") or {}).get("host")) or None
    if not part or not host or host == "laptop":
        return hold, {}
    mine = set((part.get("lanes") or {}).get(host) or [])
    keep = partition_held(part, t)
    notes = ctrl.get("lane_notes") or {}
    released, expired = {}, {}
    # K-OPS-I15（SLIM-CDE 11-05）：人工显式 hold（lane_notes[道].held_by）必须带 expires_at；没带的挂满 6 h 自动忽略（写入时刻取 note.at / since）
    for ln, nt in list(notes.items()):
        if isinstance(nt, dict) and nt.get("held_by") and ln in hold and ln in mine:
            ok, why = hold_alive(nt.get("expires_at"), nt.get("at") or nt.get("since"), t)
            if not ok:
                notes = {**notes, ln: {k: v for k, v in nt.items() if k != "held_by"}}
                expired[ln] = f"lane_notes.held_by 失效：{why}"
    for ln in sorted(hold):
        if ln in mine and ln not in keep and not (notes.get(ln) or {}).get("held_by"):
            hold.discard(ln)
            released[ln] = (f"本机（{host}）的道，分区 partition.json 已不再 hold（退役 / 借道 / 临时 hold 都没有或已到期），"
                            f"control.json 的 hold 是 dispatch {(ctrl.get('dispatch_by') or {}).get('at')} 的旧快照")
    released.update({k: v for k, v in expired.items() if k in released})
    return hold, released


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


L183_ITEMS = ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9")


def q19_clean(pf: dict) -> bool:
    """L-183：Q1–Q9 全过（pass；na 也算——Q9 的 na 须看图模型真看过 = evidence.model，与 sop_gate._q9_pass 同口径）。
    Q1、Q9 必须有（没打分 / 没看图的版本不算）"""
    st = {i.get("id"): i for i in (pf or {}).get("items") or []}
    if "Q1" not in st or "Q9" not in st:
        return False
    for q in L183_ITEMS:
        it = st.get(q)
        if it is None:
            continue
        s = it.get("status")
        if s == "pass" or (s == "na" and (q != "Q9" or (it.get("evidence") or {}).get("model"))):
            continue
        return False
    return True


def review_pick(td: dict, stage: str, ns: set | None = None) -> int | None:
    """L-183：这一阶段（只看 ns 里的版本，None = 全部）Q1–Q9 全过、没被驳回 / 标坏的版本里 score_key 最高的一版"""
    c = [t for t in td.get("takes") or [] if t.get("stage") == stage and (ns is None or t.get("n") in ns)
         and not t.get("bad") and not t.get("master_reject") and q19_clean(take_pf(t))]
    return max(c, key=lambda t: score_key(take_pf(t)))["n"] if c else None


def safe_take(pf: dict) -> bool:
    """L-196 兜底采用：没有成人安全 / 文字水印硬项不过（身份 / 人数不过的最好一版允许采用，标 review_needed）"""
    for i in (pf or {}).get("items") or []:
        if i.get("status") in ("fail", "untested") and i.get("id") in ("Q6", "Q9", "QB") and not i.get("record_only"):
            ev = i.get("evidence") or {}
            if i.get("id") == "Q6" or "underage_look" in (ev.get("defects") or []) or (ev.get("label") or {}).get("age") == "fail"                     or (ev.get("label") or {}).get("ocr") == "fail":
                return False
    return True


def review_pick_relaxed(td: dict, stage: str, ns: set | None = None) -> int | None:
    """L-196：重试用尽、没有 Q1–Q9 全过的版本时，取没被驳回 / 标坏、成人安全与文字水印没挡的版本里 score_key 最高的一版"""
    c = [t for t in td.get("takes") or [] if t.get("stage") == stage and (ns is None or t.get("n") in ns)
         and not t.get("bad") and not t.get("master_reject") and t.get("file") is not None and safe_take(take_pf(t))]
    return max(c, key=lambda t: score_key(take_pf(t)))["n"] if c else None


def review_adopt(paths: "Paths", oid: str, n: int | None = None, by: str = "L-183 自动", ns: set | None = None,
                 relaxed: bool = False) -> int | None:
    """L-183（总调度 11-04 04:2x / 05:0x，项目方“不卡整集”）：尽力用尽不再排除出拼接——取 Q1–Q9 全过里分数最高的一版设为当前，
    postflight 标 review_needed=true 并改 ok=true（原结论留 ok_before_review / blocking_before_review，审片可见），
    这样尾帧 / 出图检测 / 视频编单都按“过”往下走；V2_LIVE 记“待项目方复核”。没有 Q1–Q9 全过的版本 → None（照旧尽力）"""
    from ns_render import pipeline as P
    kind, sid = oid.split(":", 1)
    stage = "image" if kind == "first" else "last"
    td = P.load_takes(sid)
    if n is None:
        n = review_pick(td, stage, ns) or (review_pick_relaxed(td, stage, ns) if relaxed else None)
    t = next((x for x in td.get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None) if n else None
    if t is None or not (q19_clean(take_pf(t)) or (relaxed and safe_take(take_pf(t)))):
        return None
    note = {"by": by, "at": iso(), "rule": "L-183", "why": "尽力用尽，取 Q1–Q9 全过里分数最高的一版，待项目方复核"}

    def _mark(d):
        for x in d.get("takes") or []:
            if x.get("stage") == stage and x.get("n") == n:
                pf = x.get("postflight") if isinstance(x.get("postflight"), dict) else take_pf(x)
                if pf.get("review_needed"):
                    return
                pf.update(ok_before_review=pf.get("ok"), blocking_before_review=list(pf.get("blocking") or []),
                          ok=True, blocking=[], review_needed=True, review=note)
                x["postflight"] = pf
    P.mutate_takes(sid, _mark, op="review_adopt", by=f"producer（{by}）")
    P.set_active(sid, stage, n, reason=f"L-183 尽力用尽取 v{n}（Q1–Q9 全过），待项目方复核", actor=f"producer.review_adopt（{by}）")
    log_event(paths, "review_adopt", obj=oid, take=n, by=by, counted=False)
    try:
        promote_live(paths.root, f"W38/L-183：{oid} 尽力用尽 → 取 v{n}（Q1–Q9 全过、分数最高）设为当前，待项目方复核 {sid}")
    except Exception:  # noqa: BLE001  # arch-ok: V2_LIVE 写不进去不挡（takes.json review_needed 是权威）
        pass
    return n


# ---------------------------------------------------------------------------------------------- 状态推导
class World:
    """一次快照：把各处真实记录读进来（每轮重读）"""

    def __init__(self, paths: Paths, script=None, shots_filter: set | None = None):
        self.p = paths
        self.script = script
        self.filter = shots_filter
        self.procs = python_procs() if paths.root == ROOT else []
        self.fv2 = fv2_for_run(paths, jl(paths.frames_v2, {}) or {})   # W33：全局 frames_v2 按镜号存 → 只留本剧的尝试 / final
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
                if not fv2_proc_run_ok(self.p, c):   # W33：frames_v2 是 V1 专用工具（--run 只许 legacy）——不把 V2 的集标成 ASSETMASTER 在做
                    continue
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
                          waiting_for="项目方挑定身份参考（characters 闸门）" if gate else "资产登记 / 期望 refs 表一更新就自动放回重查",
                          gate="characters" if gate else None)
            elif pfb and not pfb.get("ok"):
                ao.update(status="failed", reason="出图前契约没过：" + "；".join(pfb.get("reasons") or [])[:200], waiting_for="资料补齐后自动重查")
            else:
                ao.update(status="passed" if io_["status"] == "passed" else "pending",
                          reason="参考槽位齐（出图前再查一次 preflight）" if io_["status"] == "passed" else None)
            # 首帧 / 尾帧
            stl = stale_requeue_map((sm or {}).get("stale") or {})   # 剧本 / 输入改了：画布摘要的过期标记（与 /api/shots 同源）；K-REN-956 去掉编译变化
            fo = _frame_obj("first", "image", sid, n, td, fv, ledger, leases, canvas, n in fv2_eps, deps_ok=ao["status"] == "passed",
                            stale=stl.get("image"))
            lo = _frame_obj("last", "last", sid, n, td, fv, ledger, leases, canvas, n in fv2_eps, deps_ok=fo["status"] == "passed",
                            first=fo, stale=stl.get("last"))
            fo = first_input_changed(w.p, sid, fo, ledger.get(f"first:{sid}") or {})   # K-OPS-E24：重新导入后作业变了 → 重出
            if _VM.no_last(w.p.run_id, n, w.p.root):  # L-197 A：本集视频只用首帧（I2VA）→ 尾帧对象 = 不适用（不创建 / 不派 / 不评分 / 不挡视频）
                lo = {**obj("last", sid, ep=n, shot=sid), "status": "passed", "na": True, "i2va_no_last": True,
                      "reason": "L-197：视频只用首帧（I2VA），不出尾帧", "attempts": 0, "max_attempts": None}
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
            vo_.update(status="pending", waiting_for="VOICE10 定本剧演员表（config/voices.json series=<本剧>）",
                       where="VOICE10")
        bo = obj("bgm", f"ep{n:02d}", ep=n)
        if (p.music / f"ep{n:02d}.wav").exists():
            bo.update(status="passed", reason=f"data/music/series10/ep{n:02d}.wav")
        else:
            bo.update(status="pending", waiting_for="BGM10 出本集配乐（缺时合成用 --no-bgm，不挡成片）", where="BGM10", optional=True)
        ao_ = obj("assembly", f"ep{n:02d}", ep=n)
        night_ep = (w.night.get("eps") or {}).get(str(n)) or {}
        finals = sorted((f for f in (p.eps_out.glob(f"ep{n:02d}_v*.mp4") if p.eps_out.is_dir() else [])
                         if f.stem.rsplit("_v", 1)[-1].isdigit()), key=lambda f: int(f.stem.rsplit("_v", 1)[-1]))   # 按版本号取最新
        final = finals[-1] if finals else p.eps_out / f"ep{n:02d}_v1.mp4"     # W44 ③：night finalize 出 ep01_vN（N 递增），不只认 v1
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
        if final.exists():                       # W44 ③：与 sop_gate“整集预览”同一口径——night finalize 的 epNN_vN.mp4 就是整集预览
            po.update(status="passed", reason=str(final.relative_to(p.root)).replace("\\", "/"))
        elif (p.review / f"ep{n:02d}" / "index.html").exists():
            po.update(status="passed", reason=str((p.review / f"ep{n:02d}" / "index.html").relative_to(p.root)).replace("\\", "/"))
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


# K-REN-956（PROMPTFIX × DEBUG-RSI 11-02，总调度定“先验收、后重出”）：编译规则变化（编译器升级 / 系统固定句变了）不作废已通过的版本；
# 只有本镜输入真改了（剧本 / 提示词 / 造型 / 首帧 / 参考覆盖）才算过期重出。已通过的帧由出图后验收（站位核对、服装验收）查，
# 查出问题的走验收失败重出，不走过期。
STALE_NO_REQUEUE = ("编译器升级", "编译规则", "系统固定句")


STALE_REQUEUE_ON = ("提示词已改", "导演加强已改", "本集加强已改", "剧本已改")


def stale_requeue_reasons(v) -> list[str]:
    """过期标记（列表 / 字符串 / True）→ 会触发重出的原因。
    护栏（总调度 11-02 17:3x，ALIGNMENT 第 8 步）：白名单——只有人主动改的（STALE_REQUEUE_ON）才把已通过版本放回重出；
    编译器升级、本镜输入已改（站位句 / 参考槽调整也会落在这里）、造型已改、不明原因（True）一律不重出，已通过的交验收判，
    验收不过才重出（否则 sv-14 一上线约 56 镜被无谓重出）"""
    if not v or isinstance(v, bool):
        return []
    items = v if isinstance(v, (list, tuple)) else [v]
    return [str(x) for x in items if any(w in str(x) for w in STALE_REQUEUE_ON)]


def stale_requeue_map(st: dict) -> dict:
    out = {}
    for k, v in (st or {}).items():
        r = stale_requeue_reasons(v)
        if r:
            out[k] = "、".join(r) if not isinstance(v, bool) else True
    return out


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
    if rj.get("regen"):                    # B2：换代中——旧当前版保留（视频 / 合成仍可用），新版过闸前不清空
        ot = active_take(td, "image" if kind == "first" else "last")
        o.update(reason="换代中：" + str(rj.get("reason")), regen=True)
        if ot and take_pf(ot).get("ok"):
            o["regen_keep"] = f"v{ot['n']}"
    lease = leases.get(oid)
    if lease:
        return {**o, "status": "running", "where": lease.get("lane"), "reason": o["reason"] + "；" + str(lease.get("rung"))}
    if led.get("redo_candidate") and rj.get("regen"):
        return {**o, "status": "pending",
                "waiting_for": "换代版 v{} 已过契约，等看图闸门 / 复核后换成当前（旧当前版仍有效）".format(led["redo_candidate"])}
    if led.get("redo_candidate"):
        return {**o, "status": "pending",
                "waiting_for": "总调度复核替换版 v{}（已过契约；驳回版 v{} 已撤下，这一镜暂无当前版本）".format(led["redo_candidate"], rj.get("reject_n"))}
    if rj.get("wait"):
        return {**o, "status": "pending", "waiting_for": rj["wait"]}
    if kind == "last" and first and first.get("redo") and not first.get("regen_keep"):
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
        if st in ("done", "best_effort") and fo["status"] != "passed" and not fo.get("regen_keep"):
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
    if (fo["status"] != "passed" and not fo.get("regen_keep")) or lo["status"] not in ("passed", "best_effort"):
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
             (("first", "首帧", "过契约"), ("last", "尾帧", "过契约"), ("video", "视频", "已定下"))
             if not (kind == "last" and shots and all(S["objects"]["last"].get("i2va_no_last") for S in shots))]   # L-197：无尾帧集不显示尾帧计数
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

    script_fn = None                            # 类默认：绕过 __init__ 构造（测试 / 子类）时也有该属性
    def __init__(self, paths: Paths, script, script_fn=None):
        self.p, self._script = paths, script
        self.script_fn = script_fn              # B2：每次出图现取最新导入稿（Producer.script 按 sha / mtime 热重载）；None = 固定稿
        self.post_pool = cf.ThreadPoolExecutor(max_workers=3, thread_name_prefix="producer-postflight")

    @property
    def script(self):
        if self.script_fn is not None and script_hot_reload(self.p.root):
            return self.script_fn()
        return self._script

    @script.setter
    def script(self, v):
        self._script = v

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
        if rung.get("variant") == "faces_look" and kind == "first":   # 双人镜 A 版：两张脸 + 主角本镜造型设定图（第 3 槽）
            first_job = lead_sheet_variant(project, ep, shot, first_job, rung.get("plan_kw") or {}, lead=lead_char(self.p.run_id))
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
                             "asset_refs": AR.record(sr, plan2), "face_files": face_files_of(plan2.slots)}
        owner_edit = ((jl(self.p.rejects, {}) or {}).get(f"{kind}:{sid}") or {}).get("edit")
        if kind == "first":
            job = apply_owner_edit(first_job, owner_edit)
            dl = vqa_delta(sid, "image")        # VQAGATE：上一版看图没过 → 套用写作网关给的一维修正（K-REN-V05）
            if dl:
                from ns_agent.vqa import judge as VJ
                job = {**job, "prompt": VJ.apply_delta(job["prompt"], dl), "vqa_delta": dl}
            job = {**job, "lane": lane}                    # K-REN-958：preflight I12 按道判本地专用资产
            trig = owner_trigger_ids(self.p)
            if job.get("adult") and not ({f"first:{sid}", f"{self.p.run_id}/first:{sid}"} & trig):   # L-128：成人资产 → 等项目方触发
                raise ComfyError(f"{sid} 生成契约 preflight 不通过，未提交：成人画面资产（{'；'.join(job.get('adult_reasons') or [])[:160]}）"
                                 "只由项目方在界面触发，producer 不自动派")
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
            job = apply_owner_edit(job, owner_edit)
            if rung.get("preset"):
                job["preset"] = rung["preset"]
            if rung.get("variant") == "double_face" and job.get("face_files"):     # 策略 B（尾帧）：身份脸再放一槽
                f0 = job["face_files"][0]
                k = len(job["refs"]) + 1
                job = {**job, "refs": [*job["refs"], f0],
                       "prompt": f"图{k}是同一人的脸部参考（与图2同一张，加强身份，只取脸和发型）。" + job["prompt"]}
            if job.get("route") == "local_only" and not owner_lane(lane):   # K-REN-958 × L-128：只许项目方自有机器的道
                raise ComfyError(f"{sid} 生成契约 preflight 不通过，未提交：I12 本地专用资产只许项目方自有机器的道（{'；'.join(job.get('route_reasons') or [])[:200]}）")
            stage = "last"
        job = {**job, "seed_policy": rung.get("seed_info") or "producer"}  # K-REN-954：种子来源进 compile_trace
        take = UF._run(client, sid, stage, job, rung["seed"], timeout_s=render_timeout_s())[0]   # REFLOCK 11-01 起返回 (take, eff, post_rec)
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
                # W41（11-04）：host_path 不在本机（笔记本上跑 producer）时同时给本机交付图 file——远端打分仍按 host_path 读原始输出
                # （full_score：有 host_path 不上传），postflight_full 在本进程里跑的 G1 视线 / Q9 看图改读 file；以前笔记本上
                # cv2.imread 服务器路径 → G1“读不到图”、Q9 看不到图。服务器上 host_path 就在本机，行为不变
                from ns_render import pipeline as P
                local = {} if Path(host_path).is_file() else {"file": str(P.DATA / file_rel)}
                d = RS.postflight_full("gpu33", [{"id": "x", "host_path": host_path, **local,
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
        if not pf.get("score_infra"):
            if not accept_run_qb(self.p.root):
                mark_qb_skipped(pf, why="L-196 全自动：QB 只记录不挡，不再整张再看一遍（accept.run_qb=false；人数 / 文字 / 年龄已由 Q10 / Q6 / Q9 覆盖）")
            elif pf.get("ok") is False and accept_skip_prefailed(self.p.root):
                mark_qb_skipped(pf)                 # AUDIT-PERF 11-05：已判不过的图不再做共用验收（开关 accept.skip_prefailed）
            else:
                pf = shared_accept(self.p, self.script, sid, file_rel, job, pf)   # PRODMERGE-O：共用验收（bundle + retry 三态）
        pf = apply_blocking_policy(pf)            # L-196：只有 gen_contract.json blocking_items 里的硬项挡，其余只记录
        pf["code_sha"] = code_sha()               # W44 ①：每条结论记“哪份代码判的”（本进程启动时的内容 sha）
        pf["judged_pid"] = os.getpid()
        try:                                     # canary_after_redo：换版后前 6 镜同一阻断项失败 > 34% → 暂停派单（kind=canary）
            from ns_agent.vqa import canary as CN  # W44 ①：只数本进程 / 本代码的结论；pid / code_sha 变了自动恢复，到点重评估
            _ign = canary_ignore_items(self.p.root)
            _pfc = {**pf, "blocking": [b for b in pf.get("blocking") or [] if b not in _ign]} if _ign else pf
            hit = CN.observe(sid, stage, _pfc, key=canary_key(self.p, CN.version_key()))
            if hit:
                canary_pause(self.p, hit)
        except Exception as e:  # noqa: BLE001 — canary 出错不挡出图，但要记
            log_event(self.p, "canary_err", obj=f"{stage}:{sid}", error=repr(e)[:200])
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
        from ns_render import render_paths as RP     # W33：带剧名前缀（原来写死 renders/epNN/SNN 落进 V1 目录）
        rel = f"{RP.shot_take_rel_dir(sid)}/{stage}_{n:03d}.png"
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
NIGHT_STALE_S = 1200          # W44 ③：night_state.json 这么久没更新 = night 不在跑（resident health A-RESIDENT-NIGHT 同一口径 20 分钟）


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
            NT = self._night_mod()
            if self._night_state is None:
                self._night_state = jl(NT.STATE, None) or {"eps": {}, "pending_shots": {}, "started": time.time()}
            try:
                NT.loop_once(self._night_state)
            except Exception as e:  # noqa: BLE001
                logf("video_err", error=repr(e)[:300], kind=classify(repr(e)))
            return
        why = self.night_stalled(reg, night_alive) if ctrl.get("video_takeover", True) else None
        if why:
            self.takeover(why, logf)

    def _night_mod(self):
        """night.py 按 NS_RUN 定剧（import 时求值）：本进程第一次 import 前钉成本剧；已 import 成别的剧 → 拒绝（不跨剧出片）"""
        os.environ.setdefault("NS_RUN", self.p.run_id)
        import night as NT  # noqa: PLC0415
        if getattr(NT, "RUN_ID", self.p.run_id) != self.p.run_id:
            raise RuntimeError(f"night 模块已按 {NT.RUN_ID} 加载，不替 {self.p.run_id} 出片")
        return NT

    def night_stalled(self, reg: dict, night_alive: bool, t: float | None = None) -> str | None:
        """W44 ③ 阶段自动接力：有镜首尾帧都定下、视频 ready（等派），但本机没有 night 进程、night_state.json 不在或
        ≥ NIGHT_STALE_S 没更新 → 视频段没人接（W18 lifecycle 只在整集阶段 ≥ 尾帧才起 night，一镜卡住全集视频都等）。
        → 原因（producer 接手跑 night.loop_once）；None = 不用接"""
        if night_alive:
            return None
        t = now() if t is None else t
        # 总调度 05:1x（W38 落地）：只接本机分区里的集——partition.json video 把这一集分给本机（OFFLINE_SELF）才接手，
        # 否则会和分区主机的 night 抢（ep01 视频现归 gpu36，gpu33 不能起 night）。笔记本（无 OFFLINE_SELF）/ 分区读不到 = 不接
        me = os.environ.get("OFFLINE_SELF")
        try:
            part = self._night_mod().partition_hosts() if me else {}
        except Exception:  # noqa: BLE001  # arch-ok: 分区读不到 = 不接手（失败关闭，不和别的机器抢）
            part = {}
        mine = {int(e) for e, h in (part or {}).items() if h == me}
        ready = [S["shot"] for E in reg.get("episodes") or [] if int(E.get("ep") or 0) in mine for S in E.get("shots") or []
                 if ((S.get("objects") or {}).get("video") or {}).get("status") == "ready"]
        if not ready:
            return None
        sp = self.p.vid / "night_state.json"
        age = t - sp.stat().st_mtime if sp.exists() else None
        if age is not None and age < NIGHT_STALE_S:
            return None
        return (f"{len(ready)} 镜视频等派（{'、'.join(ready[:6])}{'…' if len(ready) > 6 else ''}），本机没有 night 进程，"
                f"night_state {'不存在' if age is None else f'{round(age / 60)} 分钟没更新'}：producer 接手跑 night.loop_once")

    def takeover(self, why: str, logf) -> bool:
        """后台线程跑一轮 night.loop_once（单飞：上一轮没完不再起；不挡 producer 主循环）。night 进程一出现就自动停（night_stalled=None）"""
        th = getattr(self, "_takeover_th", None)
        if th is not None and th.is_alive():
            return False
        if why != getattr(self, "_takeover_why", None):
            self._takeover_why = why
            logf("video_takeover", why=why, counted=False)

        def run():
            try:
                NT = self._night_mod()
                if self._night_state is None:
                    self._night_state = jl(NT.STATE, None) or {"eps": {}, "pending_shots": {}, "started": time.time()}
                NT.loop_once(self._night_state)
            except Exception as e:  # noqa: BLE001
                logf("video_err", error=repr(e)[:300], kind=classify(repr(e)), takeover=True)
        self._takeover_th = threading.Thread(target=run, name="producer-night-takeover", daemon=True)
        self._takeover_th.start()
        return True


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
    _relay_hold_fn = None
    relay_lanes: set = frozenset()      # 类默认：测试用 object.__new__ 绕过 __init__ 构造时也有（AUDIT-PERF 11-05，test_debug_rsi e17）

    def __init__(self, paths: Paths | None = None, *, script=None, frames=None, video=None, lanes: dict | None = None,
                 lane_probe=None, only: set | None = None, run_summary_fn=None, train_locks_fn=None, lock_now_fn=None):
        self.p = paths or Paths()
        self.p.pd.mkdir(parents=True, exist_ok=True)
        self.leases = Leases(self.p)
        self._script = script
        self.frames = frames
        self.video = video or VideoBridge(self.p)
        self.lanes = lanes if lanes is not None else {**IMAGE_LANES, **render_image_only_lanes()}
        self.relay_lanes: set = set()
        if lanes is None:                          # 跨机借道（CODER-XH 11-05，config/pipeline/lane_relay.json 默认关）：gpu33 producer 经笔记本代理用 gpu36:0
            if str(Path(__file__).resolve().parent) not in sys.path:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
            import lane_relay as LR
            self._relay_hold_fn = LR.runtime_hold
            rl = LR.consumer_lanes()
            self.lanes.update(rl)
            self.relay_lanes = set(rl)
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
        self.rescoring: set[str] = set()           # W20：只重打分的对象（不占道；心跳算 scoring，不算 rendering）
        self._rescore_futs: dict[str, cf.Future] = {}   # 对象 → 只重打分的 future（超时放位后仍留着，回来前不重派、占上限）
        self._score_down_until = 0.0               # W20：打分链路熔断到（这之前不派只重打分）
        self.rescore_pool = cf.ThreadPoolExecutor(max_workers=max(2, RESCORE_MAX + 2), thread_name_prefix="producer-rescore")
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
        mt = self._mtime()
        if self._script is None or self._script_mtime != mt:
            from ns_render import pipeline as P
            old = self._script is not None
            self._script = P.load_script()
            self._script_mtime = mt
            sha = self._script_sha()
            if old and sha != getattr(self, "_script_sha_v", None):     # B2：导入稿变了 → 热重载，不用重启（以前 FrameExec 手里的旧稿 → find_shot KeyError）
                try:
                    self.logf("script_reloaded", old_sha=getattr(self, "_script_sha_v", None), new_sha=sha, counted=False)
                except Exception:  # noqa: BLE001  # arch-ok: 日志写不进不挡重载
                    pass
            self._script_sha_v = sha
        return self._script

    def _script_sha(self):
        import hashlib
        from ns_render import pipeline as P
        try:
            return hashlib.sha256(Path(P.SCRIPT_JSON).read_bytes()).hexdigest()[:16]
        except OSError:  # arch-ok: 读不到 = 无签名，不触发热重载（保持旧稿，下一拍再试）
            return None

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
        c["run"] = self.p.run_id
        st = run_status(self.p.root, self.p.run_id)
        if st == "preparing":
            st = self.maybe_promote() or st          # PRODMERGE-O：preparing → producing 只按 sop_gate.promote（与阶段模型同一规则）
        if st and st != "producing" and not c.get("paused"):
            # K-OPS-F20（总调度 11-02 17:0x）：暂停状态只有一个来源 = runs.json 的 status。control.json 会被 dispatch 重算覆盖
            # （16:07 gpu36 第二季 control 被改回 paused=false，暂停后又派单），所以每拍都按 runs.json 判，不靠 control 里的字段
            c.update(paused=True, paused_by="runs.json", reason_kind="owner", note=f"config/pipeline/runs.json status={st}")
        return c

    def maybe_promote(self, every_s: float = 60) -> str | None:
        """runs.json status=preparing 时每分钟问一次 sop_gate.promote_check：
        有一集已可进“出图” → config/pipeline/sop_gate.json promote.auto=true 才真的写 producing（status_history 留痕）并返回 "producing"；
        auto=false 只记日志“可以提升”（由总调度 sop_gate.py promote --apply）。返回新状态或 None"""
        if now() - getattr(self, "_promote_t", 0) < every_s:
            return None
        self._promote_t = now()
        try:
            SG = sop_gate_mod(self.p.root)
            auto = bool((SG.config(self.p.root).get("promote") or {}).get("auto"))
            res = SG.promote(self.p.run_id, self.p.root, by="auto:producer.maybe_promote", apply=auto)   # W18：status_history 记 auto
        except Exception as e:  # noqa: BLE001  # arch-ok: 判不了 = 保持 preparing（暂停，失败关闭）
            self.logf("promote_err", error=repr(e)[:200], counted=False)
            return None
        if res.get("applied"):
            self.logf("run_promoted", run=self.p.run_id, why=res.get("why"), counted=False, rule="PRODMERGE-O / sop_gate.promote")
            promote_live(self.p.root, f"✅ 自动提升（producer.maybe_promote，L-154）：{self.p.run_id} preparing → producing，{res.get('why')}")
            return "producing"
        if res.get("promote") and getattr(self, "_promote_logged", None) != res.get("episodes"):
            self._promote_logged = res.get("episodes")
            self.logf("promote_ready", run=self.p.run_id, episodes=res.get("episodes"), counted=False,
                      note="sop_gate 判定可提升 producing；promote.auto=false，等总调度 sop_gate.py promote --apply")
        return None

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

    def heal_lanes(self, every_s: float = 60) -> list:
        """GPU 道卡死自愈（tools/autopilot/lane_heal.py，MASTER-WSL 11-03 ASSIGN D）：每 every_s 秒一拍。
        锁：train_locks_cached（None = 读不到）；卡上进程 / 占用：GET /api/gpu3/gpus（gpu_monitor，5 s 缓存，只有 gpu33）"""
        if now() - getattr(self, "_heal_at", 0.0) < every_s:
            return []
        try:                                       # 演练 / 测试（临时目录的 producer）不碰真实道、不写 data/producer
            Path(self.p.pd).resolve().relative_to((ROOT / "data").resolve())
        except (ValueError, AttributeError, OSError):
            return []
        self._heal_at = now()
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("lane_heal_p", ROOT / "tools/autopilot/lane_heal.py")
            LH = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(LH)  # type: ignore[union-attr]
            lanes = LH.all_lanes()
            locks: dict = {}
            for srv in sorted({lane_split(l)[0] for l in lanes}):
                try:
                    got = train_locks_cached(srv)
                except Exception:  # noqa: BLE001  # arch-ok: 读锁出错 = 读不到，交 lane_heal 计时登记
                    got = None
                for l in lanes:
                    if lane_split(l)[0] == srv:
                        locks[l] = None if got is None else (lane_split(l)[1] in got)
            gpus: dict = {}
            try:
                with urllib.request.urlopen(os.environ.get("NS_API", "http://127.0.0.1:8800") + "/api/gpu3/gpus", timeout=10) as r:
                    for g in (json.loads(r.read()).get("gpus") or []):
                        gpus[f"gpu33:{g.get('id')}"] = {"procs": [str(p.get("cmdline") or p.get("cmd") or "") for p in g.get("processes") or []],
                                                        "util": g.get("util")}
            except Exception:  # noqa: BLE001  # arch-ok: 读不到卡信息只跳过“过期锁”判定
                gpus = {}
            acts = LH.tick(lanes, gpus=gpus or None, locks=locks)
            for a in acts:
                self.logf("lane_heal", **{k: v for k, v in a.items() if k != "event"}, heal_event=a.get("event"))
            return acts
        except Exception as e:  # noqa: BLE001  # arch-ok: 自愈出错不挡出图主循环，原因进日志
            self.logf("lane_heal_err", error=repr(e)[:200])
            return []

    # -- 一轮 --
    def tick(self, dispatch: bool = True) -> dict:
        try:
            canary_tick(self.p)                    # W44 ①：旧进程 / 旧代码的 canary 自动失效；到点重评估（在 pause_tick 之前）
        except Exception as e:  # noqa: BLE001
            self.logf("canary_tick_err", error=repr(e)[:200])
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
        self.auto_regen_tick(w)
        led_all = {**self.ledger(), "_master_rejects": jl(self.p.rejects, {}) or {}}
        reg = derive(w, led_all, leases, self.run_summary_fn())
        lanes = self.probe_lanes(ctrl)
        try:
            self.reap_rescores()                   # W20：超时的只重打分放位（暂停时也照做，不让心跳一直挂着 inflight）
        except Exception as e:  # noqa: BLE001
            self.logf("rescore_reap_err", error=repr(e)[:300])
        self.heal_lanes()                          # ASSIGN D：卡死道自愈（定向打断自己 / 孤儿的超时单；过期锁、读不到锁登记）
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
                    self.release_waiting_assets()      # K-OPS-E26：等资产的对象签名一变就放回
                except Exception as e:  # noqa: BLE001
                    self.logf("asset_release_err", error=repr(e)[:300])
                try:
                    self.adopt_best_effort_sweep(reg)  # L-196：用尽停在 best_effort 的自动取最高分版
                except Exception as e:  # noqa: BLE001
                    self.logf("be_adopt_err", error=repr(e)[:300])
                try:
                    self.auto_reset_best_effort(reg)   # K-OPS-E11：尽力版在规则 / 资产版本变化时自动重置
                except Exception as e:  # noqa: BLE001
                    self.logf("be_reset_err", error=repr(e)[:300])
                try:
                    self.escalate_exhausted(reg)  # K-OPS-E09：驳回阶梯用完的对象自动定下一步（不停下等人）
                except Exception as e:  # noqa: BLE001
                    self.logf("escalate_err", error=repr(e)[:300])
                try:
                    self.rescore_cap_reset()           # W44 ②：看图 health 恢复 loaded → 封顶的只重打分清零
                except Exception as e:  # noqa: BLE001
                    self.logf("rescore_cap_reset_err", error=repr(e)[:300])
                try:
                    self.dispatch_rescores(reg)        # W20：只重打分独立派（不要空闲道、熔断 + 上限 + 退避）
                except Exception as e:  # noqa: BLE001
                    self.logf("rescore_dispatch_err", error=repr(e)[:300])
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
        js(self.p.heartbeat, {"ts": iso(), "t": now(), "pid": os.getpid(), "paused": reg["paused"],
                              **self.hb_counts(),                    # K-OPS-F12：重启队列只等 rendering=0
                              **self.identity()})                    # ISS-1103-033310-5833：心跳带 run 身份（为哪部剧在跑、从哪读的）
        sig = json.dumps([[(o["id"], o["status"], o.get("attempts")) for S in E["shots"] for o in S["objects"].values()]
                          for E in reg["episodes"]] + [reg["paused"]], ensure_ascii=False)
        if sig != self.last_sig:
            self.last_sig = sig
            js(self.p.mirror, {"updated": reg["updated"], "counts": reg["counts"], "paused": reg["paused"],
                               "note": "PRODUCER 状态变了（live.py 据此推 stage 事件，界面重取 /api/producer/status）"})
        return reg

    def hb_counts(self) -> dict:
        """心跳口径：inflight = 全部在途；scoring = 出好等打分 + 只重打分（W20：只重打分不占道，不算 rendering）；
        rendering = 真在出图道上的"""
        with self.mu:
            scoring_n = len(self.scoring) + len(self.rescoring)
            return {"inflight": len(self.inflight), "scoring": scoring_n, "rescoring": len(self.rescoring),
                    "rendering": max(0, len(self.inflight) - scoring_n)}

    def auto_reset_best_effort(self, reg, every_s: float = 300) -> dict:
        """K-OPS-E11（总调度 11-02 02:2x / DISTILL gates.best_effort_policy）：尽力版（不进合成）在规则或资产版本变化时自动重置、
        重新进正常流程，不计次。第一次见到尽力版只记下当时的依据（be_basis），之后依据变了才重置。资产暂缓清单里的不动。每 5 分钟查一次"""
        if now() - getattr(self, "_be_check_t", 0) < every_s:
            return {}
        self._be_check_t = now()
        rule = be_rule_sig(self.p.root)
        held = asset_hold_objects(self.p.data, self.p.run_id, default_run(self.p.root))
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

    def adopt_best_effort_sweep(self, reg, every_s: float = 120) -> list:
        """L-196（项目方 11-05“全自动”）：已经停在 best_effort（重试用尽）的首 / 尾帧，review_adopt_auto 开时自动取最高分版设为当前
        （标 review_needed，下游照常往下走）；与主循环用尽那一刻同口径，补上开关打开之前就已停下的对象。每 2 分钟查一次"""
        if now() - getattr(self, "_ba_check_t", 0) < every_s or not review_adopt_auto(self.p.root):
            return []
        self._ba_check_t = now()
        done = []
        for E in reg.get("episodes") or []:
            for S in E["shots"]:
                for k in ("first", "last"):
                    o = S["objects"][k]
                    led = self.ledger().get(o["id"]) or {}
                    if o.get("status") != "best_effort" or led.get("final") != "best_effort" or (led.get("tries") or 0) < MAX_TRIES:
                        continue
                    r = review_adopt(self.p, o["id"], by="L-196 自动", relaxed=True)
                    if r:
                        self.led_update(o["id"], final="passed", hard_capped=None,
                                        reason=f"L-196 重试用尽，自动取最高分 v{r} 设为当前，待项目方复核")
                        self.logf("passed", obj=o["id"], take=r, review_needed=True, rule="L-196", via="adopt_sweep")
                        done.append(o["id"])
        return done

    def release_waiting_assets(self, every_s: float = 60) -> list:
        """K-OPS-E26：等资产的对象，资产登记签名或期望 refs 表签名变了 → 清退避、回到 ready（不计次）。每分钟查一次"""
        if now() - getattr(self, "_wa_check_t", 0) < every_s:
            return []
        self._wa_check_t = now()
        asig, rsig = asset_sig(self.p), refs_table_sig(self.p.root)
        out = []
        for oid, r in list(self.ledger().items()):
            wa = r.get("waiting_asset") if isinstance(r, dict) else None
            if not wa or not r.get("blocked_until"):
                continue
            changed = (wa.get("kind") == "asset" and wa.get("asset_sig") != asig) or \
                      (wa.get("kind") == "refs" and (wa.get("refs_sig") != rsig or wa.get("asset_sig") != asig))
            if changed:
                self.led_update(oid, blocked_until=0, waiting_asset=None,
                                reason=("资产登记有更新" if wa.get("kind") == "asset" else "期望 refs 表 / 资产有更新") + "，自动放回重派（不计次）")
                sid = oid.split(":", 1)[-1]
                if (self.ledger().get(f"assets:{sid}") or {}).get("blocked"):
                    self.led_update(f"assets:{sid}", blocked=False, released_at=now())
                self.logf("asset_release", obj=oid, kind=wa.get("kind"), counted=False)
                out.append(oid)
        return out

    def hard_capped(self, o: dict, cap: int | None = None) -> bool:
        """K-OPS-E28（总调度 FOCUS #2）：每镜每阶段 24 小时内自动出图到上限 → 不派、转人工 / 本地修、开工单。
        各条重置路径（E09 阶梯重置、E11 尽力版重置、E24 输入变化、驳回重出）都只重置“阶梯次数”，不重置这里的计数；
        只有人工 `producer.py uncap --obj X --n N` 能多放 N 次（24 小时有效）"""
        kind, sid = o["id"].split(":", 1)
        if kind not in ("first", "last"):
            return False
        from ns_render import pipeline as P
        stage = "image" if kind == "first" else "last"
        td = P.load_takes(sid)
        n = stage_renders_24h(td, stage)
        led = self.ledger().get(o["id"]) or {}
        lim = cap or hard_cap_per_stage()
        if n < lim:
            return False
        ex = led.get("cap_extra") or {}
        if ex and now() - float(ex.get("t") or 0) < 24 * 3600:
            # uncap = 放行之后再出 N 版（以前写成“上限 + N”，108 版的镜放 3 次等于没放；ep01-S1 17:00 实测）
            since = float(ex.get("t") or 0)
            after = sum(1 for x in td.get("takes") or [] if x.get("stage") == stage and x.get("origin") != "manual_edit"
                        and (ts_epoch(x.get("created_at")) or 0) >= since)
            if after < int(ex.get("n") or 0):
                return False
            lim = n
        hc = led.get("hard_capped") or {}
        if now() - float(hc.get("t") or 0) > 24 * 3600 or int(hc.get("lim") or 0) != lim:
            self.led_update(o["id"], hard_capped={"t": now(), "at": iso(), "n": n, "lim": lim},
                            reason=f"24 小时内已自动出 {n} 版（硬上限 {lim}），停止自动重出，转人工 / 本地修（K-OPS-E28）")
            sentinel_ticket(self.p, o["id"], f"重出硬上限：{stage} 24 小时 {n} 版（上限 {lim}），已停止自动重出，转人工 / 本地修",
                            {"renders_24h": n, "cap": lim}, led)
            self.logf("hard_cap", obj=o["id"], renders_24h=n, cap=lim, counted=False)
        return True

    def obj_rate_exceeded(self, o: dict, cap: int = 8) -> bool:
        """K-OPS-E21（总调度 08:0x P0：ep05-S3 出到第 82 版、S7 46 次，计次没拦住）：同一对象最近 1 小时派单 ≥ cap →
        写 data/autopilot/runaway_hold.json（按镜暂停，reason_kind=runaway，6 小时到期）+ SENTINEL 工单，这一单不派"""
        t = now()
        hist = self.__dict__.setdefault("_obj_disp", {})
        recent = [x for x in hist.get(o["id"], []) if t - x <= 3600]
        hist[o["id"]] = recent
        f = self.p.data / "autopilot" / "runaway_hold.json"
        d = jl(f, {}) or {}
        rel = max([float((it.get("released") or {}).get("t") or ts_epoch((it.get("released") or {}).get("at")) or 0) for it in d.get("shots") or []
                   if it.get("shot") == o["shot"] and it.get("released")] or [0])
        if rel:                                         # B2：人工释放（retry / unhold）之前的派单不再计数
            recent = hist[o["id"]] = [x for x in recent if x > rel]
        if len(recent) < cap:
            return False
        items = {it.get("shot"): it for it in d.get("shots") or [] if not it.get("released")}
        if o["shot"] not in items:
            exp = iso(t + 6 * 3600)
            items[o["shot"]] = {"shot": o["shot"], "run": self.p.run_id, "objects": [f"first:{o['shot']}", f"last:{o['shot']}"], "expires_at": exp,
                                "why": f"1 小时内派了 {len(recent)} 次（上限 {cap}）", "at": iso()}
            d.update(active=True, reason_kind=d.get("reason_kind") or "runaway",
                     shots=[it for it in d.get("shots") or [] if it.get("released")] + list(items.values()),   # 释放记录保留历史
                     rule="K-OPS-E21 单对象出图速率超限自动暂停；到期（expires_at）自动失效")
            f.parent.mkdir(parents=True, exist_ok=True)
            js(f, d)
            sentinel_ticket(self.p, o["id"], f"单对象出图速率超限：1 小时 {len(recent)} 次（上限 {cap}），已自动按镜暂停",
                            {"per_hour": len(recent), "cap": cap}, self.ledger().get(o["id"]) or {})
            self.logf("runaway_hold", obj=o["id"], per_hour=len(recent), cap=cap, counted=False)
        return True

    def regen_auto_approve(self, oid: str, n: int, pf: dict) -> bool:
        """B2：换代版（master_rejects[oid].regen）过了契约，且看图闸门没开（开了的由 auto_review_redo 管）→ 自动换成当前"""
        try:
            rj = (jl(self.p.rejects, {}) or {}).get(oid) or {}
            if not rj.get("regen"):
                return False
            from ns_agent.vqa import contract as VQ
            if VQ.enforced():
                return False
            return master_approve(self.p, oid, n, "REGEN", f"换代版过契约（{rj.get('reason')}）") == 0
        except Exception as e:  # noqa: BLE001
            log_event(self.p, "regen_auto_approve_err", obj=oid, take=n, error=repr(e)[:200], counted=False)
            return False

    def auto_regen_tick(self, w, every_s: float = 60) -> dict | None:
        if not dispatch_ok_cfg(self.p.root) or now() - getattr(self, "_last_regen_chk", 0) < every_s:
            return None
        self._last_regen_chk = now()
        try:
            shots = shots_of_all(self.p)
            r = auto_regen_check(self.p, shots)
            if r.get("regen"):
                self.logf("auto_regen", shots=r["regen"], counted=False)
            return r
        except Exception as e:  # noqa: BLE001
            self.logf("auto_regen_err", error=repr(e)[:200], counted=False)
            return None

    def uncount_dispatch(self, oid: str) -> None:
        """把最近一次派单时刻从 obj_rate 计数里去掉（派单后在出图前就失败 = 没占 GPU）"""
        with self.mu:
            h = self.__dict__.setdefault("_obj_disp", {}).get(oid)
            if h:
                h.pop()

    def escalate_exhausted(self, reg) -> dict:
        """K-OPS-E09 驳回阶梯（config/policies/retry.yaml redo_ladder，decider=code）：
          ① 还在资产暂缓清单（*_hold.json）→ 继续等；
          ② 最后一次失败之后输入变了（提示词 / 参考图集合 / 参考图文件更新 / 编译输入哈希）→ 重置驳回次数，counted=false，原因“输入已更新”；
          ③ 输入没变 → 下一级：追加 frame_v9_heavy 换 seed ×2（只追加一次）；
          ④ 再不过 → 标尽力版（不进合成）+ 给 SENTINEL 开工单（附失败原因统计）。"""
        held = asset_hold_objects(self.p.data, self.p.run_id, default_run(self.p.root))
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
                    elif not led.get("ladder_plan") and not heavy_cannot_fix(led, lad):
                        plan = [plan_item(x) for x in lad["heavy_plan"]]
                        self.led_update(oid, ladder_plan=plan, ladder_sig=sig, reason="驳回重出用完、输入没变 → 下一级：" + "、".join(lad["heavy_plan"]))
                        self.logf("redo_escalate", obj=oid, counted=False, plan=lad["heavy_plan"])
                        out["heavy"] += 1
                    else:
                        stats = fail_stats(led)
                        skipped = heavy_cannot_fix(led, lad) if not led.get("ladder_plan") else None
                        why = (("重档跳过：上次不过项 " + "、".join(skipped) + " 换预设救不回（retry.redo_ladder.skip_heavy_on）；") if skipped else "") +                               "驳回阶梯走完仍没过（" + "、".join(f"{a}×{b}" for a, b in stats.items()) + "），标尽力版，不进合成"
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
        part = jl(self.p.root / "config" / "netfix" / "partition.json", None)
        hold, released = effective_holds(ctrl, self.lanes, part)     # W44 ④：本机道的过期 hold 快照不再挡派单
        rel_sig = json.dumps(released, sort_keys=True, ensure_ascii=False)
        if released and rel_sig != getattr(self, "_hold_rel_sig", None):
            self.logf("hold_stale_release", lanes=sorted(released), why=released, dispatch_at=(ctrl.get("dispatch_by") or {}).get("at"),
                      counted=False)
        self._hold_rel_sig = rel_sig if released else None
        hold |= {ln for ln in self.lanes if lane_held(ln)}
        hold -= self.relay_lanes                 # 借道：别机的道（dispatch 照“别的机器的道”hold）在开关打开时归本机用；坏卡仍 hold
        hold |= set(BAD_LANES)
        if self.relay_lanes and self._relay_hold_fn:
            hold |= self._relay_hold_fn(self.relay_lanes)       # 阶段交接：出图 → 视频，借道还给 gpu36 本机（data/pipeline/lane_relay_hold.json）
        out = {}
        for ln, url in self.lanes.items():
            q = self.lane_probe(url)
            mine = list(self.lane_busy.get(ln) or [])
            cool = self.lane_cool.get(ln, 0)
            srv, idx = lane_split(ln)
            locks = set() if ln in self.relay_lanes else self.train_locks_fn(srv)   # 借道：gpu36 的训练锁本机读不到（服务器不互连）；开借道前由人确认 gpu36:0 无训练
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
        dprobs = decision_file_problems(self.p.run_id)     # 按本进程的剧查（V2 资产包模式要求不同）
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
        cands.sort(key=episode_order_key)        # K-OPS-E30（L-124）：集号从小到大、集内驳回 / 插队先、尾帧先、按镜号
        held = asset_hold_objects(self.p.data, self.p.run_id, default_run(self.p.root))
        rate_cap = int(os.environ.get("NS_PRODUCER_OBJ_PER_HOUR", "8"))
        try:
            local_only = local_only_shots(self.script())
            adult_shots = adult_shot_ids(self.script())
            owner_triggers = owner_trigger_ids(self.p)
        except Exception:  # noqa: BLE001  读不到剧本 = 失败关闭：这一拍不派
            self.logf("local_only_unknown", counted=False)
            return
        for _ep, _k, _i, o in cands:
            if o["shot"] in local_only and not any(owner_lane(ln) for ln in free):   # K-OPS-E22 × L-128：只拦非自有机器
                if o["id"] not in self.__dict__.setdefault("_local_only_logged", set()):
                    self._local_only_logged.add(o["id"])
                    self.logf("local_only_skip", obj=o["id"], counted=False, why="剧本 H3校验 标了本地生成 / 占位，空闲道都不在项目方自有机器上")
                continue
            if o["shot"] in adult_shots and o["id"] not in owner_triggers:   # L-128 不变项：成人画面只由项目方在界面触发
                if o["id"] not in self.__dict__.setdefault("_adult_wait_logged", set()):
                    self._adult_wait_logged.add(o["id"])
                    self.logf("adult_wait_owner", obj=o["id"], counted=False, why="成人画面：等项目方在界面触发（系统 / agent 不自动派）")
                continue
            try:
                if self.hard_capped(o):                  # K-OPS-E28：每镜每阶段 24 小时硬上限，到了就停、转人工 / 本地修
                    continue
            except Exception as e:  # noqa: BLE001  # arch-ok: 计数读不到 = 这一单不派（失败关闭），记日志
                self.logf("hard_cap_err", obj=o["id"], error=repr(e)[:200], counted=False)
                continue
            if self.obj_rate_exceeded(o, rate_cap):      # K-OPS-E21：同一对象 1 小时出图超过上限 → 自动按镜暂停 + 工单
                continue
            if self._dispatch_only and o["shot"] not in self._dispatch_only:
                continue
            if o["id"] in held:                  # IMGFIX r5：资产修复待点选的造型（data/autopilot/*_hold.json）暂缓派单
                continue
            if self.sop_gate_block(o):           # HARNESS-O / PRODMERGE-O：SOP 阶段闸门按镜挡（首帧 = 出图、尾帧 = 尾帧）
                continue
            if not free:
                break
            led = self.ledger().get(o["id"]) or {}
            if led.get("rescore_take") or o.get("rescore_take"):   # 只重打分归 dispatch_rescores（W20），这里不派、不占道
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
        self.dispatch_fanout(cands, free)

    def sop_gate_block(self, o: dict) -> bool:
        """派单前按镜过 SOP 闸门（HARNESS-O 的 require 下沉到 producer 派单，PRODMERGE-O）：首帧 = “出图”、尾帧 = “尾帧”。
        legacy 剧直接放行；observe 阶段只记违规；enforce 没过 → 本拍不派（不计次），10 分钟记一次日志"""
        try:
            SG = sop_gate_mod(self.p.root)
            m = re.search(r"ep(\d+)-S(\d+)", o["shot"])
            if not m:
                raise ValueError(f"镜号认不出：{o['shot']}")
            ep, n = int(m.group(1)), int(m.group(2))
            # W8 / A1-5：走 sop_gate.require_backoff（与 asset_worker 同一实现）——judge 只读判定，同一集同一缺口签名退避期内
            # 不再写违规（observe 照样放行、enforce 照样挡）；原来每拍每个候选都 require → observe 下每分钟几十条 violations
            r = SG.require_backoff(self.p.run_id, ep, "出图" if o["kind"] == "first" else "尾帧", shot=n, root=self.p.root, by="producer")
            if r.get("allow"):
                return False
            raise SG.SopGateError(r.get("error") or "SOP 闸门未过")
        except Exception as e:  # noqa: BLE001  # arch-ok: SopGateError / 判不了 = 不派（失败关闭）
            k = f"_sop_logged_{o['id']}"
            if now() - getattr(self, k, 0) > 600:
                setattr(self, k, now())
                self.logf("sop_gate_block", obj=o["id"], why=str(e)[:300], counted=False)
            return True

    def fanout_ok(self) -> int:
        """一镜多种子分道（原 golden_worker 调度，PRODMERGE-O）：每个对象最多同时几个在途种子；0/1 = 关（老行为：一对象一道）"""
        f = producer_cfg(self.p.root)["fanout"]
        if not f.get("enabled") or (f.get("runs") and self.p.run_id not in f["runs"]) or self.p.primary:
            return 1
        return max(1, int(f.get("max_per_obj") or 1))

    def dispatch_fanout(self, cands: list, free: list) -> None:
        """派完“一对象一道”以后还有空闲道：给已在途的首帧对象再派种子（每道一个，先铺满每个对象再叠第二个），
        种子走同一个种子流（seed_pick 跳过 takes.json 用过的 + 本对象在途的），每个种子算一次尝试（≤ MAX_TRIES）。
        额外在途记在 inflight["<对象>#<k>"]；结果由 _run_one 照常写 takes.json（帧只记一本账）"""
        cap = self.fanout_ok()
        if cap <= 1 or not free:
            return
        progress = True
        while free and progress:
            progress = False
            for _ep, _k, _i, o in cands:
                if not free:
                    break
                if o["kind"] != "first" or o["id"] not in self.inflight:
                    continue
                with self.mu:
                    mine = [k for k in self.inflight if k == o["id"] or k.startswith(o["id"] + "#")]
                if len(mine) >= cap:
                    continue
                led = self.ledger().get(o["id"]) or {}
                attempt = max(int(led.get("tries") or 0), int(o.get("attempts") or 0)) + len(mine) + 1
                if attempt > MAX_TRIES or led.get("final") == "passed":
                    continue
                key = f"{o['id']}#{attempt}"
                lane = free.pop(0)
                rung = self.rung_strategy(o, attempt, led) or self.rung_ab(o, attempt) or self.rung(o, attempt)
                rung = {**rung, "name": rung["name"] + "（分道并行）", "fanout": key}
                from ns_agent import comfy_tag as CT
                tag = CT.make(AGENT, "first_frame", episode=o["ep"], shot=o["shot"].split("-")[1], label=f"自动制作 {rung['name']}",
                              attempt=attempt, max_attempts=MAX_TRIES, obj=o["id"], job=key)
                with self.mu:
                    self.lane_busy.setdefault(lane, []).append(key)
                    self.inflight[key] = {"lane": lane, "since": now(), "fanout_of": o["id"]}
                self.logf("dispatch", obj=o["id"], lane=lane, attempt=attempt, rung=rung["name"], seed=rung["seed"], fanout=key,
                          comfy_tag=tag)
                self.pool.submit(self._run_one, o, lane, attempt, rung, tag)
                progress = True

    def seed_pick(self, o: dict, attempt: int, salt: str = "", legacy_key: str | None = None) -> tuple[int, dict | None]:
        """K-REN-954 种子流（ns_render.seed_stream）：这一镜这一 stage 用过的种子一律跳过，重试永不复用；开关 promptfix.seed_stream"""
        from ns_render import pipeline as P
        from ns_agent import asset_refs as AR
        if not AR.pf_on("seed_stream"):
            return P.seed_for(legacy_key or f"{o['shot']}/producer/{o['kind']}", attempt), None
        from ns_render import seed_stream as SS
        stage = "image" if o["kind"] == "first" else "last"
        try:
            takes = (P.load_takes(o["shot"]) or {}).get("takes") or []
        except Exception:  # noqa: BLE001
            takes = []
        return SS.pick(o["shot"], stage, attempt, takes, salt=salt)

    def rung(self, o: dict, attempt: int) -> dict:
        """自修阶梯：1 默认 → 2 换 seed → 3 换参考（双人镜两张脸各占一槽；单人镜再换 seed）"""
        from ns_render import pipeline as P
        seed, sinfo = self.seed_pick(o, attempt)
        if attempt == 1:
            return {"name": "第 1 次（frame_v9 默认）", "seed": seed, "seed_info": sinfo}
        if attempt == 2:
            return {"name": "第 2 次：换 seed", "seed": seed, "seed_info": sinfo}
        plan_kw = {}
        name = "第 3 次：再换 seed"
        try:
            _ep, shot = P.find_shot(self.script(), o["shot"])
            if sum(1 for c in shot.cast if getattr(c, "presence", None) == "在画") >= 2:
                plan_kw = {"two_person": "both_faces"}
                name = "第 3 次：换参考（两张脸各占一槽）"
        except Exception:  # noqa: BLE001
            pass
        return {"name": name, "seed": seed, "plan_kw": plan_kw, "seed_info": sinfo}

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
        seed, sinfo = self.seed_pick(o, attempt, f"strategy{stg}", f"{o['shot']}/producer/{o['kind']}/strategy{stg}")
        var = "faces_only" if stg == "A" else "double_face"
        word = "只挂脸（服装靠正文点名）" if stg == "A" else "双份身份脸"
        kw = {"two_person": "both_faces"} if stg == "A" else {}
        if attempt < 3:
            return {"name": f"第 {attempt} 次：策略 {stg} {word}", "seed": seed, "plan_kw": kw, "variant": var, "strategy": stg,
                    "seed_info": sinfo}
        return {"name": f"第 {attempt} 次：策略 C 重档 frame_v9_heavy + {word}", "seed": seed, "plan_kw": kw,
                "variant": var, "preset": "frame_v9_heavy", "strategy": "C", "seed_info": sinfo}

    def rung_ab(self, o: dict, attempt: int) -> dict | None:
        """双人镜首帧（总调度 11-01 06:16 定默认，依据 A/B：A 4/12 过、B 0/8 过）：第 1、2 次 两张脸 + 主角造型设定图（A，
        第 2 次换 seed），第 3 次才退到 两张脸 + 参考板（B）；每次都记 variant"""
        if o["kind"] != "first" or not self.two_person(o["shot"]):
            return None
        from ns_render import pipeline as P
        seed, sinfo = self.seed_pick(o, attempt, "ab")
        if attempt < 3:
            return {"name": f"第 {attempt} 次：两张脸 + 主角造型设定图（A）" + ("，换 seed" if attempt == 2 else ""), "seed": seed,
                    "plan_kw": {"two_person": "both_faces"}, "variant": "faces_look", "seed_info": sinfo}
        return {"name": f"第 {attempt} 次：退到 两张脸 + 参考板（B）", "seed": seed, "plan_kw": {"two_person": "both_faces"},
                "board": True, "variant": "faces_board", "seed_info": sinfo}

    def _run_one(self, o, lane, attempt, rung, tag) -> None:
        oid, sid, kind = o["id"], o["shot"], o["kind"]
        slot = rung.get("fanout") or oid              # PRODMERGE-O：分道并行的额外种子用自己的在途键，账本仍记在对象上
        url = self.lanes[lane]
        t0 = now()
        try:
            if lane not in self.relay_lanes and self.lock_now_fn(lane):            # 出发前现读一次训练锁（不走缓存，在派单线程里读，不卡主循环）
                raise RuntimeError(f"训练锁：{lane} 上锁了（train.lock），未提交，换道")
            res = self.frames.render(kind, sid, lane, url, attempt, rung, tag)
            if res.get("na"):
                self.led_update(oid, na=True, final="na", reason="剧本这一镜没有结束状态，不需要尾帧")
                self.logf("na", obj=oid)
                return
            with self.mu:
                if slot in (self.lane_busy.get(lane) or []):     # 出图完成即放道（只放自己这一单，别动同道预取的后来者）
                    self.lane_busy[lane].remove(slot)
            render_s = round(now() - t0, 1)
            self.logf("rendered", obj=oid, lane=lane, take=res["take"], secs=render_s, render_s=render_s, gpu_s=res.get("gpu_s"))
            with self.mu:
                self.scoring.add(slot)
            t1 = now()
            try:
                pf = res["pf_future"].result(timeout=1800)
            except Exception as e:  # noqa: BLE001  # A-02（总调度：进 sv-14）：图已入库，打分超时 / 出错只重打分、不重出、不计次
                self.led_update(oid, rescore_take=res["take"], backoff_until=now() + 300,
                                reason=f"契约打分超时或出错（{type(e).__name__}），图已入库，5 分钟后只重打分、不重出，不算一次尝试")
                self.logf("score_timeout", obj=oid, take=res["take"], error=repr(e)[:200], counted=False,
                          render_s=render_s, contract_s=round(now() - t1, 1), gpu_s=res.get("gpu_s"))
                self.score_chain_trip(f"{oid} 出图后契约打分超时")
                return
            contract_s = round(now() - t1, 1)
            if pf.get("score_infra"):
                self.led_update(oid, rescore_take=res["take"], backoff_until=now() + 300,
                                reason=("共用验收没拿到结论（看图排队 / 超时：retry，不判 fail），5 分钟后只重打分、不重出，不算一次尝试"
                                        if pf.get("accept_retry") else
                                        "契约打分时 gpu33 出错（显存 / 连接），5 分钟后只重打分、不重出，不算一次尝试"))
                self.logf("score_infra", obj=oid, take=res["take"], error=str(pf.get("remote_error") or pf.get("error"))[:200],
                          counted=False, render_s=render_s, contract_s=contract_s, gpu_s=res.get("gpu_s"))
                self.score_chain_trip(f"{oid} 出图后契约打分 score_infra")
                return
            L = self.ledger().get(oid) or {}
            if rung.get("redo"):
                rh = list(L.get("redo_history") or []) + [{"try": attempt, "take": res["take"], "ok": bool(pf.get("ok")),
                                                          "blocking": pf.get("blocking"), "rung": rung["name"],
                                                          "preset": rung.get("preset"), "at": iso()}]
                if pf.get("ok"):
                    self.led_update(oid, redo_tries=attempt, redo_history=rh, redo_candidate=res["take"])
                    if auto_review_redo(self.p, oid, res["take"], pf) or self.regen_auto_approve(oid, res["take"], pf):   # G0：替换版过了本地看图闸门 → 自动换上（总调度改抽查）
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
                                passed_sig=job_sig(self.p, sid) if kind == "first" else None,
                                passed_input_sig=input_sig(self.p, sid) if kind == "first" else None)
                self.logf("passed", obj=oid, take=res["take"], attempt=attempt, variant=rung.get("variant"), strategy=rung.get("strategy"),
                          render_s=render_s, contract_s=contract_s,
                          gpu_s=res.get("gpu_s"), scored_from=pf.get("scored_from") or pf.get("measured_on"))
                return
            why = pf_reason(pf)
            if (self.ledger().get(oid) or {}).get("final") == "passed":   # 分道并行：兄弟种子已过，本张只记历史
                self.led_update(oid, history=hist)
                self.logf("content_fail", obj=oid, attempt=attempt, why=why, counted=True, note="兄弟种子已通过，不改结论")
                return
            if attempt >= MAX_TRIES:
                best = self._best(sid, "image" if kind == "first" else "last", hist)
                # G3：没过契约的版本绝不设为当前；契约分最好的一版只记下来给人看
                reason = (f"试了 {attempt} 次（{' → '.join(str(h.get('rung') or h.get('source') or '?') for h in hist)}）仍没过：{why}；契约分最好的是 v{best}"
                          f"（没过契约，不设为当前），标“尽力”，不进合成")
                ra = auto_review_adopt(self.p, oid, {h.get("take") for h in hist if h.get("take")})   # L-183；L-187：开关默认关
                if not ra and not review_adopt_auto(self.p.root):
                    reason += "；L-187 自动取最高分已关，等项目方在 #/queue 挑"
                if ra:
                    self.led_update(oid, tries=attempt, history=hist, final="passed", last_error=why,
                                    reason=f"试了 {attempt} 次没全过；L-183 取 Q1–Q9 全过里分数最高的 v{ra} 设为当前，待项目方复核")
                    self.logf("passed", obj=oid, take=ra, attempt=attempt, review_needed=True, rule="L-183")
                    return
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
            if k in ("code", "preflight"):     # B2（K-OPS-E21）：派单前异常没出图，不算 runaway 的“每小时派单数”
                self.uncount_dispatch(oid)
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
                wk = wait_kind(err)
                if wk:                              # K-OPS-E26：缺资产 / 期望表不一致 → 标“等资产”，签名一变自动放回（不靠 30 分钟退避反复派）
                    self.led_update(oid, blocked_until=now() + WAIT_ASSET_MAX_S, last_error=err[:300], reason=plain_reason(k, err),
                                    waiting_asset={"kind": wk, "asset_sig": asset_sig(self.p), "refs_sig": refs_table_sig(self.p.root),
                                                   "at": iso()})
                else:
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
                if slot in (self.lane_busy.get(lane) or []):     # 11-01 08:38：只放自己这一单
                    self.lane_busy[lane].remove(slot)
                self.inflight.pop(slot, None)
                if slot in self.scoring:
                    self.score_done.append(now())
                    self.score_done = self.score_done[-500:]
                self.scoring.discard(slot)
            if slot == oid:
                self.leases.release(oid)

    def _rescore_dispatchable(self, o: dict) -> int | None:
        """W20：这一对象是不是“只重打分”且现在可以派 → 返回要重打的版本号"""
        if o.get("status") != "ready" or str(o.get("waiting_for") or "").startswith("基础设施退避"):
            return None
        if o["id"] in self.inflight or o["id"] in self._rescore_futs:
            return None
        if self._dispatch_only and o.get("shot") not in self._dispatch_only:
            return None
        led = self.ledger().get(o["id"]) or {}
        if float(led.get("backoff_until") or 0) > now():
            return None
        rt = led.get("rescore_take") or o.get("rescore_take")
        if not rt:
            return None
        recent = [x for x in led.get("rescore_times") or [] if now() - float(x) < 3600]
        if len(recent) >= RESCORE_HOURLY_MAX:      # W44 ②：每镜每小时 ≤3 次只重打分；超了退避 30 分钟（不重出、不计次）
            until = now() + RESCORE_CAP_BACKOFF_S
            self.led_update(o["id"], rescore_times=recent, rescore_capped=True, backoff_until=until,
                            reason=f"1 小时内已只重打分 {len(recent)} 次仍没拿到结论（看图 / 打分链路），"
                                   f"退避 {RESCORE_CAP_BACKOFF_S // 60} 分钟；看图 health 恢复 loaded 后自动清零")
            self.logf("rescore_cap", obj=o["id"], take=int(rt), n_1h=len(recent), max=RESCORE_HOURLY_MAX,
                      until=iso(until), counted=False)
            return None
        return int(rt)

    def rescore_cap_reset(self, health_fn=None, every_s: float = 60) -> list:
        """W44 ②：有对象因 rescore_cap 退避时，每 every_s 探一次看图 health；loaded=True → 清零这些对象的次数和退避
        （ev=rescore_cap_reset），马上可以再重打分。没有被封顶的对象就不探"""
        capped = [k for k, r in self.ledger().items() if isinstance(r, dict) and r.get("rescore_capped")]
        if not capped or now() - getattr(self, "_cap_health_at", 0.0) < every_s:
            return []
        self._cap_health_at = now()
        h = (health_fn or getattr(self, "vlm_health_fn", None) or vlm_health)()
        if not h.get("loaded"):
            return []
        for k in capped:
            self.led_update(k, rescore_times=[], rescore_capped=None, backoff_until=0, rescore_infra=None)
        self.logf("rescore_cap_reset", objs=capped, health=h, counted=False)
        return capped

    def score_chain_trip(self, why: str, cool_s: float = SCORE_CHAIN_COOL_S) -> None:
        """W20：打分链路（gpu33 ssh 打分 / 共用验收）刚出错 → 熔断一段时间：期间不派只重打分（出图照派，打分积压闸照管）"""
        until = now() + cool_s
        if until > self._score_down_until:
            self._score_down_until = until
            self.logf("score_chain_down", why=str(why)[:200], until=iso(until), counted=False)

    def dispatch_rescores(self, reg) -> int:
        """W20：只重打分（K-OPS-F12 / A-02：图已入库、只是打分没打成）独立派单：
        不要空闲道、不进出图线程池；打分链路熔断期间不派；同时在跑（含超时后还没回来的）≤ RESCORE_MAX；返回本拍派出数"""
        with self.mu:
            self._rescore_futs = {k: f for k, f in self._rescore_futs.items() if not f.done()}
            busy = len(self._rescore_futs)
        pend = [o for E in reg.get("episodes") or [] for S in E.get("shots") or []
                for k in ("last", "first") for o in [(S.get("objects") or {}).get(k)] if o]
        pend = [(o, rt) for o in pend for rt in [self._rescore_dispatchable(o)] if rt]
        if not pend:
            return 0
        if self._score_down_until > now():
            if getattr(self, "_last_rs_defer_log", 0) < now() - 300:
                self._last_rs_defer_log = now()
                self.logf("rescore_defer", n=len(pend), until=iso(self._score_down_until), counted=False,
                          why="打分链路刚出错（隧道 / gpu33 打分 / 共用验收），熔断期内不派只重打分，不占位")
            return 0
        n = 0
        for o, rt in pend:
            if busy >= RESCORE_MAX:
                if getattr(self, "_last_rs_cap_log", 0) < now() - 300:
                    self._last_rs_cap_log = now()
                    self.logf("rescore_busy", busy=busy, max=RESCORE_MAX, waiting=len(pend) - n, counted=False)   # W44：原名 rescore_cap（并发上限），改名让出给每镜上限
                break
            oid = o["id"]
            if not self.leases.acquire(oid, holder_note="rescore"):
                continue
            with self.mu:
                self.inflight[oid] = {"lane": None, "since": now(), "rescore": True, "take": rt}
                self.rescoring.add(oid)
                self._rescore_futs[oid] = self.rescore_pool.submit(self._rescore_one, o, rt)
            busy += 1
            n += 1
            L0 = self.ledger().get(oid) or {}
            self.led_update(oid, rescore_times=[x for x in L0.get("rescore_times") or [] if now() - float(x) < 3600] + [now()])
            self.logf("rescore_dispatch", obj=oid, take=rt, counted=False)
        return n

    def reap_rescores(self, timeout_s: float | None = None) -> list:
        """W20：只重打分超过时限还没回来（隧道断、ssh 卡住、退回 CPU 慢算）→ 放位：出 inflight / rescoring、放租约、
        逐级退避、熔断打分链路。线程回不来也不再挡心跳和重启队列；future 留着，回来前不重派（占 RESCORE_MAX）"""
        lim = RESCORE_TIMEOUT_S if timeout_s is None else timeout_s
        out = []
        with self.mu:
            late = [(k, v) for k, v in self.inflight.items() if v.get("rescore") and now() - float(v.get("since") or 0) > lim]
            for k, _v in late:
                self.inflight.pop(k, None)
                self.rescoring.discard(k)
        for oid, v in late:
            L = self.ledger().get(oid) or {}
            ki = int(L.get("rescore_infra") or 0) + 1
            back = RESCORE_BACKOFF[min(ki - 1, len(RESCORE_BACKOFF) - 1)]
            self.led_update(oid, rescore_infra=ki, backoff_until=now() + back,
                            reason=f"只重打分超过 {int(lim)} s 没拿到结论（打分链路不可用），{back // 60} 分钟后再试（不重出、不计次）")
            self.leases.release(oid)
            self.logf("rescore_timeout", obj=oid, take=v.get("take"), waited_s=round(now() - float(v.get("since") or 0), 1),
                      backoff_s=back, counted=False)
            out.append(oid)
        if out:
            self.score_chain_trip(f"只重打分超时：{'、'.join(out)[:120]}")
        return out

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
            L = self.ledger().get(oid) or {}
            if pf.get("accept_retry"):            # PRODMERGE-O：共用验收 retry 有上限（accept.max_rechecks），满了按没过处理（不再无限复核）
                k = int(L.get("accept_rechecks") or 0) + 1
                cap = int((producer_cfg(self.p.root)["accept"] or {}).get("max_rechecks") or 2)
                self.led_update(oid, accept_rechecks=k)
                if k > cap:
                    pf = {**pf, "ok": False, "score_infra": False,
                          "reasons": list(pf.get("reasons") or []) + [f"共用验收复核 {k - 1} 次仍没拿到结论"]}
            if pf.get("score_infra"):
                ki = int(L.get("rescore_infra") or 0) + 1
                back = RESCORE_BACKOFF[min(ki - 1, len(RESCORE_BACKOFF) - 1)]
                self.led_update(oid, rescore_infra=ki, backoff_until=now() + back,
                                reason=f"契约打分 / 共用验收仍没拿到结论，{back // 60} 分钟后再试（不重出、不计次）")
                self.logf("score_infra", obj=oid, take=n, counted=False, backoff_s=back,
                          error=str(pf.get("remote_error") or pf.get("error") or "")[:200])
                self.score_chain_trip(f"{oid} 只重打分 score_infra")
                return
            hist = [dict(h, ok=bool(pf.get("ok")), blocking=pf.get("blocking")) if h.get("take") == n else h
                    for h in L.get("history") or []]
            self.led_update(oid, rescore_take=None, rescore_infra=None, rescore_times=[], rescore_capped=None, history=hist,
                            **({"final": "passed", "reason": None} if pf.get("ok") else {"reason": "重打分后：" + pf_reason(pf)}))
            self.logf("rescore", obj=oid, take=n, ok=pf.get("ok"), blocking=pf.get("blocking"), counted=False)
        except Exception as e:  # noqa: BLE001
            L = self.ledger().get(oid) or {}
            ki = int(L.get("rescore_infra") or 0) + 1
            back = RESCORE_BACKOFF[min(ki - 1, len(RESCORE_BACKOFF) - 1)]
            self.led_update(oid, rescore_infra=ki, backoff_until=now() + back, last_error=repr(e)[:200])
            self.logf("rescore_err", obj=oid, take=n, error=repr(e)[:200], backoff_s=back)
            self.score_chain_trip(f"{oid} 只重打分出错：{repr(e)[:120]}")
        finally:
            with self.mu:
                mine = (self.inflight.get(oid) or {}).get("rescore")
                if mine:                          # 已被 reap_rescores 放位的不再动 inflight / 租约（可能已是别的单）
                    self.inflight.pop(oid, None)
                self.rescoring.discard(oid)
            if mine:
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
            if t and take_pf(t).get("ok") and (stale_requeue_map(sm.get("stale") or {}).get(stage)):
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
        fv = jl(self.p.frames_v2, {}) or {}       # 按剧过滤在下面 _adopt_same_run（逐条记 adopt_skip 留痕，W28）
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
                    atts = [a for a in atts if self._adopt_same_run(S["shot"], stage, a)]   # W28：C-14 跨剧不认领
                    for a in sorted(atts, key=lambda a: score_key(a["postflight"]), reverse=True):
                        pf = a["postflight"]
                        it = {"shot": S["shot"], "stage": stage, "file": a["file"], "seed": a.get("seed"),
                              "prompt": a.get("sent_prompt") or "", "refs": a.get("refs"), "workflow": "frame_v9_unified",
                              "label": "ASSETMASTER 已出（PRODUCER 接手登记）",
                              "postflight": {"ok": bool(pf.get("ok")), "items": pf.get("items") or [], "reasons": pf.get("reasons") or []},
                              "origin": {"run": "assetmaster/frames_v2", "src_run": self.p.run_id, "adopted_by": AGENT, "seed": a.get("seed"),
                                         "lane": a.get("lane"), "contract_ok": bool(pf.get("ok"))}}
                        r = RT.register(it, label=it["label"])
                        if r.get("status") == "registered":
                            n_new += 1
                            self.logf("adopt", obj=o["id"], take=r.get("n"), ok=bool(pf.get("ok")), seed=a.get("seed"),
                                      current=r.get("current"), rerendered=False)
        return n_new

    def _adopt_same_run(self, sid: str, stage: str, a: dict) -> bool:
        """W28（C-14 / L-126）：frames_v2/state.json 是全局文件、按镜号不按剧 —— 只认本剧的尝试：
        条目 run == 本剧，或文件在本剧渲染目录下；都不满足（他剧 / 无剧名的 V1 旧图）→ 不认领，记 adopt_skip（每进程每条一次）"""
        if fv2_attempt_run_ok(self.p, a):
            return True
        key = (sid, stage, a.get("file"))
        seen = self.__dict__.setdefault("_adopt_skipped", set())
        if key not in seen:
            seen.add(key)
            self.logf("adopt_skip", obj=f"{sid}:{stage}", file=a.get("file"), att_run=a.get("run"), run=self.p.run_id,
                      counted=False, why="跨剧" if a.get("run") else "无剧名")
        return False

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

    run_source = "explicit"          # serve 启动时改成 "--run" / "runs.json:primary"
    started_at = None

    def identity(self) -> dict:
        """ISS-1103-033310-5833：本进程的 run 身份（写进心跳 / pid 文件，master_check ⑥ 与 resident health 据此判断“为哪部剧在跑”）"""
        return {"run": self.p.run_id, "run_source": self.run_source, "started": self.started_at,
                "pd": _rel(self.p.pd, self.p.root), "code": "run-identity-v1"}

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
    if run_scoped_import(run, paths.root) and not run_import_path_ok(run, path, paths.root):
        log_event(paths, "import_blocked", path=path, step="path", by=by, run=run)
        print(json.dumps({"ok": False, "why": "path", "detail": f"不是本剧写作链产物（只认 data/pipeline/runs/{run}/ 下的 .md）：{path}"}, ensure_ascii=False))
        return 1
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
    if run_scoped_import(run, paths.root):                      # 按剧导入稿（data/import/runs/<run>/script_v2.json）：第二季等非主剧，以及 V2 这种非旧版的主剧
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


# ---------------------------------------------------------------------------------------------- PRODMERGE-O 11-03（L-151）
_SG_MODS: dict = {}


def sop_gate_mod(root: Path = ROOT):
    """tools/master/sop_gate.py（唯一阶段模型）；按 root 各载一份（演练 / 测试临时根用自己的 runs.json）"""
    key = str(Path(root).resolve())
    if key not in _SG_MODS:
        import importlib.util as _u
        src = Path(root) / "tools" / "master" / "sop_gate.py"
        sp = _u.spec_from_file_location(f"sop_gate_for_producer_{abs(hash(key))}", src if src.is_file() else ROOT / "tools/master/sop_gate.py")
        m = _u.module_from_spec(sp)
        sp.loader.exec_module(m)
        _SG_MODS[key] = m
    return _SG_MODS[key]


def promote_live(root: Path, line: str) -> None:
    """W18：自动提升写 V2_LIVE 一行（report_issue._insert_live 同一写法；文件不在 = 不写，测试临时根不会凭空建文件）"""
    try:
        import importlib.util as _u
        sp = _u.spec_from_file_location("report_issue_for_producer", ROOT / "tools/master/report_issue.py")
        m = _u.module_from_spec(sp)
        sp.loader.exec_module(m)
        m._insert_live(f"{time.strftime('%H:%M')} {line}", Path(root) / "docs/master/V2_LIVE.md")
    except Exception:  # noqa: BLE001  # arch-ok: V2_LIVE 写不进去不拦提升（runs.json status_history 是权威）
        pass


def producer_cfg(root: Path = ROOT) -> dict:
    """config/pipeline/producer.json（fanout 一镜多种子分道、accept 共用验收）；读不到 = 默认（fanout 关、accept 开）"""
    d = jl(Path(root) / "config" / "pipeline" / "producer.json", {}) or {}
    fan = {"enabled": False, "max_per_obj": 3, "runs": [], **(d.get("fanout") or {})}
    return {"fanout": fan, "accept": d.get("accept") or {}, "review_adopt_auto": d.get("review_adopt_auto") is True,
            "script_hot_reload": d.get("script_hot_reload") is not False,        # B2：默认开
            "auto_regen_on_change": d.get("auto_regen_on_change") is True,        # B2：默认关
            "approve_guard": d.get("approve_guard") is not False}                 # B2：默认开


def script_hot_reload(root: Path = ROOT) -> bool:
    try:
        return bool(producer_cfg(root)["script_hot_reload"])
    except Exception:  # noqa: BLE001  # arch-ok: 配置读不到 = 开（默认）
        return True


def cfg_flag(root: Path, key: str) -> bool:
    try:
        return bool(producer_cfg(root)[key])
    except Exception:  # noqa: BLE001  # arch-ok: 读不到 = 取默认
        return key == "approve_guard"


def review_adopt_auto(root: Path = ROOT) -> bool:
    """L-187（项目方 11-04）：重试用尽后是否自动取 Q1–Q9 全过里最高分设为当前（L-183）；缺键 / 读不到 / 非 true = 关（失败关闭）"""
    try:
        return bool(producer_cfg(root)["review_adopt_auto"])
    except Exception:  # noqa: BLE001  # arch-ok: 配置读不到 = 关
        return False


def auto_review_adopt(paths: "Paths", oid: str, ns: set | None = None) -> int | None:
    """主循环用：开关关 = 不取（走原 best_effort，等项目方挑）；开 = review_adopt（L-183）。手工 CLI review-adopt 不经此处"""
    if not review_adopt_auto(paths.root):
        log_event(paths, "review_adopt_skipped", obj=oid, rule="L-187", counted=False, note="自动取最高分开关关")
        return None
    return review_adopt(paths, oid, ns=ns, relaxed=True)   # L-196：没有全过版也取最高分版


def shared_accept(paths: "Paths", script, sid: str, file_rel: str, job: dict, pf: dict, evaluate_fn=None) -> dict:
    """共用验收（ns_agent.gen_contract.accept，原 golden 的判定）：资产包剧才加判；出错 = retry（只重打分，不判 fail）"""
    try:
        from ns_agent.gen_contract import accept as ACC
        if not ACC.enabled(paths.run_id, paths.root):
            return pf
        from ns_render import pipeline as P
        _ep, shot = P.find_shot(script, sid)
        acc = (evaluate_fn or ACC.evaluate)(str(P.DATA / file_rel), pf, job, shot, paths.run_id)
        return ACC.apply(pf, acc)
    except Exception as e:  # noqa: BLE001  # arch-ok: 验收服务出错不是图的问题 → retry（只重打分），不放行
        log_event(paths, "accept_err", obj=sid, error=repr(e)[:200], counted=False)
        pf["accept_retry"] = True
        pf["score_infra"] = True
        return pf


def accept_skip_prefailed(root: Path) -> bool:
    """config/pipeline/producer.json accept.skip_prefailed（默认 false）：契约 / 看图已不过的图不再做共用验收（见 FrameExec._postflight）"""
    try:
        from ns_agent.gen_contract import accept as ACC
        return bool(ACC.config(root).get("skip_prefailed"))
    except Exception:  # noqa: BLE001  # arch-ok: 读不到配置 = 关（原口径：照做共用验收）
        return False


def accept_run_qb(root: Path) -> bool:
    """config/pipeline/producer.json accept.run_qb（L-196；缺键 = true 原口径）：false = 不跑共用验收 QB"""
    try:
        from ns_agent.gen_contract import accept as ACC
        return bool(ACC.config(root).get("run_qb", True))
    except Exception:  # noqa: BLE001  # arch-ok: 读不到配置 = 照跑（原口径）
        return True


def canary_ignore_items(root: Path) -> set:
    """config/pipeline/producer.json canary.ignore_items（SLIM-CDE 11-05 E3，缺键 / 读不到 = 空 = 原口径）：这些阻断项不计入换版首批复核。
    base35 下 Q1 不过 ~50% 是已知底噪（DEBUG-35：单脸镜 0.60 / 多脸镜 0.49 均值），不是“规则 / 资产换版坏了”，而 canary 一触发就暂停整台派单
    （11-05 19:42 暂停 135 s、20:02 暂停 1025 s，6 道全停）；Q1 仍是硬闸（挡图、自动重出不变），只是不再触发整台暂停"""
    try:
        d = json.loads((root / "config" / "pipeline" / "producer.json").read_text(encoding="utf-8"))
        return {str(x) for x in ((d.get("canary") or {}).get("ignore_items") or [])}
    except (OSError, ValueError):  # arch-ok: 配置读不到 = 空集 = 原口径（canary 照常计 Q1），不放宽
        return set()


def apply_blocking_policy(pf: dict) -> dict:
    """L-196：gen_contract.json blocking_items（Q1 / count / text / adult）以外的项只记录不挡；缺键 = 旧口径。出错不改结论"""
    try:
        from ns_agent.gen_contract import blocking as BL
        return BL.apply(pf)
    except Exception:  # noqa: BLE001  # arch-ok: 策略出错 = 保持原判（更严），不放宽
        pf.setdefault("reasons", [])
        return pf


def mark_qb_skipped(pf: dict, why: str | None = None) -> dict:
    """AUDIT-PERF 11-05（开关 config/pipeline/producer.json accept.skip_prefailed，默认关）：契约 / 看图已判不过（ok=False）的图，
    共用验收只会再加 QB、从不翻回通过（gen_contract.accept.apply）；而它的 ensure_q9 会把 vqa_gate 刻意跳过的整张看图再跑一遍
    （+ bundle 再看一遍）——11-05 实测每张白耗 4–6 次看图、~160 s 看图 GPU、~80 s 关键路径。QB 记 na（不挡），结论不变"""
    pf["items"] = [i for i in pf.get("items") or [] if i.get("id") != "QB"] + [
        {"id": "QB", "title": "共用验收（看图逐条 + 年龄 + OCR + 人数，PRODMERGE-O）", "status": "na", "blocking": False,
         "detail": why or ("前置契约不过（" + "、".join(str(b) for b in pf.get("blocking") or []) + "），未做共用验收（accept.skip_prefailed）")}]
    pf["accept"] = {"status": "skipped", "why": "L-196" if why else "prefailed", "blocking": list(pf.get("blocking") or [])}
    return pf


def run_status(root: Path, run_id: str) -> str | None:
    """runs.json 里这部剧的 status（producing / paused / ...）；登记表读不到 → None（不改变 control 的判断）"""
    try:
        d = json.loads((root / "config/pipeline/runs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 没有登记表（老部署 / 演练目录）= 不额外暂停，沿用 control
        return None
    return ((d.get("runs") or {}).get(run_id) or {}).get("status")


def run_scoped_import(run: str | None, root: Path) -> bool:
    """这部剧的导入稿是不是按剧存放（runs.import_path = data/import/runs/<run>/script_v2.json）。
    22:34 series10_v2 事故：V2 成了主剧后走“主剧”分支，收件箱接口只认收件箱目录，pipeline 产出的 P4_epNN.final.md 被 404“不是导入候选”拒了。
    判据改成“是不是旧版单一导入稿”（runs.is_legacy），不再按“是不是主剧”：只有旧版（V1）走收件箱接口，其余一律按剧导入"""
    return bool(run) and not _runs().is_legacy(run, root)


def run_import_path_ok(run: str | None, path: str, root: Path) -> bool:
    """按剧导入只放行本剧自己 run 目录（runs.run_dir）下的写作链产物 .md；V1 路径、别的剧、run 目录以外一律拒绝（L-126 完全切割）"""
    if not run or _runs().is_legacy(run, root):
        return False
    try:
        p = (Path(root) / path).resolve()
        base = _runs().run_dir(run, root).resolve()
    except (OSError, ValueError):  # arch-ok: 配置读不到 = 用缺省（原口径），不放宽
        return False
    return p.suffix == ".md" and base in p.parents and p.is_file()


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
        # MERGE-OPS-O（ISS-1103-044539-f93d）：import_script 的拒绝原因（v1_leak block 等）打在 stdout，以前只记 stderr → detail 为空
        out_t = (r.stdout or b"").decode("utf-8", "replace")
        why = next((ln.strip() for ln in reversed(out_t.splitlines()) if ln.startswith("拒绝导入")), "")
        detail = " | ".join(x for x in (why, (r.stderr or b"").decode("utf-8", "replace")[-300:].strip(),
                                        "" if why else out_t[-300:].strip()) if x)
        log_event(paths, "import_blocked", path=path, step="import_script", run=run, by=by, rc=r.returncode, detail=detail[-600:])
        print(json.dumps({"ok": False, "why": "import_script 失败", "run": run, "rc": r.returncode, "detail": detail[-600:]},
                         ensure_ascii=False))
        return 1
    eps = imported_episodes(paths, path, None)
    RN.register_run(run, source="import", episode=min(eps) if eps else None, root=paths.root)
    try:
        import import_events as IE
        IE.append_import(eps, by=f"PRODUCER import_staged（{by}）", source=path, note=note, run_id=run, old_script=backup or (out.parent / "_none_.json"))
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
                 expires_at=iso(exp), overdue_alert_t=None)
    else:
        c.update(paused=False, paused_by=None, paused_at=None, note=note or None, reason_kind=None,
                 expires_at=None, overdue_alert_t=None)
    c.pop("expires_t", None)
    c.pop("canary", None)                      # W44 ①：canary 判定记录只属于那一次 canary 暂停（canary_pause 写完再补）
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
    exp = iso(now() + minutes * 60)
    for sid in shots:
        items[sid] = {"shot": sid, "run": paths.run_id, "objects": [f"first:{sid}", f"last:{sid}"], "by": by, "note": note, "at": iso(),
                      "expires_at": exp}
    d.update(active=True, rule="K-OPS-E19 按镜暂停；到期（expires_at）自动失效", shots=list(items.values()))
    f.parent.mkdir(parents=True, exist_ok=True)
    js(f, d)
    log_event(paths, "pause_shots", shots=shots, by=by, note=note, expires_at=exp, counted=False)
    return d


def release_holds(paths: Paths, shots: list, by: str, why: str, files=("pause_hold.json", "runaway_hold.json")) -> list:
    """B2：按镜释放 data/autopilot/<file> 里的条目（不删历史：条目加 released={by, why, at}，asset_hold_objects 不再算它）→ 释放了的 [文件:镜]"""
    out = []
    for fn in files:
        f = paths.data / "autopilot" / fn
        d = jl(f, {}) or {}
        hit = False
        for it in d.get("shots") or []:
            if it.get("shot") in shots and not it.get("released") and (not it.get("run") or it.get("run") == paths.run_id):
                it["released"] = {"by": by, "why": why, "at": iso(), "t": now()}
                out.append(f"{fn}:{it['shot']}")
                hit = True
        if hit:
            if not any(not it.get("released") for it in d.get("shots") or []):
                d["active"] = False
            js(f, d)
    if out:
        log_event(paths, "hold_released", shots=shots, by=by, why=why, released=out, counted=False)
    return out


def resume_shots(paths: Paths, shots: list, by: str, note: str = "") -> dict:
    """B2：解除按镜暂停（pause --shots 的对称命令；不再需要“再 pause 一个极短时间”）。runaway 冻结用 unhold"""
    return {"released": release_holds(paths, shots, by, note or "resume --shots", files=("pause_hold.json",))}


def unhold(paths: Paths, oid: str, by: str, note: str = "") -> dict:
    """B2：解冻 K-OPS-E21 runaway（也清 pause_hold 里这一镜的条目）"""
    sid = oid.split(":", 1)[-1]
    return {"obj": oid, "released": release_holds(paths, [sid], by, note or "unhold")}


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

def _rel(p: Path, root: Path) -> str:
    try:
        return Path(p).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(p)


RUN_STOP_STATUSES = ("archived", "frozen")      # 这两种状态的剧不再出图：常驻 producer 必须退出，不能空占进程 / 写旧心跳
RUN_ENV_KEYS = ("NS_RUN", "NS_RENDERS_DIR", "NS_SCRIPT_JSON")


def primary_now(root: Path, tries: int = 3, pause: float = 0.2) -> str | None:
    """W8 / A1-1：常驻进程判“现在主剧是谁”专用。读不准 = None（未知，不动），绝不回退 DEFAULT_PRIMARY。
    runs.json 在 → 只认它的 primary；截断 / 撞 os.replace（PermissionError）/ 没 runs / 没 primary → 短暂重试后仍坏 = None。
    runs.json 不在（演练目录 / 老部署）→ run.json 指针；也没有 = None。
    事故：runs.json 一次读坏 → runs.registry 非 strict 回退 run.json → 再回退 series10_v1 → 正确的 V2 进程以为“主剧切走了”停派退出"""
    rp = Path(root) / "config" / "pipeline" / "runs.json"
    if rp.exists():
        for i in range(max(1, tries)):
            try:
                d = json.loads(rp.read_text(encoding="utf-8"))
            except (OSError, ValueError):   # arch-ok: 撞上写入方 / 截断 = 这次读不准，重试后仍坏 = 未知
                d = None
            if isinstance(d, dict) and d.get("runs") and str(d.get("primary") or "").strip():
                return str(d["primary"]).strip()
            if i < tries - 1:
                time.sleep(pause * (i + 1))
        return None
    v = jl(Path(root) / "config" / "pipeline" / "run.json", {}) or {}
    v = v.get("run_id") if isinstance(v, dict) else None
    return (str(v).strip() or None) if v else None


def identity_drift(paths: Paths, pinned: bool) -> str | None:
    """ISS-1103-033310-5833（SYSAUDIT-F 11-03）：常驻 producer 的 run 是启动时定的（RUN_ID / Paths.run_id 进程内缓存），
    11-02 primary 从 V1 切到 V2 后，笔记本那个 01:45 起的进程一直在为已归档的 V1 跑、心跳写 V1 目录，V2 没人出图 8 小时。
    这里每拍重判：① 本剧在 runs.json 已 archived / frozen → 该退；② 没用 --run 钉死的进程，主剧（runs.json primary）已换 → 该退（交给新剧的进程）。
    返回退出原因；None = 身份仍然对，或登记表读不准（W8 / A1-1：未知 = 不动，不拿默认剧当“已切换”）"""
    st = run_status(paths.root, paths.run_id)
    if st in RUN_STOP_STATUSES:
        return f"config/pipeline/runs.json 里 {paths.run_id} status={st}（已归档 / 冻结，不再出图）"
    if not pinned:
        cur = primary_now(paths.root)
        if cur and cur != paths.run_id:
            return f"主剧（config/pipeline/runs.json primary）已切到 {cur}（本进程为 {paths.run_id} 启动）"
    return None


def spawn_successor(paths: Paths, log_path: Path) -> int:
    """为现在的主剧（runs.json primary）拉起一个新的 producer serve（脱离本进程：本进程随后退出，不带走它）。
    环境里去掉旧剧的 NS_RUN / NS_RENDERS_DIR / NS_SCRIPT_JSON，新进程自己按 run.json 设"""
    env = {k: v for k, v in os.environ.items() if k not in RUN_ENV_KEYS}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    kw: dict = {"cwd": str(paths.root), "env": env, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    with open(log_path, "ab") as out:
        p = subprocess.Popen([sys.executable, "-u", str(paths.root / "tools" / "autopilot" / "producer.py"), "serve"],
                             stdout=out, stderr=subprocess.STDOUT, **kw)
    return p.pid


DRIFT_CONFIRM_TICKS = 2           # W8 / A1-1：身份不对要连续 2 拍一致才交接（第 1 拍只停派单观察）
PID_GRACE_S = 120                  # W8 / A1-3：pid 文件刚写、还没心跳的宽限
PID_HB_FRESH_S = 600               # 持有者心跳超过 10 分钟没更新 = 不认（PID 复用 / 进程卡死）


def _hb_merge(pr, paths: Paths, **kw) -> None:
    """排空期间心跳：在本进程最近一次心跳上改 state，不丢 tick 写的字段"""
    hb = jl(paths.heartbeat, {}) or {}
    if not isinstance(hb, dict) or hb.get("pid") != os.getpid():
        hb = {}
    hb.update({"ts": iso(), "t": now(), "pid": os.getpid(), "paused": True, "inflight": len(pr.inflight), **pr.identity()}, **kw)
    hb.pop("exited", None)
    js(paths.heartbeat, hb)


def handoff(pr: "Producer", paths: Paths, why: str, pinned: bool, spawn=None, drain_s: float = 900,
            wait_s: float = LEASE_S) -> dict:
    """身份不对了：停派单 → 等手上的图做完 → 复核身份 → 心跳写 exited → 放 pid 文件 → 没钉 run 的进程为新剧拉起接班 → 返回（进程退出）。
    W8 / A1-1：排空后再判一次身份，已恢复（登记表读回来了、new==本剧且未归档）→ 放弃交接，返回 aborted，serve 继续跑。
    W8 / A1-2：drain_s 内边收结果边排空；没排完再只等在途线程（≤ wait_s，默认 LEASE_S）；期间心跳 state=draining（不是 exited），
    真排空了才写 exited；wait_s 到了还没排空 → 心跳保持 draining（不谎报已退出：解释器退出时仍会 join 在途线程）"""
    log_event(paths, "run_switch", why=why, run=paths.run_id, inflight=len(pr.inflight))
    t_end = now() + drain_s
    while pr.inflight and now() < t_end:
        try:
            pr.tick(dispatch=False)
        except Exception as e:  # noqa: BLE001  排空期间一拍出错不影响退出
            log_event(paths, "tick_err", error=repr(e)[:300])
        _hb_merge(pr, paths, state="draining", exit_reason=why)
        pr.wait_idle(min(30.0, max(0.0, t_end - now())))
    if pr.inflight and wait_s > 0:
        t2 = now() + wait_s
        log_event(paths, "drain_overrun", inflight=len(pr.inflight), wait_s=wait_s)
        while pr.inflight and now() < t2:
            _hb_merge(pr, paths, state="draining", exit_reason=why, drain_overrun=True)
            pr.wait_idle(min(30.0, max(0.0, t2 - now())))
    if not identity_drift(paths, pinned):
        out = {"why": why, "aborted": True, "drained": not pr.inflight, "successor": None}
        log_event(paths, "run_switch_abort", **out)
        return out
    out = {"why": why, "drained": not pr.inflight, "successor": None}
    if not pinned:
        new = primary_now(paths.root)
        if new and new != paths.run_id and run_status(paths.root, new) not in RUN_STOP_STATUSES:
            npd = _runs().producer_dir(new, paths.root)
            try:
                out["successor"] = {"run": new, "pid": (spawn or spawn_successor)(paths, npd / "producer.out")}
            except Exception as e:  # noqa: BLE001  拉不起来如实写心跳；master_check ⑥ 会显示新剧没有 producer
                out["successor"] = {"run": new, "error": repr(e)[:200]}
    base = {"ts": iso(), "t": now(), "pid": os.getpid(), "paused": True, "inflight": len(pr.inflight),
            **pr.identity(), "exit_reason": why, "successor": out["successor"]}
    if out["drained"]:
        js(paths.heartbeat, {**base, "state": "exited", "exited": iso()})
    else:                                        # A1-2：在途还没做完——不写 exited
        js(paths.heartbeat, {**base, "state": "draining", "drain_overrun": True})
    pidf = paths.pd / "producer.pid"
    if int((jl(pidf, {}) or {}).get("pid") or 0) == os.getpid():
        pidf.unlink(missing_ok=True)
    log_event(paths, "exit", **out)
    return out


def _pid_holder_alive(paths: Paths, pidf: Path, old) -> bool:
    """W8 / A1-3：pid 文件的持有者是不是一个活着的本剧 producer。只看 pid_alive 会被 PID 复用骗（别的进程拿到同一个 pid → 永不启动）"""
    try:
        age = now() - pidf.stat().st_mtime
    except OSError:
        return False
    if not isinstance(old, dict) or not old.get("pid"):
        return age < PID_GRACE_S                 # 对方刚 O_EXCL 建了文件还没写完：宽限期内算有人
    if int(old["pid"]) == os.getpid() or not pid_alive(old["pid"]):
        return False
    hb = jl(paths.heartbeat, {}) or {}
    if isinstance(hb, dict) and hb.get("pid") == old["pid"] and not hb.get("exited"):
        same_start = not (old.get("started") and hb.get("started")) or hb.get("started") == old.get("started")
        if same_start and now() - float(hb.get("t") or 0) <= PID_HB_FRESH_S:
            return True
    return age < PID_GRACE_S                     # 刚启动、第一拍心跳还没写


def acquire_pidfile(paths: Paths, rec: dict) -> tuple[bool, dict]:
    """O_EXCL 建 pid 文件（W8 / A1-3）。已有且持有者确认是活着的本剧 producer → (False, 旧记录)；陈旧 / PID 被复用 → 删掉重建"""
    pidf = paths.pd / "producer.pid"
    pidf.parent.mkdir(parents=True, exist_ok=True)
    old = None
    for _ in range(3):
        try:
            fd = os.open(pidf, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raw = None
            try:
                raw = pidf.read_text(encoding="utf-8")
                old = json.loads(raw)
            except (OSError, ValueError):   # arch-ok: 对方正在写 / 坏文件，交给 _pid_holder_alive 按宽限判
                old = None
            if _pid_holder_alive(paths, pidf, old):
                return False, old if isinstance(old, dict) else {}
            try:                             # 陈旧：确认内容没被别人换掉再删（缩小两个启动者互删的窗口）
                if raw is None or pidf.read_text(encoding="utf-8") == raw:
                    pidf.unlink()
                    log_event(paths, "pidfile_stale", old=old if isinstance(old, dict) else str(raw)[:120])
            except FileNotFoundError:        # 别的启动者已删 → 下一轮 O_EXCL 重抢
                log_event(paths, "pidfile_gone", old=old if isinstance(old, dict) else str(raw)[:120])
            except OSError:
                return False, old if isinstance(old, dict) else {}
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False))
        return True, rec
    return False, old if isinstance(old, dict) else {}


def serve(paths: Paths, pinned: bool = False, *, producer=None, spawn=None, sleep=None, max_ticks: int | None = None) -> int:
    """常驻。pinned = 用 --run 显式指定了剧（多剧并行的额外剧）；否则跟着 config/pipeline/runs.json primary 走。
    测试注入：producer（不起 FrameExec）/ spawn（接班进程）/ sleep / max_ticks"""
    sleep = sleep or time.sleep
    pr = producer or Producer(paths)
    pr.run_source = "--run" if pinned else "runs.json:primary"
    pr.started_at = iso()
    why = identity_drift(paths, pinned)
    if why:                                      # 一启动就不对（例：V1 已归档还有人起 serve）：隔一会儿再确认一次（A1-1），仍不对才交接退出
        sleep(2)
        why = identity_drift(paths, pinned)
    if why:
        print("PRODUCER 不启动：", why)
        out = handoff(pr, paths, why, pinned, spawn=spawn, drain_s=0, wait_s=0)
        if not out.get("aborted"):
            return 0
    ok, old = acquire_pidfile(paths, {"pid": os.getpid(), "started": pr.started_at, "run": paths.run_id, "run_source": pr.run_source})
    if not ok:
        print("PRODUCER 已在运行 pid", old.get("pid"), "run", old.get("run"))
        return 0
    if producer is None:
        pr.frames = FrameExec(paths, pr.script(), script_fn=pr.script)
    log_event(paths, "start", pid=os.getpid(), lanes=list(pr.lanes), run=paths.run_id, run_source=pr.run_source,
              code_sha=code_sha())   # W44 ①：启动时算一次代码 sha（之后热推不变，重启才变）
    n = 0
    suspect, seen = None, 0
    while max_ticks is None or n < max_ticks:
        n += 1
        why = identity_drift(paths, pinned)
        if why:
            seen = seen + 1 if why == suspect else 1
            suspect = why
            if seen < DRIFT_CONFIRM_TICKS:           # A1-1：第 1 拍只停派单（手上的照收），下一拍还一样才交接
                log_event(paths, "run_switch_suspect", why=why, seen=seen)
                try:
                    pr.tick(dispatch=False)
                except Exception as e:  # noqa: BLE001
                    log_event(paths, "tick_err", error=repr(e)[:300], tb=traceback.format_exc()[-600:])
                sleep(TICK_S)
                continue
            out = handoff(pr, paths, why, pinned, spawn=spawn)
            if not out.get("aborted"):
                return 0
            suspect, seen = None, 0                  # 复核身份已恢复：继续跑
        elif suspect:
            log_event(paths, "run_switch_cleared", why=suspect)
            suspect, seen = None, 0
        try:
            pr.tick()
        except Exception as e:  # noqa: BLE001
            log_event(paths, "tick_err", error=repr(e)[:300], tb=traceback.format_exc()[-600:])
        sleep(TICK_S)
    return 0


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
    paths = Paths(root=root, run_id=legacy_run_id())     # 演练用系统剧本（legacy 剧，旧路径）；K-OPS-F24 后 primary 可能是还没剧本的 V2
    paths.vid.mkdir(parents=True)
    old = (P.DATA, P.RENDERS, P.SCRIPT_JSON)
    P.DATA, P.RENDERS = root / "data", root / "data" / "renders"
    P.SCRIPT_JSON = ROOT / "data" / "import" / "script_v2.json"
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
        P.DATA, P.RENDERS, P.SCRIPT_JSON = old
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


PRESET_WORD = {"frame_v9": "frame_v9 换 seed", "frame_v9_heavy": "frame_v9_heavy（写实·重，krea2 0.8）"}


VARIANT_WORD = {"faces_look": "两张脸 + 主角造型设定图（A）", "faces_board": "两张脸 + 参考板（B）", "faces_only": "只挂脸（策略 A）",
                "double_face": "双份身份脸（策略 B）"}


def plan_item(x: str) -> dict:
    """"frame_v9" / "frame_v9_heavy" / "frame_v9:faces_look" → 计划项"""
    preset, _, variant = x.partition(":")
    name = PRESET_WORD.get(preset, preset) + (f" · {VARIANT_WORD.get(variant, variant)}" if variant else "")
    return {"preset": preset or None, "variant": variant or None, "name": name}


def master_reject(paths: Paths, oid: str, n: int, reason: str, presets: list, wait, by: str, edit: dict | None = None) -> int:
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
    P.mutate_takes(sid, lambda d: d.setdefault("master_gate", {}).__setitem__(stage, {"reject_n": n, "reason": reason, "by": by, "at": iso()}),
                   op="master_reject", by=f"producer（{by}）")
    rj = jl(paths.rejects, {}) or {}
    rj[oid] = {"reject_n": n, "reason": reason, "by": by, "at": iso(), "wait": wait,
               "label": "总调度插队" if not n else "驳回重出",
               "plan": [plan_item(x) for x in presets if x]}
    if edit:      # L-123：项目方在界面上“修改”写的一句话（已由写作模型改写成修改要求）；出图时追加进提示词（apply_owner_edit），n=0 不撤下当前版
        rj[oid]["edit"] = {k: edit.get(k) for k in ("id", "text", "prompt", "zh_summary", "negative_add", "base_n") if edit.get(k) is not None}
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


def master_approve(paths: Paths, oid: str, n: int, by: str, note: str = "", force: bool = False) -> int:
    """总调度复核通过替换版：设为当前、清掉 master_gate 和驳回记录；首帧换了 → 同镜在等首帧的尾帧开始重做"""
    from ns_render import pipeline as P
    from ns_render import frame_edit as FE
    kind, sid = oid.split(":", 1)
    stage = "image" if kind == "first" else "last"
    from ns_render import auto_current as AC
    if cfg_flag(paths.root, "approve_guard") and not force:
        # B2：契约没过的版本 approve 会被 reconcile_demoted 下一轮撤下（只认 take_pf.ok）→ 拒绝并指路（不自动转：review-adopt 要 Q1–Q9 全过，
        # 转不转由总调度明确选，免得悄悄改了语义）
        t = next((x for x in P.load_takes(sid).get("takes") or [] if x.get("stage") == stage and x.get("n") == n), None)
        pf = take_pf(t)
        if pf and pf.get("ok") is False and not pf.get("review_needed"):
            msg = f"拒绝 approve {oid} v{n}：这一版契约没过（{pf_reason(pf)[:120]}），approve 会被下一轮 reconcile 撤下；请用 review-adopt --obj {oid} --n {n}"
            log_event(paths, "approve_refused", obj=oid, take=n, by=by, why=msg, counted=False)
            print(msg, file=sys.stderr)
            return 2
    FE.annotate(sid, stage, n, master_review={"ok": True, "by": by, "at": iso(), "note": note})
    P.mutate_takes(sid, lambda d: [(d.get("master_gate") or {}).pop(stage, None), None][1], op="master_approve", by=f"producer（{by}）")
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
        P.mutate_takes(sid, lambda d: [(d.get("master_gate") or {}).pop("last", None), None][1], op="master_approve_last", by=f"producer（{by}）")
    js(paths.rejects, rj)
    L = jl(paths.ledger, {}) or {}
    L.setdefault(oid, {}).update(redo_candidate=None, final="passed")
    js(paths.ledger, L)
    log_event(paths, "master_approve", obj=oid, take=n, by=by)
    return 0


def regen_shots(paths: Paths, shots: list, reason: str, by: str, presets: list | None = None, dry: bool = False) -> dict:
    """B2 换代入口：对选中镜的当前首帧标“换代中”并按默认方案重出。走驳回重出（master_rejects，n=0）那条已有链路——
    不撤下当前版（active 不清空，视频 / 合成仍可用旧版；_redo_obj 对 regen 标 regen_keep，视频不等首帧），新版过契约 + 看图闸门后
    master_approve 换成当前（首帧换了 → 尾帧随首帧重做的现有逻辑）。没有当前首帧 / 已在重出 / 在换代的镜跳过"""
    from ns_render import pipeline as P
    out = {"regen": [], "skipped": {}, "dry": bool(dry), "at": iso()}
    for sid in shots:
        oid = f"first:{sid}"
        if (P.load_takes(sid).get("active") or {}).get("image") is None:
            out["skipped"][sid] = "没有当前首帧（走常规出图）"
            continue
        rj0 = (jl(paths.rejects, {}) or {}).get(oid)
        if rj0 and not rj0.get("cleared"):
            out["skipped"][sid] = "已在重出 / 换代中"
            continue
        if dry:                                  # --dry：只列“会换代”的镜，不写 rejects / ledger / log
            out["regen"].append(sid)
            continue
        master_reject(paths, oid, 0, reason, presets or ["frame_v9", "frame_v9"], None, by)
        rj = jl(paths.rejects, {}) or {}
        rj[oid].update(regen={"by": by, "reason": reason, "at": iso()}, label="换代重出")
        js(paths.rejects, rj)
        L = jl(paths.ledger, {}) or {}
        L.setdefault(oid, {}).update(redo_exhausted=None, ladder_plan=[])
        js(paths.ledger, L)
        log_event(paths, "regen", obj=oid, reason=reason, by=by, counted=False)
        out["regen"].append(sid)
    return out


def status_json(paths: Paths, ep: int | None = None) -> dict:
    """status --json：episode_run 等外部编排器只读用（不在服务器上跑内联 python）。字段与 episode_run.IMAGE_SNAP 同口径"""
    reg = jl(paths.registry, {}) or {}
    ctl = jl(paths.ctrl, {}) or {}
    hb = jl(paths.heartbeat, {}) or {}

    def hold(f):
        return [x for x in (jl(paths.root / "data" / "autopilot" / f, {}) or {}).get("shots") or [] if not x.get("released")]
    eps = []
    for E in reg.get("episodes") or []:
        if ep and int(E.get("ep") or 0) != int(ep):
            continue
        shots = []
        for S in E.get("shots") or []:
            fo = (S.get("objects") or {}).get("first") or {}
            shots.append({"shot": S.get("shot"), "first": fo.get("status"),
                          "why": str(fo.get("last_error") or fo.get("waiting_for") or "")[:120]})
        eps.append({"ep": E.get("ep"), "headline": E.get("headline"), "shots": shots})
    return {"run": paths.run_id, "counts": reg.get("counts"), "episodes": eps, "paused": ctl.get("paused"),
            "hold_lanes": ctl.get("hold_lanes") or [], "only": ctl.get("only") or [],
            "pause_hold": hold("pause_hold.json"), "runaway_hold": hold("runaway_hold.json"),
            "heartbeat": hb.get("ts"), "server_now": iso()}


def shots_of_episode(paths: Paths, ep: int) -> list:
    reg = jl(paths.registry, {}) or {}
    for E in reg.get("episodes") or []:
        if int(E.get("ep") or 0) == int(ep):
            return [S["shot"] for S in E.get("shots") or [] if S.get("shot")]
    return []


def regen_cmd(paths: Paths, ep: int, shots: list, reason: str, by: str, presets: list | None = None, dry: bool = False) -> dict:
    norm = []
    for x in shots:
        x = x.strip()
        norm.append(f"ep{int(ep):02d}-S{x.lstrip('Ss')}" if re.fullmatch(r"[Ss]?\d+", x) else x)
    if not norm:
        if not ep:
            return {"regen": [], "error": "要 --episode N 或 --shots"}
        norm = shots_of_episode(paths, ep)
    if not norm:
        return {"regen": [], "error": f"登记表里找不到第 {ep} 集的镜"}
    return regen_shots(paths, norm, reason or "换代", by, presets, dry=dry)


def dispatch_ok_cfg(root: Path) -> bool:
    return cfg_flag(root, "auto_regen_on_change")


def shots_of_all(paths: Paths) -> list:
    reg = jl(paths.registry, {}) or {}
    return [S["shot"] for E in reg.get("episodes") or [] for S in E.get("shots") or [] if S.get("shot")]


def regen_signature(paths: Paths, sid: str) -> str | None:
    """auto_regen_on_change 的签名：本镜剧本输入（input_sig）+ 画风 / 契约配置（be_rule_sig）"""
    isg = input_sig(paths, sid)
    return None if isg is None else f"{isg}|{be_rule_sig(paths.root)}"


def auto_regen_check(paths: Paths, shots: list, by: str = "AUTO_REGEN") -> dict:
    """B2 可选（producer.json auto_regen_on_change，默认关）：签名变了的镜自动 regen；首次见到只记基线，不出图。
    签名记在 <pd>/regen_sigs.json"""
    f = paths.pd / "regen_sigs.json"
    sigs = jl(f, {}) or {}
    changed = []
    for sid in shots:
        sg = regen_signature(paths, sid)
        if sg is None:
            continue
        if sid not in sigs:
            sigs[sid] = sg
        elif sigs[sid] != sg:
            changed.append(sid)
            sigs[sid] = sg
    js(f, sigs)
    res = regen_shots(paths, changed, "导入稿 / 画风配置签名变化，自动换代", by) if changed else {"regen": [], "skipped": {}}
    res["changed"] = changed
    return res


def best_effort_objs(paths: Paths, shots: set[str] | None = None) -> list[dict]:
    """本剧 registry（paths.pd 按剧：V2 = data/producer/runs/<run>/registry.json，不读 V1 的 data/producer/）里还是“尽力”的首帧 / 尾帧"""
    reg = jl(paths.registry, {}) or {}
    return [o for E in reg.get("episodes") or [] for S in E.get("shots") or [] for k, o in (S.get("objects") or {}).items()
            if k in ("first", "last") and o.get("status") == "best_effort" and not o.get("redo")
            and (not shots or S.get("shot") in shots)]


def reset_best_effort_dry(paths: Paths, shots: set[str] | None = None) -> dict:
    """W33：reset-best-effort --dry：只列会被重置的对象 + 账本现值 + 全局 frames_v2 里被 W33 过滤掉的他剧尝试数，不暂停、不写任何文件"""
    L = jl(paths.ledger, {}) or {}
    raw = jl(paths.frames_v2, {}) or {}
    mine = fv2_for_run(paths, raw)
    rows = []
    for o in best_effort_objs(paths, shots):
        sid = o.get("shot") or o["id"].split(":", 1)[1]
        stg = "image" if o["id"].startswith("first:") else "last"
        r = L.get(o["id"]) or {}
        all_n = len(((raw.get(sid) or {}).get(stg) or {}).get("attempts") or [])
        own_n = len(((mine.get(sid) or {}).get(stg) or {}).get("attempts") or [])
        rows.append({"obj": o["id"], "reason": o.get("reason"), "ledger_tries": r.get("tries"), "ledger_final": r.get("final"),
                     "fv2_attempts_all": all_n, "fv2_attempts_this_run": own_n, "fv2_final_foreign": bool(
                         ((raw.get(sid) or {}).get(stg) or {}).get("final")) and not ((mine.get(sid) or {}).get(stg) or {}).get("final")})
    return {"run": paths.run_id, "registry": paths.registry.relative_to(paths.root).as_posix(),
            "ledger": paths.ledger.relative_to(paths.root).as_posix(),
            "would_reset": len(rows), "objs": rows}


def reset_best_effort(paths: Paths, why: str, by: str, shots: set[str] | None = None) -> int:
    """总调度 11-01：门槛 / 编译器更新后，仍是“尽力”的首帧 / 尾帧重新给 3 次（旧次数标 before_gate_change，不算）。
    安全做法：先暂停、等手上的活做完（heartbeat inflight=0，最多 15 分钟），改账本，再恢复原来的暂停状态。
    只动本剧（paths.pd 按剧）的 registry / ledger；W33：shots 给了只重置这些镜"""
    was = bool((jl(paths.ctrl, {}) or {}).get("paused"))
    set_paused(paths, True, by="reset-best-effort", kind="restart", expires_s=180)   # K-OPS-E08：运维暂停 ≤180 s
    t_end = now() + 170
    while now() < t_end and int((jl(paths.heartbeat, {}) or {}).get("inflight") or 0) > 0:
        time.sleep(10)
    objs = best_effort_objs(paths, shots)
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


def retry_obj(paths: Paths, oid: str, by: str, note: str = "") -> dict:
    """W20：总调度“放回重派”（资产 / 代码修好后不等 30 分钟 preflight 退避、不等签名变化）：
    清对象的 blocked_until / waiting_asset / backoff_until，assets:<镜> blocked=False；不动 tries / history（不计次）；写 log_event。
    只认 first:/last: 对象；返回改动前后的关键字段"""
    kind, _, sid = (oid or "").partition(":")
    if kind not in ("first", "last") or not sid:
        raise ValueError(f"retry 只认 first:<镜> / last:<镜>，收到 {oid!r}")
    L = jl(paths.ledger, {}) or {}
    r = L.setdefault(oid, {})
    keys = ("blocked_until", "waiting_asset", "backoff_until", "reason")
    before = {k: r.get(k) for k in keys}
    r.update(blocked_until=0, waiting_asset=None, backoff_until=0,
             reason=f"{by} 放回重派（不计次）" + (f"：{note}" if note else ""), retried_by={"by": by, "at": iso(), "note": note})
    a = L.get(f"assets:{sid}")
    a_before = (a or {}).get("blocked")
    if isinstance(a, dict) and a.get("blocked"):
        a.update(blocked=False, released_at=now(), released_by=by)
    js(paths.ledger, L)
    released = release_holds(paths, [sid], by, note or "retry 放回重派", files=("runaway_hold.json",))   # B2：同时释放 runaway 冻结
    log_event(paths, "retry", obj=oid, by=by, note=note, counted=False, before=before, assets_blocked_before=a_before,
              runaway_released=released)
    return {"obj": oid, "before": before, "assets_blocked_before": a_before, "tries": r.get("tries"), "runaway_released": released}


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


# ---------------------------------------------------------------------------------------------- W28：跨剧隔离（C-14 / L-126）
def _renders_rel(paths: Paths) -> str:
    """本剧渲染目录相对 data/ 的前缀（take.file 的口径）：V2 = renders/<run>/；legacy（V1 不带前缀）= renders/"""
    return paths.renders.relative_to(paths.data).as_posix().rstrip("/") + "/"


def _in_run_renders(paths: Paths, f: str, *, data_rel: bool) -> bool:
    """文件路径是否在本剧渲染目录下。data_rel=True：take.file 口径（相对 data/）；False：相对仓库根（frames_v2 口径）"""
    f = str(f or "").replace("\\\\", "/").replace("\\", "/").lstrip("./")
    if not f:
        return False
    if not data_rel:
        if not f.startswith("data/"):
            return False
        f = f[len("data/"):]
    pre = _renders_rel(paths)
    if not f.startswith(pre):
        return False
    if paths.primary:                              # legacy 不带前缀：renders/<别的剧>/… 不算本剧
        return bool(re.match(r"(ep\d+|_h3_keyframes)/", f[len(pre):]))
    return True


def fv2_attempt_run_ok(paths: Paths, a: dict) -> bool:
    """frames_v2/state.json 的一条尝试是否属于本剧：run 字段 == 本剧，或文件在 data/renders/<run>/ 下"""
    r = a.get("run")
    if r:
        return r == paths.run_id
    return _in_run_renders(paths, a.get("file") or "", data_rel=False)


def fv2_proc_run_ok(paths: Paths, cmdline: str) -> bool:
    """W33：一条 frames_v2.py 进程是不是在做本剧：命令行带 --run X / NS_RUN=X → X == 本剧；不带 = 旧行为 = legacy（V1）"""
    m = re.search(r"--run[=\s]+(\S+)", cmdline or "") or re.search(r"\bNS_RUN=(\S+)", cmdline or "")
    if m:
        return m.group(1).strip("'\"") == paths.run_id
    return bool(paths.primary)


def _fv2_final_run_ok(paths: Paths, fin: dict, own_files: set[str]) -> bool:
    """final 属于本剧：带 run 字段 → 等于本剧；否则 final.file 是本剧某条尝试的文件或在本剧渲染目录下"""
    if fin.get("run"):
        return fin["run"] == paths.run_id
    f = fin.get("file") or ""
    return bool(f) and (f in own_files or _in_run_renders(paths, f, data_rel=False))


def fv2_for_run(paths: Paths, fv: dict) -> dict:
    """W33（C-14 / L-126）：data/assetmaster/frames_v2/state.json 是全局文件、按镜号不按剧。
    registry 读之前过滤：每镜每阶段只留 fv2_attempt_run_ok 的尝试；final 只在属于本剧时保留（V1 的“不合格”不再把 V2 判尽力）；
    job.preflight 只在本阶段还有本剧尝试 / final 时保留。V1（legacy）自己读 = 原样（行为不变）"""
    if paths.primary:
        return fv
    out: dict = {}
    for sid, rec in (fv or {}).items():
        if not isinstance(rec, dict):
            continue
        nrec: dict = {}
        for stg, v in rec.items():
            if not isinstance(v, dict) or not ({"attempts", "final", "job"} & set(v)):
                if stg == "run" and v == paths.run_id:
                    nrec[stg] = v
                continue
            atts = [a for a in v.get("attempts") or [] if isinstance(a, dict) and fv2_attempt_run_ok(paths, a)]
            own = {a.get("file") for a in atts if a.get("file")}
            nv = {}
            if atts:
                nv["attempts"] = atts
            fin = v.get("final")
            if isinstance(fin, dict) and fin and _fv2_final_run_ok(paths, fin, own):
                nv["final"] = fin
            if nv and v.get("job") is not None:
                nv["job"] = v["job"]
            if nv:
                nrec[stg] = nv
        if nrec:
            out[sid] = nrec
    return out


def run_role_ids(paths: Paths) -> set[str]:
    """本剧角色表：P1_looks.json[].char_id ∪ P1_storyline.json characters[].char_id ∪ 资产包清单 characters（runs.json assets_manifest）"""
    ids: set[str] = set()
    for c in jl(paths.run / "P1_looks.json", []) or []:
        if isinstance(c, dict) and c.get("char_id"):
            ids.add(c["char_id"])
    for c in (jl(paths.run / "P1_storyline.json", {}) or {}).get("characters") or []:
        if isinstance(c, dict) and c.get("char_id"):
            ids.add(c["char_id"])
    try:
        ent = ((jl(paths.root / "config" / "pipeline" / "runs.json", {}) or {}).get("runs") or {}).get(paths.run_id) or {}
        man = ent.get("assets_manifest")
        if man:
            ids |= set((jl(paths.root / man, {}) or {}).get("characters") or {})
    except Exception:  # noqa: BLE001
        pass
    return ids


def take_identity_ids(t: dict) -> set[str]:
    """postflight 身份项（Q1）里出现的角色 id：evidence.sims 的键 + evidence.ref 的键与值"""
    out: set[str] = set()
    for pf in (t.get("postflight"), (t.get("params") or {}).get("postflight")):
        for it in (pf or {}).get("items") or [] if isinstance(pf, dict) else []:
            if not isinstance(it, dict) or it.get("id") != "Q1":
                continue
            ev = it.get("evidence") or {}
            out |= {k for k in (ev.get("sims") or {}) if isinstance(k, str)}
            ref = ev.get("ref") or {}
            if isinstance(ref, dict):
                out |= {x for x in list(ref) + list(ref.values()) if isinstance(x, str)}
    return out


def foreign_reasons(paths: Paths, t: dict, roles: set[str], rules: set[str]) -> list[str]:
    """判据：origin = 从全局 frames_v2 认领、却没带本剧 src_run（W28 前的 adopt 全是这种）；role = 身份项角色不在本剧角色表；
    path = take.file 不在 data/renders/<run>/ 下（注意：ns_render 写版本时 rel 丢了剧名前缀，V2 自己出的图也会命中，缺省不开）"""
    why = []
    o = (t.get("params") or {}).get("origin") or {}
    if "origin" in rules and o.get("run") == "assetmaster/frames_v2" and o.get("src_run") != paths.run_id:
        why.append(f"origin：从全局 frames_v2 认领（{o.get('registered_at') or '?'}），不带本剧剧名")
    if "path" in rules and not _in_run_renders(paths, t.get("file") or "", data_rel=True):
        why.append(f"path：文件不在 data/{_renders_rel(paths)} 下（{t.get('file')}）")
    if "role" in rules and roles:
        bad = sorted(take_identity_ids(t) - roles)
        if bad:
            why.append(f"role：身份项角色 {','.join(bad)} 不在本剧角色表")
    return why


def quarantine_foreign(paths: Paths, *, apply: bool, rules: set[str] | None = None, by: str = "PRODUCER quarantine-foreign",
                       ts: str | None = None, mutate=None) -> dict:
    """W28：扫本剧全部 takes.json，他剧 / V1 混进来的版本 → takes.json 的 quarantined[]（保留全部字段 + 原因 + 时间）。
    文件在本剧目录内 → 移到 data/quarantine/<run>/<ts>/（只移不删）；不在本剧目录的文件不动。current / 定稿指向它 → 清空并记原因。
    dry（apply=False）只出清单，不写任何文件。mutate = takes.json 写入口（缺省 ns_render.pipeline.mutate_takes(path=…)）"""
    rules = set(rules or {"origin", "role"})
    ts = ts or time.strftime("%Y%m%d-%H%M%S")
    roles = run_role_ids(paths)
    qdir = paths.data / "quarantine" / paths.run_id / ts
    rows, shots = [], 0
    for tj in sorted(paths.renders.glob("ep*/S*/takes.json")):
        if paths.primary and tj.parent.parent.parent != paths.renders:
            continue
        doc = jl(tj, {}) or {}
        sid = f"{tj.parent.parent.name}-{tj.parent.name}"
        hits = []
        for t in doc.get("takes") or []:
            why = foreign_reasons(paths, t, roles, rules)
            if why:
                stg, n = t.get("stage"), t.get("n")
                hits.append({"shot": sid, "stage": stg, "n": n, "file": t.get("file"), "why": why,
                             "current": (doc.get("active") or {}).get(stg) == n,
                             "locked": (doc.get("locked") or {}).get(stg) == n,
                             "file_in_run": _in_run_renders(paths, t.get("file") or "", data_rel=True)})
        if not hits:
            continue
        shots += 1
        if apply:
            moved = {}
            for h in hits:
                src = paths.data / str(h["file"] or "")
                if h["file_in_run"] and src.is_file():
                    dst = qdir / "files" / Path(str(h["file"]))
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                    moved[(h["stage"], h["n"])] = dst.relative_to(paths.root).as_posix()
                    h["moved_to"] = moved[(h["stage"], h["n"])]

            def _fn(d, _hits=hits, _moved=moved):
                keys = {(h["stage"], h["n"]): h for h in _hits}
                keep, q = [], d.setdefault("quarantined", [])
                for t in d.get("takes") or []:
                    h = keys.get((t.get("stage"), t.get("n")))
                    if not h:
                        keep.append(t)
                        continue
                    rec = {**t, "quarantine": {"why": h["why"], "at": iso(), "by": by, "batch": ts,
                                               "moved_to": _moved.get((t.get("stage"), t.get("n")))}}
                    for k in ("active", "locked"):
                        if (d.get(k) or {}).get(t.get("stage")) == t.get("n"):
                            d[k].pop(t.get("stage"))
                            rec["quarantine"][f"{k}_cleared"] = f"{k} 指向跨剧版本 v{t.get('n')}，已清空（W28 隔离）"
                    q.append(rec)
                d["takes"] = keep
                return d
            if mutate is None:
                from ns_render import pipeline as P
                P.mutate_takes(sid, _fn, op="producer.quarantine_foreign", by=by, op_id=f"quarantine_foreign:{ts}:{sid}", path=tj)
                for h in hits:
                    if h["current"]:
                        P.audit_active(sid, h["stage"], h["n"], None, f"W28 跨剧隔离：{'；'.join(h['why'])}", by)
            else:
                mutate(tj, _fn)
        rows += hits
    out = {"run": paths.run_id, "mode": "apply" if apply else "dry", "ts": ts, "rules": sorted(rules),
           "role_table": sorted(roles), "role_rule": "on" if roles and "role" in rules else "off（角色表为空或未启用）",
           "shots": shots, "takes": len(rows),
           "by_rule": {r: sum(1 for x in rows if any(w.startswith(r + "：") for w in x["why"])) for r in sorted(rules)},
           "current": sum(1 for x in rows if x["current"]), "locked": sum(1 for x in rows if x["locked"]),
           "files_in_run": sum(1 for x in rows if x["file_in_run"]), "rows": rows}
    if apply and rows:
        js(qdir / "manifest.json", out)
        log_event(paths, "quarantine_foreign", takes=len(rows), shots=shots, dir=qdir.relative_to(paths.root).as_posix(),
                  by=by, counted=False)
    return out


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["serve", "once", "status", "pause", "resume", "dryrun", "rescore", "reject", "approve", "unwait", "uncap", "retry", "reset-best-effort", "review-adopt", "import-staged",
                                        "quarantine-foreign", "regen", "unhold"])
    ap.add_argument("--obj", default="")
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--reason", default="")
    ap.add_argument("--plan", default="frame_v9,frame_v9", help="reject：驳回重出计划（预设，逗号分隔）")
    ap.add_argument("--wait-for", default="")
    ap.add_argument("--edit-file", default="", help="reject：项目方“修改”的记录（JSON：id / text / prompt / zh_summary），出图时追加进提示词")
    ap.add_argument("--items", default="Q4,Q5,Q8", help="rescore：只重打“没过的项全在这里面”的版本")
    ap.add_argument("--only", default="")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--no-dispatch", action="store_true")
    ap.add_argument("--by", default="owner")
    ap.add_argument("--note", "--why", dest="note", default="")
    ap.add_argument("--shots", default="", help="pause：只停这些镜（逗号分隔，默认做法）；不写 = 整条道全局暂停（必须带 --kind）")
    ap.add_argument("--minutes", type=float, default=60, help="pause --shots：多少分钟后自动失效")
    ap.add_argument("--run", default="", help="import-staged：目标剧（config/pipeline/runs.json）；不写 / 主剧 = 合并进主导入稿，其它 = data/import/runs/<run>/")
    ap.add_argument("--kind", default="", choices=["", "ops", "line_switch", "restart", "deploy", "master", "owner"],
                    help="pause 的 reason_kind：line_switch / restart / deploy = 运维暂停（≤180 s 到点恢复）；master / owner = 显式暂停（不自动恢复，超 180 s 报警）；不写按 --by 推断")
    ap.add_argument("--expires-s", type=float, default=0, help="pause：到点自动恢复的秒数（ops 上限 180）")
    ap.add_argument("--inject-fail", action="store_true")
    ap.add_argument("--dry", action="store_true", help="quarantine-foreign：只出清单（缺省即 dry）；reset-best-effort：只列会重置的对象（W33）；regen：只列会换代的镜，不写任何文件")
    ap.add_argument("--apply", action="store_true", help="quarantine-foreign：真的隔离（只移不删，写 manifest）")
    ap.add_argument("--rules", default="origin,role", help="quarantine-foreign：判据 origin / role / path（逗号分隔；path 在 ns_render 路径前缀修好前会误伤本剧版本）")
    ap.add_argument("--episode", type=int, default=0, help="regen / status --json：集号")
    ap.add_argument("--json", action="store_true", help="status：机器可读 JSON（登记表摘要 + pause_hold / runaway_hold / hold_lanes / 心跳）")
    ap.add_argument("--force", action="store_true", help="approve：跳过“契约没过拒绝”的保护（B2）")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--skip-rubric-gate", action="store_true", help="import-staged：跳过 rubric 导入闸门（只有总调度能批，--by 须写总调度，记审计）")
    a = ap.parse_args(argv)
    run = (a.run or "").strip() or default_run()
    if a.cmd == "quarantine-foreign":               # W28：只读扫描 / 隔离，不起进程、不改 ns_render 环境（冒烟剧也能扫）
        if a.apply and a.dry:
            print("--dry 与 --apply 只能选一个", file=sys.stderr)
            return 2
        r = quarantine_foreign(Paths(run_id=run), apply=a.apply, rules={x for x in a.rules.split(",") if x},
                               by=a.by if a.by != "owner" else "PRODUCER quarantine-foreign")
        print(json.dumps({k: v for k, v in r.items() if k != "rows"}, ensure_ascii=False, indent=1))
        for x in r["rows"]:
            print(json.dumps(x, ensure_ascii=False))
        return 0
    if a.run and a.cmd != "import-staged" and not _runs().is_registered(run):   # PRODMERGE-O：--run 只认 runs.json 登记的剧
        print(f"--run {run} 不在 config/pipeline/runs.json（只认登记表里的剧）", file=sys.stderr)
        return 2
    if a.cmd != "import-staged":                    # 导入时还没有该剧的导入稿，不能把 ns_render 指过去（rubric 闸门要读主剧结构）
        os.environ.update(run_env(run))             # K-OPS-E15：非主剧进程的渲染 / 导入稿目录（ns_render 在函数里才 import）
    paths = Paths(run_id=run) if a.cmd != "import-staged" else Paths()
    if a.cmd == "serve":
        return serve(paths, pinned=bool((a.run or "").strip()))
    if a.cmd == "reject":
        edit = json.loads(Path(a.edit_file).read_text(encoding="utf-8")) if a.edit_file else None
        return master_reject(paths, a.obj, a.n, a.reason, a.plan.split(","), a.wait_for or None, a.by, edit)
    if a.cmd == "reset-best-effort":
        shots = {x.strip() for x in a.shots.split(",") if x.strip()} or None
        if a.dry:                                   # W33：只出清单，不暂停、不改账本
            print(json.dumps(reset_best_effort_dry(paths, shots), ensure_ascii=False, indent=1))
            return 0
        return reset_best_effort(paths, a.note or "门槛 / 编译器更新后重新给 3 次（总调度 11-01）", a.by, shots)
    if a.cmd == "import-staged":          # 总调度派的整稿导入（走 PRODUCER 令牌通道）：--obj <暂存稿路径> --reason <sha256> --note
        return import_staged(paths, a.obj, a.reason, a.note, a.by, skip_rubric_gate=a.skip_rubric_gate, run=a.run or None)
    if a.cmd == "review-adopt":           # L-183 手工：--obj first:ep01-S4 [--n N]（不给 N = Q1–Q9 全过里分数最高的一版）
        r = review_adopt(paths, a.obj, a.n or None, by=a.by, relaxed=True)   # L-196：没有全过版也取最高分版
        if r:                             # 与主循环同口径：账本改 passed（否则对象仍按“尽力”推导，尾帧 / 视频不往下走）
            L = jl(paths.ledger, {}) or {}
            L.setdefault(a.obj, {}).update(final="passed", hard_capped=None,
                                           reason=f"L-183 取 v{r}（Q1–Q9 全过）设为当前，待项目方复核（{a.by}）")
            js(paths.ledger, L)
        print(json.dumps({"obj": a.obj, "adopted": r}, ensure_ascii=False))
        return 0 if r else 1
    if a.cmd == "uncap":                  # K-OPS-E28：人工看过后多放 N 次（24 小时有效），不清计数
        L = jl(paths.ledger, {}) or {}
        L.setdefault(a.obj, {}).update(cap_extra={"n": max(1, a.n or 3), "t": now(), "at": iso(), "by": a.by, "note": a.note},
                                        hard_capped=None)
        js(paths.ledger, L)
        log_event(paths, "uncap", obj=a.obj, n=max(1, a.n or 3), by=a.by, note=a.note, counted=False)
        return 0
    if a.cmd == "retry":                  # W20：放回重派（清 blocked / 等资产 / 退避，assets 解挡，不计次）
        print(json.dumps(retry_obj(paths, a.obj, a.by, a.note), ensure_ascii=False))
        return 0
    if a.cmd == "unwait":                 # 驳回重出在等的前提（如 REFLOCK 修 Q1）满足了 → 放行
        rj = jl(paths.rejects, {}) or {}
        if a.obj in rj:
            rj[a.obj]["wait"] = None
            js(paths.rejects, rj)
            log_event(paths, "unwait", obj=a.obj, by=a.by)
        return 0
    if a.cmd == "approve":
        return master_approve(paths, a.obj, a.n, a.by, a.note, force=a.force)
    if a.cmd == "unhold":
        print(json.dumps(unhold(paths, a.obj, a.by, a.note), ensure_ascii=False))
        return 0
    if a.cmd == "regen":
        r = regen_cmd(paths, a.episode, [x for x in a.shots.split(",") if x.strip()], a.reason or a.note, a.by, a.plan.split(","),
                      dry=a.dry)
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r.get("regen") else 1
    if a.cmd == "resume" and a.shots:
        print(json.dumps(resume_shots(paths, [x for x in a.shots.split(",") if x], a.by, a.note), ensure_ascii=False))
        return 0
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
    if a.cmd == "status" and a.json:
        print(json.dumps(status_json(paths, a.episode or None), ensure_ascii=False))
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
    pr.frames = FrameExec(paths, pr.script(), script_fn=pr.script)
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
