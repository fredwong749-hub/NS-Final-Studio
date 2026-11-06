"""大脑状态页 data/brain/STATUS.md（BRAIN-FW）：每轮（API 常驻 / 会话内提交动作后）重生成——项目方 / 总调度看大脑看到了什么、决定了什么。
来源：data/brain/snapshot.json（telemetry）、decisions.jsonl（actions）、owner_notes.md、brain_api 的 cycle 记录（cycles.jsonl）。只读这些文件。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_REL = "data/brain"


def _tail(p: Path, n: int) -> list[dict]:
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:   # arch-ok: 文件还没有 = 空
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:   # arch-ok: 坏行跳过（只追加日志里半行）
            continue
    return out


def render(root: Path = ROOT, n_decisions: int = 30) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import telemetry as T
    snap = T._j(root / OUT_REL / "snapshot.json", {}) or {}
    cycles = _tail(root / OUT_REL / "cycles.jsonl", 10)
    dec = _tail(root / OUT_REL / "decisions.jsonl", n_decisions)
    L = ["# BRAIN 状态页（自动生成，别手改）", ""]
    cfg = T._j(root / "config/brain/brain.json", {}) or {}
    L.append(f"模式：API 常驻 {'开' if cfg.get('enabled') else '关'}（dry_run={cfg.get('dry_run', True)}，model={cfg.get('model')}，每 {cfg.get('interval_s')} s）；"
             f"关着时由会话内 PS-MASTER 按 tools/brain/session_brain.md 充当大脑。")
    L.append("")
    if cycles:
        L.append("## 最近轮次（API 大脑）")
        for c in cycles[-6:]:
            L.append(f"- {c.get('at')} hash={c.get('snapshot_hash')} 动作 {c.get('n_actions')} 拒 {c.get('n_rejected')} "
                     f"tokens in/out {c.get('input_tokens')}/{c.get('output_tokens')} cache_read {c.get('cache_read')} ${c.get('usd')} "
                     f"今日累计 ${c.get('usd_day')} stop={c.get('stop_reason')}{'  ' + str(c.get('error')) if c.get('error') else ''}")
            if c.get("text"):
                L.append(f"  > {str(c['text'])[:600]}")
        L.append("")
    L.append("## 最近决定（decisions.jsonl）")
    for d in reversed(dec):
        p = d.get("params") or {}
        L.append(f"- {d.get('at')} **{d.get('kind')}** {'DRY ' if d.get('dry') else ''}{json.dumps({k: v for k, v in p.items() if k not in ('reason', 'expected_effect', 'check_after_s')}, ensure_ascii=False)[:160]}")
        if p.get("reason"):
            L.append(f"  - 理由：{str(p['reason'])[:300]}")
        if p.get("expected_effect"):
            L.append(f"  - 预期：{str(p['expected_effect'])[:200]}（{p.get('check_after_s')} s 后复查）")
        L.append(f"  - 结果：{str(d.get('result'))[:200]}")
    L.append("")
    notes = root / OUT_REL / "owner_notes.md"
    if notes.is_file():
        L.append("## 给项目方的话")
        L.extend("- " + x for x in notes.read_text(encoding="utf-8").splitlines()[-8:])
        L.append("")
    L.append("## 快照摘要")
    L.append(T.summary_md(snap) if snap else "（还没有快照：跑 tools/brain/telemetry.py snapshot）")
    return "\n".join(L) + "\n"


def write(root: Path = ROOT) -> Path:
    p = root / OUT_REL / "STATUS.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(render(root), encoding="utf-8")
    os.replace(tmp, p)
    return p


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(write())
