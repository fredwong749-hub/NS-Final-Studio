"""W46 EP01-FINALIZE 沙箱驱动：视频齐 → night finalize → data/episodes/<剧>/epNN_vN.mp4 → sop_gate 整集预览 → episode_retro --auto。

只在沙箱副本里跑（仓库整份复制到别的目录、config/factory/hosts.json video_root 指向副本；ROOT = 本文件所在副本），
不碰生产 takes.json / data/episodes 正式目录 / 生产 night_state。

    python tools/master/finalize_trial.py prep --run series10_v2 --ep 1 --real ep01-S10=/path/video_002_w41.mp4
        → 按导入稿逐镜写 video/clips/epNN/<镜>__w46_s0.mp4（--real 给的 = 真视频；其余 = 本剧该镜首帧缓推代片，
          时长 = 导入稿 duration_s，768×1344@24 + 静音轨，标 w46_standin），video/jobs.json + state_<host>.json
          （vidgen 出完、每镜 done 的样子）+ night_state.json（本集 rendering，等 EP_RESOLVED）
    python tools/master/finalize_trial.py loop --run series10_v2 [--host gpu33] [--reopen]
        → import night（按 --run 钉剧），dispatch_hosts 换成只记日志（沙箱不派 GPU），跑一轮 loop_once；打印本集状态

不是生产路径：生产由 producer video_takeover / night 常驻调 loop_once（同一份 night 代码）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
sys.path.insert(0, str(ROOT / "tools/factory"))
import runs as _RUNS  # noqa: E402
import hosts as _HOSTS  # noqa: E402


def _prod_roots() -> set[str]:
    """生产部署目录 = 车道表 config/factory/hosts.json 各机 repo / video_root（不写死路径）；车道表读不到 = 当作生产（失败关闭）"""
    try:
        hs = (_HOSTS.load().get("hosts") or {}).values()
    except _HOSTS.HostsError:
        return {str(ROOT)}
    return {str(v.get(k)) for v in hs for k in ("repo", "video_root") if v.get(k)}


def _guard_sandbox() -> None:
    """失败关闭：在生产部署目录里不许跑（这个驱动会改 video/ 状态文件）"""
    prod = _prod_roots()
    if str(ROOT) in prod or os.environ.get("NS_FINALIZE_TRIAL_OK") != "1":
        raise SystemExit(f"finalize_trial 只在沙箱副本里跑（ROOT={ROOT}；需要 NS_FINALIZE_TRIAL_OK=1，且不是 {sorted(prod)}）")


def _jl(p: Path, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _js(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def shot_image(run: str, ep: int, idx: int) -> Path | None:
    """本剧该镜首帧：takes.json active.image，没有就最后一版 image；只认 renders/<剧>/ 前缀（C-14）"""
    d = _jl(_RUNS.renders_dir(run, ROOT) / f"ep{ep:02d}" / f"S{idx}" / "takes.json", {}) or {}
    takes = [t for t in d.get("takes") or [] if t.get("stage") == "image"
             and str(t.get("file") or "").startswith(f"renders/{run}/")]
    act = (d.get("active") or {}).get("image")
    pick = next((t for t in takes if t.get("n") == act), None) or (takes[-1] if takes else None)
    if not pick:
        return None
    p = ROOT / "data" / pick["file"]
    return p if p.is_file() else None


def standin(img: Path | None, secs: float, dst: Path) -> None:
    src = ["-f", "lavfi", "-i", "color=c=gray:s=768x1344:r=24"] if img is None else ["-loop", "1", "-framerate", "24", "-i", str(img)]
    vf = ("scale=768:1344:force_original_aspect_ratio=increase,crop=768:1344,"
          "zoompan=z='min(zoom+0.0008,1.08)':d=1:s=768x1344:fps=24,format=yuv420p")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *src, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-t", f"{secs:.3f}", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-c:a", "aac", "-shortest", str(dst)], check=True, capture_output=True, timeout=600)


def prep(a) -> dict:
    os.environ["NS_RUN"] = a.run
    sys.path.insert(0, str(ROOT / "tools/series10_video"))
    import run_ctx as RC
    import build_jobs as B
    if B.RUN_ID != a.run:
        B.set_run(a.run)
    vid = ROOT / RC.vid_rel(a.run)
    real = dict(x.split("=", 1) for x in a.real or [])
    specs = sorted((s for s in B.load_specs(source="import").values() if s.episode == a.ep), key=lambda s: s.index)
    jobs = {"schema": "w46_trial", "run": a.run, "built_at": time.time(), "built_by": "finalize_trial", "shots": []}
    st = _jl(vid / f"state_{a.host}.json", {}) or {}
    st.setdefault("shots", {})
    rows = []
    for s in specs:
        rel = f"{RC.vid_rel(a.run)}/clips/ep{a.ep:02d}/{s.id}__w46_s0.mp4"
        dst = ROOT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if s.id in real:
            subprocess.run(["cp", real[s.id], str(dst)], check=True, timeout=120)
            kind = "real"
        else:
            standin(shot_image(a.run, a.ep, s.index), float(s.duration_s or 5.0), dst)
            kind = "w46_standin"
        jobs["shots"].append({"shot": s.id, "ep": a.ep, "variants": {"w46": {"recipe": "i2va_pika_flex", "seed": 0,
                              "status": "ready", "frames": int(round(float(s.duration_s or 5) * 24)) + 1}}})
        t = time.time()
        st["shots"][s.id] = {"status": "done", "chosen": "w46", "renders": [
            {"variant": "w46", "recipe": "i2va_pika_flex", "seed": 0, "lane": f"{a.host}:1", "state": "scored",
             "file": rel, "t_sub": t, "t_done": t, "params": {"w46_trial": kind},
             "score": {"gate": {"pass": True, "fails": []}, "penalty": 0, "w46_trial": kind}}]}
        rows.append({"shot": s.id, "kind": kind, "spec_s": s.duration_s, "file": rel})
    _js(vid / "jobs.json", jobs)
    _js(vid / f"state_{a.host}.json", st)
    _js(vid / "hosts.json", {**(_jl(vid / "hosts.json", {}) or {}), str(a.ep): a.host})
    ns = _jl(vid / "night_state.json", None) or {"eps": {}, "pending_shots": {}, "started": time.time()}
    ns["eps"][str(a.ep)] = {"host": a.host, "dispatched": time.time(), "status": "rendering", "ready_shots": [r["shot"] for r in rows]}
    _js(vid / "night_state.json", ns)
    out = {"prep": rows, "total_spec_s": sum(float(r["spec_s"] or 0) for r in rows)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def loop(a) -> dict:
    os.environ["NS_RUN"] = a.run
    sys.argv = [sys.argv[0], "--run", a.run]
    sys.path.insert(0, str(ROOT / "tools/series10_video"))
    import night as NT
    assert NT.RUN_ID == a.run, NT.RUN_ID
    NT.dispatch_hosts = lambda hosts, st, ctrl: (NT.log("W46_TRIAL_NO_DISPATCH", sorted(hosts)), True)[1]
    st = NT.jl(NT.STATE, None) or {"eps": {}, "pending_shots": {}, "started": time.time()}
    if a.reopen and str(a.ep) in st.get("eps", {}):     # 再合成一版（版本号照常递增，旧版不覆盖）：验证新代码的整条接力
        st["eps"][str(a.ep)].update(status="rendering", resolved_sig=None)
    t0 = time.time()
    NT.loop_once(st)
    ep = (st.get("eps") or {}).get(str(a.ep)) or {}
    out = {"loop_s": round(time.time() - t0, 1), "ep": {k: ep.get(k) for k in ("status", "final", "assembled_n", "assemble_err",
                                                                              "hold_why", "wait_msg", "director", "lip_redo")},
           "episodes": sorted(p.name for p in NT.EPS_OUT.glob(f"ep{a.ep:02d}*"))}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "loop"])
    ap.add_argument("--run", required=True)
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--host", default="gpu33")
    ap.add_argument("--real", action="append", help="<镜>=<真视频路径>")
    ap.add_argument("--reopen", action="store_true", help="loop：本集已 assembled 也回到 rendering 再合成一版")
    a = ap.parse_args(argv)
    _guard_sandbox()
    (prep if a.cmd == "prep" else loop)(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
