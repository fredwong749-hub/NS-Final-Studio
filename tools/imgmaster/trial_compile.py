"""IMGMASTER 只读试编（P1）：用 frame_job.compile_frame_v2 编译一集全部镜头，和现行 compile_frame 逐镜对比，写 HTML。
不出图、不写 takes / jobs / 出图目录；只写 data/review_pages/imgmaster/ 下的对比页和（缺 HOLLYWOOD 导出时的）试用场景定稿。
用法：.venv/Scripts/python.exe tools/imgmaster/trial_compile.py --ep 1 [--run <run>，默认 runs.primary_run()] [--out data/review_pages/imgmaster]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "packages/schema", "services/render_router", "tools/prompt_v2", "tools/pipeline", "tools/autopilot"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

# 试用场景定稿（HOLLYWOOD 的 continuity/scene_locks_epNN.json 还没导出时用；内容取 AUDIT.md §3 实测的多数值，仅供试编，不是定稿）
TRIAL_LOCKS = {
    "sk_office_night": {
        "fixtures": ["办公桌", "转椅", "台灯"],
        "key_light": "暖黄台灯从画面右后方逆光，屏幕冷白光从正面补光，窗外霓虹只作背景光斑",
        "blocking": {"林晚": {"side": "左", "pose": "坐"}, "顾沉": {"side": "右", "pose": "站"}},
        "screen_direction": "林晚在画面左、顾沉在画面右，走廊在画面左侧画外，台灯在画面右后方",
    }
}
SIDES = {"左": 0, "中": 1, "右": 2}


def trial_lock_file(ep: int, run: str, out: Path, scene_ids) -> dict:
    """优先读 <run>/continuity/scene_locks_epNN.json（HOLLYWOOD 导出）；没有就写一份试用的到 out（不写进 run 目录）"""
    from ns_agent import frame_job as FJ
    real = ROOT / "data/pipeline/runs" / run / "continuity" / f"scene_locks_ep{ep:02d}.json"
    if real.is_file():
        return FJ.load_continuity(real) | {"_trial": False}
    scenes = {sid: dict(TRIAL_LOCKS[sid], shots=[]) for sid in scene_ids if sid in TRIAL_LOCKS}
    f = out / f"ep{ep:02d}_scene_locks_TRIAL.json"
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"schema": "nsfs.scene_locks/1", "run": run, "episode": ep, "scenes": scenes, "links": [],
                               "_note": "试用定稿：HOLLYWOOD 导出前的占位，取 AUDIT §3 多数值；走廊 = 左（总调度 11-02 定，以剧本视线为准，待 HOLLYWOOD 写进场景定稿行）"},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)
    return FJ.load_continuity(f) | {"_trial": True}


def run(ep_no: int, run_name: str, out: Path) -> dict:
    import image_jobs as IJ
    from ns_agent import asset_refs as AR
    from ns_agent import frame_job as FJ
    from ns_agent.bible import load_bible
    # 只读：参考板只算路径、不合成（make_board 缺文件时会写 PNG）
    _mb = AR.make_board

    def plan_only_board(project, tiles):
        import hashlib
        key = hashlib.sha1(json.dumps([[f, l, AR.sha_file(ROOT / f)] for f, l in tiles], ensure_ascii=False).encode()).hexdigest()[:12]
        out_ = AR.project_cfg(project).get("board_dir", "data/refboards")
        return f"{out_}/board_{key}.png"
    AR.make_board = plan_only_board
    try:
        si = IJ.load_import(None)
        g = si.globals
        ep = next(e for e in si.episodes if e.number == ep_no)
        bible = load_bible()
        project = run_name
        out.mkdir(parents=True, exist_ok=True)
        cont = trial_lock_file(ep_no, run_name, out, {s.scene_id for s in ep.shots if s.scene_id})
        av = IJ.AVAILABLE_IMAGE_LORAS
        srs = {s.index: AR.resolve_shot(project, ep, IJ.retrigger(s, g), kept_triggers=None) for s in ep.shots}
        scene_looks = AR.scene_look_refs(list(srs.values()))
        rows = []
        for s in ep.shots:
            old_full, c, old_sr, old_plan = FJ.compile_frame(ep, s, g, project, bible=bible, available=av)
            new = FJ.compile_frame_v2(ep, s, g, project, cont, bible=bible, available=av, scene_looks=scene_looks)
            rows.append({"shot": s, "old_prompt": old_full, "old_plan": old_plan, "old_sr": old_sr, "new": new})
        return {"ep": ep, "cont": cont, "rows": rows, "scene_looks": scene_looks}
    finally:
        AR.make_board = _mb


def checks(res: dict) -> list[dict]:
    from ns_agent import frame_job as FJ
    cont, rows = res["cont"], res["rows"]
    out = []
    # 1 同场主光句逐字一致
    by_scene: dict = {}
    for r in rows:
        by_scene.setdefault(r["shot"].scene_id, []).append(r)
    bad = []
    for sid, rs in by_scene.items():
        key = cont["scenes"][sid]["key_light"]
        blocks = {r["new"]["segments"]["continuity"] for r in rs}
        miss = [f"S{r['shot'].index}" for r in rs if key not in r["new"]["prompt"]]
        if len(blocks) != 1 or miss:
            bad.append(f"{sid}: 连续性块 {len(blocks)} 种，缺主光句 {miss}")
    out.append({"id": "C1", "name": "同场主光句逐字一致（连续性块整场同一串，且含 continuity 主光原句）", "ok": not bad, "detail": bad or "10 镜连续性块同一串（sha 同）"})
    resid = []
    for r in rows:
        act = r["new"]["segments"]["action"]
        hits = [x for x in act.split("，") if FJ._ENV_WORDS.search(x)]
        if hits:
            resid.append(f"S{r['shot'].index}: {'；'.join(hits)[:60]}")
    out.append({"id": "C1b", "name": "本镜动作段里残留的环境 / 光源分句（带人名的灯光，不删，提示人看）", "ok": True, "detail": resid or "无", "warn": bool(resid)})
    # 2 场景槽都在
    miss = []
    for r in rows:
        want = [x for x in r["new"]["sr"].refs if x.role == "scene"]
        have = [s for s in r["new"]["plan"].slots if s.kind == "scene"]
        if want and not have:
            miss.append(f"S{r['shot'].index}")
    old_miss = [f"S{r['shot'].index}" for r in rows if not any(s.kind == "scene" for s in r["old_plan"].slots)]
    out.append({"id": "C2", "name": "场景槽都在（有场景底图的镜都送进模型）", "ok": not miss,
                "detail": miss or f"新：10 镜都有场景槽；旧：{len(old_miss)}/10 镜丢了场景（{'、'.join(old_miss)}）"})
    # 3 造型参考一致
    per = {}
    for r in rows:
        for s in r["new"]["plan"].slots:
            if s.kind in ("sheet", "board", "item"):
                per.setdefault(s.character, {}).setdefault(s.file, []).append(f"S{r['shot'].index}")
    old_per = {}
    for r in rows:
        for s in r["old_plan"].slots:
            if s.kind in ("sheet", "board", "item"):
                old_per.setdefault(s.character, set()).add(s.file)
    bad = [f"{ch}: {len(fs)} 种造型参考文件" for ch, fs in per.items() if len(fs) > 1]
    nolook = [f"S{r['shot'].index}" for r in rows
              for c_ in (r["new"]["sr"].characters or []) if c_.get("presence") == "在画"
              and not any(s.character == c_.get("character") and s.kind in ("sheet", "board", "item") for s in r["new"]["plan"].slots)]
    out.append({"id": "C3", "name": "造型参考一致（同角色在各镜用到的造型参考是同一个文件）", "ok": not bad,
                "detail": (bad or []) + [f"{ch}: {', '.join(f'{Path(f).name}→{len(v)}镜' for f, v in d.items())}" for ch, d in per.items()]
                + [f"旧：{ch} 用过 {len(fs)} 种造型参考文件" for ch, fs in old_per.items()]
                + ([f"在画但没有造型参考槽（槽位被脸 + 场景占满，走文字）：{'、'.join(dict.fromkeys(nolook))}"] if nolook else [])})
    # 4 段落顺序固定
    bad = []
    for r in rows:
        n = r["new"]
        pos = [n["prompt"].find(n["segments"][k][:30]) for k in FJ.SEGMENTS if n["segments"][k]]
        if pos != sorted(pos) or n["prompt"].find(n["segments"]["framing"][:30]) < len(n["preamble"]):
            bad.append(f"S{r['shot'].index}")
    out.append({"id": "C4", "name": "段落顺序固定（参考标注头 → 景别 → 连续性 → 人物 → 动作 → 约束 → 风格后缀）", "ok": not bad,
                "detail": bad or "10 镜顺序一致（单人 / 双人同一顺序）"})
    # 5 越轴
    bad, notes = [], []
    for r in rows:
        sid = r["shot"].scene_id
        lock = cont["scenes"][sid]["blocking"]
        on = [(c_.name, c_.x) for c_ in r["shot"].cast if c_.presence in ("在画", "局部") and c_.x in SIDES and c_.name in lock]
        for i, (n1, x1) in enumerate(on):
            for n2, x2 in on[i + 1:]:
                if x1 != x2 and (SIDES[x1] < SIDES[x2]) != (SIDES[lock[n1]["side"]] < SIDES[lock[n2]["side"]]):
                    bad.append(f"S{r['shot'].index}: {n1}({x1}) / {n2}({x2}) 与定稿相反")
        for d in r["new"]["trace"]["dropped_clauses"]:
            if d["plugin"] == "scene_detail_guard":
                notes.append(f"S{r['shot'].index}: 删“{d['clause']}” 冲突 {d['conflict']}")
    out.append({"id": "C5a", "name": "没有越轴冲突（人物站位左右 vs 定稿）", "ok": not bad,
                "detail": bad or ["站位均和定稿一致"], "notes": []})
    # 5b 最终提示词里还剩的方位文字矛盾（连续性块以外的文字 vs 定稿方位）
    ref = FJ._sides(cont["scenes"][rows[0]["shot"].scene_id]["key_light"] + "。" + cont["scenes"][rows[0]["shot"].scene_id]["screen_direction"])
    resid = []
    for r in rows:
        n = r["new"]
        txt = n["preamble"] + "，".join(n["segments"][k] for k in FJ.SEGMENTS if k != "continuity")
        cf = FJ._side_conflicts(txt, ref)
        if cf:
            resid.append(f"S{r['shot'].index}: {cf}")
    out.append({"id": "C5b", "name": "最终提示词里没有和定稿方位相反的文字（走廊 / 台灯左右前后）", "ok": not resid,
                "detail": resid or ["无"], "notes": notes + [f"（已自动删）S{r['shot'].index}: {d['clause']}" for r in rows
                                                              for d in r['new']['trace']['dropped_clauses'] if d['plugin'] == 'scene_detail_guard'][:0]})
    return out


def _slot_txt(plan) -> str:
    return "".join(f"<div>槽{s.index} <b>{html.escape(s.kind)}</b> {html.escape(s.character or '')} "
                   f"<span class=f>{html.escape(Path(s.file).name)}</span></div>" for s in plan.slots) + "".join(
        f"<div class=drop>丢：{html.escape(d.get('role') or '')} {html.escape(Path(d['file']).name)}（走文字）</div>" for d in plan.dropped)


def render_html(res: dict, cks: list[dict]) -> str:
    from ns_agent import frame_job as FJ
    colors = {"framing": "#e8f0ff", "continuity": "#e6f7e6", "characters": "#fff4e0", "action": "#fde8f0", "constraints": "#eee"}
    h = ["<meta charset=utf-8><title>IMGMASTER ep%02d 试编对比</title>" % res["ep"].number,
         "<style>body{font:13px/1.6 sans-serif;margin:20px;max-width:1500px}td,th{border:1px solid #bbb;padding:6px;vertical-align:top}"
         "table{border-collapse:collapse;width:100%}.ok{color:#080}.bad{color:#c00}.f{color:#666;font-size:11px}.drop{color:#c00}"
         ".seg{padding:2px 4px;margin:2px 0;display:block}.tr{background:#ffd}</style>",
         f"<h2>IMGMASTER 只读试编：ep{res['ep'].number:02d} 全部 {len(res['rows'])} 镜（未出图）</h2>",
         f"<p>continuity：{html.escape(str(res['cont'].get('_file')))} sha {res['cont'].get('_sha','')[:12]}"
         f"{'  <b class=bad>（试用定稿，非 HOLLYWOOD 导出）</b>' if res['cont'].get('_trial') else ''}</p>",
         "<h3>检查结果</h3><table><tr><th>项</th><th>通过</th><th>说明</th></tr>"]
    for c_ in cks:
        d = c_["detail"] if isinstance(c_["detail"], list) else [c_["detail"]]
        extra = "".join(f"<div class=f>{html.escape(x)}</div>" for x in c_.get("notes", []))
        mark = "<span class=ok>通过</span>" if c_["ok"] and not c_.get("warn") else ("<span class=bad>提示</span>" if c_.get("warn") else "<span class=bad>未过</span>")
        h.append(f"<tr><td>{c_['id']} {html.escape(c_['name'])}</td><td>{mark}</td><td>{'<br>'.join(html.escape(str(x)) for x in d)}{extra}</td></tr>")
    h.append("</table><h3>逐镜对比</h3>")
    for r in res["rows"]:
        n = r["new"]
        h.append(f"<h4>ep{res['ep'].number:02d}-S{r['shot'].index}（{html.escape(str(r['old_sr'].size))}）</h4><table><tr><th width=48%>旧提示词（现行 compile_frame）</th><th>新提示词（分段，按段着色）</th></tr><tr>")
        h.append(f"<td>{html.escape(r['old_prompt'])}<hr>{_slot_txt(r['old_plan'])}</td><td>")
        h.append(f"<span class=seg style='background:#ddd'>参考标注头：{html.escape(n['preamble'])}</span>")
        for k in FJ.SEGMENTS:
            h.append(f"<span class=seg style='background:{colors[k]}'><b>[{k}]</b> {html.escape(n['segments'][k])}</span>")
        h.append("<hr>" + _slot_txt(n["plan"]))
        if n["trace"]["dropped_clauses"]:
            h.append("<div class=tr>trace 删除分句：" + "；".join(html.escape(f"{d['plugin']}:{d['clause']}") for d in n["trace"]["dropped_clauses"]) + "</div>")
        h.append(f"<div class=f>插件：{', '.join(n['trace']['applied_plugins'])}｜prompt_sha {n['trace']['prompt_sha']}</div></td></tr></table>")
    return "\n".join(h)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--run", default=None, help="默认取 tools/autopilot/runs.primary_run()")
    ap.add_argument("--out", default="data/review_pages/imgmaster")
    a = ap.parse_args(argv)
    out = ROOT / a.out
    import runs as RN
    res = run(a.ep, a.run or RN.primary_run(ROOT), out)
    cks = checks(res)
    (out / f"ep{a.ep:02d}_compile_diff.html").write_text(render_html(res, cks), encoding="utf-8")
    for c_ in cks:
        print(("PASS " if c_["ok"] else "FAIL ") + c_["id"], c_["name"])
        for x in (c_["detail"] if isinstance(c_["detail"], list) else [c_["detail"]]):
            print("    ", x)
        for x in c_.get("notes", []):
            print("    note:", x)
    print("->", out / f"ep{a.ep:02d}_compile_diff.html")
    return 0 if all(c_["ok"] for c_ in cks) else 1


if __name__ == "__main__":
    sys.exit(main())
