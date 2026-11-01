"""VQA：本地视觉模型复核每张出图 / 每条视频（R11-4 / R11-5 / R11-7 / R11-10；owner = VQA）。

    rubric.build_image_request(take|dict)   → 发给本地看图模型的请求（只含本地文件路径 / 本地图片字节）
    rubric.parse(text)                      → 规范化判定 {checks: {id: {s, e}}, people, scene, framing, defects}
    client.inspect_image(...) / inspect_video(...) → 调 gpu36 本地服务（127.0.0.1:8870，或 ssh 管道），带缓存
    contract.q9(verdict) / contract.v9(verdict)    → 契约 Q9 / V9 项（status, detail, evidence），只记录 / 阻断按 config
    judge.judge(...)                        → 写作网关（只发文字）判 pass / fail + prompt_delta（R11-10 闭环）

硬规则 K-REV-V01：图片 / 帧只进本地模型，任何外部 API 只收文字。judge.py 里有断言守住（text_only_guard）。
参数：config/vqa.json；提示词：config/prompts/vqa_inspect.md、vqa_judge.md；规则：knowledge/rules/vqa.yaml。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CFG = ROOT / "config" / "vqa.json"


def cfg() -> dict:
    try:
        return json.loads(CFG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
