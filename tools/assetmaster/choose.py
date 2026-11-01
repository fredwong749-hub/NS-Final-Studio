"""ASSETMASTER：Qwen 版 vs FLUX 版按契约自动选暂定，并全部登记（项目方原话："要用新的模型，用那个 flux 的模型"）。

规则（总调度 2026-11-01）：
  场景 / 单品（不涉及身份）：FLUX 通过契约 → 用 FLUX；否则用 Qwen（IMGGEN scenes.json / items.json）。
  造型设定图（涉及身份）：两版都过 Q1 → FLUX；只有一版过 → 用过的那版；都不过 → 不替换旧图，标不合格。
结果写 data/assetmaster/final_choice.json；--apply 时：
  单品 → items.json[slug].chosen_final，register_items.py --all 登记（取 chosen_final）；
  场景 → POST /api/assets/<scene_id>/refs（role=space，最新一张即解析器用的底图）；
  设定图 → sheets_v2.json[key].chosen = 最终，gen_look_sheets.py adopt。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AM = ROOT / "data/assetmaster"
FL = AM / "flux"


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def enforce_item_check(live: dict, checks: dict | None = None) -> dict:
    """K-AST-260：设定图选暂定 = Q1 通过 且 单品一致性检查通过（data/assetmaster/sheet_item_checks.json：Q2 自动或目检记录，
    seed 必须与选中的一致）。没有记录或记录不过 → chosen.ok=False（不 adopt），原因写进 chosen.why"""
    checks = checks if checks is not None else (jl(AM / "sheet_item_checks.json", {}) or {})
    for k, d in live.items():
        c = d.get("chosen")
        if not c or not c.get("ok"):
            continue
        ck = checks.get(k) or {}
        if (str(ck.get("seed")) != str(c.get("seed")) or ck.get("verdict") != "pass"
                or (ck.get("model") or "qwen-image-2.1") != (c.get("model") or "qwen-image-2.1")):
            c["ok"] = False
            c["why"] = "待单品一致性检查（K-AST-260）" if not ck else f"单品一致性检查记录是 seed {ck.get('seed')} / {ck.get('verdict')}"
        else:
            c["item_check"] = {x: ck.get(x) for x in ("how", "by", "at", "note")}
        # K-AST-264（IMGFIX r6，L-102）：入库检查（左右袖子一致、外层单品在）——人工 / 自动单品检查记录之外再机检一遍
        f = c.get("file")
        if c.get("ok") and f and (ROOT / f).is_file():
            try:
                import sys as _s
                for _p in ("services/agent", "packages/schema", "packages/qc"):
                    if str(ROOT / _p) not in _s.path:
                        _s.path.insert(0, str(ROOT / _p))
                from ns_agent import sheet_intake as SI
                cid, _, lk = k.partition("_look")
                chk = SI.check(f, cid, lk[:1] or None)
                c["intake"] = {"ok": chk["ok"], "blocking": chk["blocking"]}
                if not chk["ok"]:
                    c["ok"], c["why"] = False, "设定图入库检查没过（K-AST-264）：" + "；".join(chk["blocking"])
            except Exception as e:  # noqa: BLE001
                c["intake"] = {"ok": None, "error": repr(e)[:200]}
    return live


def merged_qwen_sheets() -> dict:
    """Qwen v2 设定图分了几个进程出（sheets_v2.json + sheets_v2_<gc|cy|al|linwanB>.json）；林晚 B 只认 O10 单独槽的重出版
    （101/202 画成抹胸，项目方 LW-O10 决定下作废）。合并后重新跑 Q1 选暂定，写回 sheets_v2.json"""
    import sys as _s
    _s.path[:0] = [str(ROOT / p) for p in ("tools/assetmaster", "tools/series10_imggen", "services/render_router",
                                           "services/agent", "packages/schema", "tools/pipeline")]
    import gen_look_sheets as GS
    base = jl(AM / "sheets_v2.json", {}) or {}
    rej = base.pop("lin_wan_lookB", None)
    if rej:
        base["_rejected_lin_wan_lookB_v2a"] = {"why": "束腰画成抹胸，不符合项目方 LW-O10", "data": rej}
    for f in sorted(AM.glob("sheets_v2_*.json")):
        if f.name in ("sheets_v2_snapshot.json",) or f.stem.endswith(("picked", "snapshot")):
            continue
        for k, v in (jl(f, {}) or {}).items():
            base.setdefault(k, {}).update(v)
    live = {k: v for k, v in base.items() if not k.startswith("_")}
    GS.pick(live)
    for k, ov in (jl(AM / "sheet_overrides.json", {}) or {}).items():   # 目检覆盖（Q1 只管脸，管不了服装与单品是否一致）
        v = (live.get(k) or {}).get(str(ov["seed"]))
        if v and v.get("ok"):
            live[k]["chosen"] = {"seed": str(ov["seed"]), "file": v["file"], "ok": True, "tentative": True, "override": ov["why"]}
    enforce_item_check(live)
    base.update(live)
    (AM / "sheets_v2.json").write_text(json.dumps(base, ensure_ascii=False, indent=1), encoding="utf-8")
    return live


def choose() -> dict:
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "items": {}, "scenes": {}, "sheets": {}}
    qi, fi = jl(AM / "items.json", {}), jl(FL / "items.json", {})
    for slug, q in qi.items():
        f = fi.get(slug) or {}
        fc, qc = f.get("chosen") or {}, q.get("chosen") or {}
        if fc.get("ok"):
            pick = {"model": "flux2-klein-4b", "file": fc["file"], "why": "FLUX 通过契约（优先）"}
        elif qc.get("ok"):
            pick = {"model": "qwen-image-2.1", "file": qc["file"], "why": "FLUX 未通过" if f else "FLUX 未出"}
        else:
            pick = {"model": None, "file": None, "why": "两版都不过"}
        out["items"][slug] = {"char": q["char"], "name": q["name"], **pick,
                              "qwen": qc.get("file"), "flux": fc.get("file"), "flux_ok": fc.get("ok"), "qwen_ok": qc.get("ok")}
    qs = jl(ROOT / "data/pipeline/runs/series10_v1/images/scenes/scenes.json", {})
    fixed = (jl(AM / "scene_choice.json", {}) or {}).get("scenes")     # 首帧开跑前已定并登记的场景（不再变）
    for sid, f in (fixed or jl(FL / "scenes.json", {}) or {}).items():
        fc = f.get("chosen") or {}
        qc = (qs.get(sid) or {}).get("chosen") or {}
        if fc.get("ok"):
            pick = {"model": "flux2-klein-4b", "file": fc["file"], "why": "FLUX 通过（0 脸 0 字）"}
        else:
            pick = {"model": "qwen-image-2.1", "file": qc.get("file"), "why": "FLUX 未通过，保留 IMGGEN Qwen 版"}
        out["scenes"][sid] = {**pick, "qwen": qc.get("file"), "flux": fc.get("file")}
    qsh, fsh = merged_qwen_sheets(), jl(FL / "sheets.json", {})
    for key in sorted(set(qsh) | set(fsh)):
        qc = (qsh.get(key) or {}).get("chosen") or {}
        fc = (fsh.get(key) or {}).get("chosen") or {}
        qsim = ((qsh.get(key) or {}).get(str(qc.get("seed"))) or {}).get("sim") if qc else None
        fsim = next((v.get("sim") for v in (fsh.get(key) or {}).get("cands", {}).values() if v.get("file") == fc.get("file")), None)
        fseed = next((str(v.get("seed")) for v in (fsh.get(key) or {}).get("cands", {}).values() if v.get("file") == fc.get("file")), None)
        fck = enforce_item_check({key: {"chosen": {**fc, "seed": fseed, "model": "flux2-klein-4b"}}})[key]["chosen"] if fc else {}
        if fc.get("ok") and fck.get("ok"):
            pick = {"model": "flux2-klein-4b", "file": fc["file"], "seed": fseed, "why": "FLUX 过 Q1 且过单品一致性检查（优先）"}
        elif qc.get("ok"):
            pick = {"model": "qwen-image-2.1", "file": qc["file"], "seed": qc.get("seed"),
                    "why": "FLUX " + ("未过 Q1" if not fc.get("ok") else "未过单品一致性检查（K-AST-260）") + "，用 Qwen v2"}
        else:
            pick = {"model": None, "file": None, "why": "两版都没过 Q1 + 单品检查：不替换旧设定图"}
        out["sheets"][key] = {**pick, "qwen": qc.get("file"), "flux": fc.get("file"), "qwen_sim": qsim, "flux_sim": fsim}
    (AM / "final_choice.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def apply(ch: dict, api: str):
    import httpx
    # 单品
    qi = jl(AM / "items.json", {})
    for slug, c in ch["items"].items():
        if c.get("file"):
            qi[slug]["chosen_final"] = {"file": c["file"], "model": c["model"], "ok": True}
    (AM / "items.json").write_text(json.dumps(qi, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "tools/assetmaster/register_items.py"), "--all", "--api", api], cwd=str(ROOT))
    # 场景
    reg = jl(AM / "registered_scenes.json", {})
    for sid, c in ch["scenes"].items():
        if not c.get("file") or c["model"] != "flux2-klein-4b" or reg.get(sid, {}).get("file") == c["file"]:
            continue
        with open(ROOT / c["file"], "rb") as fh:
            r = httpx.post(f"{api}/api/assets/{sid}/refs", files={"file": (Path(c["file"]).name, fh, "image/png")},
                           data={"role": "space", "note": f"暂定｜ASSETMASTER FLUX.2 klein 4B 空镜底图（契约 0 脸 0 字）｜{c['why']}"}, timeout=120)
        reg[sid] = {"file": c["file"], "status": r.status_code, "resp": r.text[:300]}
        print("scene", sid, r.status_code)
    (AM / "registered_scenes.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    # 设定图
    qsh = jl(AM / "sheets_v2.json", {})
    for key, c in ch["sheets"].items():
        if c.get("file"):
            qsh.setdefault(key, {})["chosen"] = {"file": c["file"], "ok": True, "tentative": True, "model": c["model"], "seed": c.get("seed")}
    (AM / "sheets_v2.json").write_text(json.dumps(qsh, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "tools/assetmaster/gen_look_sheets.py"), "adopt"], cwd=str(ROOT))


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--api", default="http://127.0.0.1:5173")
    a = ap.parse_args(argv)
    ch = choose()
    for k in ("items", "scenes", "sheets"):
        from collections import Counter
        print(k, dict(Counter(v["model"] for v in ch[k].values())))
    if a.apply:
        apply(ch, a.api)
    return 0


if __name__ == "__main__":
    sys.exit(main())
