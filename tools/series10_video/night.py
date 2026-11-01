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
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
VID_REL = "data/pipeline/runs/series10_v1/video"
VID = ROOT / VID_REL
DEST = "/root/work/fredw/video10_srv"
PY = str(ROOT / ".venv/Scripts/python.exe")
STATE = VID / "night_state.json"
CTRL = VID / "night_control.json"
LOG = VID / "night.log"
STATUS = ROOT / "docs/series10_video/STATUS.md"
EPS_OUT = ROOT / "data/episodes/series10"
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


def run(args, timeout=3600):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       cwd=str(ROOT), env={**__import__("os").environ, "PYTHONUTF8": "1"})
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def ssh(host, cmd, timeout=600):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", host, cmd], capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return r.stdout + r.stderr


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


def specs_by_ep():
    import build_jobs as B
    sp = B.load_specs(source="import")
    eps = {}
    for sid, s in sp.items():
        eps.setdefault(s.episode, []).append(s)
    return eps


def ready_eps(eps_specs, ctrl) -> list[int]:
    import build_jobs as B
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
    import build_jobs as B
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
    for h in ("gpu33", "gpu36"):
        busy = ssh(h, f"cd {DEST} 2>/dev/null && [ -f run/vidgen.pid ] && kill -0 $(cat run/vidgen.pid) 2>/dev/null && "
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
    rc, out = run([PY, "tools/series10_video/build_jobs.py"], 1800)
    log("build_jobs", rc, out.strip()[-300:].replace("\n", " "))
    if rc:
        return False
    hosts = jl(VID / "hosts.json", {}) or {}
    for host in sorted(hosts_touched):
        rc, out = run([PY, "tools/series10_video/deploy.py", "push", host], 3600)
        log("push", host, rc, out.strip()[-200:].replace("\n", " "))
        if rc:
            return False
        eps_on = sorted(int(e) for e, h in hosts.items() if h == host)
        hold, per_lane, shared = ctrl.get("hold_lanes", []), ctrl["per_lane"], ctrl.get("shared_lanes", [])
        if ctrl.get("ep01_lane") and host == hosts.get("1"):
            hold = [x for x in IMAGE_LANES if x != "gpu33:3"]
            eps_on, per_lane, shared = [1], 1, [x for x in shared if x != "gpu33:3"]
        c = {"jobs": "jobs.json", "mode": "prod", "eps": eps_on, "per_lane": per_lane, "linger": True,
             "hold_lanes": hold, "shared_lanes": shared, "yield_s": ctrl["yield_s"]}
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


def ep_sig(ep, host) -> str:
    stt = jl(VID / f"state_{host}.json", {}) or {}
    return json.dumps({sid: [r.get("status"), r.get("chosen"), len(r.get("renders") or [])]
                       for sid, r in sorted((stt.get("shots") or {}).items()) if int(sid[2:4]) == ep}, ensure_ascii=False)


def ep_resolved(ep, host) -> tuple[bool, dict]:
    stt = jl(VID / f"state_{host}.json", {}) or {}
    jobs = jl(VID / "jobs.json", {}) or {}
    ids = [s["shot"] for s in jobs.get("shots", []) if s["ep"] == ep]
    recs = {sid: (stt.get("shots") or {}).get(sid, {}) for sid in ids}
    fin = all(r.get("status") in ("done", "best_effort", "blocked") for r in recs.values()) and ids
    return bool(fin), recs


def voices_ok() -> bool:
    """总调度 11-01：config/voices.json 还是旧 60 集的 Kokoro 演员表（林晚 = zf_067 等），series10 声音没重做前不合成成片。
    voices.json 顶层 "series" 标成 "series10_v1"（由声音负责方改）后才放行。"""
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
        miss = tts_preflight(root=ROOT)
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
        if s == "hold_tts" and not tts_missing():
            x["status"] = "rendering"
            log("RETRY_ASSEMBLE", f"ep{int(e):02d}", "配音解释器已到位")
        elif s == "assemble_failed" and int(x.get("assemble_retries", 0)) < ASM_RETRY_MAX \
                and time.time() - float(x.get("finalized") or 0) >= ASM_RETRY_S:
            x["assemble_retries"] = int(x.get("assemble_retries", 0)) + 1
            x["status"] = "rendering"
            log("RETRY_ASSEMBLE", f"ep{int(e):02d}", f"第 {x['assemble_retries']}/{ASM_RETRY_MAX} 次自动重试",
                str(x.get("assemble_err") or "")[-120:])


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
    ep_renders = [x for sid, v in ((jl(VID / f"state_{host}.json", {}) or {}).get("shots") or {}).items()
                  if sid.startswith(f"ep{ep:02d}-") for x in v.get("renders") or []]
    if old_man.get("shots") and (old_man.get("t") or 0) >= max([float(x.get("t_done") or 0) for x in ep_renders] + [0]):
        _tl, bad0 = assembly_sources(old_man)
        if bad0:   # K-EDT-V10：原片还没拉回来（每轮 sync 补 4 条）→ 先等，不每轮重做代理
            msg = f"等原片 {len(bad0)} 条：" + "; ".join(bad0)[:200]
            if st["eps"][str(ep)].get("wait_msg") != msg:
                log("ASSEMBLE_WAIT", f"ep{ep:02d}", msg)
            st["eps"][str(ep)].update(status="rendering", wait_msg=msg)
            return
    out = ssh(host, f"cd {DEST} && PYTHONUTF8=1 /root/work/fredw/venv_idm/bin/python tools/series10_video/vidgen.py proxies {host} {ep}", 1800)
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
    music = ROOT / "data/music/series10" / f"ep{ep:02d}.wav"
    args = [PY, "tools/assemble_episode.py", f"ep{ep:02d}", "--out", str(EPS_OUT / "_work"), "--sources-from", str(tlp),
            "--variant", ver, "--dialogue-source", "h3"]
    if bgm == "off" or (bgm == "auto" and not music.exists()):
        args.append("--no-bgm")   # data/music/epNN.wav 是旧剧（《为他而骚》）的 BGM，不能用在 series10
    else:
        args += ["--music-dir", "data/music/series10"]   # BGM10 的整集 BGM（tools/bgm/agent.py）
    t_asm = time.time()
    rc, out = run(args, 5400)
    log("assemble", f"ep{ep:02d}", rc, out.strip()[-300:].replace("\n", " "))
    # K-OPS-309：合成器非 0 退出 = 失败，不拿 _work 里同版本号的旧残片冒充；只认这次跑出来的文件
    cands = sorted((p for p in (EPS_OUT / "_work").glob(f"ep{ep:02d}_*_{ver}.mp4") if p.stat().st_mtime >= t_asm - 5),
                   key=lambda p: p.stat().st_mtime) if rc == 0 else []
    if rc:
        st["eps"][str(ep)]["assemble_err"] = out.strip()[-300:]
    final = None
    if cands:
        final = EPS_OUT / f"ep{ep:02d}_{ver}.mp4"
        shutil.copy2(cands[-1], final)
        tlj = cands[-1].with_suffix(".timeline.json")
        if tlj.exists():
            shutil.copy2(tlj, EPS_OUT / f"ep{ep:02d}_{ver}.timeline.json")
    rc2, out2 = run([PY, "tools/series10_video/episode_report.py", str(ep), host, ver], 1800)
    log("report", f"ep{ep:02d}", rc2, out2.strip()[-200:].replace("\n", " "))
    st["eps"][str(ep)].update(status="assembled" if final else "assemble_failed", final=str(final) if final else None,
                              finalized=time.time(), assembled_n=int(ver[1:]) if final else int(ver[1:]) - 1,
                              resolved_sig=ep_sig(ep, host))


def write_status(st):
    rc = jl(VID / "recipe_choice.json", {}) or {}   # 配方口径从 recipe_choice.json 读（D-VID-01 改 Pika Flex 后自动跟着走）
    rtxt = "、".join(f"{k} = {v}" for k, v in rc.items() if k.endswith("_default")) or "（recipe_choice.json 读不到）"
    L = ["# series10 视频 · 夜间进度（night.py 自动写；交总调度）", "", f"更新：{time.strftime('%Y-%m-%d %H:%M:%S')}", "",
         f"当前配方（data/pipeline/runs/series10_v1/video/recipe_choice.json）：{rtxt}", "",
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
    key = mode + ("+ep01@gpu33:3" if ep01_open else "")
    if st.get("lane_mode") == mode and st.get("lane_key") == key:
        return ctrl
    hosts = jl(VID / "hosts.json", {}) or {}
    for host in ("gpu33", "gpu36"):
        eps_on = sorted(int(e) for e, h in hosts.items() if h == host)
        hold = IMAGE_LANES if mode == "video_lane_only" else ctrl.get("hold_lanes", [])
        per_lane, shared = ctrl["per_lane"], ctrl.get("shared_lanes", [])
        if ep01_open and host == hosts.get("1"):
            hold = [x for x in IMAGE_LANES if x != "gpu33:3"]
            eps_on, per_lane, shared = [1], 1, [x for x in shared if x != "gpu33:3"]
        c = {"jobs": "jobs.json", "mode": "prod", "eps": eps_on, "per_lane": per_lane, "linger": True,
             "hold_lanes": hold, "shared_lanes": shared, "yield_s": ctrl["yield_s"]}
        run([PY, "tools/series10_video/deploy.py", "control", host, json.dumps(c, ensure_ascii=False)])
        if mode == "video_lane_only":
            ports = {"gpu33": [8188, 8189, 8191], "gpu36": [8188, 8189]}[host]
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


def loop_once(st):
    ctrl = {**DEFAULT_CTRL, **(jl(CTRL, {}) or {})}
    apply_lane_policy(st, ctrl)
    if st.get("lane_mode") == "video_lane_only":
        ctrl = {**ctrl, "hold_lanes": IMAGE_LANES}
        if "+ep01@gpu33:3" in str(st.get("lane_key")):
            ctrl["ep01_lane"] = True
    eps_specs = specs_by_ep()
    ready_eps(eps_specs, ctrl)                     # 只为 force_eps 入账
    rs, files = ready_shots(eps_specs, ctrl)
    sig = json.dumps({"shots": rs, "files": files}, sort_keys=True, ensure_ascii=False)
    if rs and sig != st.get("ready_sig"):
        hosts = jl(VID / "hosts.json", {}) or {}
        touched = set()
        for ep, ids in rs.items():
            if str(ep) not in hosts:
                # 有 >260 帧长镜头的集只能在 gpu36（长镜头道 gpu36:2，K-OPS-I03）；ep09-S3 328 帧
                h = "gpu36" if any(s.frames > 260 for s in eps_specs[ep]) else pick_host(st)
                if not h:
                    continue
                hosts[str(ep)] = h
                js(VID / "hosts.json", hosts)
            touched.add(hosts[str(ep)])
            x = st["eps"].setdefault(str(ep), {"host": hosts[str(ep)], "dispatched": time.time(), "status": "rendering"})
            x["ready_shots"] = ids
            st.setdefault("pending_shots", {})[str(ep)] = len(eps_specs[ep])
        if touched and dispatch_hosts(touched, st, ctrl):
            st["ready_sig"] = sig
            log("READY", {f"ep{e:02d}": len(v) for e, v in rs.items()})
    run([PY, "tools/series10_video/sync.py"], 1800)
    # DATAALIGN 11-01：过门的镜登记进 takes.json（/api/progress、集摘要、画布才读得到）；按 sha256 去重，重复调无害
    rc, out = run([PY, "tools/pipeline/register_takes.py", "--video10", "data/pipeline/runs/series10_v1/video",
                   "--label", "VIDEO10 预览片"], 1800)
    if rc:
        log("register_takes", rc, out.strip()[-200:].replace("\n", " "))
    retry_assembly(st)
    for e, x in st["eps"].items():
        if x.get("status") == "assembled" and x.get("resolved_sig") and x["resolved_sig"] != ep_sig(int(e), x["host"]):
            fin, _r = ep_resolved(int(e), x["host"])
            if not fin:
                x["status"] = "rendering"
                log("REOPEN", f"ep{int(e):02d}", "入选版本有变（重出中），完成后按新版本号重合成")
        if x.get("status") == "rendering":
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
