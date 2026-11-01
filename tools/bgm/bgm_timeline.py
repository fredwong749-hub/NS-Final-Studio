"""P4 剧本分镜 → 整集时间轴（确定性解析，不判断内容）。

每镜：起点、时长（**时长**：N秒）、有没有人声（**对白** / **🎙**）、本镜【配乐】cue 原文；本集 **配乐** 行原文与【BGM】英文。
人声区间按“整镜”计（P4 没有逐句时间）；合成时 assemble 再按逐句 placement 精确压低。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SHOT_RE = re.compile(r"^\*\*镜(\d+)｜", re.M)
DUR_RE = re.compile(r"^\*\*时长\*\*：\s*(\d+(?:\.\d+)?)\s*秒", re.M)
VOICE_RE = re.compile(r"^\*\*(对白|🎙)", re.M)
CUE_RE = re.compile(r"【配乐】([^【\n]*)")
MUSIC_LINE_RE = re.compile(r"^\*\*配乐\*\*：(.*)$", re.M)
BGM_RE = re.compile(r"【BGM】(.*)$")
TITLE_RE = re.compile(r"^## ep(\d+)《(.*?)》", re.M)


def parse_p4(text: str) -> dict:
    m = TITLE_RE.search(text)
    head_end = SHOT_RE.search(text)
    head = text[: head_end.start()] if head_end else text
    ml = MUSIC_LINE_RE.search(head)
    music_raw = ml.group(1).strip() if ml else ""
    bm = BGM_RE.search(music_raw)
    starts = [x.start() for x in SHOT_RE.finditer(text)] + [len(text)]
    shots, t = [], 0.0
    for k, mm in enumerate(SHOT_RE.finditer(text)):
        body = text[starts[k]: starts[k + 1]]
        d = DUR_RE.search(body)
        dur = float(d.group(1)) if d else 0.0
        voices = [v.group(1) for v in VOICE_RE.finditer(body)]
        cue = CUE_RE.search(body)
        shots.append({"index": int(mm.group(1)), "start_s": round(t, 3), "dur_s": dur,
                      "voice": bool(voices), "voice_kinds": sorted(set("dialogue" if v == "对白" else "voiceover" for v in voices)),
                      "music_cue": (cue.group(1).strip().rstrip("；;。") if cue else "")})
        t += dur
    return {"episode": int(m.group(1)) if m else None, "title": m.group(2) if m else "",
            "music_raw": music_raw, "bgm_en": bm.group(1).strip() if bm else "",
            "duration_s": round(t, 3), "shots": shots}


def voiced_spans(tl: dict) -> list[tuple[float, float]]:
    """有人声的镜头 → 合并后的 [t0, t1]"""
    out: list[list[float]] = []
    for s in tl["shots"]:
        if not s["voice"]:
            continue
        a, b = s["start_s"], s["start_s"] + s["dur_s"]
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in out]


IMPORT_JSON = Path(__file__).resolve().parents[2] / "data" / "import" / "script_v2.json"


def import_episode_text(ep: int, import_json: Path = IMPORT_JSON) -> tuple[str, str] | None:
    """CLEANUP 11-01（K-OPS-Q24，总调度 r2：P4 旧来源迁到导入稿）：导入稿里这一集的分镜原文。
    取 script_v2.json sources 里最后一个覆盖本集、且文件 sha256 与导入记录一致的来源 md，切出 `## epNN《…》` 到下一集之前。
    格式与 P4 相同（写作链 P4 合并后导入），parse_p4 直接可用。找不到返回 None。"""
    import hashlib
    if not import_json.is_file():
        return None
    root = import_json.resolve().parents[2]
    d = json.loads(import_json.read_text(encoding="utf-8"))
    for src in reversed(d.get("sources") or []):
        if ep not in (src.get("episodes") or []):
            continue
        p = Path(src.get("path") or "")
        p = p if p.is_absolute() else root / p
        if not p.is_file() or (src.get("sha256") and hashlib.sha256(p.read_bytes()).hexdigest() != src["sha256"]):
            continue
        text = p.read_text(encoding="utf-8")
        heads = list(TITLE_RE.finditer(text))
        for i, m in enumerate(heads):
            if int(m.group(1)) == ep:
                end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
                return text[m.start():end].rstrip() + "\n", f"{p.relative_to(root).as_posix() if p.is_relative_to(root) else p}#ep{ep:02d}"
    return None


def episode_inputs(run_dir: Path, ep: int) -> dict:
    """一集的 P3 原文 + 导入稿分镜原文 + 时间轴（brief 的输入）。键名 p4_* 保留（下游 brief 不改）"""
    import os
    d = run_dir / f"ep{ep:02d}"
    p3 = d / f"P3_ep{ep:02d}_screenplay.json"
    got = import_episode_text(ep)
    if got is not None:
        p4_text, p4 = got
    else:
        p4 = d / f"P4_ep{ep:02d}.md"
        if os.environ.get("NS_ALLOW_P4_SOURCE") != "1":
            raise FileNotFoundError(f"导入稿里没有 ep{ep:02d}（data/import/script_v2.json sources）；P4 旧稿默认不读，确需读设 NS_ALLOW_P4_SOURCE=1")
        if not p4.is_file():
            raise FileNotFoundError(p4)
        p4_text = p4.read_text(encoding="utf-8")
    tl = parse_p4(p4_text)
    p3_obj = json.loads(p3.read_text(encoding="utf-8")) if p3.is_file() else {}
    tl["target_duration_s"] = p3_obj.get("target_duration_s")
    return {"episode": ep, "p3_path": str(p3), "p4_path": str(p4), "p3": p3_obj, "p4_text": p4_text, "timeline": tl}


if __name__ == "__main__":
    import sys
    x = episode_inputs(Path(sys.argv[1]), int(sys.argv[2]))
    print(json.dumps(x["timeline"], ensure_ascii=False, indent=1))
