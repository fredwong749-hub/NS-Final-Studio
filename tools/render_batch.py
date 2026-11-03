"""
批量渲染（可断点续跑），与画布共用 ns_render.pipeline 的版本管理。

    uv run python tools/render_batch.py --stage image                  # 全部镜头出首帧（含成人）
    uv run python tools/render_batch.py --stage video --shots ep01     # ep01 出视频
    uv run python tools/render_batch.py --stage image                  # 含成人镜头（过滤器已取消）
    uv run python tools/render_batch.py --report                       # 只重写报告
    uv run python tools/render_batch.py --stage image --face-lock on   # 含角色锁的镜头用参考图锁脸
    uv run python tools/render_batch.py --qc                           # 给已有首帧补做裸露质检（只记录）
    uv run python tools/render_batch.py --stage last --shots ep01 ep02 # 独立尾帧（以当前首帧为图1编辑出结束状态）
    uv run python tools/render_batch.py --stage image --candidates 3 --rounds 3   # C5 多候选多轮（默认值见 pipeline）
    uv run python tools/render_batch.py --stage image --method spec    # 画面说明层提示词（试点）

首帧/尾帧：每轮多张候选 → 调色（色调参考图）→ 裸露质检 → 自动评分，最高分设为当前；不达标再来一轮，仍不达标在报告里标“待审”。
⚠ 不要在出图/质检进程运行时跑 --stage video（本机 32GB 内存，H3 与 Qwen/质检模型同时加载会 OOM）。

首帧每次出图后自动做裸露质检（NudeNet + CLIP），只写进 Take.qc；2026-10-30 起不再否决或撤下。
跑 --stage image 前也会先给已有首帧补做质检。

已有当前版本的镜头会跳过；--force 再出一个新版本。失败只做技术层面的重试（换种子、缩短帧数），不改写提示词。
"""
import argparse
import json
import sys
import time

from ns_agent.compiler import compile_shot
from ns_render import pipeline as P
from ns_render import render_paths as RP   # W33
from ns_render.comfy_client import ComfyClient, ComfyUnavailable


def migrate_legacy(shot_id: str):
    """早期批量脚本只写了 frame.png + status.json，补成 take 1"""
    d = P.shot_dir(shot_id)
    st = json.loads((d / "status.json").read_text(encoding="utf-8")) if (d / "status.json").exists() else {}
    im = st.get("image", {})
    if not (d / "frame.png").exists() and im and not im.get("ok", True) and not (d / "errors.json").exists():
        # 旧脚本把失败写在 status.json 里，转成报告能读到的 errors.json
        P._write_json(d / "errors.json", {"last": str(im.get("error") or im), "at": P.now()})
    if not (d / "frame.png").exists() or (d / "takes.json").exists():
        return
    comp = json.loads((d / "compiled.json").read_text(encoding="utf-8")) if (d / "compiled.json").exists() else {}
    rel = f"{RP.take_rel_dir(d, P.DATA, P.RENDERS)}/image_001.png"   # W33
    (P.DATA / rel).parent.mkdir(parents=True, exist_ok=True)
    (P.DATA / rel).write_bytes((d / "frame.png").read_bytes())
    take = P.Take(n=1, stage="image", file=rel, seed=im.get("seed", 0), prompt=comp.get("image_prompt", ""),
                  negative=comp.get("image_negative", ""), seconds=im.get("seconds"), created_at=P.now(),
                  workflow="qwen_t2i")
    P._add_take(shot_id, take)


def _master_time() -> str:
    m = P.ROOT / "assets" / "characters" / "lin_wan" / "plates" / "master.png"
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(m.stat().st_mtime)) if m.exists() else "9999"


MASTER_APPROVED_AT = _master_time()


def write_report(script):
    first_master: dict = {}
    rows, n = [], {"shots": 0, "adult": 0, "image": 0, "last": 0, "video": 0, "qc_rejected": 0, "qc_shots": 0,
                   "review": 0}
    secs = {"image": [], "last": [], "video": []}
    for ep in script.episodes:
        for s in ep.shots:
            c = compile_shot(ep, s, script.globals, set())
            data = P.load_takes(s.id)
            active = data.get("active", {})
            n["shots"] += 1
            n["adult"] += c.adult
            cells = []
            for stage in ("image", "last", "video"):
                t = next((t for t in data["takes"] if t["stage"] == stage and t["n"] == active.get(stage)), None)
                if t:
                    n[stage] += 1
                    if t.get("seconds"):
                        secs[stage].append(t["seconds"])
                cell = "—"
                if t:
                    cell = f"✅ v{t['n']}"
                    if (t.get("workflow") or "").startswith("qwen_edit") and stage == "image":
                        cell += " 底板" if "plate" in t["workflow"] else " 锁脸"
                    refs_used = " ".join(t.get("references") or []) + " " + (t.get("reference") or "")
                    if "plates/master.png" in refs_used or "refs/master_face_" in refs_used:
                        # 同一路径先后是两张图：v1（项目方未通过）与通过版；按版本创建时间对比现母版文件时间区分
                        if t.get("created_at", "") < MASTER_APPROVED_AT:
                            cell += " 母版v1(未通过)"
                            n["master_v1"] = n.get("master_v1", 0) + 1
                        else:
                            cell += " 母版"
                            n["master"] = n.get("master", 0) + 1
                            first_master.setdefault("shot", s.id)
                    if (t.get("score") or {}).get("total") is not None:
                        cell += f" {t['score']['total']:.2f}"
                    if stage in data.get("review", {}):
                        cell += " ⚠待审"
                        n["review"] += 1
                cells.append(cell)
            err = P._read_json(P.shot_dir(s.id) / "errors.json", {})
            if P.gpu3_owns(s.id):
                cells[0] += " · gpu3负责"
                n["gpu3"] = n.get("gpu3", 0) + 1
            bad = [t for t in data["takes"] if (t.get("qc") or {}).get("nudity")]
            n["qc_rejected"] += len(bad)
            n["qc_shots"] += bool(bad)
            act = next((t for t in data["takes"] if t["stage"] == "image" and t["n"] == active.get("image")), None)
            qc_cell = "未检" if act and not act.get("qc") else "通过" if act else "无首帧"
            if bad:
                qc_cell += f"；拦截 {', '.join('v' + str(t['n']) for t in bad)}"
            rows.append(f"| {s.id} | {'成人' if c.adult else '普通'} | {cells[0]} | {cells[1]} | {cells[2]} | {qc_cell} | "
                        f"{', '.join(c.dropped_triggers)} | {err.get('last', '')[:80]} |")
    avg = lambda xs: f"{sum(xs) / len(xs):.0f} 秒" if xs else "—"
    text = [
        "# 渲染报告", "",
        f"> 成人镜头 {n['adult']} 个；2026-10-30 起不再单独拦截，与普通镜头一起出图。", "",
        f"更新时间：{time.strftime('%Y-%m-%d %H:%M')}", "",
        f"- 镜头 {n['shots']}（成人 {n['adult']}）",
        f"- 首帧 {n['image']}，平均 {avg(secs['image'])}",
        f"- 独立尾帧 {n['last']}，平均 {avg(secs['last'])}（单张）",
        f"- 视频 {n['video']}，平均 {avg(secs['video'])}",
        f"- gpu3 负责整条链（首帧+尾帧+视频）的镜头：{n.get('gpu3', 0)}（表中标“gpu3负责”；本机批量跳过的明细见 gpu3_skipped.json）",
        f"- 多候选评分低于 {P.SCORE_PASS} 的待审项：{n['review']}（takes.json 的 review）",
        f"- 用了写实母版 v1（项目方未通过）作身份参考的当前版本：{n.get('master_v1', 0)}（表中标“母版v1(未通过)”，可按镜重出）",
        f"- 用项目方通过的母版 plates/master.png（{MASTER_APPROVED_AT} 起）的当前版本：{n.get('master', 0)}"
        + (f"，按镜头顺序第一个是 {first_master['shot']}" if first_master else ""),
        f"- 裸露质检（全部首帧，只记录）：标记 {n['qc_rejected']} 个版本，涉及 {n['qc_shots']} 个镜头；"
        "标记只写 Take.qc，不撤版（明细见 qc_log.jsonl）", "",
        "| 镜头 | 分类 | 首帧 | 尾帧 | 视频 | 裸露质检 | 未加载的触发词（LoRA 未就绪） | 最近错误 |",
        "|---|---|---|---|---|---|---|---|", *rows,
    ]
    (P.RENDERS / "REPORT.md").write_text("\n".join(text), encoding="utf-8")


def write_sheets(script, out_dir: str, episodes: list[str]):
    """每集一张对比表：每镜一列，上 = 当前首帧，下 = 当前尾帧；标注分数与待审"""
    from PIL import Image, ImageDraw, ImageFont
    out = P.ROOT / out_dir
    out.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16)
    except OSError:
        font = ImageFont.load_default()
    W_, H_ = 270, 480
    for ep in script.episodes:
        tag = f"ep{ep.number:02d}"
        if episodes and tag not in episodes:
            continue
        cols = []
        for s in ep.shots:
            data = P.load_takes(s.id)
            col = []
            for stage, name in (("image", "frame.png"), ("last", "last.png")):
                t = next((t for t in data["takes"] if t["stage"] == stage and t["n"] == data["active"].get(stage)),
                         None)
                f = P.shot_dir(s.id) / name
                if stage == "last" and not t:
                    f = None
                im = Image.open(f).convert("RGB").resize((W_, H_)) if f and f.exists() else Image.new("RGB", (W_, H_))
                d = ImageDraw.Draw(im)
                sc = (t or {}).get("score") or {}
                label = f"{s.id} {'首帧' if stage == 'image' else '尾帧'} v{(t or {}).get('n', '-')}"
                if sc.get("total") is not None:
                    label += f" {sc['total']:.2f}"
                if stage in data.get("review", {}):
                    label += " 待审"
                d.rectangle((0, 0, W_, 24), fill=(0, 0, 0))
                d.text((4, 2), label, fill=(255, 230, 140), font=font)
                col.append(im)
            cols.append(col)
        sheet = Image.new("RGB", (W_ * len(cols), H_ * 2), (10, 10, 10))
        for i, col in enumerate(cols):
            for j, im in enumerate(col):
                sheet.paste(im, (i * W_, j * H_))
        sheet.save(out / f"{tag}.jpg", quality=85)
    print(f"对比表 -> {out}")


def run_qc_sweep(script, shots: list[str], client=None, recheck: bool = False):
    for ep in script.episodes:
        for s in ep.shots:
            if shots and not any(s.id == f or s.id.startswith(f + "-") for f in shots):
                continue
            before = P.load_takes(s.id)["active"].get("image")
            flagged = P.qc_sweep(s.id, adult=bool(compile_shot(ep, s, script.globals, set()).adult),
                                 qc_fn=P.qc_with_vlm(client) if client else None,
                                 recheck=recheck, only_active=recheck)
            after = P.load_takes(s.id)["active"].get("image")
            if before != after:
                print(f"质检：{s.id} 当前首帧 v{before} 未通过 -> {'v' + str(after) if after else '已撤下，待重出'}",
                      flush=True)
            elif flagged:
                print(f"质检：{s.id} 历史版本 {[t['n'] for t in flagged]} 未通过（不是当前版本）", flush=True)


def _missing_after_sweep(script, args) -> list[str]:
    """质检撤下当前首帧的镜头（之前因为已有版本被跳过）也要重出"""
    out = []
    for ep in script.episodes:
        for s in ep.shots:
            if args.shots and not any(s.id == f or s.id.startswith(f + "-") for f in args.shots):
                continue
            if not P.load_takes(s.id)["active"].get("image"):
                out.append(s.id)
    return out[:args.limit] if args.limit else out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["image", "refine", "last", "video"])
    ap.add_argument("--shots", nargs="*", default=[], help="ep01 或 ep01-S1，可多个；默认全部")
    ap.add_argument("--include-adult", action="store_true")
    ap.add_argument("--force", action="store_true", help="已有版本也再出一个新版本")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--qc", action="store_true", help="给已有首帧补做裸露质检（只记录）")
    ap.add_argument("--sheets", default="", help="每集对比表输出目录（如 golden/rerun_v2），本批结束后生成")
    ap.add_argument("--comfy", default="http://127.0.0.1:8188")
    ap.add_argument("--frames", type=int, default=0, help="视频帧数（0 = 按剧本时长 duration*24+1）")
    ap.add_argument("--limit", type=int, default=0, help="本次最多渲染几个镜头")
    ap.add_argument("--candidates", type=int, default=0, help="每轮候选张数（0 = pipeline.CANDIDATES）")
    ap.add_argument("--rounds", type=int, default=0, help="最多轮数（0 = pipeline.ROUNDS）")
    ap.add_argument("--ref-mode", choices=["plate", "portrait"], default=None, help="参考图：身份底板（默认）/旧定妆图")
    ap.add_argument("--method", choices=["script", "spec"], default=None, help="提示词：剧本透传（默认）/画面说明层")
    ap.add_argument("--face-lock", choices=["auto", "on", "off"], default="auto",
                    help="首帧锁脸（单参考编辑）：auto 按 pipeline.FACE_LOCK_DEFAULT")
    args = ap.parse_args()
    frames = P.snap_frames(args.frames) if args.frames else None
    if frames and frames != args.frames:
        print(f"帧数 {args.frames} 不在 17k+5 网格上，按 {frames} 帧渲染", flush=True)

    gate = P.project_gate_message()
    if gate and args.stage:   # 一镜一条链：项目由 gpu3 负责时本机不出首尾帧/视频（报告与质检照常）
        print(f"{gate}：本机不渲染（--stage {args.stage} 已取消）", flush=True)
        return 3
    script = P.load_script()
    for ep in script.episodes:
        for s in ep.shots:
            migrate_legacy(s.id)
    if args.qc:   # --qc：用 v3 质检（含本地看图模型）复检当前首帧/尾帧，不合格的撤下
        run_qc_sweep(script, args.shots, ComfyClient(args.comfy), recheck=True)
    if args.report or not args.stage:
        write_report(script)
        if args.sheets:
            write_sheets(script, args.sheets, [])
        print(f"报告 -> {P.RENDERS / 'REPORT.md'}")
        return 0

    todo = []
    for ep in script.episodes:
        for s in ep.shots:
            if args.shots and not any(s.id == f or s.id.startswith(f + "-") for f in args.shots):
                continue
            if args.stage == "refine":
                if not (P.shot_dir(s.id) / "frame.png").exists():
                    continue
                act = P.load_takes(s.id)
                cur = next((t for t in act["takes"] if t["stage"] == "image"
                            and t["n"] == act["active"].get("image")), {})
                if (cur.get("workflow") or "").startswith("qwen_refine") and not args.force:
                    continue
                todo.append(s.id)
                continue
            if P.load_takes(s.id)["active"].get(args.stage) and not args.force:
                continue
            if args.stage == "last" and not (P.shot_dir(s.id) / "frame.png").exists():
                continue
            todo.append(s.id)
    if args.limit:
        todo = todo[:args.limit]

    client = ComfyClient(args.comfy)
    try:
        client.system_stats()
    except ComfyUnavailable as e:
        print(f"ComfyUI 不可用（{e}），本次不渲染", flush=True)
        write_report(script)
        return 2
    if args.stage == "image":
        run_qc_sweep(script, args.shots)  # 给已有首帧补做质检（只记录）
        todo += [sid for sid in _missing_after_sweep(script, args) if sid not in todo]
    done = 0
    script_mtime = P.SCRIPT_JSON.stat().st_mtime
    for i, shot_id in enumerate(todo, 1):
        if P.SCRIPT_JSON.stat().st_mtime != script_mtime:   # 剧本重新导入了：后面的镜头用新剧本
            script_mtime = P.SCRIPT_JSON.stat().st_mtime
            script = P.load_script()
            print(f"[{time.strftime('%H:%M:%S')}] 剧本已重新导入，从 {shot_id} 起使用新剧本", flush=True)
        print(f"[{time.strftime('%H:%M:%S')}] ({i}/{len(todo)}) {shot_id} {args.stage}", flush=True)
        t0 = time.time()
        try:
            multi = {"candidates": args.candidates or None, "rounds": args.rounds or None, "method": args.method}
            if args.stage == "image":
                lock = {"auto": None, "on": True, "off": False}[args.face_lock]
                t = P.render_image(client, script, shot_id, face_lock=lock, ref_mode=args.ref_mode, **multi)
            elif args.stage == "refine":
                t = P.refine_image(client, script, shot_id)
            elif args.stage == "last":
                t = P.render_last_frame(client, script, shot_id, **multi)
            else:
                t = P.render_video(client, script, shot_id, frames=frames)
            sc = (t.score or {}).get("total")
            review = P.load_takes(shot_id).get("review", {}).get(args.stage)
            print(f"    完成 v{t.n} {t.seconds}s {t.workflow or ''} 分数 {sc} 用时 {time.time() - t0:.0f}s"
                  + (f" ⚠ 待审：{review['reason']}" if review else ""), flush=True)
        except P.Gpu3Owned as e:   # gpu3 认领了：跳过，不记错误
            print(f"    跳过（gpu3 负责）: {e}", flush=True)
            skipped = P._read_json(P.RENDERS / "gpu3_skipped.json", {})
            skipped[shot_id] = {"at": P.now(), "stage": args.stage, "why": str(e)}
            P._write_json(P.RENDERS / "gpu3_skipped.json", skipped)
            continue
        except ComfyUnavailable as e:  # 服务器没了：不给镜头记错误，整批停下
            print(f"    ComfyUI 不可用，停止本批（{shot_id} 未完成，可直接重跑续上）: {e}", flush=True)
            write_report(script)
            return 2
        except Exception as e:  # 单镜失败不中断整批（含文件错误）
            P._write_json(P.shot_dir(shot_id) / "errors.json", {"last": f"{type(e).__name__}: {e}", "at": P.now()})
            print(f"    失败: {type(e).__name__}: {str(e)[:200]}", flush=True)
        done += 1
        if done % 5 == 0:
            write_report(script)
    write_report(script)
    if args.sheets:
        write_sheets(script, args.sheets, sorted({sid.split("-")[0] for sid in todo}))
    print(f"本次渲染 {done} 个，报告 -> {P.RENDERS / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
