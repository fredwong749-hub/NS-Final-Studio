"""
T04：笔记本导入器（ns_agent.importer.script_md）与 gpu3 渲染器解析器（scripts/weita_render.py parse_script）逐镜对比。

    .venv\\Scripts\\python.exe tools\\parser_diff.py <script.md> [<script.md> ...] [--gpu3 weita_render.py] [--json] [--limit N]

- gpu3 解析器：默认用 scp 只读拷一份 gpu33:/root/claude-kimi-ns-studio-v1/ns-studio/scripts/weita_render.py 到临时目录，
  只执行到 `def load_script` 之前的解析部分（纯标准库），不在 gpu3 上运行或修改任何东西；也可用 --gpu3 指定本地副本。
- 对比字段（每镜）：镜号集合、时长(+来源)、img/motion 触发词与正文、sound 正文段、【H3 audio】、【亲密声】、【配乐】、
  对白 (说话人, 台词)、🎙 独白、**H3提示词** 全文；每集：本集 BGM（【BGM】）。
- 只做结构对比，不读、不评价剧情内容；输出里截断文本只用于定位。

退出码：0 = 无差异；1 = 有差异；2 = 解析失败。
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "packages" / "schema", ROOT / "services" / "agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ns_agent.importer.script_md import import_script  # noqa: E402

GPU3_HOST = "gpu33"
GPU3_PARSER = "/root/claude-kimi-ns-studio-v1/ns-studio/scripts/weita_render.py"
SOUND_SPLIT_RE = re.compile(r"【(?:H3 audio|H3音频|亲密声|配乐)】")
SHOT_FIELDS = ("duration", "img_triggers", "img", "motion_triggers", "motion", "sound", "sound_h3",
               "sound_intimate", "music_cue", "dialogue", "voiceover", "h3")


# ------------------------------------------------------------------ gpu3 解析器

def fetch_gpu3_parser(dest_dir: Path) -> Path:
    """只读拷贝（scp），不在 gpu3 上执行任何命令"""
    dest = dest_dir / "weita_render.py"
    subprocess.run(["scp", "-o", "BatchMode=yes", "-q", f"{GPU3_HOST}:{GPU3_PARSER}", str(dest)], check=True)
    return dest


def load_gpu3_parser(path: Path) -> types.ModuleType:
    """只执行 weita_render.py 的解析部分（文件头到 load_script 之前：纯标准库，无 GPU/网络副作用）"""
    src = Path(path).read_text(encoding="utf-8")
    cut = src.find("\ndef load_script(")
    if cut < 0:
        raise RuntimeError(f"{path} 里找不到 load_script，gpu3 解析器结构变了")
    mod = types.ModuleType("weita_parser_copy")
    mod.__file__ = str(path)
    sys.modules[mod.__name__] = mod
    exec(compile(src[:cut], str(path), "exec"), mod.__dict__)  # noqa: S102 — 只读副本的解析部分
    return mod


# ------------------------------------------------------------------ 统一成可比结构

def _sound_plain(sound: str) -> str:
    return SOUND_SPLIT_RE.split(sound or "", maxsplit=1)[0].strip(" ；;，,")


def _strip_triggers(text: str, triggers: list[str]) -> str:
    """去掉开头已识别的触发词（两边都把触发词单独存放，正文对比时不算）"""
    s = text or ""
    for t in triggers:
        s = re.sub(rf"^\s*{re.escape(t)}\s*[，,]\s*", "", s, count=1)
    return s


def laptop_view(path: Path) -> dict:
    imp = import_script(Path(path))
    eps = {}
    for ep in imp.episodes:
        shots = {}
        for s in ep.shots:
            shots[s.index] = {
                "duration": (s.duration, s.duration_source),
                "img_triggers": list(s.img_triggers),
                "img": _strip_triggers(s.img_prompt, s.img_triggers),
                "motion_triggers": list(s.motion_triggers),
                "motion": _strip_triggers(s.motion_prompt, s.motion_triggers),
                "sound": _sound_plain(s.sound),
                "sound_h3": s.sound_h3,
                "sound_intimate": s.sound_intimate,
                "music_cue": s.music_cue,
                "dialogue": [(d.speaker_note or "", d.text) for d in s.dialogue],
                "voiceover": [(s.voiceover.note or "", s.voiceover.text)] if s.voiceover else [],
                "h3": s.h3_prompt or "",
            }
        eps[ep.number] = {"bgm": ep.music_bgm, "shots": shots}
    return eps


def gpu3_view(path: Path, w: types.ModuleType) -> dict:
    sc = w.parse_script(Path(path).read_text(encoding="utf-8"))
    eps = {}
    for ep in sc.episodes:
        shots = {}
        for s in ep.shots:
            shots[s.number] = {
                "duration": (s.duration, s.duration_source),
                "img_triggers": list(s.img_triggers),
                "img": s.img,
                "motion_triggers": list(s.motion_triggers),
                "motion": s.motion,
                "sound": s.sound,
                "sound_h3": s.sound_h3,
                "sound_intimate": s.sound_intimate,
                "music_cue": s.music_cue,
                "dialogue": [(u.note, u.line) for u in s.dialogue],
                "voiceover": [tuple(v) for v in s.voiceover],
                "h3": s.h3_field or "",
            }
        # weita 的 Episode 没有 BGM 字段（gpu3 运行时从共享导入器取 music_bgm）；没有就记 None
        eps[ep.number] = {"bgm": getattr(ep, "music_bgm", None), "shots": shots}
    return eps


# ------------------------------------------------------------------ 对比

def diff_views(lap: dict, gpu: dict) -> list[dict]:
    out = []
    for n in sorted(set(lap) | set(gpu)):
        if n not in lap or n not in gpu:
            out.append({"id": f"ep{n:02d}", "field": "episode", "laptop": n in lap, "gpu3": n in gpu})
            continue
        le, ge = lap[n], gpu[n]
        if ge["bgm"] is None:
            if le["bgm"]:
                out.append({"id": f"ep{n:02d}", "field": "bgm(gpu3 无字段)", "laptop": le["bgm"], "gpu3": None})
        elif le["bgm"] != ge["bgm"]:
            out.append({"id": f"ep{n:02d}", "field": "bgm", "laptop": le["bgm"], "gpu3": ge["bgm"]})
        ls, gs = le["shots"], ge["shots"]
        if sorted(ls) != sorted(gs):
            out.append({"id": f"ep{n:02d}", "field": "shot_ids", "laptop": sorted(ls), "gpu3": sorted(gs)})
        for k in sorted(set(ls) & set(gs)):
            for f in SHOT_FIELDS:
                if ls[k][f] != gs[k][f]:
                    out.append({"id": f"ep{n:02d}s{k}", "field": f, "laptop": ls[k][f], "gpu3": gs[k][f]})
    return out


def compare(path: Path, w: types.ModuleType) -> dict:
    diffs = diff_views(laptop_view(path), gpu3_view(path, w))
    return {"script": str(path), "count": len(diffs),
            "by_field": dict(collections.Counter(d["field"] for d in diffs)), "diffs": diffs}


def _short(v, n=90) -> str:
    s = repr(v)
    return s if len(s) <= n else s[:n] + "…"


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("scripts", nargs="+", type=Path)
    ap.add_argument("--gpu3", type=Path, help="weita_render.py 本地副本（默认 scp 只读拷贝）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=40, help="每份剧本最多列出几条差异（0 = 全部）")
    args = ap.parse_args(argv)
    try:
        if args.gpu3:
            w = load_gpu3_parser(args.gpu3)
        else:
            with tempfile.TemporaryDirectory() as d:
                w = load_gpu3_parser(fetch_gpu3_parser(Path(d)))
        reports = [compare(p, w) for p in args.scripts]
    except Exception as e:  # noqa: BLE001
        print(f"解析失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=1, default=list))
    else:
        for r in reports:
            print(f"== {r['script']}：差异 {r['count']} 条 {r['by_field']}")
            for d in r["diffs"][: args.limit or None]:
                print(f"  {d['id']} {d['field']}: laptop={_short(d['laptop'])} | gpu3={_short(d['gpu3'])}")
    return 1 if any(r["count"] for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
