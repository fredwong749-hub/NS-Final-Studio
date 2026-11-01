"""流水线出图登记为画布版本（SERIES 2026-11-01，BE-5，UIAUDIT 提）。

把 series 流水线（IMGGEN 等）出的首帧 / 尾帧登记成 data/renders/<ep>/<S>/takes.json 里的候选 take：
  - 走系统已有的写入函数 ns_render.pipeline._add_take（每镜锁、版本号顺延、坏图检查、规则版本 / 输入哈希盖章），
    activate=False（不设为当前）、不加锁 —— 界面上能选定、对比、回滚；
  - 标暂定 + 来源：take.params = {tentative, label, origin{run, job, attempt, file, sha256, lane, pid, qc}, rendered_size}；
  - 可重复执行：同一镜同一 stage 已有 params.origin.sha256 相同的 take → 跳过（不重复登记）。
设定图（人物）不在这里：人物身份底图在资产系统里不走版本链，按暂定参考图登记（POST /api/assets/{id}/refs）。

用法：
  # 从 IMGGEN 的 state.json 登记每镜当前选中的首帧（标“旧配方”）
  .venv/Scripts/python.exe tools/pipeline/register_takes.py --imggen-state data/pipeline/runs/<run_id>/images/state.json --label 旧配方
  # 通用清单：[{shot, stage?, file, seed?, prompt?, refs?, label?, origin?}]
  .venv/Scripts/python.exe tools/pipeline/register_takes.py --manifest items.json --label 新配方
  # 跟随：每 N 秒重读 state.json，新出 / 新选中的图自动登记（新配方重出时用）
  .venv/Scripts/python.exe tools/pipeline/register_takes.py --imggen-state … --label 新配方 --follow 60
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/render_router", "packages/schema", "services/agent", "services/recipes"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

STAGES = ("image", "last", "video")   # DATAALIGN 11-01：video = VIDEO10 过了门的片子（见 items_from_video10）


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _size(p: Path) -> list[int] | None:
    try:
        from PIL import Image
        with Image.open(p) as im:
            return [int(im.width), int(im.height)]
    except Exception:  # noqa: BLE001
        return None


def items_from_imggen(state_path: Path, *, all_attempts: bool = False) -> list[dict]:
    """IMGGEN state.json → 登记条目：每个 frame 作业的 chosen（或全部已出图的尝试）"""
    st = json.loads(Path(state_path).read_text(encoding="utf-8"))
    run = Path(state_path).parent.parent.name
    out = []
    for key, job in (st.get("jobs") or {}).items():
        if job.get("kind") != "frame" or not job.get("shot"):
            continue
        # 只要已出完的尝试（有 t_done / 已评分）：跟随模式下不会把正在写的图登记进去
        atts = [a for a in job.get("attempts") or [] if a.get("file") and (a.get("t_done") or a.get("state") == "scored")]
        if not all_attempts:
            atts = [a for a in atts if a.get("id") == job.get("chosen")]
        for a in atts:
            out.append({"shot": job["shot"], "stage": "image", "file": a["file"], "seed": a.get("seed") or 0,
                        "prompt": a.get("prompt") or "", "refs": a.get("refs") or [],
                        "origin": {"run": run, "job": key, "attempt": a.get("id"), "lane": a.get("lane"),
                                   "pid": a.get("pid"), "chosen": a.get("id") == job.get("chosen"),
                                   "job_status": job.get("status"), "qc": a.get("qc")}})
    return out


def _first_take_for(shot: str, input_name: str) -> int | None:
    """VIDEO10 的首帧输入文件名 = <镜号>_<首帧源文件 sha256 前 8 位>.jpg → 对应的首帧版本号"""
    from ns_render import pipeline as P
    sha8 = Path(input_name).stem.rsplit("_", 1)[-1]
    for t in reversed(P.load_takes(shot).get("takes", [])):
        if t.get("stage") != "image":
            continue
        o = ((t.get("params") or {}).get("origin") or {}).get("sha256") or ""
        if o.startswith(sha8):
            return t["n"]
        f = P.DATA / t["file"]
        if f.is_file() and _sha(f).startswith(sha8):
            return t["n"]
    return None


def items_from_video10(video_dir: Path) -> list[dict]:
    """VIDEO10（tools/series10_video）state_<host>.json → 视频登记条目：每镜 status=done 的 chosen 片子。
    文件优先 clips/（原片），本机没有就用 _preview/（标 origin.preview=true）。postflight = 片子门（score.gate）"""
    video_dir = Path(video_dir)
    jobs = {}
    try:
        jobs = {j["shot"]: j for j in json.loads((video_dir / "jobs.json").read_text(encoding="utf-8")).get("shots") or []}
    except (OSError, ValueError):
        pass
    out = []
    for sf in sorted(video_dir.glob("state_*.json")):
        if sf.stem.endswith("_validate"):
            continue
        st = json.loads(sf.read_text(encoding="utf-8"))
        for sid, v in (st.get("shots") or {}).items():
            ch = v.get("chosen")
            if v.get("status") != "done" or not ch:
                continue
            r = next((x for x in v.get("renders") or [] if x.get("variant") == ch and x.get("state") == "scored"), None)
            if not r:
                continue
            gate = (r.get("score") or {}).get("gate") or {}
            f = r.get("file")
            preview = not (f and (ROOT / f).is_file())
            if preview:
                f = r.get("preview")
            if not f:
                continue
            job = jobs.get(sid) or {}
            var = (job.get("variants") or {}).get(ch) or {}
            # VIDEO10 11-01 起每次出片记 first_frame_take（state 的 render 或 jobs.json）；旧片按首帧输入文件名的 sha8 反查
            ff = r.get("first_frame_take") or job.get("first_frame_take")
            if ff is None and job.get("first_frame"):
                ff = _first_take_for(sid, job["first_frame"])
            out.append({
                "shot": sid, "stage": "video", "file": f, "seed": r.get("seed") or 0, "prompt": var.get("prompt") or "",
                "workflow": "video10", "frames": var.get("frames") or job.get("frames"), "seconds": job.get("seconds"),
                "from_first": ff,
                "origin": {"run": f"{video_dir.parent.name}/{video_dir.name}", "host": st.get("host"), "variant": ch, "recipe": r.get("recipe"),
                           "lane": r.get("lane"), "pid": r.get("pid"), "remote_file": r.get("file"), "preview": preview,
                           "first_frame_input": job.get("first_frame"), "spec_hash": job.get("spec_hash"),
                           "verdict": (r.get("score") or {}).get("verdict"), "score": r.get("score")},
                "postflight": {"ok": bool(gate.get("pass")), "items": [], "reasons": list(gate.get("fails") or [])},
            })
    return out


def retract_stale_video10(log=print) -> list[dict]:
    """当前视频是 VIDEO10 片子、但它用的首帧（from_first）已不是当前首帧或不再过契约 → 撤下当前视频（版本留着，
    params.retracted 记原因与时间）。与 VIDEO10 编排器“出片用的首帧被撤 → 旧片进 superseded”同一规则（11-01 约定）"""
    from ns_render import auto_current as AC
    from ns_render import pipeline as P
    out = []
    for sid in sorted(current_shots()):
        with P.shot_lock(sid):
            data = P.load_takes(sid)
            act = data.get("active") or {}
            vn = act.get("video")
            vt = next((t for t in data.get("takes") or [] if t.get("stage") == "video" and t.get("n") == vn), None)
            if not vt or vt.get("workflow") != "video10" or (data.get("locked") or {}).get("video") == vn:
                continue
            ff = vt.get("from_first")
            img = next((t for t in data["takes"] if t.get("stage") == "image" and t.get("n") == act.get("image")), None)
            why = None
            if ff is None:
                why = "片子用的首帧不在版本链里（无法确认是当前首帧）"
            elif act.get("image") != ff:
                why = f"片子用的首帧 v{ff} 已不是当前首帧（当前 {act.get('image')}）"
            elif not AC.passes(img):
                why = f"片子用的首帧 v{ff} 已不过契约"
            elif (img or {}).get("master_reject"):
                mr = img["master_reject"]
                why = f"片子用的首帧 v{ff} 被总调度打回（{mr.get('reason') if isinstance(mr, dict) else mr}）"
            if not why:
                continue
            act.pop("video", None)
            vt.setdefault("params", {})["retracted"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "why": why,
                                                        "by": "tools/pipeline/register_takes.py --video10"}
            P._save_takes(sid, data)
        r = {"shot": sid, "stage": "video", "status": "retracted", "n": vn, "why": why}
        out.append(r)
        log(json.dumps(r, ensure_ascii=False))
    return out


def registered_shas(shot_id: str, stage: str) -> set[str]:
    from ns_render import pipeline as P
    return {((t.get("params") or {}).get("origin") or {}).get("sha256")
            for t in P.load_takes(shot_id).get("takes", []) if t.get("stage") == stage} - {None}


def register(item: dict, *, label: str, dry: bool = False) -> dict:
    """登记一条；→ {shot, stage, status: registered|skipped|missing, n?}"""
    from ns_render import pipeline as P
    from ns_schema.edits import Take
    shot, stage = item["shot"], item.get("stage") or "image"
    if stage not in STAGES:
        raise ValueError(f"stage 只能是 {STAGES}")
    src = Path(item["file"])
    src = src if src.is_absolute() else ROOT / src
    if not src.is_file():
        return {"shot": shot, "stage": stage, "status": "missing", "file": item["file"]}
    sha = _sha(src)
    if sha in registered_shas(shot, stage):
        return {"shot": shot, "stage": stage, "status": "skipped", "reason": "已登记（sha256 相同）"}
    if dry:
        return {"shot": shot, "stage": stage, "status": "would_register"}
    lab = item.get("label") or label
    origin = {**(item.get("origin") or {}), "file": item["file"], "sha256": sha,
              "registered_by": "tools/pipeline/register_takes.py", "registered_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with P.shot_lock(shot):
        n = P._next_n(shot, stage)
        # 总调度 11-01：文件名防撞——带内容哈希前 8 位，takes.json 被改写后 n 重复也不会覆盖别的版本的文件
        rel = f"renders/{P.shot_dir(shot).relative_to(P.RENDERS).as_posix()}/takes/{stage}_{n:03d}_pipeline_{sha[:8]}{src.suffix.lower()}"
        dest = P.DATA / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        size = _size(dest)
        take = Take(n=n, stage=stage, file=rel, seed=int(item.get("seed") or 0), prompt=item.get("prompt") or "",
                    created_at=P.now(), workflow=item.get("workflow") or "series_pipeline", source="pipeline",
                    references=item.get("refs") or None,
                    **({k: item[k] for k in ("frames", "from_first") if item.get(k) is not None} if stage == "video" else {}),
                    params={"tentative": True, "label": lab, "origin": origin,
                            **({"rendered_size": size} if size else {})})
        P._add_take(shot, take, activate=False)        # 候选：不设为当前、不加锁
    pf = item.get("postflight")
    out = {"shot": shot, "stage": stage, "status": "registered", "n": take.n, "label": lab}
    if pf is not None:
        # 总调度 2026-11-01 接口决定：契约通过的首 / 尾帧，把 postflight 结果写进该 take，并设为当前
        # （项目方授权“全部默认同意” = 后台自动采用；VIDEO10 night.py 读 takes.json 的 postflight / active）
        rec = {"ok": bool(pf.get("ok")), "items": pf.get("items") or [], "reasons": pf.get("reasons") or [],
               "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with P.shot_lock(shot):
            data = P.load_takes(shot)
            for t in data["takes"]:
                if t["stage"] == stage and t["n"] == take.n:
                    t["postflight"] = rec
            P._save_takes(shot, data)
        if item.get("activate", True) and stage == "video":
            # DATAALIGN 11-01：视频不归 auto_current（只管首尾帧）——片子门过了、项目方没定稿别的视频 → 设为当前
            with P.shot_lock(shot):
                data = P.load_takes(shot)
                lock = (data.get("locked") or {}).get("video")
                if rec["ok"] and (lock is None or lock == take.n):
                    P.set_active(shot, "video", take.n)
                    out["active"] = True
                else:
                    out["active"] = False
                    out["current"] = {"why": "片子门没过" if not rec["ok"] else f"项目方定稿了视频 v{lock}"}
        elif item.get("activate", True):
            # G3（项目方 11-01）：设为当前只走 ns_render.auto_current.on_contract——过契约且非坏图才设，项目方定稿不挤掉
            from ns_render import auto_current as AC
            r = AC.on_contract(shot, stage, take.n)
            out["active"] = r["action"] in ("activate", "keep") and r["n"] == take.n
            out["current"] = r
    return out


def _primary_run() -> str:
    """K-OPS-W17：主 run 从 config/pipeline/runs.json 读（笔记本侧，缺文件回退 DEFAULT_PRIMARY）"""
    if str(ROOT / "tools/autopilot") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import runs as RUNS
    return RUNS.primary_run()


FRAMES_OK = ROOT / "data/pipeline/runs" / _primary_run() / "video/frames_ok.json"


def mark_episode_done(ep: int, path: Path | None = None) -> list[int]:
    """一集首尾帧全部出完 → frames_ok.json 的 _episodes_done 追加集号（VIDEO10 night.py 读）"""
    p = Path(path or FRAMES_OK)
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    eps = sorted(set(d.get("_episodes_done") or []) | {int(ep)})
    d["_episodes_done"] = eps
    d["_episodes_done_at"] = {**(d.get("_episodes_done_at") or {}), str(int(ep)): time.strftime("%Y-%m-%dT%H:%M:%S")}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return eps


def current_shots() -> set[str]:
    """当前正式剧本（data/import/script_v2.json）里的全部镜头 id；只往这些镜头登记"""
    from ns_render import pipeline as P
    d = json.loads(P.SCRIPT_JSON.read_text(encoding="utf-8"))
    return {f"ep{e['number']:02d}-S{s['index']}" for e in d.get("episodes") or [] for s in e.get("shots") or []}


def run(items: list[dict], *, label: str, dry: bool = False, log=print, known: set[str] | None = None) -> dict:
    out = {"registered": 0, "skipped": 0, "missing": 0, "rows": []}
    for it in items:
        if known is not None and it["shot"] not in known:
            r = {"shot": it["shot"], "stage": it.get("stage") or "image", "status": "missing", "reason": "当前剧本没有这个镜头"}
            out["rows"].append(r); out["missing"] += 1; log(json.dumps(r, ensure_ascii=False))
            continue
        r = register(it, label=label, dry=dry)
        out["rows"].append(r)
        k = {"registered": "registered", "would_register": "registered", "skipped": "skipped"}.get(r["status"], "missing")
        out[k] += 1
        if r["status"] in ("registered", "would_register", "missing"):
            log(json.dumps(r, ensure_ascii=False))
    return out


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="流水线出图登记为画布候选版本（暂定、不设当前、不加锁、可重复执行）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--imggen-state")
    src.add_argument("--manifest")
    src.add_argument("--video10", help="VIDEO10 视频目录（含 state_<host>.json / jobs.json），登记每镜选中的片子")
    ap.add_argument("--label", required=True, help="版本标签，如 旧配方 / 新配方")
    ap.add_argument("--all-attempts", action="store_true", help="IMGGEN：登记全部已出图的尝试（默认只登记 chosen）")
    ap.add_argument("--only", default="", help="只登记这些镜头 / 集前缀，逗号分隔（如 ep01,ep02-S3）")
    ap.add_argument("--follow", type=float, default=0, help="每 N 秒重读一次，新图自动登记（Ctrl+C 停）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    def load():
        items = (items_from_imggen(Path(a.imggen_state), all_attempts=a.all_attempts) if a.imggen_state
                 else items_from_video10(Path(a.video10)) if a.video10
                 else json.loads(Path(a.manifest).read_text(encoding="utf-8")))
        if a.only:
            pre = tuple(x.strip() for x in a.only.split(",") if x.strip())
            items = [i for i in items if i["shot"].startswith(pre)]
        return items

    while True:
        r = run(load(), label=a.label, dry=a.dry_run, known=current_shots())
        if a.video10 and not a.dry_run:
            r["retracted"] = len(retract_stale_video10())
        print(json.dumps({k: r[k] for k in ("registered", "skipped", "missing", "retracted") if k in r}, ensure_ascii=False), flush=True)
        if not a.follow:
            return 0
        time.sleep(a.follow)


if __name__ == "__main__":
    raise SystemExit(main())
