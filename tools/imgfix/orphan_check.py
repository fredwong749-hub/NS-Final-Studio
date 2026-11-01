"""主语保留回归检查（IMGLAB 11-02，K-REN-901 / K-REN-902）。

ep06-S2 v6 顾沉长出林晚的蓝色长发：编译层按景别删句（strip_fullbody / filter_parts）把带人名的分句整句删掉，
剩下的描写没有主语，紧跟在最后一个【角色】锁后面，属性就归给了那个人。本检查按生产同一路径编译
（tools/pipeline/image_jobs.frame_prompt_full → ns_agent.frame_job.compile_frame → compiler.compile_shot），逐镜判：

  orphan    剧本 img 正文里写了名字的在画角色，编译后正文（CompiledShot.image_body）里名字没了 = 孤儿描述
  clash     同一首帧提示词既写“脸占六成”又写“两张脸都清晰入画”（特写 + ≥2 人露脸，K-REN-902）

用法：
  .venv/Scripts/python.exe tools/imgfix/orphan_check.py                       # 全部镜头
  .venv/Scripts/python.exe tools/imgfix/orphan_check.py --shots ep06-S2,ep08-S5 --json
  .venv/Scripts/python.exe tools/imgfix/orphan_check.py --hold data/autopilot/orphan_hold.json --json   # 只查暂停单里的镜
退出码：0 = 所查镜头孤儿 0、冲突 0；1 = 有孤儿或冲突；2 = 参数 / 镜头不存在。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "packages/schema", "services/render_router", "tools/prompt_v2", "tools/pipeline"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))



def _shot_key(ep, shot) -> str:
    sid = str(shot.id)
    return sid if sid.startswith("ep") else f"ep{int(ep.number):02d}-{sid}"


SPLIT = r"[，,；;、。]"


def owners(body: str, names: list[str]) -> list[tuple[str, str | None]]:
    """正文按小句归人：以人名开头的小句换主语，之后的小句归这个人（与 frame_job._covered 同一思路）"""
    import re
    out, cur = [], None
    for cl in re.split(SPLIT, body or ""):
        c = cl.strip()
        if not c:
            continue
        lead = next((n for n in names if c.startswith(n)), None)
        if lead:
            cur = lead
        out.append((c, cur))
    return out


def misowned(orig: str, body: str, names: list[str]) -> list[dict]:
    """编译后正文里，归属人和剧本原文不一致的小句（孤儿描述）。通用质感句、编译器补回的单独人名句不计"""
    from ns_agent import framing as FR
    src = {}
    for c, o in owners(orig, names):
        src.setdefault(c, o)
    bad = []
    for c, o in owners(body, names):
        if c in names or any(w in c for w in FR.GENERIC_CLAUSE) or c not in src:
            continue
        if src[c] is not None and src[c] != o:
            bad.append({"clause": c, "script_owner": src[c], "compiled_owner": o})
    return bad


def _primary() -> str:
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import runs as RN
    return RN.primary_run(ROOT)


def check(shots: list[str] | None = None, project: str | None = None, run: str | None = None) -> dict:
    """run：哪部剧（tools/autopilot/runs.py；None = primary）；project：framing / 资产项目键（缺省 = run 名）"""
    os.chdir(ROOT)
    import image_jobs as IJ
    run = run or _primary()
    project = project or run
    from ns_agent import compiler as C
    from ns_agent import framing as FR
    from runs import is_primary
    si = IJ.load_import(None if is_primary(run, ROOT) else run)
    g = si.globals
    want = set(shots or [])
    rows, seen = [], set()
    for ep in si.episodes:
        for sh in ep.shots:
            key = _shot_key(ep, sh)
            if want and key not in want:
                continue
            seen.add(key)
            prompt, c, _sr, _plan = IJ.frame_prompt_full(ep, sh, g, [], project)
            orig = C._strip_triggers(sh.img_prompt or "", list(sh.img_triggers or []))
            cast = [x.name for x in (sh.cast or []) if getattr(x, "visible", True)]
            lost = [n for n in cast if n in orig and n not in (c.image_body or "")]
            mis = misowned(orig, c.image_body or "", cast) if len(cast) >= 1 else []
            orphans = lost + [f"{m['clause'][:16]}（{m['script_owner']}→{m['compiled_owner']}）" for m in mis]
            clash = FR.framing_clash(prompt)
            rows.append({"shot": key, "orphans": orphans, "lost_names": lost, "misowned": mis, "clash": clash,
                         "ok": not orphans and not clash, "image_body": c.image_body})
    missing = sorted(want - seen)
    bad = [r for r in rows if not r["ok"]]
    return {"checked": len(rows), "orphan_shots": sum(1 for r in rows if r["orphans"]),
            "orphans": sum(len(r["orphans"]) for r in rows), "clash_shots": sum(1 for r in rows if r["clash"]),
            "bad": [r["shot"] for r in bad], "missing": missing, "rows": rows,
            "rule": "K-REN-901 删句保主语 / K-REN-902 特写双人露脸冲突"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots", default="", help="逗号分隔，例 ep06-S2,ep08-S5；不给 = 全部")
    ap.add_argument("--hold", default="", help="从暂停单（data/autopilot/orphan_hold.json）读镜头清单")
    ap.add_argument("--run", default=None, help="剧（runs.json 里的 run id）；缺省 = primary")
    ap.add_argument("--project", default=None, help="framing / 资产项目键；缺省 = run")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    shots = [s.strip() for s in a.shots.split(",") if s.strip()]
    if a.hold:
        hold = json.loads((ROOT / a.hold).read_text(encoding="utf-8"))
        shots += [x["shot"] for x in hold.get("shots") or []]
    r = check(shots or None, a.project, a.run)
    if r["missing"]:
        print(json.dumps({"error": "镜头不存在", "missing": r["missing"]}, ensure_ascii=False))
        return 2
    if a.json:
        out = dict(r)
        out["rows"] = [{k: v for k, v in x.items() if k != "image_body" or not x["ok"]} for x in r["rows"]]
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(f"查 {r['checked']} 镜：孤儿 {r['orphans']}（{r['orphan_shots']} 镜），构图冲突 {r['clash_shots']} 镜")
        for x in r["rows"]:
            if not x["ok"]:
                print(f"  ✗ {x['shot']} 孤儿={x['orphans']} 冲突={x['clash']}")
    return 0 if not r["bad"] else 1


if __name__ == "__main__":
    sys.exit(main())
