"""L-088 全量重做（WORKFLOW 牵头，项目方 11-01 ~18:0x：“图片：全部重新勾一次，用最新的瑞丽 R0 方案；视频：全部用皮卡来做，
皮卡做不了就等”；规则 K-OPS-W08）。可续跑、可暂停；在服务器常驻模式下执行（K-OPS-W07）。

前置闸门（全部 ok 才会派图片；顺序 = 总调度 18:0x / 18:3x）：
  G20         RSI：林晚身份脸高清重裁
  SCRIPT      SCRIPT-RSI：R11-3 剧本返修并导入（tools/pipeline/repair_chain.py）
  G21         RSI：导入之后重编 first_frame_jobs.json（自动核：jobs 修改时间晚于 data/import/script_v2.json）
  W5          PROD：局部特写编译器修复
  PIKA_SMOKE  跳板恢复后服务器上 Pika 冒烟一镜，总调度亲审通过（resident_sync.py smoke）
闸门由负责方 / 总调度登记：full_redo.py gate <ID> --by <谁> --note <证据>。

做法（复用现有部件，不另造）：
  图片：对每镜 first:<镜>，在负责该集的服务器上调 producer.py reject（驳回重出，计划 frame_v9×2，原因“L-088 全量重做（R0）”，
        不计 3 次上限）；替换版过契约 + 本地看图闸门 → producer.auto_review_redo 自动换上（VQAGATE 已接通），旧版保留不删；
        尾帧在首帧换版后由 producer 按过期重做。
  视频：recipe_choice.json 全是 i2va_pika_flex，config/pipeline/video_policy.json pika_only；首帧换版 → vidgen.check_stale 把旧片
        挪进 superseded（不删）→ 新首帧过闸门后派 Pika（video_requires_q9，VQAGATE after_network.py）；flush 类镜 hold。
  合成：night.py 一集齐了在服务器上合成（原片 + 放大，PROD）。

  status                       闸门 + 进度
  gate ID --by X [--note N]    登记一个闸门通过
  plan                         写 data/autopilot/full_redo/plan.json（80 镜、负责机器、hold 清单、GPU 时长估算）
  apply [--host H] [--dry]     闸门全过才派；逐镜记 state.json，已派的跳过（可续跑）
  pause / resume               两台服务器 producer pause / resume（by FULL_REDO）
  reset-redo [--since ISO] [--shots a,b] [--dry]   白出不占次数：L-088 驳回对象的 redo_tries 归零（历史保留）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
OUT = ROOT / "data/autopilot/full_redo"


def run_dir() -> Path:
    """现行主 run 的目录（tools/autopilot/runs.py；K-OPS-W17 / K-OPS-S01 不写死 run_id）"""
    import runs as RUNS
    return ROOT / "data/pipeline/runs" / RUNS.primary_run()
GATES = OUT / "gates.json"
STATE = OUT / "state.json"
PLAN = OUT / "plan.json"
GATE_IDS = ["G20", "SCRIPT", "G21", "W5", "PIKA_SMOKE"]
REASON = "L-088 全量重做（R0：现行 frame_v9 / 徕卡 S★）"
PRESETS = "frame_v9,frame_v9"
# GPU 时长估算口径（出处见 plan.json 的 basis）
FRAME_RENDER_S = 64.1          # data/producer/log.jsonl 869 次首尾帧 render_s 中位数（p90 158.8）
FRAME_TRIES = 1.6
PIKA_S_PER_FRAME = 513 / 175   # ep01-S3 冒烟：GPU 513 s / 175 帧（含载入）
VIDEO_TRIES = 1.8
IMAGE_LANES, VIDEO_LANES = 5, 6


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def js(p, d):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(".tmp")
    t.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(t, p)


def g21_check(run_dir: Path) -> dict:
    """K-OPS-Q24：tools/pipeline/image_jobs.jobs_vs_import（镜头集合一致 + 每条作业提示词来源 sha = 现行 script_v2.json）"""
    import importlib.util as _ilu
    _sp = _ilu.spec_from_file_location("ns_image_jobs_g21", Path(__file__).resolve().parents[2] / "tools/pipeline/image_jobs.py")
    _ij = _ilu.module_from_spec(_sp)
    _sp.loader.exec_module(_ij)
    return _ij.jobs_vs_import(run_dir)


def gates_status() -> dict:
    g = jl(GATES, {}) or {}
    out = {i: g.get(i) or {"ok": False} for i in GATE_IDS}
    jobs = run_dir() / "assets/first_frame_jobs.json"
    script = ROOT / "data/import/script_v2.json"
    if out["G21"].get("ok") and jobs.exists() and script.exists():
        # K-OPS-Q24（RSI 11-01，总调度授权）：不比修改时间，核对镜头集合 + 每条作业的提示词来源 sha = 现行 script_v2.json
        try:
            chk = g21_check(jobs.parent.parent)
        except Exception as e:  # noqa: BLE001
            chk = {"ok": False, "error": repr(e)[:200]}
        if not chk.get("ok"):
            out["G21"] = {**out["G21"], "ok": False,
                          "auto": "首帧作业和导入稿对不上：缺 {} 镜、多 {} 镜、提示词来源 sha 过期 {} 条{}".format(
                              len(chk.get("missing") or []), len(chk.get("extra") or []), len(chk.get("stale_sha") or []),
                              "；" + chk["error"] if chk.get("error") else "")}
    return out


def image_jobs_green() -> dict:
    """AUDIT 22:13：作业清单必须和现行编译器一致（tests/test_image_jobs.py 绿）且 jobs_vs_import ok，否则一提交就被
    compile_mismatch 拦下、白占次数。恢复 producer / apply 前的前置检查（不缓存，约 4 秒）"""
    import subprocess
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_image_jobs.py"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                       env={**os.environ, "PYTHONUTF8": "1"})
    tail = [ln for ln in (r.stdout or "").splitlines() if ln.strip()][-3:]
    try:
        chk = g21_check(run_dir())
    except Exception as e:  # noqa: BLE001
        chk = {"ok": False, "error": repr(e)[:200]}
    return {"ok": r.returncode == 0 and bool(chk.get("ok")), "tests_rc": r.returncode, "tests": " | ".join(tail)[-300:],
            "jobs_vs_import": {k: chk.get(k) for k in ("ok", "missing", "extra", "stale_sha", "error") if k in chk}}


def gates_ok(check_jobs: bool = True) -> bool:
    if not all(v.get("ok") for v in gates_status().values()):
        return False
    return image_jobs_green()["ok"] if check_jobs else True


def owner_host(ep: int) -> str:
    import resident_sync as RS
    return next(h for h, eps in RS.HOSTS.items() if ep in eps)


def make_plan() -> dict:
    sys.path[:0] = [str(ROOT / p) for p in ("tools/series10_video", "services/recipes", "packages/schema", "services/agent",
                                             "services/render_router")]
    import build_jobs as B
    from ns_schema.shot_spec import frames_for_seconds
    from ns_render import pipeline as P
    reg, specs, ch = B.R.load(), B.load_specs(), B.recipe_choice()
    from ns_recipes import selector as S
    shots, holds, frames_tot = [], [], 0
    for sid, sp in sorted(specs.items(), key=lambda kv: (kv[1].episode, kv[1].index if hasattr(kv[1], "index") else kv[0])):
        ep = sp.episode
        fr = frames_for_seconds(sp.duration_s, 24)
        frames_tot += fr
        td = P.load_takes(sid) if (P.shot_dir(sid) / "takes.json").exists() else {}
        cur = {**(td.get("locked") or {}), **(td.get("active") or {})}     # 当前 = active（无则定稿）
        rid = ch["face_default"] if sp.faces else ch["noface_default"]
        sel = S.select(sp, reg, allow={rid})
        from ns_recipes import compiler as C
        why = C.hold_reason(reg, rid, sel.overlays, sp)
        row = {"shot": sid, "ep": ep, "host": owner_host(ep), "frames": fr, "recipe": rid,
               "current_first": cur.get("image"), "current_last": cur.get("last"), "video_hold": why}
        shots.append(row)
        if why:
            holds.append({"shot": sid, "reason": why})
    img_s = len(shots) * 2 * FRAME_RENDER_S * FRAME_TRIES
    vid_s = frames_tot * PIKA_S_PER_FRAME * VIDEO_TRIES
    plan = {"schema": "nsfs.full_redo_plan/1", "decision": "L-088", "made_at": time.strftime("%F %T"), "shots": shots,
            "video_holds": holds,
            "estimate": {"image_gpu_h": round(img_s / 3600, 1), "video_gpu_h": round(vid_s / 3600, 1),
                         "total_gpu_h": round((img_s + vid_s) / 3600, 1),
                         "wall_h_if_full": round(img_s / 3600 / IMAGE_LANES + vid_s / 3600 / VIDEO_LANES, 1),
                         "basis": {"frame_render_s_median": FRAME_RENDER_S, "frame_tries": FRAME_TRIES,
                                   "pika_s_per_frame": round(PIKA_S_PER_FRAME, 2), "video_tries": VIDEO_TRIES,
                                   "frames_total": frames_tot, "objects_image": len(shots) * 2,
                                   "src": "data/producer/log.jsonl render_s 中位数；data/autopilot/pika_smoke/ep01-S3.job.json（513 s / 175 帧）"}}}
    js(PLAN, plan)
    return plan


def import_sha_now() -> str:
    import hashlib
    p = ROOT / "data/import/script_v2.json"
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else ""


def apply(host: str | None = None, dry: bool = False, executor: str = "laptop", eps: set | None = None) -> dict:
    """executor=laptop（默认，总调度 18:4x 分工：出图由笔记本 producer 统一负责，道 = laptop:0 + 跳板通时的服务器出图道）：
    在笔记本本机调 producer.py reject；executor=server：在负责该集的服务器上调（服务器 producer 常驻时才用）。
    逐镜记 state.json，已标的跳过（可续跑）；能用几条道由 producer 的道表 / 退避决定（部分道可用就先跑几条）"""
    if not gates_ok():
        return {"ok": False, "why": "前置闸门没全过（a/b 未完成前不开始全量出图），或作业清单与编译器 / 导入稿不一致（AUDIT 22:13）",
                "gates": gates_status(), "image_jobs": image_jobs_green()}
    import resident_sync as RS
    plan = jl(PLAN) or make_plan()
    st = jl(STATE, {"done": {}, "errors": {}}) or {"done": {}, "errors": {}}
    sent = 0
    for row in plan["shots"]:
        if host and row["host"] != host:
            continue
        if eps and int(row.get("ep") or 0) not in eps:
            continue
        oid = f"first:{row['shot']}"
        # 逐集流水线（总调度 22:06）：同一镜号在新导入稿里可能是新内容——只有“同一份导入稿 sha 下已标过”才跳过
        if (st["done"].get(oid) or {}).get("import_sha") == import_sha_now():
            continue
        args = ["reject", "--obj", oid, "--n", str(int(row.get("current_first") or 0)), "--reason", REASON, "--plan", PRESETS,
                "--by", "WORKFLOW-L088"]
        where = "laptop" if executor == "laptop" else row["host"]
        if dry:
            print(where, " ".join(args))
            continue
        try:
            if executor == "laptop":
                import subprocess
                r = subprocess.run([sys.executable, str(ROOT / "tools/autopilot/producer.py"), *args], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=120, cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"})
                if r.returncode:
                    raise RuntimeError(r.stderr[-200:])
            else:
                cmd = (f"cd {RS.R} && OFFLINE_SELF={row['host']} {RS.OFF}/venv/bin/python tools/autopilot/producer.py "
                       + " ".join(f"'{x}'" for x in args))
                RS.ssh(row["host"], cmd, timeout=120, tries=4)
            st["done"][oid] = {"at": time.strftime("%F %T"), "where": where, "reject_n": row.get("current_first"),
                               "import_sha": import_sha_now()}
            st["errors"].pop(oid, None)
            sent += 1
        except Exception as e:  # noqa: BLE001
            st["errors"][oid] = repr(e)[:200]
        js(STATE, st)
    return {"ok": True, "sent": sent, "done": len(st["done"]), "errors": len(st["errors"])}


def reset_redo(since: str | None = None, shots: list[str] | None = None, by: str = "WORKFLOW", dry: bool = False) -> dict:
    """总调度 19:41：IMGFIX 修根因期间白出的驳回重出不占次数——把 L-088 驳回对象的账本 redo_tries 归零、清 redo_candidate，
    redo_history 保留并追加一条“次数恢复”记录（审计）。since：只恢复这之后出的（ISO）；shots：只恢复这些镜。
    驳回计划（master_rejects.json，frame_v9×2）不动，恢复派单时直接接着用"""
    led_p = ROOT / "data/producer/attempts.json"
    rj = jl(ROOT / "data/producer/master_rejects.json", {}) or {}
    L = jl(led_p, {}) or {}
    changed = []
    for oid, r in rj.items():
        if "L-088" not in str(r.get("reason")):
            continue
        if shots and oid.split(":", 1)[1] not in shots:
            continue
        rec = L.get(oid) or {}
        hist = rec.get("redo_history") or []
        n_since = [h for h in hist if not since or str(h.get("at") or "") >= since]
        if not int(rec.get("redo_tries") or 0) and not rec.get("redo_candidate"):
            continue
        if since and not n_since:
            continue
        changed.append({"obj": oid, "redo_tries_was": rec.get("redo_tries"), "candidate_was": rec.get("redo_candidate")})
        if not dry:
            rec["redo_history"] = hist + [{"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": "次数恢复：IMGFIX 修根因期间白出不占次数（总调度 19:41）",
                                           "by": by, "redo_tries_was": rec.get("redo_tries")}]
            rec.update(redo_tries=0, redo_candidate=None)
            L[oid] = rec
    if changed and not dry:
        js(led_p, L)
    return {"changed": len(changed), "objects": changed[:100], "dry": dry}


def reject_stale_clause(pattern: str, since: str, reason: str, watch_min: int = 0, dry: bool = False, whole: bool = False) -> dict:
    """编译器改了某句（例 VIDEO-RCA 23:5x 双人句切回实测句）之后：since 之后出的首 / 尾帧版本里提示词还含旧句 pattern 的，
    逐个 producer reject（驳回重出 frame_v9×2，不计次，旧版保留）。watch_min > 0：每分钟再扫一次，接住还在出的单（在途的旧稿）"""
    import glob
    import subprocess
    done = set()
    t_end = time.time() + watch_min * 60
    while True:
        for f in glob.glob(str(ROOT / "data/renders/ep*/S*/takes.json")):
            sid = "-".join(Path(f).parent.parts[-2:])
            d = jl(f, {}) or {}
            for t in d.get("takes") or []:
                key = (sid, t.get("stage"), t.get("n"))
                if (t.get("stage") not in ("image", "last") or key in done or str(t.get("created_at") or "") < since
                        or pattern not in (json.dumps(t, ensure_ascii=False) if whole else (t.get("prompt") or "")) or t.get("master_reject")):
                    continue
                done.add(key)
                oid = ("first:" if t["stage"] == "image" else "last:") + sid
                if dry:
                    print("would reject", oid, t["n"], t.get("created_at"))
                    continue
                subprocess.run([sys.executable, str(ROOT / "tools/autopilot/producer.py"), "reject", "--obj", oid, "--n", str(t["n"]),
                                "--reason", reason, "--plan", PRESETS, "--by", "WORKFLOW"], cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120, env={**os.environ, "PYTHONUTF8": "1"})
                print(time.strftime("%H:%M:%S"), "rejected", oid, t["n"], t.get("created_at"), flush=True)
        if time.time() >= t_end:
            break
        time.sleep(60)
    return {"rejected": sorted(done)}


def reject_old_jobs(shots: list[str], since: str, reason: str, watch_min: int = 0, dry: bool = False) -> dict:
    """作业重编后（例 IMGFIX 00:1x K-REN-705），这些镜 since 之后出的首帧若不是按现行作业出的（版本提示词 ≠ 现行作业提示词），
    逐个 producer reject（frame_v9×2、不计次、旧版保留）；watch_min > 0 每分钟再扫，接住按旧作业派出、还在出的单"""
    import subprocess
    done = set()
    t_end = time.time() + watch_min * 60
    while True:
        jobs = {j["shot"]: j for j in (jl(run_dir() / "assets/first_frame_jobs.json", {}) or {}).get("jobs") or []
                if not str(j.get("status", "")).startswith("stale:")}
        for sid in shots:
            ep, sn = sid.split("-")
            d = jl(ROOT / "data/renders" / ep / sn / "takes.json", {}) or {}
            cur = (jobs.get(sid) or {}).get("prompt") or ""
            for t in d.get("takes") or []:
                key = (sid, t.get("n"))
                if (t.get("stage") != "image" or key in done or str(t.get("created_at") or "") < since or t.get("master_reject")
                        or not cur or (t.get("prompt") or "").strip() == cur.strip() or cur.strip() in (t.get("prompt") or "")):
                    continue
                done.add(key)
                if dry:
                    print("would reject", sid, t["n"], t.get("created_at"))
                    continue
                subprocess.run([sys.executable, str(ROOT / "tools/autopilot/producer.py"), "reject", "--obj", f"first:{sid}",
                                "--n", str(t["n"]), "--reason", reason, "--plan", PRESETS, "--by", "WORKFLOW"], cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                               env={**os.environ, "PYTHONUTF8": "1"})
                print(time.strftime("%H:%M:%S"), "rejected", sid, t["n"], t.get("created_at"), flush=True)
        if time.time() >= t_end:
            break
        time.sleep(60)
    return {"rejected": sorted(done)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["status", "gate", "plan", "apply", "pause", "resume", "reset-redo", "reject-stale-clause", "reject-old-jobs"])
    ap.add_argument("--pattern", default="")
    ap.add_argument("--reason", nargs="*", default=[])     # 总调度 01:2x：调用方没加引号时多个词也收下（拼回一句），不再参数报错
    ap.add_argument("--watch-min", type=int, default=0)
    ap.add_argument("--whole-take", action="store_true", help="在整条版本记录里找（参考图路径等），不只提示词")
    ap.add_argument("--since")
    ap.add_argument("--eps", default="")
    ap.add_argument("--shots", default="")
    ap.add_argument("gate_id", nargs="?")
    ap.add_argument("--by", default="")
    ap.add_argument("--note", nargs="*", default=[])
    ap.add_argument("--host")
    ap.add_argument("--executor", choices=["laptop", "server"], default="laptop")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    a.reason = " ".join(a.reason) if isinstance(a.reason, list) else a.reason
    a.note = " ".join(a.note) if isinstance(a.note, list) else a.note
    if a.cmd == "status":
        print(json.dumps({"gates": gates_status(), "image_jobs": image_jobs_green(), "gates_ok": gates_ok(),
                          "state": jl(STATE, {})}, ensure_ascii=False, indent=1)[:4000])
    elif a.cmd == "gate":
        if a.gate_id not in GATE_IDS or not a.by:
            print("用法：gate <" + "|".join(GATE_IDS) + "> --by <谁> [--note 证据]")
            return 2
        g = jl(GATES, {}) or {}
        g[a.gate_id] = {"ok": True, "by": a.by, "note": a.note, "at": time.strftime("%F %T")}
        js(GATES, g)
        print(json.dumps(gates_status(), ensure_ascii=False))
    elif a.cmd == "plan":
        p = make_plan()
        print(json.dumps({"shots": len(p["shots"]), "video_holds": p["video_holds"], "estimate": p["estimate"]}, ensure_ascii=False, indent=1))
    elif a.cmd == "apply":
        eps = {int(x) for x in a.eps.split(",") if x.strip()} if a.eps else None
        print(json.dumps(apply(a.host, a.dry, a.executor, eps), ensure_ascii=False, indent=1)[:3000])
    elif a.cmd == "reject-old-jobs":
        print(json.dumps(reject_old_jobs([x for x in a.shots.split(",") if x], a.since or "", a.reason or "作业已重编", a.watch_min, a.dry),
                         ensure_ascii=False)[:3000])
    elif a.cmd == "reject-stale-clause":
        print(json.dumps(reject_stale_clause(a.pattern, a.since or "", a.reason or "编译器旧句失效", a.watch_min, a.dry, a.whole_take),
                         ensure_ascii=False)[:3000])
    elif a.cmd == "reset-redo":
        print(json.dumps(reset_redo(a.since, [x for x in a.shots.split(",") if x] or None, a.by or "WORKFLOW", a.dry),
                         ensure_ascii=False, indent=1)[:3000])
    elif a.cmd in ("pause", "resume"):
        import resident_sync as RS
        for h in RS.HOSTS:
            try:
                RS.ssh(h, f"cd {RS.R} && {RS.OFF}/venv/bin/python tools/autopilot/producer.py {a.cmd} --by FULL_REDO --note 'L-088 全量重做 {a.cmd}'",
                       timeout=120, tries=3)
                print(h, a.cmd, "ok")
            except Exception as e:  # noqa: BLE001
                print(h, a.cmd, "失败", repr(e)[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
