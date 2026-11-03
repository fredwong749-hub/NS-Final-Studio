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
GUARD = ROOT / "config" / "v1_guard.json"     # HEADER-O 11-03：道具词 / 额外 id / 放行短语统一放配置（只用来检查，不改写）


def guard_cfg(root: Path = ROOT) -> dict:
    p = root / "config" / "v1_guard.json"
    if not p.is_file():
        raise RuntimeError(f"缺少 {p}：V1 内容词表必须在配置里（失败关闭）")
    return json.loads(p.read_text(encoding="utf-8"))


PROP_LINE = tuple(guard_cfg().get("props") or ())


def _json(p: Path):
    t = p.read_text(encoding="utf-8")
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    return json.loads(m.group(1) if m else t)


def old_runs(current: str | None, root: Path = ROOT) -> list[str]:
    """旧剧 = config/pipeline/runs.json 里登记的、除当前（完全切割的）run 以外的所有 run（不在代码里写死剧名）"""
    sys.path.insert(0, str(root / "tools" / "autopilot"))
    import runs as RN
    return sorted(r for r in (RN.registry(root).get("runs") or {}) if r != current)


def _strings(o) -> list[str]:
    if isinstance(o, str):
        return [o]
    if isinstance(o, dict):
        return [x for v in o.values() for x in _strings(v)]
    if isinstance(o, list):
        return [x for v in o for x in _strings(v)]
    return []


def run_style_text(root: Path, current: str | None) -> str:
    """本剧风格 bible 的正文（白名单来源，MERGE-OPS-O 11-03；项目方 04:3x“徕卡级锐利风格是我要的”、L-145 徕卡 + ARRI + Kodak）：
    config/compile/run_style.json runs.<本剧> 条目里的全部字符串值 + 它登记的 bible（toml）里的全部字符串值。
    只取解析后的值，不取注释（注释里写“不回落到 V1 的 Leica 模板”这种话不算放行）。V1 风格短语（v1_style_phrases）
    只有在这里出现的才放行；“S★ / R0 / 暖调通透”这类 V1 参数标记本剧 bible 不写，照拦。没有本剧 / 没登记 → 空串（全拦）"""
    if not current:
        return ""
    rs = root / "config" / "compile" / "run_style.json"
    try:
        ent = ((json.loads(rs.read_text(encoding="utf-8")).get("runs") or {}).get(current) or {}) if rs.exists() else {}
    except (OSError, ValueError) as e:                     # 风格表读不到 = 不放行任何风格词（更严），报出来
        raise RuntimeError(f"读不到 {rs}：{e!r}") from e
    out = _strings({k: v for k, v in ent.items() if k != "bible"})
    b = ent.get("bible")
    if b and (root / b).is_file():
        import tomllib
        try:
            out += _strings(tomllib.loads((root / b).read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            raise RuntimeError(f"读不到本剧风格 bible {b}：{e!r}") from e
    return chr(10).join(out)


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
                names.add(c.get("name", ""))
                if not str(c.get("char_id", "")).startswith("lead_"):    # 女主 id lead_f 是 V2 固定 id（asset_refs series10_v2.lead），smoke_v2 等旧 run 里出现也不算旧内容
                    ids.add(c.get("char_id", ""))
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
    dv = root / "docs" / "v2" / "DIRECTION_V2.md"          # 项目方给 V2 的方向原话（> 引用行）整句放行：他自己的话不算旧内容
    if dv.exists():
        allow |= {ln.lstrip("> ").strip() for ln in dv.read_text(encoding="utf-8").splitlines() if ln.startswith(">") and len(ln) > 10}
    mf = root / "assets_v2" / "manifest.json"
    if mf.exists():
        lf = (json.loads(mf.read_text(encoding="utf-8")).get("characters") or {}).get("lead_f") or {}
        for lk in (lf.get("looks") or {}).values():         # 项目方给 V2 的造型 / 鞋 / 饰品名：只从 manifest 读（OVERSIGHT-F 第 4 轮）
            allow.add(lk.get("name", ""))
        for it in (lf.get("items") or {}).values():
            allow.add((it or {}).get("name", ""))
    clean = lambda xs: sorted(x for x in xs if x and len(x) >= 2)
    rs = root / "config" / "compile" / "run_style.json"     # V1 风格短语（S★ / 徕卡暖调这一组，PROMPTFIX 20:4x）：V2 稿 / 编译提示词出现即命中
    style = (json.loads(rs.read_text(encoding="utf-8")).get("v1_style_phrases") or []) if rs.exists() else []
    own_style = run_style_text(root, current)              # MERGE-OPS-O（L-127 / L-145）：本剧风格 bible 里正当使用的画风词不算旧内容
    style = [w for w in style if w.lower() not in own_style.lower()]     # 英文词不分大小写（Leica / leica）
    return {"names": clean(names), "char_ids": clean(ids), "scenes": clean(scenes), "titles": clean(titles), "props": list(guard_cfg(root).get("props") or []),
            "style": clean(style), "allow_text": sorted(allow)}


def scan(text: str, v: dict) -> list[dict]:
    body = text
    for a in v.get("allow_text") or []:
        if a and len(a) >= 2:                  # 空串 replace 会在每个字之间插空格，把所有命中都打散（11-02 发现的 bug）
            body = body.replace(a, " ")        # 项目方指定的 V2 造型名整串放行
    hits = []
    for kind in ("names", "char_ids", "scenes", "titles", "props", "style"):
        for w in v.get(kind) or []:
            n = body.count(w)
            if n:
                i = body.find(w)
                hits.append({"kind": kind, "word": w, "count": n, "context": body[max(0, i - 15):i + len(w) + 15].replace("\n", " ")})
    return hits


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
