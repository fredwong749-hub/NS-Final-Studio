"""HOLLYWOOD r7（总调度 fredw-2b 派，11-02，0 花费）：用 rubric_code 对现行 10 集逐集、逐镜跑代码判定，并做导入闸门。

两种口径：
  script   : 剧本原文（img 行）——写作方写了什么
  compiled : img 换成编译后的首帧提示词（tools/pipeline/image_jobs.frame_prompt，与 rebuild_first_frame_jobs 同一入口），
             即编译层已经自动补的技术契约句（角色锁、视线句、外层单品登记描述等）算进去之后还剩什么
失败项分两类：TECH（技术缺口：人物卡原文 / 景别 / 视线 / 站位·光线·运镜·分拍缺行）与 WRITING（写法：回头、穿脱过程、情绪直陈……）。

    .venv/Scripts/python.exe tools/script_rsi/rubric_audit.py audit                         # 10 集 → data/review_pages/hollywood_r5/code_gaps/
    .venv/Scripts/python.exe tools/script_rsi/rubric_audit.py gate <剧本.md> [--episodes 1-10]   # 导入闸门：代码判定失败项 = 0 才放行（退出码 0 / 1）
"""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import runs as RUNS  # noqa: E402
_LEGACY = RUNS.legacy_run(ROOT)   # I-16：第一季专用历史工具（入口 gate_legacy_tool 要求显式 --run）
for _p in (ROOT / "tools" / "pipeline", ROOT / "packages" / "schema", ROOT / "services" / "agent", ROOT / "services" / "api",
           ROOT / "services" / "recipes"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


H = _load("hollywood", "tools/script_rsi/hollywood.py")
RC6 = _load("rubric_code", "tools/script_rsi/rubric_code.py")
RL = H.RL
OUT = ROOT / "data" / "review_pages" / "hollywood_r5" / "code_gaps"

TECH = {("consistency", 1), ("consistency", 2), ("consistency", 3), ("specificity", 1), ("specificity", 2), ("pika", 3),
        ("hook5s", 1), ("endhook", 3), ("show", 1), ("subtext", 5)}
OWNER_HINT = {("consistency", 1): "IMGFIX（人物卡原文：发型）", ("consistency", 2): "IMGFIX（人物卡原文：服装）",
              ("consistency", 3): "IMGFIX（人物卡原文：饰品）", ("specificity", 1): "REFLOCK / IMGFIX（景别句、视线句）",
              ("specificity", 2): "DIRECTOR（分拍字段）", ("pika", 3): "DIRECTOR（景别 / 运镜字段）", ("hook5s", 1): "DIRECTOR（分拍字段）",
              ("endhook", 3): "DIRECTOR（分拍字段）", ("show", 1): "DIRECTOR（分拍视线）", ("subtext", 5): "DIRECTOR（分拍视线）"}


def episode_eval(pre: str, chunk: str, ep: int, wd: Path, compiled: bool, si=None) -> dict:
    obj = H.episode_obj(pre, chunk, ep, wd)
    shots = sorted(obj.shots, key=lambda s: s.index)
    blocks = [RL.block_text(chunk, k) for k in range(len(shots))]
    codes = H.lint(chunk, ep)["codes"]
    imgs = None
    if compiled:
        import image_jobs as IJ
        si = si or IJ.load_import()
        pe = next((e for e in si.episodes if e.number == ep), None)
        if pe is not None and [s.index for s in pe.shots] == [s.index for s in shots]:
            imgs = [IJ.frame_prompt(pe, s, si.globals, [], _LEGACY)[0] for s in sorted(pe.shots, key=lambda s: s.index)]
    cc = RC6.code_checks(chunk, shots, blocks, RL.block_text(chunk, "head"), codes, imgs=imgs)
    if RC6.uses_v2(blocks):        # 第二季起的镜头块 v2 + 【灯光】（K-WRT-805 / 806）
        cc["v2"] = RC6.v2_checks(shots, blocks, pre + RL.block_text(chunk, "head"))
    fails = [{"item": f"{d}#{i}", "kind": "TECH" if (d, i) in TECH else "WRITING", "detail": why,
              "shots": sorted({int(x) for x in re.findall(r"镜(\d+)", why)} | {int(x) for x in re.findall(r"\[([\d, ]+)\]", why) for x in [x] if False}),
              "owner": OWNER_HINT.get((d, i), "写作规则 + lint（HOLLYWOOD）")}
             for d in list(RC6.DIMS) + (["v2"] if "v2" in cc else []) for i, (ok, why) in cc[d].items() if not ok]
    for f in fails:     # 详情里“[1, 4]”形式的镜号也收进来
        for grp in re.findall(r"\[([\d, ]+)\]", f["detail"]):
            f["shots"] = sorted(set(f["shots"]) | {int(x) for x in grp.split(",") if x.strip().isdigit()})
    met = sum(ok for d in list(RC6.DIMS) + (["v2"] if "v2" in cc else []) for ok, _ in cc[d].values())
    return {"met": met, "total": sum(len(v) for v in cc.values()), "fails": fails, "compiled_used": imgs is not None, "shots": len(shots)}


def cmd_audit(a) -> int:
    import image_jobs as IJ
    OUT.mkdir(parents=True, exist_ok=True)
    wd = OUT / "_work"
    wd.mkdir(exist_ok=True)
    srcs = H.RC.episode_sources()
    si = IJ.load_import()
    summary = {"at": time.strftime("%F %T"), "share": RC6.share(), "eps": {}}
    for ep in range(1, 11):
        text, rec = H.RC.assemble(RL, [ep], srcs)
        pre, ch = RL.split_doc(text)
        s = episode_eval(pre, ch[0], ep, wd, False)
        c = episode_eval(pre, ch[0], ep, wd, True, si)
        per_shot: dict = {}
        for f in s["fails"]:
            for k in f["shots"] or [0]:
                per_shot.setdefault(k, []).append(f["item"])
        rep = {"episode": ep, "source": rec[0], "script": s, "compiled": c, "per_shot_script": {str(k): v for k, v in sorted(per_shot.items())},
               "filled_by_compiler": sorted({f["item"] for f in s["fails"]} - {f["item"] for f in c["fails"]})}
        (OUT / f"ep{ep:02d}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        summary["eps"][ep] = {"script_met": s["met"], "compiled_met": c["met"], "total": s["total"], "compiled_used": c["compiled_used"],
                              "tech_script": sum(f["kind"] == "TECH" for f in s["fails"]), "tech_compiled": sum(f["kind"] == "TECH" for f in c["fails"]),
                              "writing": sorted({f["item"] for f in s["fails"] if f["kind"] == "WRITING"}),
                              "filled_by_compiler": rep["filled_by_compiler"]}
        print(f"ep{ep:02d} 代码判定 {s['met']}/{s['total']} → 编译后 {c['met']}/{c['total']}；技术缺口 {summary['eps'][ep]['tech_script']} → "
              f"{summary['eps'][ep]['tech_compiled']}；写法 {summary['eps'][ep]['writing']}", flush=True)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    write_page(summary)
    return 0


def write_page(summary: dict):
    E = html.escape
    rows = []
    for ep, v in summary["eps"].items():
        d = json.loads((OUT / f"ep{int(ep):02d}.json").read_text(encoding="utf-8"))
        det = "".join(f"<div>[{E(f['kind'])}] {E(f['item'])} 镜{E(str(f['shots']))}：{E(f['detail'][:200])}｜{E(f['owner'])}</div>" for f in d["compiled"]["fails"])
        rows.append(f"<tr><td>ep{int(ep):02d}</td><td>{v['script_met']}/{v['total']}</td><td>{v['compiled_met']}/{v['total']}</td>"
                    f"<td>{v['tech_script']} → {v['tech_compiled']}</td><td>{E('、'.join(v['writing']))}</td>"
                    f"<td><details><summary>编译后仍失败 {len(d['compiled']['fails'])} 条</summary>{det}</details></td></tr>")
    page = ("<!doctype html><meta charset=utf-8><title>HOLLYWOOD r7 代码判定缺口</title><style>body{font-family:system-ui,'Microsoft YaHei';margin:24px}"
            "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px;font-size:13px;vertical-align:top}</style>"
            f"<h1>现行 10 集 · 清单代码判定（rubric_code，{E(summary['at'])}）</h1>"
            f"<p>代码判定条目 = 整条代码 {summary['share']['code']} + 混合的代码部分 {summary['share']['mixed']}，共 27 条 / 50。"
            "“编译后” = img 换成编译后的首帧提示词（编译层已补的角色锁、视线句、外层单品描述算进去）。</p>"
            "<table><tr><th>集</th><th>剧本原文</th><th>编译后</th><th>技术缺口（剧本 → 编译后）</th><th>写法问题</th><th>编译后仍失败</th></tr>"
            + "".join(rows) + "</table>")
    (OUT / "index.html").write_text(page, encoding="utf-8")


def gate(path: Path, eps: list[int] | None = None) -> dict:
    """导入闸门（总调度 r7 第 3 条）：剧本稿每集代码判定失败项 = 0 才放行。只读"""
    from ns_agent.importer.script_md import import_script
    text = Path(path).read_text(encoding="utf-8")
    pre, chunks = RL.split_doc(text)
    wd = OUT / "_work_gate"
    wd.mkdir(parents=True, exist_ok=True)
    res = {"ok": True, "eps": {}}
    for ch in chunks:
        m = RL.EP_RE.match(RL._norm(ch.split("\n", 1)[0]))
        ep = int(m.group(1))
        if eps and ep not in eps:
            continue
        r = episode_eval(pre, ch, ep, wd, False)
        fails = [f"{f['item']} {f['detail'][:120]}" for f in r["fails"]]
        # K-WRT-H13（总调度 11-02）：编译后 0 孤儿描述、特写 0 双人露脸——和 RSI 线 3 打分器同一来源 tools/script_rsi/shootable.py
        SH = _load("shootable", "tools/script_rsi/shootable.py")
        bad = [x for x in SH.shootable_rows(pre + ch, ep) if not x["ok"]]
        fails += [f"shootable#镜{x['shot']} {SH.why(x)[:160]}" for x in bad]
        # K-WRT-H15 / H16（总调度 11-02，项目方融合样本）：在画人物接触场景物件、不正面直立对镜头；双人不用紧景别
        ST = _load("staging", "tools/script_rsi/staging.py")
        st_bad = [x for x in ST.staging_rows(pre + ch, ep) if not x["ok"]]
        if (Path(path).parent / f"P4_ep{ep:02d}.md.v3").exists() or (Path(path).parent / "CLEAN_CUT.json").exists():   # v3 集 / V2 完全切割 run：H19 / H20 / H23–H25 / K-WRT-211 进闸门
            obj3 = H.episode_obj(pre, ch, ep, wd)
            sh3 = sorted(obj3.shots, key=lambda s: s.index)
            v3 = RC6.v3_checks(sh3, [RL.block_text(ch, k) for k in range(len(sh3))])
            fails += [f"v3#{i} {why[:160]}" for i, (ok, why) in v3.items() if not ok]
            SL = _load("scene_lock", "tools/script_rsi/scene_lock.py")
            scn = SL.check_episode(RL.block_text(ch, "head"), sh3, [RL.block_text(ch, k) for k in range(len(sh3))])
            fails += [f"scene#{i} {why[:160]}" for i, (ok, why) in scn.items() if not ok]
            k211 = RC6.mirror_hand_checks(sh3, [RL.block_text(ch, k) for k in range(len(sh3))])
            fails += [f"k211#{i} {why[:160]}" for i, (ok, why) in k211.items() if not ok]
            v3 = {**v3, **{f"scene#{i}": x for i, x in scn.items()}, **{f"k211#{i}": x for i, x in k211.items()}}
            r["fails"] = list(r["fails"]) + [{"item": f"v3#{i}"} for i, (ok, _w) in v3.items() if not ok]
            l1 = RC6.l1_checks(sh3, [RL.block_text(ch, k) for k in range(len(sh3))])      # L-188：平光禁用词 / 多人三层构图（只在 V2 run 闸门）
            fails += [f"l1#{i} {why[:160]}" for i, (ok, why) in l1.items() if not ok]
            r["fails"] = list(r["fails"]) + [{"item": f"l1#{i}"} for i in l1]
        fails += [f"staging#镜{x['shot']} {ST.why(x)[:160]}" for x in st_bad]
        res["eps"][ep] = {"met": r["met"], "total": r["total"], "fails": fails, "unshootable": [x["shot"] for x in bad],
                          "staging_bad": [x["shot"] for x in st_bad]}
        res["ok"] &= not bad and not st_bad
        res["ok"] &= not r["fails"]
    return res


def main(argv=None) -> int:
    argv = RUNS.gate_legacy_tool(argv, __file__)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit")
    g = sub.add_parser("gate")
    g.add_argument("path")
    g.add_argument("--episodes", default="")
    a = ap.parse_args(argv)
    if a.cmd == "audit":
        return cmd_audit(a)
    eps = sorted(H.RL.parse_episodes(a.episodes)) if a.episodes else None
    r = gate(Path(a.path), eps)
    print(json.dumps(r, ensure_ascii=False, indent=1)[:4000])
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
