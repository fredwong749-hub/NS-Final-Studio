"""VIDEO10 夜间按集推进驱动（笔记本端，项目方 10-31 夜：“按照剧本……把 10 集都做完……每集自查、修、再下一集”）。

每 120 s 一轮：
 1. 资料闸门：一集的每个镜都有“过契约并设为当前”的首帧（build_jobs.passed_frames：takes.json postflight.ok 或
    video/frames_ok.json 的 ASSETMASTER 通知；frames_ok.json 的 "_episodes_done": [n] 也算整集就绪）→ 该集就绪。
    night_control.json 的 "force_eps" 可强制放行（露脸镜走纯 Ref2VA，无人露脸镜没首帧不出）。
 2. 新就绪的集：选主机（两台里“可用道多、排队少”的那台；可用道 = 不在别人手里的道），写 video/hosts.json，
    重新编译 jobs.json（build_jobs，系统编译器），推 jobs + 输入图，control 里加上这一集，编排器没跑就起。
 3. 已派出的集：同步 state；整集每镜都定下（通过 / 尽力 / 等首帧）→ 服务器出 540×960 合成代理 → 拉回 →
    tools/assemble_episode.py（预览模式、剪辑规则 post.edit_rules、旁白 narrator QAg；series10 没有自己的 BGM 时 --no-bgm）
    → data/episodes/series10/epNN_v1.mp4 → episode_report.py 写 docs/series10_video/epNN_review.md 与
    data/review_pages/series10_video/epNN/index.html（不自动打开，交总调度亲审）。
状态：video/night_state.json；日志 video/night.log；对外摘要 docs/series10_video/STATUS.md（总调度看这个）。

    .venv/Scripts/python.exe tools/series10_video/night.py            # 常驻
    .venv/Scripts/python.exe tools/series10_video/night.py --once
    .venv/Scripts/python.exe tools/series10_video/night.py --run series10_v2      # MERGE-VID-O：按剧（不给 = NS_RUN / 当前剧）
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
import os  # noqa: E402
import run_ctx as RC  # noqa: E402

# MERGE-VID-O（ISS-1103-024206-3737，L-137）：按剧（--run / NS_RUN / 当前剧；没登记 / 没视频政策 → 失败关闭）。
# 子进程（build_jobs / deploy / sync / register_takes / upscale_preview / episode_report / assemble）一律继承 NS_RUN
RUN_ID = RC.resolve()
os.environ["NS_RUN"] = RUN_ID
LEGACY = RC.is_legacy(RUN_ID)
VID_REL = RC.vid_rel(RUN_ID)
VID = ROOT / VID_REL
PIDF = "run/vidgen.pid" if LEGACY else f"run/vidgen_{RUN_ID}.pid"
def _video_root() -> str:
    """PRODMERGE-O 11-03：服务器视频代码根只从 config/factory/hosts.json video_root 取（= 发版部署目录，video10_srv 退役）"""
    import importlib.util as _u
    sp = _u.spec_from_file_location("hosts_video_root", Path(__file__).resolve().parents[2] / "tools" / "factory" / "hosts.py")
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m.video_root()


DEST = _video_root()
PY = str(ROOT / ".venv/Scripts/python.exe")
STATE = VID / "night_state.json"
CTRL = VID / "night_control.json"
LOG = VID / "night.log"
STATUS = ROOT / ("docs/series10_video/STATUS.md" if LEGACY else f"docs/series10_video/{RUN_ID}/STATUS.md")
EPS_OUT = RC.episodes_out(RUN_ID)        # V1 = data/episodes/series10（原样），其它剧 = data/episodes/<剧>
# 道归属（总调度 10-31 夜）：gpu33 三道 = 出图优先（让道模式）；gpu36:0/1 = BAKEOFF（让道模式，可写 hold 文件借用）；gpu36:2 = 视频
DEFAULT_CTRL = {"force_eps": [], "shared_lanes": ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1"],
                "hold_lanes": [], "per_lane": 2, "yield_s": 180, "bgm": "auto"}


def log(*a):
    line = time.strftime("%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def js(p, d):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


_CHILD_PATHS = ("", "services/post", "services/agent", "services/recipes", "services/render_router", "services/api",
                "packages/schema", "packages/qc")


def child_env() -> dict:
    """子进程环境：服务器 venv 没有 pip install -e 本项目（ns_schema / ns_agent / ns_post 导不进）→ 一律把仓库里的包目录
    放进 PYTHONPATH（口径同 tools/ 下各脚本的 sys.path.insert），不依赖安装方式。已有 PYTHONPATH 保留在后面"""
    paths = [str(ROOT / p) if p else str(ROOT) for p in _CHILD_PATHS]
    old = os.environ.get("PYTHONPATH")
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": os.pathsep.join(paths + ([old] if old else []))}


def run(args, timeout=3600):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       cwd=str(ROOT), env=child_env())
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def ssh(host, cmd, timeout=600):
    r = _rssh().run_retry(host, cmd, timeout=timeout, tries=1, text=True)   # 原来不重试：tries=1；返回 stdout + stderr 文本
    return (r.stdout or "") + (r.stderr or "")

def _rssh():
    """K-OPS-N07 / SYSARCH 4-1：远程命令统一走 tools/netfix/rssh.run_retry（笔记本走常驻主连接；服务器上 OFFLINE_SELF 调本机 = 本机执行）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_rssh_41", Path(__file__).resolve().parents[2] / "tools/netfix/rssh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod



def lane_load(host) -> dict:
    ports = {"gpu33": [8188, 8189, 8191], "gpu36": [8188, 8189, 8190]}[host]
    cmd = "; ".join(f"printf '{p} '; curl -s -m5 localhost:{p}/queue | python3 -c \"import sys,json;d=json.load(sys.stdin);"
                    f"it=d['queue_running']+d['queue_pending'];m=sum(1 for i in it if str((i[3] or {{}}).get('client_id','')).startswith('video10-'));"
                    f"print(m, len(it)-m)\" 2>/dev/null || echo x x" for p in ports)
    out = {}
    for ln in ssh(host, cmd, 60).splitlines():
        parts = ln.split()
        if len(parts) == 3 and parts[1] != "x":
            out[int(parts[0])] = (int(parts[1]), int(parts[2]))
    return out


def _B():
    import build_jobs as B
    if B.RUN_ID != RUN_ID:
        B.set_run(RUN_ID)
    return B


def specs_by_ep():
    B = _B()
    sp = B.load_specs(source="import")
    eps = {}
    for sid, s in sp.items():
        eps.setdefault(s.episode, []).append(s)
    return eps


def ready_eps(eps_specs, ctrl) -> list[int]:
    B = _B()
    pf = B.passed_frames()
    ok = jl(B.FRAMES_OK, {}) or {}
    done = set(ok.get("_episodes_done") or []) | set(ctrl.get("force_eps") or [])
    for ep in ctrl.get("force_eps") or []:
        led = ROOT / "knowledge/RSI_LEDGER.md"
        mark = f"<!-- VIDEO10 force_eps ep{int(ep):02d} -->"
        if mark not in led.read_text(encoding="utf-8"):
            with open(led, "a", encoding="utf-8") as f:
                f.write(f"\n{mark}\n- VIDEO10 {time.strftime('%Y-%m-%d %H:%M')}：force_eps 强制放行 ep{int(ep):02d}"
                        f"（首帧未全部过契约；night_control.json 设置；没有首帧的无人露脸镜不出）\n")
    return [ep for ep, ss in sorted(eps_specs.items()) if ep in done or all(s.id in pf for s in ss)]


def ready_shots(eps_specs, ctrl) -> dict[int, list[str]]:
    """→ {集: [首帧已过契约的镜]}（逐镜派单用；force_eps 的集全部镜都算就绪）"""
    B = _B()
    pf = B.passed_frames()
    force = set(ctrl.get("force_eps") or [])
    out = {}
    for ep, ss in sorted(eps_specs.items()):
        ids = [s.id for s in ss if s.id in pf or ep in force]
        if ids:
            out[ep] = ids
    return out, {sid: v.get("file") for sid, v in pf.items()}


def pick_host(st) -> str:
    """可用道多、已派镜头少的那台（gpu36:2 视频专用道算 1；让道道只在空闲时算）"""
    score = {}
    for h in _hosts_here():      # A-07：服务器上只管本机（原来 resident_prep 就地改源码）
        busy = ssh(h, f"cd {DEST} 2>/dev/null && [ -f {PIDF} ] && kill -0 $(cat {PIDF}) 2>/dev/null && "
                      f"grep -q validate_jobs {VID_REL}/control_{h}.json && echo VALIDATING", 60)
        if "VALIDATING" in busy:
            continue
        try:
            ll = lane_load(h)
        except Exception:  # noqa: BLE001
            ll = {}
        free = sum(1 for p, (m, f) in ll.items() if f == 0) + (1 if h == "gpu36" else 0)
        pend = sum(n for e, n in st.get("pending_shots", {}).items() if st["eps"].get(e, {}).get("host") == h)
        score[h] = free * 10 - pend
    return max(score, key=score.get) if score else None


def dispatch_hosts(hosts_touched: set, st, ctrl) -> bool:
    """重新编译 jobs.json（只给首帧过契约的镜出变体），推到涉及的主机，更新 control 的集列表，编排器没跑就起"""
    if not ((sys.path.append(str(ROOT)) if str(ROOT) not in sys.path else None) or __import__("tools.master.sop_gate", fromlist=["_"]).video_dispatch_ok(VID_REL, ROOT)): return False  # HARNESS-O：SOP 阶段闸门  # noqa: E701
    rc, out = run([PY, "tools/series10_video/build_jobs.py"], 1800)
    log("build_jobs", rc, out.strip()[-300:].replace("\n", " "))
    if rc:
        return False
    hosts = jl(VID / "hosts.json", {}) or {}
    rs = _rssh()
    for host in sorted(hosts_touched):
        # DEBUG-RSI（总调度 FOCUS 第 5 条，11-02 16:1x）：两台各跑一个 night，服务器之间没有 ssh 互信。分给另一台的集推不过去，
        # 以前这里 return False → ready_sig 不更新 → 每轮重推本机 8 MB、另一台那几集永远派不出（ep07 / 09 / 10 视频 31 条卡住）。
        # 现在跳过另一台（它的集由那台自己的 night 派），不算失败
        if getattr(rs, "_local_self", lambda h: None)(host) == "other":
            log("SKIP_OTHER_HOST", host, "服务器之间不推（无互信），这台的集由它自己的 night 派")
            continue
        rc, out = run([PY, "tools/series10_video/deploy.py", "push", host], 3600)
        log("push", host, rc, out.strip()[-200:].replace("\n", " "))
        if rc:
            return False
        eps_on = _eps_on(hosts, host)
        hold, per_lane, shared = ctrl.get("hold_lanes", []), ctrl["per_lane"], ctrl.get("shared_lanes", [])
        if ctrl.get("ep01_lane") and host == hosts.get("1"):
            hold = [x for x in IMAGE_LANES if x != "gpu33:3"]
            eps_on, per_lane, shared = [1], 1, [x for x in shared if x != "gpu33:3"]
        hold, gate = video_boost(ctrl, hold)
        hold = _shard_hold(host, hold)
        c = {"jobs": "jobs.json", "mode": "prod", "eps": eps_on, "per_lane": per_lane, "linger": True,
             "hold_lanes": hold, "shared_lanes": shared, "yield_s": ctrl["yield_s"]}
        if gate:
            c["vram_gate"] = gate
        run([PY, "tools/series10_video/deploy.py", "control", host, json.dumps(c, ensure_ascii=False)])
        run([PY, "tools/series10_video/deploy.py", "start", host])
        log("DISPATCH", host, "eps", eps_on, "hold", hold)
    return True


def dispatch(ep, host, st, ctrl):   # 旧接口（整集派单），保留给手工调用
    hosts = jl(VID / "hosts.json", {}) or {}
    hosts[str(ep)] = host
    js(VID / "hosts.json", hosts)
    rc, out = run([PY, "tools/series10_video/build_jobs.py"], 1800)
    if rc:
        return False
    rc, out = run([PY, "tools/series10_video/deploy.py", "push", host], 3600)
    if rc:
        return False
    eps_on = sorted({int(e) for e, h in hosts.items() if h == host and st["eps"].get(e, {}).get("dispatched")} | {ep})
    c = {"jobs": "jobs.json", "mode": "prod", "eps": eps_on, "per_lane": ctrl["per_lane"], "linger": True,
         "hold_lanes": ctrl.get("hold_lanes", []), "shared_lanes": ctrl.get("shared_lanes", []), "yield_s": ctrl["yield_s"]}
    run([PY, "tools/series10_video/deploy.py", "control", host, json.dumps(c, ensure_ascii=False)])
    run([PY, "tools/series10_video/deploy.py", "start", host])
    st["eps"][str(ep)] = {"host": host, "dispatched": time.time(), "status": "rendering"}
    log("DISPATCH", f"ep{ep:02d}", "→", host, "eps", eps_on)
    return True


def _VS():
    """视频按镜分片模块（默认关；服务器镜像没带 = None → 全部走原逻辑）"""
    try:
        import video_shard as VS
        return VS
    except ImportError:   # arch-ok: 没有分片模块 = 不分片
        return None


def _shard_cfg(ep) -> dict | None:
    VS = _VS()
    return VS.ep_cfg(RUN_ID, int(ep)) if VS else None


def _eps_on(hosts: dict, host: str) -> list[int]:
    """本机该出的集：按集归属 ∪（开了分片时）分片集里本机是分片台的；分片关 = 原来的 sorted(int(e) for e, h in hosts.items() if h == host)"""
    VS = _VS()
    return VS.eps_on_host(RUN_ID, host, hosts) if VS else sorted(int(e) for e, h in hosts.items() if h == host)


def _eps_on_shard(host: str) -> bool:
    VS = _VS()
    return bool(VS) and any(host in c["hosts"] for c in VS.shard_eps(RUN_ID).values())


def _shard_hold(host: str, hold: list) -> list:
    """分片开着：本机不适合跑 H3 的道（gpu33:3 = 看图 + reserve-vram 9）并进挂道；关 = 原样"""
    VS = _VS()
    ex = VS.exclude_lanes(host) if VS else []
    return sorted(set(hold) | set(ex)) if ex and _eps_on_shard(host) else hold


def ep_shots(ep, host) -> dict:
    """这一集的镜状态：没分片 = state_<host>.json 里本集的镜（原行为）；分片 = 各分片台 state 合并（owner 上 helper 的 state 由 shard_relay 送来，只读）"""
    if _shard_cfg(ep):
        VS = _VS()
        return VS.merged_shots(VID, int(ep), VS.ep_hosts(RUN_ID, int(ep), host), jl(VID / "jobs.json", {}) or {})
    stt = jl(VID / f"state_{host}.json", {}) or {}
    return {sid: r for sid, r in (stt.get("shots") or {}).items() if int(sid[2:4]) == int(ep)}


def ep_sig(ep, host) -> str:
    return json.dumps({sid: [r.get("status"), r.get("chosen"), len(r.get("renders") or [])]
                       for sid, r in sorted(ep_shots(ep, host).items())}, ensure_ascii=False)


def ep_resolved(ep, host) -> tuple[bool, dict]:
    shots_st = ep_shots(ep, host)
    jobs = jl(VID / "jobs.json", {}) or {}
    ids = [s["shot"] for s in jobs.get("shots", []) if s["ep"] == ep]
    recs = {sid: shots_st.get(sid, {}) for sid in ids}
    fin = all(r.get("status") in ("done", "best_effort", "blocked") for r in recs.values()) and ids
    return bool(fin), recs


def voices_ok() -> bool:
    """总调度 11-01：config/voices.json 还是旧 60 集的 Kokoro 演员表（林晚 = zf_067 等），series10 声音没重做前不合成成片。
    voices.json 顶层 "series" 标成 "series10_v1"（由声音负责方改）后才放行。
    MERGE-VID-O：非 V1 剧按 ns_post.run_media.voice_config(<剧>)（config/voices_v2.json，L-132）——取不到 / sha 不符 → 不合成"""
    if not LEGACY:
        try:
            if str(ROOT / "services" / "post") not in sys.path:
                sys.path.insert(0, str(ROOT / "services" / "post"))
            from ns_post import run_media as RM
            return (RM.voice_config(RUN_ID, ROOT) or {}).get("series") == RUN_ID
        except Exception as e:  # noqa: BLE001  # arch-ok: 音色没登记 = 不合成（hold_voices，失败关闭）
            log("VOICES", RUN_ID, str(e)[:200])
            return False
    v = jl(ROOT / "config/voices.json", {}) or {}
    return v.get("series") == "series10_v1"


def tts_missing() -> str | None:
    """K-OPS-309：合成前检查本机配音解释器（config/voices.json speech_python：环境变量 NS_TTS_PYTHON 或 default 路径）。
    缺 → 返回原因（不合成、不耗版本号，状态 hold_tts，装好后下一轮自动继续）
    VOICE10 11-01（K-EDT-021）：改调 ns_post.tts.tts_preflight，一次查完解释器 + 模型目录 + 每个角色音色 / 参考音频 /
    ref_text / 远端模型；导入失败才退回只查解释器的旧逻辑"""
    import os
    try:
        if str(ROOT / "services" / "post") not in sys.path:
            sys.path.insert(0, str(ROOT / "services" / "post"))
        from ns_post.tts import tts_preflight
        from ns_post import run_media as RM
        # W16 / REVIEW-G4b P0-1：音色表按剧取（C-14；旧写法不传 run → 资产包剧 VoiceRunRequired → 每集永远 hold_tts）
        try:
            cfg = RM.voice_config(RUN_ID, ROOT)
        except (RM.V2MediaError, OSError, ValueError, RuntimeError) as e:  # arch-ok: 音色表读不了 = hold_tts（失败关闭）
            return f"音色表读不了：{e}"
        miss = tts_preflight(cfg, root=ROOT, run=RUN_ID)
        return "；".join(miss) if miss else None
    except ImportError:
        pass
    v = jl(ROOT / "config/voices.json", {}) or {}
    sec = v.get("speech_python") or {}
    cands = [os.environ.get(sec.get("env") or "NS_TTS_PYTHON"), sec.get("default")]
    if any(c and Path(c).exists() for c in cands):
        return None
    return f"没有配音解释器：{sec.get('env') or 'NS_TTS_PYTHON'} 未设，default {sec.get('default')} 不存在"


ASM_RETRY_S, ASM_RETRY_MAX = 1200, 3


def retry_assembly(st) -> None:
    """K-OPS-309：assemble_failed / hold_tts 不是终态。hold_tts：配音解释器到位就回到 rendering；
    assemble_failed：距上次合成 ≥ 20 分钟且自动重试 < 3 次 → 回到 rendering（走同一条 EP_RESOLVED → finalize 流程，
    版本号照常递增）；超过 3 次停在 assemble_failed，交总调度看 assemble_err"""
    for e, x in st["eps"].items():
        s = x.get("status")
        # W46：hold_voices 原来是死胡同（音色资产后到 → 本集永远不合成）；音色到位就回到 rendering
        if s == "hold_voices" and voices_ok():
            x["status"] = "rendering"
            log("RETRY_ASSEMBLE", f"ep{int(e):02d}", "音色表已到位")
        elif s == "hold_tts" and not tts_missing():
            x["status"] = "rendering"
            log("RETRY_ASSEMBLE", f"ep{int(e):02d}", "配音解释器已到位")
        elif s == "assemble_failed" and x.get("resolved_sig") and x["resolved_sig"] != ep_sig(int(e), x["host"]):
            # 镜头集合 / 版本变了 = 新输入，值得再试：重置自动重试次数（不论是否已用完）
            x["assemble_retries"] = 0
            x["status"] = "rendering"
            log("REOPEN", f"ep{int(e):02d}", "合成失败后入选版本 / 镜头集合有变，重置自动重试并重新合成")
        elif s == "assemble_failed" and int(x.get("assemble_retries", 0)) < ASM_RETRY_MAX \
                and time.time() - float(x.get("finalized") or 0) >= ASM_RETRY_S:
            x["assemble_retries"] = int(x.get("assemble_retries", 0)) + 1
            x["status"] = "rendering"
            log("RETRY_ASSEMBLE", f"ep{int(e):02d}", f"第 {x['assemble_retries']}/{ASM_RETRY_MAX} 次自动重试",
                str(x.get("assemble_err") or "")[-120:])


def reopen_changed(st) -> None:
    """已合成的集，入选版本 / 镜头集合（resolved_sig）变了 → 一律回 rendering（不看是否已全部完成；
    全部完成则同一轮 rendering 分支立刻 finalize，版本号递增）"""
    for e, x in st["eps"].items():
        if x.get("status") == "assembled" and x.get("resolved_sig") and x["resolved_sig"] != ep_sig(int(e), x["host"]):
            x["status"] = "rendering"
            log("REOPEN", f"ep{int(e):02d}", "入选版本有变，按新版本号重合成")


def clip_wh(p: Path) -> tuple[int, int]:
    import cv2
    cap = cv2.VideoCapture(str(p))
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        cap.release()


def upscaled_for(src: Path) -> Path | None:
    """原片的放大版（同目录 <名>_sr1080.mp4，tools/series10_video/upscale_preview.py 产出：SeedVR2 或 lanczos+锐化兜底）"""
    p = src.with_name(src.stem + "_sr1080.mp4")
    return p if p.is_file() else None


def assembly_sources(man: dict) -> tuple[dict, list[str]]:
    """K-EDT-V10（项目方 11-01“s5等视频出来很糊”“估计你的参数坏了”）：成片只用原片（manifest.source = video/clips/…，
    768×1344 级）或它的放大版；540×960 代理（manifest.proxy）只给审片页，禁止进成片。
    每条输入的宽高必须 ≥ 原片宽高（放大版必须更大）；不满足的镜列进 bad，整集不合成"""
    shots, bad = [], []
    for s in man.get("shots", []):
        if not s.get("proxy"):
            continue                        # 尽力版 / 没出片：本来就不进合成（manifest excluded）
        src = ROOT / str(s.get("source") or "")
        if not s.get("source") or not src.is_file():
            bad.append(f"{s['shot']} 原片不在本机（{s.get('source')}）")
            continue
        sw, sh = clip_wh(src)
        use, tag = src, f"原片 {sw}×{sh}"
        dj = src.with_name(src.stem + "_dj.mp4")          # VIDEO-RCA r1：Pika 去抖片（upscale_preview 产出，K-LOOP-004）
        if dj.is_file():
            use, tag = dj, f"去抖版 {sw}×{sh}"
        up = upscaled_for(src)
        if up:
            uw, uh = clip_wh(up)
            if uw >= sw and uh >= sh:
                use, tag = up, f"放大版 {uw}×{uh}（原片 {sw}×{sh}）"
        pw, ph = clip_wh(ROOT / s["proxy"]) if (ROOT / s["proxy"]).is_file() else (0, 0)
        if not sw or (pw and sw * sh <= pw * ph):
            bad.append(f"{s['shot']} 原片分辨率 {sw}×{sh} 不高于代理 {pw}×{ph}")
            continue
        try:   # W46（总调度 05:1x）：进合成前单镜裁到 ≤ 6.0 s（C-08，尾部裁、首帧保留；Pika 79 帧@12 = 6.58 s 的已出片兜底）
            from clip_trim import trim_le
            t6 = trim_le(use)
            if t6 != use:
                use, tag = t6, tag + "，裁到 ≤6 s"
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            bad.append(f"{s['shot']} 裁到 6 s 失败：{e}"[:200])
            continue
        shots.append({"index": s["index"], "kind": "video", "file": str(use.relative_to(ROOT)).replace("\\", "/"),
                      "origin": f"VIDEO10 {s['shot']} {s.get('chosen')} {s.get('recipe')} seed {s.get('seed')}（{tag}）"})
    return {"shots": shots}, bad


def finalize(ep, host, st, ctrl):
    ver = f"v{int(st['eps'][str(ep)].get('assembled_n', 0)) + 1}"   # 每次重合成递增：已亲审签字的旧版不覆盖
    if not voices_ok():
        st["eps"][str(ep)]["status"] = "hold_voices"
        log("HOLD", f"ep{ep:02d}", "config/voices.json 不是 series10 演员表，暂不合成")
        return
    why = tts_missing()
    if why:   # K-OPS-309：本机没有配音解释器 / 模型（离线时 night.py 跑在服务器副本上，11:11 ep04 TtsUnavailable）→ 等，不耗版本号
        st["eps"][str(ep)].update(status="hold_tts", hold_why=why)
        log("HOLD_TTS", f"ep{ep:02d}", why)
        return
    old_man = jl(VID / "episodes" / f"ep{ep:02d}" / "manifest.json", {}) or {}
    ep_renders = [x for sid, v in ep_shots(ep, host).items()
                  if sid.startswith(f"ep{ep:02d}-") for x in v.get("renders") or []]
    if old_man.get("shots") and (old_man.get("t") or 0) >= max([float(x.get("t_done") or 0) for x in ep_renders] + [0]):
        _tl, bad0 = assembly_sources(old_man)
        if bad0:   # K-EDT-V10：原片还没拉回来（每轮 sync 补 4 条）→ 先等，不每轮重做代理
            msg = f"等原片 {len(bad0)} 条：" + "; ".join(bad0)[:200]
            if st["eps"][str(ep)].get("wait_msg") != msg:
                log("ASSEMBLE_WAIT", f"ep{ep:02d}", msg)
            st["eps"][str(ep)].update(status="rendering", wait_msg=msg)
            return
    out = ssh(host, f"cd {DEST} && PYTHONUTF8=1 /root/work/fredw/venv_idm/bin/python tools/series10_video/vidgen.py proxies {host} {ep} --run {RUN_ID}", 1800)
    log("proxies", f"ep{ep:02d}", out.strip()[-200:])
    run([PY, "tools/series10_video/sync.py"], 3600)
    man = jl(VID / "episodes" / f"ep{ep:02d}" / "manifest.json", {}) or {}
    rc_up, out_up = run([PY, "tools/series10_video/upscale_preview.py", f"ep{ep:02d}"], 3600)   # K-EDT-V10：原片放大到 1080 宽
    log("upscale", f"ep{ep:02d}", rc_up, out_up.strip()[-200:].replace("\n", " "))
    tl, bad = assembly_sources(man)
    tlp = VID / "episodes" / f"ep{ep:02d}" / "sources.timeline.json"
    js(tlp, tl)
    want = sum(1 for s in man.get("shots", []) if s.get("proxy"))
    if not want or len(tl["shots"]) < want:
        # 11-01 ep01 首次合成：代理没同步回来，合成器拿全静帧占位也“成功”了 → 必须拦
        # K-EDT-V10：进成片的必须是原片（或原片的放大版），原片没拉回来 / 分辨率低于原片 → 不合成
        log("ASSEMBLE_BLOCKED", f"ep{ep:02d}", f"原片 {len(tl['shots'])}/{want} 到位", "; ".join(bad)[:300])
        st["eps"][str(ep)]["status"] = "rendering"
        return
    bgm = ctrl.get("bgm", "auto")
    try:
        mdir = RC.music_dir(RUN_ID)     # MERGE-VID-O / L-118：集级 BGM 按剧（V2 = data/music/<剧>，曲库 config/music_v2.json）
    except Exception as e:  # noqa: BLE001  # arch-ok: 曲库校验不过 = 本集不配乐（--no-bgm），不退回 V1 的配乐
        log("BGM", f"ep{ep:02d}", str(e)[:200])
        mdir = None
    music = (mdir / f"ep{ep:02d}.wav") if mdir else Path("/nonexistent")
    args = [PY, "tools/assemble_episode.py", f"ep{ep:02d}", "--out", str(EPS_OUT / "_work"), "--sources-from", str(tlp),
            "--variant", ver, "--dialogue-source", "h3", "--run", RUN_ID]   # W16：合成器按剧取导入稿 / 音色 / 配乐（C-14）
    if bgm == "off" or (bgm == "auto" and not music.exists()):
        args.append("--no-bgm")   # data/music/epNN.wav 是旧剧（《为他而骚》）的 BGM，不能用在 series10
    else:
        args += ["--music-dir", str(mdir.relative_to(ROOT)).replace("\\", "/")]   # 整集 BGM（V1：tools/bgm/agent.py；V2：tools/bgm/bgm_library.py）
    t_asm = time.time()
    rc, out = run(args, 5400)
    log("assemble", f"ep{ep:02d}", rc, out.strip()[-300:].replace("\n", " "))
    # K-OPS-309：合成器非 0 退出 = 失败，不拿 _work 里同版本号的旧残片冒充；只认这次跑出来的文件
    cands = sorted((p for p in (EPS_OUT / "_work").glob(f"ep{ep:02d}_*_{ver}.mp4") if p.stat().st_mtime >= t_asm - 5),
                   key=lambda p: p.stat().st_mtime) if rc == 0 else []
    if rc:
        st["eps"][str(ep)]["assemble_err"] = out.strip()[-300:]
    final = None
    if cands and not LEGACY:
        hr = episode_hard_rules(cands[-1])
        st["eps"][str(ep)]["hard_rules"] = hr
        log("HARD_RULES", f"ep{ep:02d}", ("pass" if hr["ok"] else "FAIL") + (f"（{len(hr.get('warnings') or [])} 条只记）" if hr.get("warnings") else ""),
            json.dumps(hr, ensure_ascii=False)[:400])
        if not hr["ok"]:   # W46：不合硬规矩的合成片不进 data/episodes/<剧>/（sop_gate“整集预览”与复盘只认那里），留在 _work 交人看
            st["eps"][str(ep)]["assemble_err"] = "硬规矩不过：" + "；".join(hr["fails"])[:300]
            cands = []
    if cands:
        final = EPS_OUT / f"ep{ep:02d}_{ver}.mp4"
        shutil.copy2(cands[-1], final)
        tlj = cands[-1].with_suffix(".timeline.json")
        if tlj.exists():
            shutil.copy2(tlj, EPS_OUT / f"ep{ep:02d}_{ver}.timeline.json")
    director = {}
    if final:   # DIRECTOR 11-02（总调度批准，CONSENT VIDEO10/WORKFLOW → DIRECTOR）：调色 + 音效 + 响度、成片分、口型重出单（K-EDT-816 / 805）
        rc_d, out_d = run([PY, "tools/director/finish.py", str(final)], 3600)
        try:
            director = json.loads([x for x in out_d.splitlines() if x.startswith("{")][-1])
        except (IndexError, ValueError):
            director = {"errors": [f"finish.py rc={rc_d}: {out_d.strip()[-200:]}"]}
        log("director", f"ep{ep:02d}", rc_d, json.dumps({k: director.get(k) for k in ("post", "film_score", "film_score_post", "lip_redo", "errors")},
                                                       ensure_ascii=False, default=str)[:400])
        if (director.get("delivery_gate") or {}).get("deliver") == "post" and director.get("post") and Path(director["post"]).exists():
            final = Path(director["post"])   # 交付闸门（K-EDT-817，decider=code）放行 → 交付后期版；原合成版 epNN_vN.mp4 保留
        if director.get("lip_redo"):        # K-EDT-805：画内对白 TTS 兜底 → 这几镜送回重出，本集不进定稿
            log("LIP_REDO", f"ep{ep:02d}", [r.get("shot") for r in director["lip_redo"]])
    rc2, out2 = run([PY, "tools/series10_video/episode_report.py", str(ep), host, ver], 1800)
    log("report", f"ep{ep:02d}", rc2, out2.strip()[-200:].replace("\n", " "))
    st["eps"][str(ep)].update(status="assembled" if final else "assemble_failed", final=str(final) if final else None,
                              finalized=time.time(), assembled_n=int(ver[1:]) if final else int(ver[1:]) - 1,
                              resolved_sig=ep_sig(ep, host),
                              director={k: director.get(k) for k in ("film_score", "film_score_post", "lip_redo", "errors", "steps", "delivery_gate")} if director else None,
                              lip_redo=[r.get("shot") for r in director.get("lip_redo") or []] if director else [])
    if final and not LEGACY:
        bgm_after_assembly(ep, ver, used_bgm="--no-bgm" not in args, st=st)
        st["eps"][str(ep)]["retro"] = retro_after_assembly(ep)


EP_SECONDS = (60.0, 120.0)     # L-092：集时长 60–120 秒
SHOT_MAX_S = 6.0               # C-08：单镜 ≤ 6 秒
SHOT_TOL_S = 0.05              # 帧取整余量（24 fps 一帧 0.042 s）


def _ffprobe(p: Path) -> dict:
    """时长 + 流类型。服务器上的 ffprobe 是 offline_20261101/bin/ffprobe 兼容壳（只认 -show_streams -show_format -of json 等两种调用，
    别的写法输出 {}；且只报 Video / Audio 流）→ 用它认得的写法；字幕流另用 ffmpeg -i 的 stderr 判（壳看不见字幕流）"""
    exe = shutil.which("ffprobe") or "ffprobe"
    r = subprocess.run([exe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode:
        return {"error": (r.stderr or "")[-200:]}
    try:
        d = json.loads(r.stdout or "{}")
    except ValueError:
        return {"error": f"ffprobe 输出不是 JSON：{(r.stdout or '')[:120]}"}
    if not (d.get("format") or {}).get("duration"):
        return {"error": f"ffprobe 没给时长：{(r.stdout or '')[:120]}"}
    ff = shutil.which("ffmpeg") or "ffmpeg"
    try:
        e = subprocess.run([ff, "-hide_banner", "-i", str(p)], capture_output=True, text=True, errors="replace", timeout=120).stderr or ""
        if re.search(r"Stream #\d+:\d+[^\n]*: Subtitle:", e):
            d.setdefault("streams", []).append({"codec_type": "subtitle"})
    except (OSError, subprocess.TimeoutExpired) as ex:
        return {"error": f"ffmpeg -i 判字幕流失败：{ex!r}"[:200]}
    return d


def episode_hard_rules(mp4: Path, probe=None) -> dict:
    """W46：整集进 data/episodes/<剧>/ 之前的硬规矩（代码判，失败关闭）：
    挡：C-08 每镜 ≤ 6 s（timeline shots[].duration_s，末镜尾帧定格不算）；C-07 / L-002 无字幕流（ffprobe + ffmpeg -i，
        timeline subtitles=false）；有视频流；L-092 集长 60–120 s 按**剧本时长**（shots[].script_duration_s 之和，写作规则口径）。
    只记不挡（warnings，进 night_state / 日志）：合成后实长不在 60–120 s（剪辑规则按运动量 / 对白修头尾，沙箱实测真 Pika 片 5.17→4.0 s，
        11 镜可能掉到 60 s 以下）；合成器 gates.verdict=fail（对白溢出 / 缺镜：“不能当成片”，预览照出）。
    C-06 不看镜头 / L-141 At 只标切镜在视频编译层判（build_jobs / hard_rule_check），成片层不重复"""
    fails, warns = [], []
    pr = (probe or _ffprobe)(mp4)
    if pr.get("error"):
        return {"ok": False, "fails": [f"ffprobe 读不了：{pr['error']}"], "warnings": []}
    dur = float((pr.get("format") or {}).get("duration") or 0)
    kinds = [s.get("codec_type") for s in pr.get("streams") or []]
    if "subtitle" in kinds:
        fails.append("C-07 成片里有字幕流")
    if "video" not in kinds:
        fails.append("没有视频流")
    tl = jl(mp4.with_suffix(".timeline.json"), None)
    script_s = None
    if not tl:
        fails.append("没有 timeline.json（判不了单镜时长）")
    else:
        if tl.get("subtitles"):
            fails.append("C-07 timeline subtitles=true")
        long_shots = [f"{s.get('shot')} {_shot_s(s):.2f}s" for s in tl.get("shots") or [] if _shot_s(s) > SHOT_MAX_S + SHOT_TOL_S]
        if long_shots:
            fails.append("C-08 单镜超 6 秒：" + "、".join(long_shots))
        sd = [float(s["script_duration_s"]) for s in tl.get("shots") or [] if s.get("script_duration_s") is not None]
        script_s = round(sum(sd), 3) if sd else None
        if script_s is not None and not EP_SECONDS[0] <= script_s <= EP_SECONDS[1]:
            fails.append(f"L-092 剧本集长 {script_s:.1f}s 不在 {EP_SECONDS[0]:.0f}–{EP_SECONDS[1]:.0f}s")
        if (tl.get("gates") or {}).get("verdict") == "fail":
            warns.append(f"合成闸门 verdict=fail（预览照出，不能当成片）：{json.dumps(tl.get('gates'), ensure_ascii=False)[:160]}")
    if not EP_SECONDS[0] <= dur <= EP_SECONDS[1]:
        (warns if script_s is not None else fails).append(f"L-092 合成实长 {dur:.1f}s 不在 {EP_SECONDS[0]:.0f}–{EP_SECONDS[1]:.0f}s"
                                                         + ("（剧本 %.1fs；剪辑修头尾所致，交剪辑 / 写手）" % script_s if script_s is not None else ""))
    return {"ok": not fails, "fails": fails, "warnings": warns, "duration_s": round(dur, 3), "script_s": script_s, "streams": kinds,
            "shots": len((tl or {}).get("shots") or []), "max_shot_s": max([_shot_s(s) for s in (tl or {}).get("shots") or []] + [0]),
            "tail_hold_s": (tl or {}).get("tail_hold_s")}


def _shot_s(s: dict) -> float:
    """单镜时长：本镜视频段 duration_s（末镜的尾帧定格 tail_hold 不算镜头本身，assemble 把它并进末镜 picture_s）；没有再用 picture_s"""
    return float(s.get("duration_s") or s.get("picture_s") or 0)


def retro_after_assembly(ep: int) -> dict:
    """W46：整集预览一进 data/episodes/<剧>/ 就走 episode_retro.auto（与 --auto 同一条路：生成 / 登记跟进 / 按配置自动 done）。
    原来写的“常驻 autoflow_resident.retro_tick”从没接上（代码与 git 历史都没有）→ 预览出了复盘也没人跑，第 N+1 集出图永远卡“复盘”。
    在 night 所在机器（服务器：producer video_takeover / night 常驻）跑，写本机 docs/master/RETRO_*.md——服务器 producer 的出图闸门读这一份。
    出错只记日志（复盘不挡成片）"""
    try:
        import importlib.util as _u
        sp = _u.spec_from_file_location("episode_retro_night", ROOT / "tools/master/episode_retro.py")
        m = _u.module_from_spec(sp)
        sp.loader.exec_module(m)
        res = m.auto(RUN_ID, int(ep), ROOT)
    except Exception as e:  # noqa: BLE001  # arch-ok: 复盘出错不影响成片，记进 night_state 交总调度
        res = {"error": repr(e)[:300]}
    log("RETRO", f"ep{int(ep):02d}", json.dumps(res, ensure_ascii=False, default=str)[:300])
    return res


BGM_AUTO_MAX = 2    # 同一份剪辑签名最多自动重合成 2 次（一次确认签名 L5，一次带 BGM）


def bgm_after_assembly(ep: int, ver: str, used_bgm: bool, st: dict) -> dict:
    """MERGE-VID-O（L-118 / L-131）：V2 集级 BGM 的写入点。合成后按本剧时间轴判剪辑锁定（tools/bgm/bgm_library.py，L1–L5）：
    只差 L5（签名要连续两版一致）→ 自动再合成一次确认；锁定且曲库配乐已交付、而这一版没带 BGM → 再合成一次带上 BGM。
    同一签名最多 BGM_AUTO_MAX 次，防循环"""
    x = st["eps"][str(ep)]
    tlj = EPS_OUT / f"ep{ep:02d}_{ver}.timeline.json"
    if not tlj.exists():
        return {}
    rc, out = run([PY, "tools/bgm/bgm_library.py", "--run", RUN_ID, "--ep", str(ep), "--timeline", str(tlj)], 1800)
    try:
        res = json.loads([ln for ln in out.splitlines() if ln.startswith("{")][-1])
    except (IndexError, ValueError):
        res = {"error": f"library.py rc={rc}: {out.strip()[-200:]}"}
    log("BGM_LIB", f"ep{ep:02d}", json.dumps(res, ensure_ascii=False)[:300])
    lock = res.get("lock") or {}
    auto = x.setdefault("bgm_auto", {})
    n = int(auto.get(lock.get("sig") or "-", 0))
    want = (res.get("status") == "delivered" and not used_bgm) or (not lock.get("locked") and lock.get("fails") == ["L5"])
    if want and n < BGM_AUTO_MAX:
        auto[lock.get("sig") or "-"] = n + 1
        x["status"] = "rendering"          # 下一轮 EP_RESOLVED → finalize 重合成（版本号照常递增）
        x["resolved_sig"] = None
        log("BGM_REASSEMBLE", f"ep{ep:02d}", "确认剪辑签名" if res.get("status") != "delivered" else "带上集级 BGM")
    x["bgm"] = res
    return res


def write_status(st):
    rc = jl(VID / "recipe_choice.json", {}) or {}   # 配方口径从 recipe_choice.json 读（D-VID-01 改 Pika Flex 后自动跟着走）
    rtxt = "、".join(f"{k} = {v}" for k, v in rc.items() if k.endswith("_default")) or "（recipe_choice.json 读不到）"
    L = [f"# {RUN_ID} 视频 · 夜间进度（night.py 自动写；交总调度）", "", f"更新：{time.strftime('%Y-%m-%d %H:%M:%S')}", "",
         f"当前配方（{VID_REL}/recipe_choice.json）：{rtxt}", "",
         "成片输入：原片（video/clips/）或其放大版 `_sr1080.mp4`；540×960 代理只给审片页（K-EDT-V10）", "",
         "| 集 | 主机 | 状态 | 成片 | 审阅 |", "|---|---|---|---|---|"]
    for e in range(1, 11):
        x = st["eps"].get(str(e), {})
        L.append(f"| ep{e:02d} | {x.get('host', '')} | {x.get('status', '等首帧')} | {x.get('final') or ''} | "
                 f"{'docs/series10_video/ep%02d_review.md' % e if x.get('status') == 'assembled' else ''} |")
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text("\n".join(L) + "\n", encoding="utf-8")


IMAGE_LANES = ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1"]
FRAME_BUSY = ("pending", "queued", "running", "waiting", "retry", "submitted", "rendering")


def gated(o: dict) -> bool:
    """K-OPS-305 修订（总调度批准，2026-11-01 离线交接）：等总调度的（master_reject / 等复核）和等 REFLOCK 的 pending 帧
    不是监督能自动派的，不算“帧忙”——否则这几镜一直挂着，视频道永远放不开。能自动派的帧照样优先（让道模式下帧先拿空闲道）"""
    if str(o.get("status")) != "pending":
        return False
    w = str(o.get("waiting_for") or "")
    return bool(o.get("master_reject") and w) or any(k in w for k in ("REFLOCK", "总调度", "复核", "项目方"))


def frames_busy() -> int:
    """PRODUCER 登记表里还在排 / 在跑的首帧、尾帧数（data/producer/registry.json）。读不到按“忙”算（保守，图片优先）"""
    d = jl(ROOT / "data/producer/registry.json", None)
    if d is None:
        return 1
    n = 0

    def walk(o):
        nonlocal n
        if isinstance(o, dict):
            if o.get("kind") in ("first", "last") and str(o.get("status")) in FRAME_BUSY and not gated(o):
                n += 1
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d.get("episodes"))
    return n


def video_boost(ctrl: dict, hold: list) -> tuple[list, dict]:
    """VIDEO-PAR（开关默认关）：night_control.json {"video_boost": {"enabled": true, "vram_gate": {"gpu36:1": 21000}}}。
    开 → gate 里的道从 hold 里摘掉，改由 vidgen 按卡上空闲显存放行（看图 / 人数检测占着就不提交）；关 / 没配 → 原样。
    返回（挂道, vram_gate）"""
    b = ctrl.get("video_boost") or {}
    gate = {str(k): int(v) for k, v in (b.get("vram_gate") or {}).items()} if b.get("enabled") else {}
    return [x for x in hold if x not in gate], gate


def apply_lane_policy(st, ctrl):
    """总调度 11-01 05:4x：首帧 / 尾帧还有在排或在跑的 → 视频只用 gpu36:2，图片道全部挂住（不再让道式插队，
    一条 9 分钟的视频会让刚到的首帧白等整条）；首帧全出完后才恢复让道模式。挂住时撤回本工具在图片道上排队未跑的任务"""
    busy = frames_busy()
    # K-OPS-305 修订（总调度批准 11-01 离线交接）：帧基本出完 → 视频可用 gpu33:0/1/3 + gpu36:0/1/2（让道模式：
    # 帧有真实派单时，空出来的道先给帧——PRODUCER 每 20 s 一轮、编排器要等道空 yield_s 才交）。
    # 要恢复“帧在排就把图片道全挂住”的旧做法：night_control.json 设 "frames_exclusive": true
    mode = "video_lane_only" if busy and ctrl.get("frames_exclusive") else "yield"
    ep01_open = mode == "video_lane_only" and (st["eps"].get("1") or {}).get("status") not in (
        "assembled", "assemble_failed", "hold_voices")
    key = mode + ("+ep01@gpu33:3" if ep01_open else "") + "|hold=" + ",".join(sorted(ctrl.get("hold_lanes", []) or []))   # K-OPS-E20：挂道变了要重算
    key += "|gate=" + json.dumps(video_boost(ctrl, [])[1], sort_keys=True)
    key += "|shard=" + ",".join(f"{e}:{c['owner']}" for e, c in sorted((_VS().shard_eps(RUN_ID) if _VS() else {}).items()))   # 分片开关变了要重算
    if st.get("lane_mode") == mode and st.get("lane_key") == key:
        return ctrl
    hosts = jl(VID / "hosts.json", {}) or {}
    for host in _hosts_here():   # A-07
        eps_on = _eps_on(hosts, host)
        # DEBUG-RSI 11-02（K-OPS-E20，CONSENT VIDEO10 → DEBUG_RSI by 总调度）：video_lane_only 模式原来只挡出图道、不看
        # control 的 hold_lanes → 挂道挡不住视频（gpu36:0 两次重启窗口被 VIDEO10 视频占住）。现在两者合并
        ctl_hold = list(ctrl.get("hold_lanes", []) or [])
        hold = sorted(set(IMAGE_LANES if mode == "video_lane_only" else []) | set(ctl_hold))
        per_lane, shared = ctrl["per_lane"], ctrl.get("shared_lanes", [])
        if ep01_open and host == hosts.get("1"):
            hold = sorted(set(x for x in IMAGE_LANES if x != "gpu33:3") | set(ctl_hold))
            eps_on, per_lane, shared = [1], 1, [x for x in shared if x != "gpu33:3"]
        hold, gate = video_boost(ctrl, hold)
        hold = _shard_hold(host, hold)
        c = {"jobs": "jobs.json", "mode": "prod", "eps": eps_on, "per_lane": per_lane, "linger": True,
             "hold_lanes": hold, "shared_lanes": shared, "yield_s": ctrl["yield_s"]}
        if gate:
            c["vram_gate"] = gate
        run([PY, "tools/series10_video/deploy.py", "control", host, json.dumps(c, ensure_ascii=False)])
        if mode == "video_lane_only":
            ports = {"gpu33": [8188, 8189, 8191], "gpu36": [8188, 8189, 8190]}[host]
            py = ("import json,urllib.request\n"
                  f"for p in {ports}:\n"
                  "    d=json.load(urllib.request.urlopen(f'http://127.0.0.1:{p}/queue',timeout=5))\n"
                  "    ids=[i[1] for i in d['queue_pending'] if str((i[3] or {}).get('client_id','')).startswith('video10-')]\n"
                  "    if ids: urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{p}/queue',json.dumps({'delete':ids}).encode(),{'Content-Type':'application/json'}),timeout=5); print(p,len(ids))\n")
            out = ssh(host, f"python3 - <<'EOF'\n{py}EOF", 60)
            log("WITHDRAW", host, out.strip()[-200:])
    st["lane_mode"] = mode
    st["lane_key"] = key
    log("LANE_POLICY", key, f"首帧 / 尾帧在排或在跑 {busy}")
    return ctrl


def _hosts_here() -> tuple:
    """服务器上（OFFLINE_SELF）只处理本机；笔记本两台都管（A-07）"""
    import os as _os
    me = _os.environ.get("OFFLINE_SELF")
    return (me,) if me else ("gpu33", "gpu36")


def partition_hosts(part: dict | None = None) -> dict:
    """K-OPS-F21（总调度 11-02 17:2x，AUDIT-M 查出视频分区 5–6 份来源且不一致）：视频归哪台只有一个来源 =
    data/state/netfix/partition.json 的 video 分区。→ {"<集号>": host}；读不到 → {}（不改 hosts.json）"""
    if part is None:
        try:
            sys.path.insert(0, str(ROOT / "tools/netfix"))
            import dispatch as _D
            part = _D.read_partition()
        except Exception:  # noqa: BLE001  # arch-ok: 分区读不到 → 本轮不改 hosts.json（下一轮再读）
            return {}
    # MERGE-VID-O：分区若按剧登记（partition.runs.<剧>.video）就用本剧的；没有 = 全局 video 分区（按集号分机，同一规则）
    vid = (((part or {}).get("runs") or {}).get(RUN_ID) or {}).get("video") or (part or {}).get("video") or {}
    return {str(e): h for h, eps in vid.items() for e in eps}


def sync_hosts_from_partition(part: dict | None = None) -> dict:
    """video/hosts.json 由 partition.json 生成（不再手改、不再 pick_host 自己挑）；有变化才写，返回写入后的表"""
    want = partition_hosts(part)
    cur = jl(VID / "hosts.json", {}) or {}
    if want and want != cur:
        js(VID / "hosts.json", want)
        log("HOSTS_FROM_PARTITION", json.dumps(want, ensure_ascii=False), "旧", json.dumps(cur, ensure_ascii=False))
        return want
    return cur


def loop_once(st):
    sync_hosts_from_partition()
    ctrl = {**DEFAULT_CTRL, **(jl(CTRL, {}) or {})}
    apply_lane_policy(st, ctrl)
    if st.get("lane_mode") == "video_lane_only":
        ctrl = {**ctrl, "hold_lanes": IMAGE_LANES}
        if "+ep01@gpu33:3" in str(st.get("lane_key")):
            ctrl["ep01_lane"] = True
    eps_specs = specs_by_ep()
    ready_eps(eps_specs, ctrl)                     # 只为 force_eps 入账
    rs, files = ready_shots(eps_specs, ctrl)
    try:   # W46：尾帧过契约才过逐镜“视频”闸门（hf-08）→ 尾帧变了也要重编作业（原来只看首帧，S4 / S6 尾帧到了也不进 jobs.json）
        lasts = {k: (v.get("file") if isinstance(v, dict) else v) for k, v in (_B().passed_lasts() or {}).items()}
    except Exception as e:  # noqa: BLE001  # arch-ok: 尾帧清单读不了 = 签名不含尾帧（退回原口径），记日志
        log("LASTS_SIG", repr(e)[:160])
        lasts = {}
    sig = json.dumps({"shots": rs, "files": files, "lasts": lasts}, sort_keys=True, ensure_ascii=False)
    if rs and sig != st.get("ready_sig"):
        hosts = jl(VID / "hosts.json", {}) or {}
        touched = set()
        for ep, ids in rs.items():
            if str(ep) not in hosts:
                # K-OPS-F21：分区里没有这一集 = 没人负责，不自己挑主机（以前 pick_host 写 hosts.json，和 partition.json 打架）
                log("NO_PARTITION", f"ep{ep:02d}", "partition.json video 分区里没有这一集，跳过")
                continue
            touched.add(hosts[str(ep)])
            sc = _shard_cfg(ep)
            if sc:   # 分片集：另一台（helper）也要派；本机不是 owner = helper，只出镜、不合成（owner 那台合成）
                touched |= set(sc["hosts"])
            x = st["eps"].setdefault(str(ep), {"host": hosts[str(ep)], "dispatched": time.time(), "status": "rendering"})
            if sc:
                me = os.environ.get("OFFLINE_SELF")
                x["shard_helper"] = bool(me) and me != sc["owner"]
            x["ready_shots"] = ids
            st.setdefault("pending_shots", {})[str(ep)] = len(eps_specs[ep])
        if touched and dispatch_hosts(touched, st, ctrl):
            st["ready_sig"] = sig
            log("READY", {f"ep{e:02d}": len(v) for e, v in rs.items()})
    run([PY, "tools/series10_video/sync.py"], 1800)
    # DATAALIGN 11-01：过门的镜登记进 takes.json（/api/progress、集摘要、画布才读得到）；按 sha256 去重，重复调无害
    rc, out = run([PY, "tools/pipeline/register_takes.py", "--video10", VID_REL,
                   "--label", "VIDEO10 预览片"], 1800)
    if rc:
        log("register_takes", rc, out.strip()[-200:].replace("\n", " "))
    if not LEGACY and st.get("eps"):   # W46（总调度 05:4x）：已登记的当前视频 > 6 s → _le6 版登记并设为当前（原版保留）
        rc_t, out_t = run([PY, "tools/series10_video/trim_takes.py", "--run", RUN_ID, "--eps", ",".join(sorted(st["eps"]))], 1800)
        if rc_t or '"changed": []' not in out_t:
            log("TRIM_TAKES", rc_t, out_t.strip()[-300:].replace("\n", " "))
    retry_assembly(st)
    reopen_changed(st)
    for e, x in st["eps"].items():
        if x.get("status") == "rendering" and not x.get("shard_helper"):
            fin, recs = ep_resolved(int(e), x["host"])
            st["pending_shots"][e] = sum(1 for r in recs.values() if r.get("status") not in ("done", "best_effort", "blocked"))
            if fin:
                log("EP_RESOLVED", f"ep{int(e):02d}", {k: v.get("status") for k, v in recs.items()})
                finalize(int(e), x["host"], st, ctrl)
                apply_lane_policy(st, ctrl)
    js(STATE, st)
    write_status(st)


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    log("RUN", RUN_ID, VID_REL)
    st = jl(STATE, None) or {"eps": {}, "pending_shots": {}, "started": time.time()}
    while True:
        try:
            loop_once(st)
        except Exception as e:  # noqa: BLE001
            log("LOOP_ERR", repr(e)[:300])
        if "--once" in argv:
            return 0
        time.sleep(120)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
