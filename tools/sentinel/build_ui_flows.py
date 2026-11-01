"""把 ui_rules.js（阈值来自 config/policies/sentinel.yaml S9_ui_rules）嵌进 detect.mjs 的 flows 文件 tools/sentinel/ui_flows.json。
  .venv/Scripts/python.exe tools/sentinel/build_ui_flows.py
页面：总览（/）、ep01 审片（/#ep01 → 点“审片”）。每页截一张图（sentinel_<页>_main.png，覆盖写）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def build() -> Path:
    from tools.autopilot import policy
    c = policy.load()["sentinel"]["S9_ui_rules"]["value"]
    js = (ROOT / "tools/sentinel/ui_rules.js").read_text(encoding="utf-8")
    js = "\n".join(ln for ln in js.splitlines() if not ln.startswith("//"))
    js = js.replace("__SAT__", str(c["color_sat_min"])).replace("__DOT__", str(c["dot_max_px"]))
    flows = [
        {"id": "overview", "title": "SENTINEL S9 总览", "path": "/", "wait": 8000, "steps": [{"wait": 4000}, {"js": js}, {"shot": "main"}]},
        {"id": "ep01_review", "title": "SENTINEL S9 ep01 审片", "path": "/#ep01", "wait": 8000,
         "steps": [{"click": "=审片", "after": 2500}, {"wait": 6000}, {"js": js}, {"shot": "main"}]},
    ]
    out = ROOT / "tools/sentinel/ui_flows.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(flows, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, out)
    return out


if __name__ == "__main__":
    print(build())
