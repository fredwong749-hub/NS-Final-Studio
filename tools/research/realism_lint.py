"""真人写实：出图参数 + 编译后提示词的系统侧检查（RESEARCH，R11-12 / R11-13，2026-11-01）。

⤴ 项目方 11-01 17:5x 看过锐化三档选 R0（“画面效果还是颜色,都非常满意”，L-087）：RL01–RL03 一律只记录（level=record），
不在写作链路或出图链路报警、不拦；现行 S★ 全套不改。

只查系统那一半（编译器补句、风格后缀、预设参数、契约口径），不查也不评价剧本内容；写作方的写法检查在
tools/qa/writer_lints.py（QW-W9）。规则：knowledge/rules/research_realism.yaml。

  RL01  双重锐化：预设开了后处理锐化（sharpen.enabled），提示词里又有 ≥2 个锐度 / 画质助推词        K-REN-X02
  RL02  色温冲突：正文写冷色主光（冷白顶光 / 冷光 / 偏冷…），风格后缀又固定写“暖调”                   K-PRM-X04
  RL03  契约 Q4 用整图 Laplacian（lap_full_min）判质感，而交付图是锐化后的图：锐化本身就能把 lap_full 翻倍  K-REV-X01

用法：
  .venv/Scripts/python.exe -X utf8 tools/research/realism_lint.py            # 扫 series10 首帧作业 + 配置，打印命中数
  .venv/Scripts/python.exe -X utf8 tools/research/realism_lint.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS = ROOT / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json"

SHARP_WORDS = ("焦点锐利", "五官锐利", "清晰对焦", "对焦清晰", "微反差", "锐利解析力", "解析力", "皮肤纹理清晰",
               "高清", "超清", "8K", "4K", "细节丰富", "超写实")
SHARP_RE = re.compile("|".join(map(re.escape, SHARP_WORDS)))
COLD_RE = re.compile(r"冷白顶光|冷白光|冷光|冷调|偏冷|冷色|冷蓝|蓝调|青白")
WARM_SUFFIX_RE = re.compile(r"暖调")


def lint_prompt(prompt: str, params: dict | None = None, suffix: str | None = None) -> list[dict]:
    """一条编译后提示词 + 生效参数（take.params.effective 或预设 params）→ 命中列表"""
    out = []
    p = prompt or ""
    params = params or {}
    sh = params.get("sharpen") or {}
    hits = SHARP_RE.findall(p)
    if sh.get("enabled") and len(hits) >= 2:
        out.append({"id": "RL01", "level": "record", "owner": "compiler",
                    "detail": f"后处理锐化已开（半径 {sh.get('radius')} / {sh.get('amount')}），提示词又有 {len(hits)} 个锐度词："
                              + "、".join(sorted(set(hits)))})
    suf = suffix if suffix is not None else params.get("style_suffix") or ""
    body = p[:p.rfind(suf)] if suf and suf in p else p
    if suf and WARM_SUFFIX_RE.search(suf) and COLD_RE.search(body):
        out.append({"id": "RL02", "level": "record", "owner": "compiler",
                    "detail": f"正文写了「{COLD_RE.search(body).group(0)}」，后缀固定写「暖调」"})
    return out


def lint_config(render_quality: dict, gen_contract: dict) -> list[dict]:
    """RL03：契约 Q4 的 lap_full 判据 × 开了锐化的出图预设"""
    q4 = ((gen_contract.get("image_thresholds") or {}).get("Q4_texture") or {})
    if not q4.get("lap_full_min"):
        return []
    sharp = [x["id"] for x in render_quality.get("image_presets", [])
             if ((x.get("params") or {}).get("sharpen") or {}).get("enabled")]
    if not sharp:
        return []
    return [{"id": "RL03", "level": "record", "owner": "contract",
             "detail": f"Q4 lap_full_min={q4['lap_full_min']} 在锐化后的交付图上测；开了锐化的预设：{', '.join(sharp)}。"
                       "data/ab/realism_ab：同一原图只去掉锐化，lap_full 降到 48–49%，3/3 从过线变不过线，p_plastic 不变"}]


def scan() -> dict:
    rq = json.loads((ROOT / "config/render_quality.json").read_text(encoding="utf-8"))
    gc = json.loads((ROOT / "config/gen_contract.json").read_text(encoding="utf-8"))
    preset = next(x for x in rq["image_presets"] if x["id"] == rq.get("frame_redo_preset", "frame_v9"))
    jobs = json.loads(JOBS.read_text(encoding="utf-8")) if JOBS.exists() else []
    jobs = jobs if isinstance(jobs, list) else jobs.get("jobs", [])
    rows, counts = [], {}
    for j in jobs:
        p = j.get("prompt") or ""
        iss = lint_prompt(p, preset["params"])
        for i in iss:
            counts[i["id"]] = counts.get(i["id"], 0) + 1
        rows.append({"shot": j.get("shot_id") or j.get("id"), "issues": iss})
    cfg = lint_config(rq, gc)
    return {"preset": preset["id"], "jobs": len(jobs), "counts": counts, "config": cfg, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    r = scan()
    print(f"预设 {r['preset']}，首帧作业 {r['jobs']} 条；命中 {r['counts']}")
    for c in r["config"]:
        print(c["id"], c["detail"])
    if a.json:
        Path(a.json).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
