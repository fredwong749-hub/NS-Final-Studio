"""V2 完全切割检查（L-126，项目方 11-02 18:5x：“旧的东西一个都不能进来”）：扫一份 V2 稿 / Brief / 造型表，报出 V1 / 第二季内容的残留。

词表（自动从旧剧的登记内容里收，不手抄；旧剧 = runs.json 里除当前 run 以外的所有 run）：
  人物  旧剧 storyline 的人物中文名 + char_id
  场景  两季 storyline 的 scene_id + 场景名
  剧名  两季 storyline / brief 的 title（整串）
  道具线  V1 内容方向的关键道具 / 情节词（PROP_LINE，总调度 11-02 点名：门卡、束腰、九环、穿孔 等）
例外：项目方给 V2 指定的造型名（assets_v2/manifest.json 里 lead_f 的 O1–O3 名称）里出现的词不算残留（如“漆皮”“绑带”“项圈”）。
用法：v1_leak.py scan --file <稿> [--file …]   → 命中清单；0 命中退出码 0
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROP_LINE = ("门卡", "束腰", "九环", "阴环", "乳环", "铁珠", "钢珠", "穿孔", "纹身", "舌钉", "水晶甲", "银戒", "红绳", "图纸", "名单", "验收",
             "投名状", "预约单", "续约单", "两碗汤", "九串", "漆皮之下", "老公", "衣帽间推拉门")


def _json(p: Path):
    t = p.read_text(encoding="utf-8")
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    return json.loads(m.group(1) if m else t)


def old_runs(current: str | None, root: Path = ROOT) -> list[str]:
    """旧剧 = config/pipeline/runs.json 里登记的、除当前（完全切割的）run 以外的所有 run（不在代码里写死剧名）"""
    sys.path.insert(0, str(root / "tools" / "autopilot"))
    import runs as RN
    return sorted(r for r in (RN.registry(root).get("runs") or {}) if r != current)


def vocab(root: Path = ROOT, current: str | None = None) -> dict:
    names, ids, scenes, titles = set(), set(), set(), set()
    for run in old_runs(current, root):
        rd = root / "data" / "pipeline" / "runs" / run
        for cand in (rd / "P1_storyline.json", rd / "writer_out" / "P1_a1.json"):
            if not cand.exists():
                continue
            try:
                d = _json(cand)
            except (OSError, ValueError) as e:      # 读不到旧季登记 = 词表不全：报出来，不当作 0 命中
                raise RuntimeError(f"读不到旧季登记 {cand}：{e!r}") from e
            for c in d.get("characters") or []:
                names.add(c.get("name", "")); ids.add(c.get("char_id", ""))
            for s in d.get("scenes") or []:
                scenes.add(s.get("scene_id", "")); scenes.add(s.get("name", ""))
            if d.get("title"):
                titles.add(d["title"])
        b = rd / "P0_brief.json"
        if b.exists():
            t = json.loads(b.read_text(encoding="utf-8")).get("title")
            if t:
                titles.add(t)
    if current:                          # 本 run 被项目方退回的稿（_rejected_*/ 里的 P1）也算旧内容：人物名 / char_id / 场景 / 剧名不许再出现（L-127）
        for cand in sorted((root / "data" / "pipeline" / "runs" / current).glob("_rejected_*/writer_out_P1_a1.json")):
            try:
                d = _json(cand)
            except (OSError, ValueError) as e:
                raise RuntimeError(f"读不到退回稿 {cand}：{e!r}") from e
            for c in d.get("characters") or []:
                names.add(c.get("name", ""))
                if not str(c.get("char_id", "")).startswith("lead_"):    # 女主 id lead_f 是项目方指定的固定 id，不算旧内容
                    ids.add(c.get("char_id", ""))
            for sc in d.get("scenes") or []:
                scenes.add(sc.get("scene_id", "")); scenes.add(sc.get("name", ""))
            if d.get("title"):
                titles.add(d["title"])
    allow = set()
    oi = root / "assets_v2" / "owner_inputs.json"         # 项目方给 V2 的造型 / 鞋 / 饰品名（19:1x 起 O1–O4、SH1 / SH2、J1 / J2）
    if oi.exists():
        allow |= {str(it.get("name")) for it in json.loads(oi.read_text(encoding="utf-8")).get("items") or [] if it.get("name")}
    dv = root / "docs" / "v2" / "DIRECTION_V2.md"          # 项目方给 V2 的方向原话（> 引用行）整句放行：他自己的话不算旧内容
    if dv.exists():
        allow |= {ln.lstrip("> ").strip() for ln in dv.read_text(encoding="utf-8").splitlines() if ln.startswith(">") and len(ln) > 10}
    mf = root / "assets_v2" / "manifest.json"
    if mf.exists():
        lf = (json.loads(mf.read_text(encoding="utf-8")).get("characters") or {}).get("lead_f") or {}
        for lk in (lf.get("looks") or {}).values():
            allow.add(lk.get("name", ""))
    clean = lambda xs: sorted(x for x in xs if x and len(x) >= 2)
    return {"names": clean(names), "char_ids": clean(ids), "scenes": clean(scenes), "titles": clean(titles), "props": list(PROP_LINE),
            "allow_text": sorted(allow)}


def scan(text: str, v: dict) -> list[dict]:
    body = text
    for a in v.get("allow_text") or []:
        if a and len(a) >= 2:                  # 空串 replace 会在每个字之间插空格，把所有命中都打散（11-02 发现的 bug）
            body = body.replace(a, " ")        # 项目方指定的 V2 造型名整串放行
    hits = []
    for kind in ("names", "char_ids", "scenes", "titles", "props"):
        for w in v[kind]:
            n = body.count(w)
            if n:
                i = body.find(w)
                hits.append({"kind": kind, "word": w, "count": n, "context": body[max(0, i - 15):i + len(w) + 15].replace("\n", " ")})
    return hits


def redact(text: str, v: dict) -> str:
    """把旧剧内容词换成中性占位（给 V2 写作包用：旧规则里的举例保留规则意思，不带旧剧内容进来）；项目方指定的 V2 造型名整串保留"""
    keep = {f"@@KEEP{i}@@": a for i, a in enumerate(v.get("allow_text") or []) if a}
    for k, a in keep.items():
        text = text.replace(a, k)
    rep = [(w, "<char_id>") for w in v["char_ids"]] + [(w, "<scene_id>") for w in v["scenes"] if w.startswith("sk_")] +           [(w, "某剧") for w in v["titles"]] + [(w, "某场景") for w in v["scenes"] if not w.startswith("sk_")] +           [(w, "某角色") for w in v["names"]] + [(w, "某道具") for w in v["props"]]
    for w, r in sorted(rep, key=lambda x: -len(x[0])):        # 长词先换（场景名里含人名等）
        text = text.replace(w, r)
    for k, a in keep.items():
        text = text.replace(k, a)
    return text


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--file", action="append", required=True)
    s.add_argument("--run", default="", help="当前（完全切割的）run；不给 = 从 --file 路径里取 data/pipeline/runs/<run>/")
    a = ap.parse_args(argv)
    cur = a.run or next((m.group(1) for f in a.file for m in [re.search(r"runs[\/]([^\/]+)[\/]", f)] if m), None)
    v = vocab(current=cur)
    total = 0
    for f in a.file:
        p = Path(f) if Path(f).is_absolute() else ROOT / f
        hits = scan(p.read_text(encoding="utf-8"), v)
        total += len(hits)
        print(json.dumps({"file": f, "hits": hits}, ensure_ascii=False, indent=1))
    print(f"V1 残留命中 {total} 处（词表：人物 {len(v['names'])}、char_id {len(v['char_ids'])}、场景 {len(v['scenes'])}、剧名 {len(v['titles'])}、道具线 {len(v['props'])}）")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
