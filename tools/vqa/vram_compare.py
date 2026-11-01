"""VQAGATE 11-01：口径对照——同一批请求在两种口径下的判定一致率（阻断项 + 全部检查项 + eye_contact 对人工标签）。
    .venv/Scripts/python.exe tools/vqa/vram_compare.py g36_orig g36_B  → data/vqa/vram_bench/compare_<a>_<b>.json"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/agent"))
from ns_agent.vqa import contract as VQ  # noqa: E402


def load(tag):
    return {r["id"]: r for r in json.loads((ROOT / "data/vqa/vram_bench" / f"{tag}.json").read_text(encoding="utf-8"))["rows"]}


def norm(r):
    v = {"checks": json.loads(json.dumps(r.get("checks") or {})), "defects": list(r.get("defects") or []), "people": r.get("people") or []}
    VQ.sanitize(v)
    return v


def main(a, b):
    A, B = load(a), load(b)
    allc = VQ._all_checks()
    blk = [k for k, x in allc.items() if x.get("blocking")]
    rows, same_blk, item_agree, item_n = [], 0, 0, 0
    for k in A:
        if k not in B or A[k].get("error") or B[k].get("error"):
            continue
        va, vb = norm(A[k]), norm(B[k])
        ba, bb = sorted(set(va["defects"]) & set(blk)), sorted(set(vb["defects"]) & set(blk))
        same_blk += ba == bb
        for c in allc:
            sa, sb = (va["checks"].get(c) or {}).get("s"), (vb["checks"].get(c) or {}).get("s")
            if sa and sb:
                item_n += 1
                item_agree += sa == sb
        rows.append({"id": k, "label": A[k].get("label"), "blocking_a": ba, "blocking_b": bb, "same": ba == bb,
                     "eye_a": "eye_contact" in va["defects"], "eye_b": "eye_contact" in vb["defects"]})
    lab = [r for r in rows if r["label"] is not None]

    def eye(key):
        P = [r for r in lab if r["label"]]
        N = [r for r in lab if not r["label"]]
        return {"recall": f"{sum(r[key] for r in P)}/{len(P)}", "false_pos": f"{sum(r[key] for r in N)}/{len(N)}"}
    out = {"a": a, "b": b, "n": len(rows), "blocking_same": f"{same_blk}/{len(rows)}",
           "item_agreement": round(item_agree / max(1, item_n), 3), "eye_vs_label_a": eye("eye_a"), "eye_vs_label_b": eye("eye_b"),
           "secs_a": sorted(x.get("secs") or 0 for x in A.values()), "secs_b": sorted(x.get("secs") or 0 for x in B.values()),
           "rows": rows}
    (ROOT / "data/vqa/vram_bench" / f"compare_{a}_{b}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False))
    for r in rows:
        if not r["same"]:
            print("  不一致", r["id"], r["blocking_a"], "vs", r["blocking_b"])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
