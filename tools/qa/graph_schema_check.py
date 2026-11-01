"""配方图 ↔ 服务器节点 schema 核对（ITERAUDIT 2026-11-01；独立复核 VIDEO10 改 graph.py 时写）。

把配方编译成 ComfyUI API 图（services/recipes/ns_recipes/graph.py），逐节点对照服务器 /object_info：
节点存在、输入名存在（mode.width 这类动态输入取点前名）、必填齐全、COMBO 取值在选项里（模型文件 / PDD 文件 / attention / nfe）、
连线输出序号不越界、无悬空连线。图片占位符（@first_frame / @ref:…）提交时才替换，不算错。

    .venv/Scripts/python.exe tools/qa/graph_schema_check.py --recipes i2va_pdd2,ref2va_pdd2 --ports 18188,18288
退出码 0 = 全部一致。只读：只 GET /object_info，不提交任何作业。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/recipes"))
from ns_recipes import graph as G  # noqa: E402
from ns_recipes import registry as RG  # noqa: E402


def check(wf: dict, port: int, cache: dict) -> list[str]:
    def schema(ct):
        if (port, ct) not in cache:
            cache[(port, ct)] = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/object_info/{ct}", timeout=30)).get(ct)
        return cache[(port, ct)]
    errs = list(G.dangling_links(wf))
    for nid, n in wf.items():
        sc = schema(n["class_type"])
        if not sc:
            errs.append(f"{nid} 服务器没有节点 {n['class_type']}")
            continue
        req, opt = sc["input"].get("required", {}), sc["input"].get("optional", {})
        for k, v in n["inputs"].items():
            base = k.split(".")[0]
            spec = req.get(base) or opt.get(base)
            if spec is None:
                errs.append(f"{nid} {n['class_type']} 没有输入 {k}")
                continue
            if isinstance(v, list):
                if len(v) == 2 and isinstance(v[0], str) and v[0] in wf:
                    outs = (schema(wf[v[0]]["class_type"]) or {}).get("output") or []
                    if v[1] >= len(outs):
                        errs.append(f"{nid}.{k} 引用 {v[0]} 输出 {v[1]}，该节点只有 {len(outs)} 个输出")
                continue
            if isinstance(v, str) and v.startswith("@"):
                continue  # 占位符
            opts = spec[0] if isinstance(spec[0], list) else (spec[1].get("options") if spec[0] == "COMBO" and len(spec) > 1 else None)
            if opts and all(isinstance(o, str) for o in opts) and v not in opts:
                errs.append(f"{nid} {k}={v!r} 不在服务器选项 {opts[:6]}")
        for k, spec in req.items():
            has_default = len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]
            if k not in n["inputs"] and not any(x.startswith(k + ".") for x in n["inputs"]) and not has_default:
                errs.append(f"{nid} {n['class_type']} 缺必填 {k}")
    return errs


def build(rid: str, reg) -> dict:
    rc = reg.resolve(rid)
    refs = [{"role": "identity", "character": "lin_wan"}, {"role": "identity", "character": "gu_chen"}]
    if rc.get("mode") == "ref2va" or "ref2va" in rid:
        return G.ref2va(rc, "p", 768, 1344, 121, 1, "x", refs)
    if (rc.get("two_stage") or {}).get("enabled"):
        return G.two_stage(rc, "p", 768, 1344, 121, 1, "x", rc.get("mode") == "fl2va")
    return G.single(rc, "p", 768, 1344, 121, 1, "x", rc.get("mode") == "fl2va")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipes", default="i2va_pdd2,ref2va_pdd2")
    ap.add_argument("--ports", default="18188", help="本机隧道端口（各 GPU 道的 ComfyUI）")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    reg, cache, bad = RG.load(), {}, 0
    for rid in a.recipes.split(","):
        wf = build(rid.strip(), reg)
        for p in a.ports.split(","):
            errs = check(wf, int(p), cache)
            bad += len(errs)
            print(f"{rid} @:{p} 节点 {len(wf)}：" + ("一致" if not errs else "；".join(errs)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
