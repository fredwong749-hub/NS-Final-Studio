"""PROMPT（2026-10-31）：把写作模型按 sysimpl-v2 产出的修订字段（data/ab/prompt_v2/ep02/items.json + voice_revision.json）
合进 ep02 现行底稿（data/import/script_v2.json 记录的 ep02 来源），生成新的 staging 稿，走正规链路 script_inbox /import（merge，只替换 ep02）。

只做机械合并（系统不写内容）：
- 本集人物表 VOICE 列 → 写作模型的 VOICE 修订（W1）
- 每镜 **衔接** 行之后插入 **分拍** / **下镜** 两行（附录 v1 允许的位置）
- 每镜 **H3提示词** 代码块 → 写作模型 v2 版本（台词逐字已由 llm_output_check 校验）
其余行（img、motion、sound、对白、🎙、配乐 cue…）一字不动。
用法：.venv/Scripts/python.exe tools/prompt_v2/build_staging_ep02.py [底稿路径] → data/staging_v3/为他而骚_ep02_补全候选_PROMPTv2_20261031.md
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_DEFAULT = ROOT / "data" / "staging_v3" / "为他而骚_ep02_补全候选_PREP_20261031 v3.md"
DST = ROOT / "data" / "staging_v3" / "为他而骚_ep02_补全候选_PROMPTv2_20261031.md"
V2 = ROOT / "data" / "ab" / "prompt_v2" / "ep02"


def build(src: Path) -> str:
    items = json.loads((V2 / "items.json").read_text(encoding="utf-8"))
    voice = json.loads((V2 / "voice_revision.json").read_text(encoding="utf-8"))
    lines = src.read_text(encoding="utf-8").splitlines()
    out, shot, in_ep, i = [], None, False, 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## ep"):
            in_ep = ln.startswith("## ep02")
        m = re.match(r"^\*\*镜(\d+)｜img", ln)
        if in_ep and m:
            shot = f"ep02-S{m.group(1)}"
        tm = re.match(r"^\| (林晚|顾沉|陈宇) \|", ln)
        if in_ep and tm and tm.group(1) in voice:
            cells = ln.split("|")
            cells[-2] = f" {voice[tm.group(1)]} "
            ln = "|".join(cells)
        if in_ep and shot and ln.startswith("**分拍**") or (in_ep and shot and ln.startswith("**下镜**")):
            i += 1
            continue   # 旧的分拍 / 下镜行由新版替换
        out.append(ln)
        if in_ep and shot and ln.startswith("**衔接**") and items.get(shot):
            out.append(f"**分拍**：{items[shot]['beats']}")
            out.append(f"**下镜**：{items[shot]['to_next']}")
        if in_ep and shot and ln.startswith("**H3提示词**") and items.get(shot):
            j = i + 1
            assert lines[j].startswith("```"), (shot, lines[j])
            k = j + 1
            while not lines[k].startswith("```"):
                k += 1
            out.append(lines[j])
            out += items[shot]["h3"].splitlines()
            out.append(lines[k])
            i = k + 1
            continue
        i += 1
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC_DEFAULT
    DST.write_text(build(src), encoding="utf-8")
    print(DST)
