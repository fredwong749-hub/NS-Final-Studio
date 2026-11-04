"""W41 VIDEO-STAGE-READY（总调度 11-04 派）：尾帧 → 视频 → 整集预览 三段在真机上的试跑驱动（沙箱，不动生产状态）。

为什么要沙箱：data/renders/<run>/epNN/SNN/takes.json 的 active 指针归 producer / W38 管，试跑出的版本不能把它挪走。
本工具把镜目录（takes.json + 版本文件）复制到 data/_w41_trial/renders/<run>/ 下，再以 NS_RENDERS_DIR 指过去跑
与生产同一份代码（producer.FrameExec.render / h3_video.render / assemble），producer 日志 / 账本写 data/_w41_trial/producer/。
只复制、不删；生产目录一个字节不改。

    .venv/Scripts/python.exe tools/master/video_stage_trial.py prep  --shot ep01-S10 [--run series10_v2]
    .venv/Scripts/python.exe tools/master/video_stage_trial.py last  --shot ep01-S10 --lane gpu33:1 [--first-n 1]
    .venv/Scripts/python.exe tools/master/video_stage_trial.py video --shot ep01-S10 --lane gpu33:1 [--seconds 6]
    .venv/Scripts/python.exe tools/master/video_stage_trial.py show  --shot ep01-S10

生产时（W38 不走沙箱）：尾帧 = producer serve 自动派（control.json only 含该镜、道不在 hold_lanes）；
视频 = tools/series10_video/night.py --run <剧>（按集）；整集预览 = tools/assemble_episode.py。见
docs/master/handover/EP01_VIDEO_STAGE_RUNBOOK.md。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = ROOT / "data" / "_w41_trial"
BROKEN_LANES = ("gpu33:2", "gpu36:2")   # CLAUDE.md 红线：坏卡


def write_atomic(p: Path, text: str) -> None:
    """tmp + os.replace 原子写（arch_scan nonatomic_json）"""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def sandbox_renders(run: str) -> Path:
    return SANDBOX / "renders" / run


def set_env(run: str) -> None:
    """必须在 import ns_render.pipeline 之前调（RENDERS 在模块级求值）"""
    os.environ["NS_RUN"] = run
    os.environ["NS_RENDERS_DIR"] = str(sandbox_renders(run))
    for p in ("services/render_router", "services/agent", "packages/schema", "tools/pipeline", "tools/gen_contract",
              "tools/series10_video", "services/api", "services/recipes", "tools/autopilot"):
        if str(ROOT / p) not in sys.path:
            sys.path.insert(0, str(ROOT / p))


def shot_rel(shot: str) -> Path:
    ep, s = shot.split("-")
    return Path(ep) / s


def prep(run: str, shot: str, refresh: bool = False) -> Path:
    """生产镜目录 → 沙箱（只复制；沙箱里已有的版本文件不覆盖。takes.json 只在沙箱没有或 refresh=True 时拷生产最新——
    否则会把沙箱里试跑登记的版本冲掉）"""
    src = ROOT / "data" / "renders" / run / shot_rel(shot)
    dst = sandbox_renders(run) / shot_rel(shot)
    if not (src / "takes.json").is_file():
        raise SystemExit(f"生产镜目录没有 takes.json：{src}")
    (dst / "takes").mkdir(parents=True, exist_ok=True)
    if refresh or not (dst / "takes.json").is_file():
        shutil.copy2(src / "takes.json", dst / "takes.json")
    for f in (src / "takes").glob("*"):
        if f.is_file() and not (dst / "takes" / f.name).exists():
            shutil.copy2(f, dst / "takes" / f.name)
    return dst


def lane_url(lane: str) -> str:
    if lane in BROKEN_LANES:
        raise SystemExit(f"{lane} 是坏卡（CLAUDE.md 红线），不派")
    hosts = json.loads((ROOT / "config" / "factory" / "hosts.json").read_text(encoding="utf-8"))["hosts"]
    spec = (hosts.get(lane.split(":")[0], {}).get("lanes") or {}).get(lane) or {}
    if not spec.get("tunnel_port") or not spec.get("enabled", True):
        raise SystemExit(f"道 {lane} 在 config/factory/hosts.json 里没有可用的 tunnel_port")
    return f"http://127.0.0.1:{spec['tunnel_port']}"


def run_prefix_ok(file_rel: str, run: str) -> bool:
    """take.file 必须在本剧前缀下（renders/<run>/…）；V1 前缀 renders/epNN/… 的版本是跨剧泄漏（C-14），不许当输入"""
    return str(file_rel or "").replace("\\", "/").startswith(f"renders/{run}/")


def v2_takes(td: dict, stage: str, run: str) -> list[dict]:
    return [t for t in td.get("takes") or [] if t.get("stage") == stage and run_prefix_ok(t.get("file"), run)]


def prod_pf_ok(run: str, shot: str, stage: str, n: int):
    """生产 takes.json 里同一版的 postflight.ok（沙箱 --force 改过的值不算数，报告里两个都给）"""
    p = ROOT / "data" / "renders" / run / shot_rel(shot) / "takes.json"
    d = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    t = next((t for t in d.get("takes") or [] if t.get("stage") == stage and t.get("n") == n), None)
    return ((t or {}).get("postflight") or {}).get("ok")


def activate_in_sandbox(shot: str, stage: str, n: int, *, lock: bool = False) -> None:
    """只改沙箱 takes.json 的 active（/ locked）：试跑用某个 V2 版本当输入"""
    from ns_render import pipeline as P
    p = P.shot_dir(shot) / "takes.json"
    assert str(p).startswith(str(SANDBOX)), p
    td = json.loads(p.read_text(encoding="utf-8"))
    td.setdefault("active", {})[stage] = n
    if lock:
        td.setdefault("locked", {})[stage] = n
    write_atomic(p, json.dumps(td, ensure_ascii=False, indent=1))


def cmd_last(a) -> dict:
    set_env(a.run)
    prep(a.run, a.shot)
    import producer as PR
    from ns_render import pipeline as P
    assert str(P.RENDERS).startswith(str(SANDBOX)), P.RENDERS
    td = P.load_takes(a.shot)
    firsts = v2_takes(td, "image", a.run)
    if not firsts:
        raise SystemExit("本镜没有本剧前缀下的首帧版本")
    fn = a.first_n or max(t["n"] for t in firsts)
    ft = next(t for t in firsts if t["n"] == fn)
    activate_in_sandbox(a.shot, "image", fn)
    # producer 尾帧分支要求首帧当前版本 postflight.ok；没打过分的 V2 首帧 → 沙箱里先补一次契约分
    pf = PR.take_pf(ft)
    report = {"shot": a.shot, "first_n": fn, "first_file": ft["file"], "first_pf_ok": pf.get("ok"),
              "first_pf_forced_in_sandbox": bool(pf.get("w41_forced")), "first_pf_ok_production": prod_pf_ok(a.run, a.shot, "image", fn)}
    if not pf.get("ok") and a.score_first:
        t0 = time.time()
        from ns_agent import frame_job as FJ
        from ns_render import unified_frame as UF
        script = P.load_script()
        ep, shot = P.find_shot(script, a.shot)
        job = FJ.build_first(UF.project_for(script), ep, shot, script.globals)
        newpf = UF._postflight(ft["file"], {"cast": job.get("cast"), "asset_refs": job.get("asset_refs")}, "gpu33")
        from ns_render import frame_edit as FE
        FE.annotate(a.shot, "image", fn, postflight=newpf)
        report.update(first_rescore_s=round(time.time() - t0, 1), first_pf_ok_after=newpf.get("ok"),
                      first_pf_reasons=(newpf.get("reasons") or [])[:6])
        if not newpf.get("ok") and not a.force:
            report["stop"] = "首帧契约不过：producer 不会做尾帧（--force 绕过只用于试跑）"
            return report
    if a.force:   # 只在沙箱：让 producer 的首帧前置检查放行
        from ns_render import frame_edit as FE
        cur = PR.take_pf(next(t for t in P.load_takes(a.shot)["takes"] if t["stage"] == "image" and t["n"] == fn))
        if not cur.get("ok"):
            FE.annotate(a.shot, "image", fn, postflight={**cur, "ok": True, "w41_forced": True})
    paths = PR.Paths(pd=SANDBOX / "producer" / a.run, run_id=a.run)
    paths.pd.mkdir(parents=True, exist_ok=True)
    script = P.load_script()
    fx = PR.FrameExec(paths, script)
    seed = P.seed_for(f"{a.shot}/w41/last", 1)
    tag = {"agent": "W41", "kind": "last_frame", "shot": a.shot, "obj": f"last:{a.shot}", "label": "W41 试跑尾帧"}
    t0 = time.time()
    out = fx.render("last", a.shot, a.lane, lane_url(a.lane), 1, {"name": "W41 试跑", "seed": seed}, tag)
    report["render_s"] = round(time.time() - t0, 1)
    if out.get("na"):
        report["stop"] = "编译器没有 last_prompt：本镜不需要尾帧（na）"
        return report
    t1 = time.time()
    pf_last = out["pf_future"].result(timeout=a.pf_timeout)
    report.update(last_n=out["take"], last_file=out["file"], gpu_s=out.get("gpu_s"),
                  postflight_s=round(time.time() - t1, 1), last_pf_ok=pf_last.get("ok"),
                  last_pf_reasons=(pf_last.get("reasons") or [])[:8], vqa_gate=pf_last.get("vqa_gate"),
                  current=pf_last.get("current"))
    fx.post_pool.shutdown(wait=False)
    return report


def cmd_show(a) -> dict:
    set_env(a.run)
    from ns_render import pipeline as P
    td = P.load_takes(a.shot)
    rows = []
    for t in td.get("takes") or []:
        pf = (t.get("postflight") or {})
        rows.append({"stage": t["stage"], "n": t["n"], "file": t["file"], "v2": run_prefix_ok(t["file"], a.run),
                     "pf_ok": pf.get("ok"), "created": t.get("created_at")})
    return {"renders": str(P.RENDERS), "active": td.get("active"), "locked": td.get("locked"), "takes": rows}


# ------------------------------------------------------------------------------------------------ 整集预览
def sandbox_videos(run: str, ep: int) -> dict:
    """沙箱 takes.json 里 W41 试跑出的视频（每镜最新一版）→ {镜: 仓库相对路径}"""
    out = {}
    for tj in sorted((sandbox_renders(run) / f"ep{ep:02d}").glob("S*/takes.json")):
        d = json.loads(tj.read_text(encoding="utf-8"))
        vs = [t for t in d.get("takes") or [] if t.get("stage") == "video" and (t.get("params") or {}).get("w41_trial")]
        if vs:
            t = max(vs, key=lambda t: t["n"])
            f = ROOT / "data" / t["file"]   # take.file 相对 DATA（NS_RENDERS_DIR 下 = _w41_trial/renders/<剧>/…）
            out[f"ep{ep:02d}-{tj.parent.name}"] = str(f.relative_to(ROOT)).replace(chr(92), "/") if f.is_file() else None
    return out


def cmd_preview(a) -> dict:
    """tools/assemble_series.build（生产同一份：配音 + 配乐 + 转场 + 响度，字幕只出 .srt）→ 沙箱 data/_w41_trial/preview/epNN/。
    生产 state 里没有视频的镜：本剧当前首帧占位；沙箱里有 W41 试跑视频的镜换成试跑视频"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.environ["NS_RUN"] = a.run
    from tools import assemble_series as A
    ep = int(a.shot.split("-")[0][2:]) if "-" in a.shot else int(a.shot.lstrip("ep"))
    trial = {k: v for k, v in sandbox_videos(a.run, ep).items() if v}
    orig_plan = A.plan

    def plan(e, state, *, best_effort_video):
        rows = orig_plan(e, state, best_effort_video=best_effort_video)
        for r in rows:
            if r["shot"] in trial:
                r.update(kind="best_effort", file=trial[r["shot"]], origin="W41 试跑视频（沙箱）", reason=None)
        return rows
    A.plan = plan
    out_dir = SANDBOX / "preview" / f"ep{ep:02d}"
    t0 = time.time()
    m = A.build(ep, preview=True, pull_on=not a.no_pull, dialogue_source=a.dialogue_source, bgm=not a.no_bgm, out_dir=out_dir)
    rep = {k: m.get(k) for k in ("output", "srt", "complete", "video_shots", "best_effort_shots", "placeholder_shots",
                                 "duration_s", "bgm", "loudness", "tts_fallback_lines", "subtitles", "warnings")}
    rep["build_s"] = round(time.time() - t0, 1)
    rep["trial_videos"] = trial
    info = ffprobe_info(ROOT / m["output"])
    rep["ffprobe"] = info
    shots = m.get("shots") or []
    rep["shot_durations"] = [(r["shot"], r["kind"], r.get("duration_s")) for r in shots]
    tot = round(sum(float(r.get("duration_s") or 0) for r in shots), 2)
    rep["duration_check"] = {"sum_shots_s": tot, "file_s": info.get("duration_s"),
                             "ok": abs(tot - float(info.get("duration_s") or 0)) <= 1.0,
                             "over_6s": [r["shot"] for r in shots if float(r.get("duration_s") or 0) > MAX_SHOT_S + 0.05]}
    rep["no_burned_subtitle_stream"] = "subtitle" not in (info.get("streams") or [])
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["prep", "last", "video", "preview", "show"])
    ap.add_argument("--run", default="series10_v2")
    ap.add_argument("--shot", required=True)
    ap.add_argument("--lane", default="gpu33:1")
    ap.add_argument("--first-n", type=int)
    ap.add_argument("--score-first", action="store_true", help="首帧没有契约分时先补打一次（沙箱）")
    ap.add_argument("--force", action="store_true", help="沙箱试跑：首帧契约不过也做尾帧")
    ap.add_argument("--pf-timeout", type=float, default=1800)
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--last-n", type=int)
    ap.add_argument("--recipe", help="默认 = video_policy / recipe_choice 的 face_default")
    ap.add_argument("--dry", action="store_true", help="video：只编译 + 硬规矩检查，不提交")
    ap.add_argument("--video-timeout", type=float, default=2400)
    ap.add_argument("--no-pull", action="store_true", help="preview：不连服务器读 state")
    ap.add_argument("--no-bgm", action="store_true")
    ap.add_argument("--dialogue-source", default="h3", choices=("tts", "h3"))
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.cmd == "prep":
        out = {"sandbox": str(prep(a.run, a.shot, refresh=True))}
    elif a.cmd == "last":
        out = cmd_last(a)
    elif a.cmd == "video":
        out = cmd_video(a)
    elif a.cmd == "preview":
        out = cmd_preview(a)
    else:
        out = cmd_show(a)
    blob = json.dumps(out, ensure_ascii=False, indent=1, default=str)
    (SANDBOX / "logs").mkdir(parents=True, exist_ok=True)
    write_atomic(SANDBOX / "logs" / f"{a.cmd}_{a.shot}_{time.strftime('%m%d-%H%M%S')}.json", blob)
    print(blob)
    return 0


# ------------------------------------------------------------------------------------------------ 视频
MAX_SHOT_S = 6.0          # C-08 / L-137：V2 单镜 ≤ 6 秒
LOOK_CAM_RE = r"(?<!not )(?<!never )(?<!no )\b(look(s|ing)? (directly )?(at|into) (the )?(camera|lens)|eye contact with the (camera|viewer))"
SUBTITLE_RE = r"\b(subtitle|caption|on-screen text|text overlay)s?\b|字幕"
AT_RE = r"\bAt \d{1,2}:\d{2}(\.\d{1,3})?\b"


def hard_rule_check(prompt: str, seconds: float, frames: int | None, fps: int = 24) -> dict:
    """视频提示词 / 时长的硬规矩（C-06 不看镜头、C-07 无字幕、C-08 ≤6 秒、L-141 At 只标切镜）。
    只查、不改；返回 {ok, problems}。At 时间戳：单镜作业里不许出现（镜内分拍用自然英文），出现就是违规"""
    import re as _re
    probs = []
    if seconds and float(seconds) > MAX_SHOT_S:
        probs.append(f"C-08 单镜 {seconds}s > {MAX_SHOT_S}s")
    if frames and frames / fps > MAX_SHOT_S + 0.5:
        probs.append(f"C-08 帧数 {frames}（{frames / fps:.2f}s @ {fps}fps）> {MAX_SHOT_S}s")
    text = prompt or ""
    neg = text.split("Negative", 1)[0]
    m = _re.search(LOOK_CAM_RE, neg, _re.I)
    if m:
        probs.append(f"C-06 提示词要求看镜头：…{neg[max(0, m.start() - 30):m.end() + 10]}…")
    m = _re.search(SUBTITLE_RE, neg, _re.I)
    if m and not _re.search(r"\b(no|without|never)\b[^.]{0,30}" + _re.escape(m.group(0)), neg, _re.I):
        probs.append(f"C-07 提示词出现字幕类词：{m.group(0)}")
    ats = _re.findall(AT_RE, text)
    if ats:
        probs.append(f"L-141 单镜作业里出现 At 时间戳 {len(ats)} 处（At 只标切镜）")
    return {"ok": not probs, "problems": probs}


def _build_jobs_mod():
    import importlib.util as u
    sp = u.spec_from_file_location("w41_build_jobs", ROOT / "tools/series10_video/build_jobs.py")
    m = u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def ffprobe_info(path: Path) -> dict:
    import subprocess
    exe = shutil.which("ffprobe") or "ffprobe"
    r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate,nb_frames",
                        "-of", "json", str(path)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return {"error": r.stderr[-300:]}
    d = json.loads(r.stdout)
    v = next((x for x in d.get("streams") or [] if x.get("codec_type") == "video"), {})
    return {"duration_s": round(float((d.get("format") or {}).get("duration") or 0), 3),
            "width": v.get("width"), "height": v.get("height"), "fps": v.get("r_frame_rate"), "nb_frames": v.get("nb_frames"),
            "streams": [x.get("codec_type") for x in d.get("streams") or []]}


def cmd_video(a) -> dict:
    """VIDEO10 同一份编译（build_jobs.compile_variant，L-088 配方 = video_policy.pika_only.allowed）→ 直接提交到一条空闲道 →
    取回 mp4 → 时长 / 硬规矩 / 运动量 → 沙箱 takes.json 登记一版 video（不设为当前）"""
    set_env(a.run)
    prep(a.run, a.shot)
    from PIL import Image
    from ns_render import pipeline as P
    from ns_render import motion_qc as MQ
    from ns_render.comfy_client import ComfyClient
    from ns_agent.vqa import contract as VQ
    from ns_schema.edits import Take
    assert str(P.RENDERS).startswith(str(SANDBOX)), P.RENDERS
    B = _build_jobs_mod()
    B.set_run(a.run)
    rep: dict = {"shot": a.shot, "lane": a.lane}
    td = P.load_takes(a.shot)
    firsts = v2_takes(td, "image", a.run)
    fn = a.first_n or max(t["n"] for t in firsts)
    ft = next(t for t in firsts if t["n"] == fn)
    pf_first = ft.get("postflight") or {}
    rep.update(first_n=fn, first_file=ft["file"], first_pf_ok=pf_first.get("ok"),
               first_pf_forced_in_sandbox=bool(pf_first.get("w41_forced")),
               first_pf_ok_production=prod_pf_ok(a.run, a.shot, "image", fn),
               first_q9_passed=VQ.q9_passed(pf_first), q9_enforced=VQ.enforced())
    lasts = [t for t in td.get("takes") or [] if t.get("stage") == "last" and (not a.last_n or t["n"] == a.last_n)
             and (run_prefix_ok(t.get("file"), a.run) or str(t.get("file") or "").startswith(f"_w41_trial/renders/{a.run}/"))]
    lt = max(lasts, key=lambda t: t["n"]) if lasts else None
    if lt:
        pf_last = lt.get("postflight") or {}
        rep.update(last_n=lt["n"], last_file=lt["file"], last_pf_ok=pf_last.get("ok"), last_q9_passed=VQ.q9_passed(pf_last))
    if not (pf_first.get("ok") and VQ.q9_passed(pf_first)) and not a.force:
        rep["stop"] = ("首帧没过契约 / Q9：生产链（build_jobs.passed_frames）不会派视频。--force 只在沙箱绕过"
                       f"（首帧 Q9 = {rep['first_q9_passed']}）")
        return rep
    # 首帧 JPEG（与 passed_frames 同法：video/inputs/<镜>_<sha8>.jpg）——放沙箱
    import hashlib
    src = P.DATA / ft["file"]
    inp = SANDBOX / "video_inputs"
    inp.mkdir(parents=True, exist_ok=True)
    jpg = inp / f"{a.shot}_{hashlib.sha256(src.read_bytes()).hexdigest()[:8]}.jpg"
    if not jpg.exists():
        with Image.open(src) as im:
            im.convert("RGB").save(jpg, "JPEG", quality=95)
    rel_jpg = str(jpg.relative_to(ROOT)).replace("\\", "/")
    frames_of = {a.shot: {"file": rel_jpg, "postflight": pf_first, "status": "pass", "take": fn,
                          "created_at": str(ft.get("created_at") or "")}}
    B.LASTS_OF.clear()
    if lt:
        B.LASTS_OF[a.shot] = {"file": "data/" + lt["file"], "created_at": str(lt.get("created_at") or "")}
    ep = int(a.shot.split("-")[0][2:])
    specs = B.load_specs(eps=[ep])
    spec = specs[a.shot]
    from ns_recipes import registry as R
    reg = R.load()
    ch = B.recipe_choice()
    rid = a.recipe or (ch["face_default"] if spec.faces else ch["noface_default"])
    t0 = time.time()
    var = B.compile_variant(spec, reg, rid, 1, "v1", frames_of)
    rep.update(recipe=rid, recipe_choice_rule=ch.get("rule"), compile_s=round(time.time() - t0, 1),
               spec_seconds=float(spec.duration_s), status=var.get("status"), frames=var.get("frames"),
               preflight=var.get("preflight"), lint_errors=[e.get("code") for e in var.get("lint_errors") or []],
               lint_warns=var.get("lint_warns"), inputs=var.get("inputs"))
    hr = hard_rule_check(var.get("prompt") or "", float(spec.duration_s), var.get("frames"))
    rep["hard_rules"] = hr
    (SANDBOX / "logs").mkdir(parents=True, exist_ok=True)
    write_atomic(SANDBOX / "logs" / f"{a.shot}.video.prompt.txt", var.get("prompt") or "")
    if var.get("status") != "ready":
        rep["stop"] = f"编译不是 ready：{var.get('status')}"
        return rep
    if not hr["ok"] and not a.force:
        rep["stop"] = "硬规矩不过，不提交"
        return rep
    if not (var.get("preflight") or {}).get("ok") and not a.force:
        rep["stop"] = "视频 preflight 不过（vidgen 非 validate 模式同样不提交）"
        return rep
    if a.dry:
        rep["stop"] = "--dry：只编译不提交"
        return rep
    client = ComfyClient(lane_url(a.lane), timeout=120)
    g = json.loads(json.dumps(var["graph"]))
    for node in g.values():
        for k, v in list((node.get("inputs") or {}).items()):
            if isinstance(v, str) and v.startswith("@"):
                node["inputs"][k] = client.upload_image(ROOT / var["inputs"][v], subfolder="video10", remote=False)
        if node["class_type"] == "SaveVideo":
            node["inputs"]["filename_prefix"] = f"video10/w41_{a.shot}"
    t1 = time.time()
    entry, gpu_secs = client.run(g, timeout_s=a.video_timeout)
    rep["render_s"] = round(time.time() - t1, 1)
    item = next(f for f in client.output_files(entry) if f["filename"].endswith(".mp4"))
    with P.shot_lock(a.shot):
        n = P._next_n(a.shot, "video")
    rel_dir = f"{str(P.shot_dir(a.shot).relative_to(P.DATA)).replace(chr(92), '/')}/takes"
    base = f"{rel_dir}/video_{n:03d}_w41"
    client.download(item, P.DATA / f"{base}.mp4")
    info = ffprobe_info(P.DATA / f"{base}.mp4")
    lf = P.extract_last_frame(P.DATA / f"{base}.mp4", P.DATA / f"{base}_last.png")
    motion = MQ.video_motion(P.DATA / f"{base}.mp4")
    dur_ok = bool(info.get("duration_s")) and info["duration_s"] <= MAX_SHOT_S + 0.1
    take = Take(n=n, stage="video", file=f"{base}.mp4", seed=int(var.get("seed") or 0), prompt=var.get("prompt") or "",
                seconds=rep["render_s"], frames=var.get("frames"), created_at=P.now(),
                last_frame=f"{base}_last.png" if lf else None, workflow=rid, from_first=fn,
                params={"w41_trial": True, "recipe": rid, "lane": a.lane, "inputs": var.get("inputs"),
                        "hard_rules": hr, "ffprobe": info, "duration_ok": dur_ok, "spec_seconds": float(spec.duration_s)},
                qc={"motion": motion})
    P._add_take(a.shot, take, activate=False)
    rep.update(video_n=n, video_file=f"{base}.mp4", ffprobe=info, duration_ok=dur_ok, motion=motion,
               extracted_last_frame=f"{base}_last.png" if lf else None)
    return rep


if __name__ == "__main__":
    sys.exit(main())
