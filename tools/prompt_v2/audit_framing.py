"""PROMPT（2026-10-31）：审核出图作业是否经系统编译器生成（K-REN-103），并核对 K-REN-101（首句景别构图）与触发词。只读，输出报告。

每条作业三项检查：
  1 提示词 == tools/pipeline/image_jobs.frame_prompt（= 参考说明 + ns_agent.compiler.compile_shot 的 image_prompt）逐字相同，
    作业图里 TextEncodeQwenImage21 的提示词也一样；
  2 景别取舍开着、且不是下半身主体（鞋 / 脚特写）的镜：参考说明与出图触发词之后的首句是“<景别>构图”。看不见的部件由编译器
    按分句删除（角色锁 / 造型段 / img 原文）；【场景】段和道具描写（手里拎着的裙子、地上的鞋）是画面内容，不算违规；
  3 图像提示词里没有视频触发词（lnwan01）。

用法：.venv/Scripts/python.exe tools/prompt_v2/audit_framing.py [data/pipeline/runs/series10_v1]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "packages/schema", "services/render_router", "tools/pipeline"):
    sys.path.insert(0, str(ROOT / p))
import image_jobs as IJ  # noqa: E402
from ns_agent import framing as F  # noqa: E402

VIDEO_TRIGGERS = re.compile(r"\b(lnwan01)\b")


def audit(run_dir: Path) -> dict:
    data = json.loads((run_dir / "assets" / "first_frame_jobs.json").read_text(encoding="utf-8"))
    bible = IJ.load_bible()
    project = data["jobs"][0].get("framing_project") or run_dir.name
    si = IJ.load_import()          # K-OPS-Q24：与 rebuild 同一来源（导入稿），不再读 P4 稿
    g, by_ep, rows = si.globals, {e.number: e for e in si.episodes}, []
    jobs = [j for j in data["jobs"] if not str(j.get("status", "")).startswith("stale:")]
    for j in jobs:
        n = int(j["ep"])
        ep = by_ep[n]
        shot = next(s for s in ep.shots if s.id == j["shot"])
        want, _c = IJ.frame_prompt(ep, shot, g, list(j.get("refs") or []), project, bible)
        p = j.get("prompt") or ""
        gp = next((x["inputs"]["prompt"] for x in (j.get("graph") or {}).values()
                   if x.get("class_type") == "TextEncodeQwenImage21"), None)
        issues = []
        if p != want or gp != want:
            issues.append("提示词不是系统编译器输出（或作业图里的提示词与 prompt 字段不一致）")
        size = F.size_of(shot.img_prompt)
        if F.enabled(n, shot.index, None, project=project) and not F.lower_focus(shot.img_prompt) and F.lead(size):
            from ns_agent.asset_refs import SINGLE_TURN_RE   # IMGFIX K-REN-704：身份脸句后的单人朝向句也属参考说明段
            head = re.sub(r"^(图\d+是[^。]*。)*", "", SINGLE_TURN_RE.sub("", p, count=1))
            head = re.sub(r"^((?:[a-z][a-z0-9_]*|pose_[^，]*)，)*", "", head)
            # K-REN-902（IMGLAB 11-02）：脸部特写 + ≥2 人露脸 → 首句是双人近景构图
            if not head.startswith(F.lead(size)) and not head.startswith(F.TWO_FACE_CLOSE_LEAD):
                issues.append(f"首句不是“{F.lead(size)}”")
        if VIDEO_TRIGGERS.search(p):
            issues.append("图像提示词里有视频触发词 lnwan01")
        rows.append({"shot": j["shot"], "size": size, "lower_focus": F.lower_focus(shot.img_prompt), "issues": issues})
    return {"run": str(run_dir.relative_to(ROOT)).replace("\\", "/"), "jobs": len(rows),
            "ok": sum(1 for r in rows if not r["issues"]), "rows": [r for r in rows if r["issues"]]}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/pipeline/runs/series10_v1"
    print(json.dumps(audit(r if r.is_absolute() else ROOT / r), ensure_ascii=False, indent=1))
