"""PROMPTFIX 11-02 全剧同类扫描（只读）：按集出清单。
  编译侧（新编译器，compile_sha 的输出）：两人以上同框镜、局部人物服装收窄（K-REN-951 生效 = 旧编译会送整套）、站位句补上
  （K-REN-952 = 旧编译站位没进提示词）、cast 局部但可能露脸（K-REN-950）、尾帧补送脸（K-REN-953）、手部单品撤出参考槽（K-REN-955）、
  手部动作超标（img + motion 手部动作词 > 2，K-WRT-211）。
  账本侧（takes.json）：标了局部 / 背影 / 不露脸的镜，出了脸的版本数（Q1“cast 写不露脸，但画面里出了脸”）、参考图里没有身份脸的版本数、
  同镜同 stage 重复用过的种子数。
    python tools/promptfix/scan.py <compile_sha 输出 json> [--out data/review_pages/promptfix/scan.json]
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("packages/schema", "services/render_router", "services/agent", "packages/qc", ""):
    sys.path.insert(0, str(ROOT / p))

HAND_ACTS = re.compile(r"抬手|伸手|收手|按|握|拨|捏|攥|扶|搭|抓|递|接过|撑|摸|抚|压|勾|掐|点在|托")
FACE_HIT = "cast 写不露脸，但画面里出了脸"



def _atomic_write(path, text: str) -> None:
    """先写临时文件再 os.replace（arch_scan nonatomic_json）"""
    import os
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)

def main(argv) -> int:
    from ns_render import pipeline as P
    comp = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    out_f = Path(argv[argv.index("--out") + 1]) if "--out" in argv else None
    s = P.load_script()
    per_ep: dict = defaultdict(lambda: Counter())
    lists: dict = defaultdict(list)
    for e in s.episodes:
        n = int(e.number)
        for sh in e.shots:
            sid = f"ep{n:02d}-S{sh.index}"
            c = comp.get(sid) or {}
            ft = c.get("first") or {}
            on = [x for x in sh.cast if x.presence in ("在画", "局部")]
            partial = [x for x in sh.cast if x.presence == "局部" or "背" in str(x.part or "")]
            E = per_ep[n]
            E["shots"] += 1
            if len(on) >= 2:
                E["two_plus"] += 1
            if ft.get("wardrobe_scope"):
                E["wardrobe_scoped"] += 1
                lists["wardrobe_scoped"].append(sid)
            if "站位：" in (c.get("prompt") or ""):
                E["blocking_added"] += 1
                lists["blocking_added"].append(sid)
            if ft.get("conflicts"):
                E["face_conflict"] += 1
                lists["face_conflict"].append(sid)
            if ft.get("last_faces"):
                E["last_face_added"] += 1
                lists["last_face_added"].append(sid)
            hands = len(HAND_ACTS.findall((sh.img_prompt or "") + "，" + (sh.motion_prompt or "")))
            if hands > 2:
                E["hand_overload"] += 1
                lists["hand_overload"].append(f"{sid}({hands})")
            td = P.load_takes(sid)
            seeds = Counter()
            for t in td.get("takes") or []:
                if t.get("stage") not in ("image", "last"):
                    continue
                if t.get("seed") is not None:
                    seeds[(t["stage"], t["seed"])] += 1
                if not partial:
                    continue
                items = (t.get("postflight") or {}).get("items") or []
                q1 = next((i for i in items if i.get("id") == "Q1"), {})
                if FACE_HIT in str(q1.get("detail") or ""):
                    E["partial_face_takes"] += 1
                    lists["partial_face_takes"].append(f"{sid}/{t['stage']}#{t.get('n')}")
                refs = t.get("references") or []
                if not any("identity_refs" in r or "/refs/" in r and "characters" in r for r in refs):
                    E["partial_no_face_ref_takes"] += 1
            rep = sum(v - 1 for v in seeds.values() if v > 1)
            if rep:
                E["seed_reuse"] += rep
                lists["seed_reuse"].append(f"{sid}({rep})")
    res = {"per_episode": {f"ep{k:02d}": dict(v) for k, v in sorted(per_ep.items())}, "lists": lists}
    tot = Counter()
    for v in per_ep.values():
        tot.update(v)
    res["total"] = dict(tot)
    if out_f:
        _atomic_write(out_f, json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({"total": res["total"], "per_episode": res["per_episode"]}, ensure_ascii=False, indent=0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
