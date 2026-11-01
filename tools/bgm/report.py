"""BGM 每集结果汇总（从 data/music/series10/epNN/meta.json 读，不重新计算）→ Markdown。

    .venv/Scripts/python.exe tools/bgm/report.py [--eps 1-10] [--out docs/bgm/r1_results.md]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deliver import ROOT, jload, load_cfg, out_dir  # noqa: E402


def parse_eps(s: str) -> list[int]:
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def ep_md(ep: int, od: Path) -> list[str]:
    st = jload(od / f"ep{ep:02d}" / "meta.json", {}) or {}
    if not st:
        return [f"## ep{ep:02d}", "", "没有记录（未运行）。", ""]
    b = st.get("brief") or {}
    ch = st.get("chosen") or {}
    L = [f"## ep{ep:02d} — {st.get('status')}", "",
         f"- brief（写作模型 {(st.get('writer') or {}).get('model')}，{(st.get('writer') or {}).get('rounds')} 轮；"
         f"`{od.relative_to(ROOT).as_posix()}/ep{ep:02d}/brief.json`）：bpm {b.get('bpm', {}).get('min')}–{b.get('bpm', {}).get('max')}"
         f"（目标 {b.get('bpm', {}).get('target')}），key {b.get('key') or '—'}；乐器 {', '.join(b.get('instrumentation') or [])}；"
         f"情绪弧 {' → '.join(m.get('mood', '') for m in b.get('mood_arc') or [])}；段落 {' / '.join(s.get('name', '') for s in b.get('sections') or [])}"
         f"；换段 {('@' + str((b.get('cue_change') or {}).get('at_s')) + ' s') if (b.get('cue_change') or {}).get('has') else '无'}；duck {len(b.get('duck') or [])} 段",
         f"- caption：{b.get('caption_en')}", "",
         "| 候选 | 轮 | 模型 | 设备 | 种子 | bpm 参数 | 实测速度 | CLAP | 能量 r | 人声 dB | p_vocal | 最长静音 s | LUFS 原始 | 闸门 | 提示 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in st.get("candidates") or []:
        m = c.get("metrics") or {}
        mark = "**✔ 选中**" if c["id"] == ch.get("id") else ("通过" if c.get("gate_pass") else "✘ " + "；".join(c.get("gate_fail") or []))
        dev = c.get("device") if c.get("device") == "cpu" else f"gpu33:{c.get('gpu')}"
        L.append(f"| {c['id']} | {c.get('round')} | {c.get('model')} | {dev} | {c.get('seed')} | {c.get('bpm_param')} | {m.get('tempo_bpm')} | "
                 f"{m.get('clap')} | {m.get('energy_r')} | {m.get('vocal_rel_db')} | {m.get('p_vocal')} | {m.get('longest_gap_s')} | "
                 f"{m.get('lufs_raw')} | {mark} | {'；'.join(c.get('flags') or [])} |")
    L += [""]
    for r in st.get("rounds") or []:
        L.append(f"- 第 {r['round']} 轮决定：{r.get('decision')}")
    if ch:
        L += [f"- 选中 **{ch.get('id')}**（{ch.get('by')}）：{ch.get('reason')}",
              f"- 文件：`{ch.get('wav')}`、`{od.relative_to(ROOT).as_posix()}/ep{ep:02d}.json`、`{od.relative_to(ROOT).as_posix()}/ep{ep:02d}/meta.json`"]
    if st.get("needs_owner_listen"):
        L.append("- 🟡 审听模型 3 轮都没选，按度量兜底，请项目方试听")
    L.append("")
    return L


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eps", default="1-10")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    od = out_dir(load_cfg())
    md = ["# 整集配乐结果（tools/bgm/report.py 从 meta.json 生成）", ""]
    for ep in parse_eps(a.eps):
        md += ep_md(ep, od)
    txt = "\n".join(md)
    if a.out:
        p = ROOT / a.out
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
        print(p)
    else:
        print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
