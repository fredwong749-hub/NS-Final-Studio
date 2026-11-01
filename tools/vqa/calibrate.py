#!/usr/bin/env python3
"""VQA 标定：用总调度已有标签算本地看图模型每类缺陷的一致率（R11-4/5，K-REV-V03）。

  build   收集带标签样本 → data/vqa/calibration/set.json（+ files.txt：要同步到 gpu36 的相对路径）
  run     逐张调本地看图服务（client.inspect_image）→ data/vqa/calibration/raw/<id>.json（可续跑）
  score   一致率（按检查项；强标签 / 弱标签分开）→ data/vqa/calibration/report.json + report.md

标签来源（全部是总调度给的，不是 Claude 判内容）：
  A data/review_pages/contract_labels_r1/labels_master.json（Q5 手 / Q6 文字 / Q7 场景 + note 里点名的 Q7-NN 身份错）
  B takes.json 的 master_reject（原因按关键词归到检查项）与 master_review ok（反例）
  C data/review_pages/asset_reflock/heldout_labels.json（q4 质感 / q2shoe 鞋 / q5hand 手；1 = 合格，0 = 不合格）
一致率 = 预测（defect = 不合格）与标签相同的比例；na / unsure 一律算“不合格之外”的预测（unsure 单列）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "agent"))
OUT = ROOT / "data" / "vqa" / "calibration"
SHOE_REF = "assets/characters/lin_wan/items/shoes/S01_side45_s0.png"
HANDS = ("extra_limbs", "hand_malformed")

# labels_master note（总调度 11-01 10:45）：“多张身份错：顾沉长发 / 双林晚 / 裸上身男”，编号见 postflight.py 注释
Q7_SPECIAL = {26: "hair_mismatch", 32: "hair_mismatch", 34: "hair_mismatch", 40: "hair_mismatch", 46: "hair_mismatch",
              36: "extra_person", 56: "extra_person", 31: "clothing_state"}
REJECT_RULES = [(r"外套|下装|长裤|铅笔裙|西装裙", "outfit_mismatch"), (r"塑料|娃娃", "plastic_doll"),
                (r"不像顾沉|不像", "identity_drift"), (r"手部大特写.*(带脸|露了脸)|露了脸", "framing_mismatch")]
SKIP_REJECT = r"早于|过期|下游于"


def _takes() -> dict[str, dict]:
    """图片文件名（去 _post）→ take 记录"""
    out = {}
    for f in (ROOT / "data" / "renders").glob("*/*/takes.json"):
        t = json.loads(f.read_text(encoding="utf-8"))
        for x in (t if isinstance(t, list) else t.get("takes") or []):
            for k in ("file", "raw_file"):
                if x.get(k):
                    out[Path(x[k]).name.replace("_post", "")] = x
    return out


def _find(takes: dict, path: str) -> dict:
    n = Path(path).name.replace("_post", "")
    return takes.get(n) or takes.get(n.replace("_raw", "")) or {}


def _norm(p: str) -> str:
    p = p.replace("\\", "/")
    return p if p.startswith(("data/", "assets/")) else "data/" + p


def build() -> dict:
    takes = _takes()
    items: list[dict] = []

    def add(iid, img, labels, src, take=None, weak=None, prompt=None, refs=None, extra=None):
        take = take or {}
        items.append({"id": iid, "image": _norm(img), "labels": labels, "weak": weak or {}, "source": src,
                      "prompt": prompt if prompt is not None else take.get("prompt") or "",
                      "references": refs if refs is not None else take.get("references") or [],
                      "extra_refs": extra or []})

    # A
    lm = json.loads((ROOT / "data/review_pages/contract_labels_r1/labels_master.json").read_text(encoding="utf-8"))
    it = json.loads((ROOT / "data/review_pages/contract_labels_r1/items.json").read_text(encoding="utf-8"))
    for q, rows in it.items():
        for i, r in enumerate(rows, 1):
            lab = lm["labels"].get(f"{q}|{r['key']}")
            if lab != "ok":
                continue
            t = _find(takes, r["file"])
            labels, weak = {}, {}
            if q == "Q5":
                labels = {"hands": "ok"}
            elif q == "Q6":
                labels = {"text_watermark": "ok"}
            elif q == "Q7":
                labels = {"wrong_scene": "ok"}
                sp = Q7_SPECIAL.get(i)
                if sp:
                    labels[sp] = "defect"
                for c in ("hair_mismatch", "extra_person", "clothing_state"):
                    if c != sp:
                        weak[c] = "ok"
            extra = [(r["scene"], "场景参考（地点 / 陈设 / 光线）")] if r.get("scene") else []
            add(f"A-{q}-{i:02d}", r["file"], labels, f"labels_master {q}-{i:02d}", t, weak, extra=extra)
    # B
    for f in (ROOT / "data" / "renders").glob("*/*/takes.json"):
        t = json.loads(f.read_text(encoding="utf-8"))
        shot = f"{f.parts[-3]}-{f.parts[-2]}"
        for x in (t if isinstance(t, list) else t.get("takes") or []):
            mr, ok = x.get("master_reject"), x.get("master_review")
            if mr and not re.search(SKIP_REJECT, mr.get("reason", "")):
                labs = {c: "defect" for pat, c in REJECT_RULES if re.search(pat, mr.get("reason", ""))}
                if labs:
                    add(f"B-rej-{shot}-{Path(x['file']).stem[:20]}", x["file"], labs, "master_reject：" + mr["reason"][:80], x)
            if ok and ok.get("ok"):
                note = ok.get("note", "")
                labs = {"outfit_mismatch": "ok"} if re.search(r"外套|套裙|铅笔裙|造型|衬衫", note) else {}
                if re.search(r"顾沉|一致", note):
                    labs["identity_drift"] = "ok"
                if "手部大特写" in note:
                    labs["framing_mismatch"] = "ok"
                if "少塑料感" in note:
                    labs["plastic_doll"] = "ok"
                if labs:
                    add(f"B-ok-{shot}-{Path(x['file']).stem[:20]}", x["file"], labs, "master_review：" + note[:80], x)
    # C
    hl = json.loads((ROOT / "data/review_pages/asset_reflock/heldout_labels.json").read_text(encoding="utf-8"))
    hi = json.loads((ROOT / "data/review_pages/asset_reflock/heldout_index.json").read_text(encoding="utf-8"))
    for grp, check in (("q4", "plastic_doll"), ("q2shoe", "shoe_mismatch"), ("q5hand", "hands")):
        for code, lab in hl.get(grp, {}).items():
            if lab is None or code not in hi.get(grp, {}):
                continue
            p = hi[grp][code]
            prompt = "【林晚】22岁中国成年女性，蓝发及腰，齐刘海。全身，穿 12cm 透明侧开细高跟（参考鞋）" if grp == "q2shoe" else ""
            extra = [(SHOE_REF, "参考鞋（12cm 透明侧开细高跟）")] if grp == "q2shoe" else []
            spec = {"items": ["12cm 透明侧开细高跟"]} if grp == "q2shoe" else None
            add(f"C-{grp}-{code}", p, {check: "ok" if lab == 1 else "defect"}, f"heldout {grp} {code}",
                prompt=prompt, refs=[], extra=extra)
            if spec:
                items[-1]["spec"] = spec
    OUT.mkdir(parents=True, exist_ok=True)
    items = [i for i in items if (ROOT / i["image"]).exists()]
    (OUT / "set.json").write_text(json.dumps({"built": time.strftime("%Y-%m-%dT%H:%M:%S"), "items": items},
                                             ensure_ascii=False, indent=1), encoding="utf-8")
    files = sorted({i["image"] for i in items} | {r for i in items for r in i["references"]} |
                   {r for i in items for r, _ in i["extra_refs"]})
    (OUT / "files.txt").write_text("\n".join(f for f in files if (ROOT / f).exists()) + "\n", encoding="utf-8")
    print(f"{len(items)} 样本；{len(files)} 个文件")
    return {"items": items}


def run(limit: int | None = None, only: str | None = None, refresh: bool = False) -> None:
    from ns_agent.vqa import client
    from ns_agent.vqa import contract as VQ
    s = json.loads((OUT / "set.json").read_text(encoding="utf-8"))
    raw = OUT / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    n = 0
    for it in s["items"]:
        if only and not re.search(only, it["id"]):
            continue
        f = raw / f"{it['id']}.json"
        if f.exists() and not refresh:
            continue
        t0 = time.time()
        v = client.inspect_image(it["image"], it["prompt"], it["references"],
                                 extra_refs=[tuple(x) for x in it["extra_refs"]], spec=it.get("spec"), label=it["id"])
        VQ.remember(ROOT / it["image"], v)
        f.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{it['id']}: {v.get('error') or ','.join(v.get('defects') or []) or 'ok'}  ({time.time() - t0:.0f}s)", flush=True)
        n += 1
        if limit and n >= limit:
            break


def _pred(v: dict, check: str) -> str | None:
    c = v.get("checks") or {}
    if check == "hands":
        ss = [c.get(h, {}).get("s") for h in HANDS]
        if not any(ss):
            return None
        return "defect" if "defect" in ss else ("unsure" if "unsure" in ss else "ok")
    return (c.get(check) or {}).get("s")


def score() -> dict:
    s = json.loads((OUT / "set.json").read_text(encoding="utf-8"))
    min_ag = 0.85
    try:
        sys.path.insert(0, str(ROOT / "services" / "agent"))
        from ns_agent.vqa import cfg
        min_ag = (cfg().get("calibration") or {}).get("min_agreement", 0.85)
    except Exception:  # noqa: BLE001
        pass
    rows: dict[str, dict] = {}
    for it in s["items"]:
        f = OUT / "raw" / f"{it['id']}.json"
        if not f.exists():
            continue
        v = json.loads(f.read_text(encoding="utf-8"))
        if v.get("error"):
            continue
        for strength, labs in (("strong", it["labels"]), ("weak", it.get("weak") or {})):
            for check, lab in labs.items():
                p = _pred(v, check)
                r = rows.setdefault(f"{check}|{strength}", {"check": check, "labels": strength, "n": 0, "agree": 0,
                                                            "tp": 0, "tn": 0, "fp": 0, "fn": 0, "unsure": 0, "missing": 0, "wrong": []})
                r["n"] += 1
                if p is None:
                    r["missing"] += 1
                    p = "na"
                if p == "unsure":
                    r["unsure"] += 1
                pf, lf = p == "defect", lab == "defect"
                r["agree"] += int(pf == lf)
                r["tp" if pf and lf else "tn" if not pf and not lf else "fp" if pf else "fn"] += 1
                if pf != lf:
                    r["wrong"].append({"id": it["id"], "label": lab, "pred": p,
                                       "e": ((v.get("checks") or {}).get(check) or {}).get("e", "")[:120]})
    for r in rows.values():
        r["agreement"] = round(r["agree"] / r["n"], 3) if r["n"] else None
        r["eligible_for_blocking"] = bool(r["labels"] == "strong" and r["n"] >= 8 and r["agreement"] is not None
                                          and r["agreement"] >= min_ag and r["tp"] + r["fn"] > 0 and r["tn"] + r["fp"] > 0)
    rep = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "min_agreement": min_ag, "rows": sorted(rows.values(), key=lambda r: r["check"])}
    (OUT / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["| 检查项 | 标签 | n | 一致率 | 漏判 fn | 误判 fp | 拿不准 | 可转阻断 |", "|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        md.append(f"| {r['check']} | {r['labels']} | {r['n']} | {r['agreement']} | {r['fn']} | {r['fp']} | {r['unsure']} | "
                  f"{'是（待总调度批准）' if r['eligible_for_blocking'] else '否'} |")
    (OUT / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "score"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    if a.cmd == "build":
        build()
    elif a.cmd == "run":
        run(a.limit, a.only, a.refresh)
    else:
        score()
