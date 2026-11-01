"""nsfs.bgm_brief/1 校验器（链接 P4-BGM，规则 BGM-B01…B14）。只查格式与可实现性，不评价内容。

    .venv/Scripts/python.exe tools/bgm/brief_schema.py <brief.json> [--run data/pipeline/runs/series10_v1]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bgm_timeline import voiced_spans  # noqa: E402

SCHEMA = "nsfs.bgm_brief/1"
SECTION_NAMES = ("intro", "build", "main", "turn", "peak", "breakdown", "outro")
ACE_TAG = {"intro": "[Intro]", "build": "[Build]", "main": "[Verse]", "turn": "[Bridge]", "peak": "[Chorus]",
           "breakdown": "[Breakdown]", "outro": "[Outro]"}
# 写作模型给的风格词里不许出现具名作品 / 艺人：只允许这些大写词（调名、缩写）
CAP_OK = {"A", "B", "C", "D", "E", "F", "G", "BPM", "Major", "Minor", "major", "minor", "Lo-fi", "R&B", "EDM", "IDM",
          "Rhodes", "Wurlitzer", "Moog", "Mellotron", "Hammond", "Fender", "Juno", "Prophet", "TR-808", "808", "909",
          "Am", "Bm", "Cm", "Dm", "Em", "Fm", "Gm"}
# “by + 大写词”只在大小写敏感时算（“led by solo bass” 不算）；featuring 是常见乐器描述用词，不算
NAMED_RE = re.compile(r"(?i:\bin the style of\b|\bstyle of\b|\bfeat\.\s|-esque\b|\bsoundtrack (?:of|from)\b|\bcover of\b)|"
                      r"\bby [A-Z]|[\"“”「」《》]|\bOST\b")
RULES = {
    "BGM-B01": "只输出一个 JSON 对象，schema = nsfs.bgm_brief/1，episode = 本集集号",
    "BGM-B02": "duration_s = 输入时间轴总长（±1 秒）",
    "BGM-B03": "bpm.min ≤ bpm.target ≤ bpm.max，范围 40–180，max − min ≤ 30",
    "BGM-B04": "mood_arc ≥ 2 段，按时间连续覆盖 0 → duration_s，每段写 mood（英文短语）",
    "BGM-B05": "sections 2–6 段，name 只用 intro/build/main/turn/peak/breakdown/outro，首尾相接覆盖 0 → duration_s",
    "BGM-B06": "energy_curve ≥ 4 个 [秒, 0–1] 点，时间递增，首点 ≤ 1 秒、末点 ≥ duration_s − 2",
    "BGM-B07": "duck 每段 t0 < t1 在时长内，depth_db 10–14；有人声的镜头区间至少 80% 被 duck 覆盖",
    "BGM-B08": "instrumentation 2–6 件乐器（英文）；不写人声类（vocal / choir / singer / humming / rap）",
    "BGM-B09": "style_words 2–8 个英文风格词；caption_en 与 style_words 不写具名歌曲 / 艺人 / 影视作品（不用引号、by、style of、-esque）",
    "BGM-B10": "caption_en 英文 40–450 字符，不写人声、歌词",
    "BGM-B11": "negative ≥ 4 项（英文），必须含 vocals",
    "BGM-B12": "cue_change.has 为 true 时 at_s 在时长内，且有一段 sections 在该时刻 ±2 秒开始",
    "BGM-B13": "clap_text 英文 10–200 字符（给音频-文本打分用的一句话描述）",
    "BGM-B14": "整集一条 BGM：loopable 为布尔；不得出现逐镜曲目（tracks / per_shot 字段）",
}
VOCAL_RE = re.compile(r"\b(vocal|vocals|voice|choir|singer|singing|humming|hum|rap|lyrics?|chant)\b", re.I)


def _issue(rule: str, msg: str) -> dict:
    return {"rule": rule, "level": "block", "msg": msg, "writer_text": RULES[rule]}


def _ascii_en(s: str) -> bool:
    return bool(s) and sum(ord(c) < 128 for c in s) / len(s) > 0.95


def _named(s: str) -> list[str]:
    bad = []
    if NAMED_RE.search(s or ""):
        bad.append(NAMED_RE.search(s).group(0))
    for w in re.findall(r"\b[A-Z][a-zA-Z0-9&\-]+\b", s or ""):
        if w not in CAP_OK and not re.fullmatch(r"[A-G](?:#|b)?m?", w):
            # 句首大写允许：只查句中（前一个字符不是句号 / 开头）
            bad.append(w)
    return bad


def _sentence_case_ok(s: str) -> list[str]:
    """caption 句首的大写词不算具名"""
    out = []
    for sent in re.split(r"(?<=[.;!?])\s+|^", s or ""):
        words = sent.strip().split(" ", 1)
        rest = words[1] if len(words) > 1 else ""
        out += _named(rest)
    return out


def _covers(segs: list[tuple[float, float]], dur: float, tol: float = 1.0) -> bool:
    if not segs:
        return False
    segs = sorted(segs)
    if segs[0][0] > tol or segs[-1][1] < dur - tol:
        return False
    return all(abs(segs[k + 1][0] - segs[k][1]) <= tol for k in range(len(segs) - 1))


def check_brief(brief, timeline: dict | None = None, episode: int | None = None) -> list[dict]:
    iss: list[dict] = []
    if isinstance(brief, str):
        try:
            brief = json.loads(brief)
        except ValueError as e:
            return [_issue("BGM-B01", f"不是 JSON：{e}")]
    if not isinstance(brief, dict):
        return [_issue("BGM-B01", "顶层不是 JSON 对象")]
    if brief.get("schema") != SCHEMA:
        iss.append(_issue("BGM-B01", f"schema 应为 {SCHEMA}"))
    if episode is not None and brief.get("episode") != episode:
        iss.append(_issue("BGM-B01", f"episode 应为 {episode}"))
    try:
        dur = float(brief.get("duration_s"))
    except (TypeError, ValueError):
        return iss + [_issue("BGM-B02", "duration_s 缺失或不是数字")]
    if timeline and abs(dur - float(timeline["duration_s"])) > 1.0:
        iss.append(_issue("BGM-B02", f"duration_s={dur} 与时间轴 {timeline['duration_s']} 不符"))
    b = brief.get("bpm") or {}
    try:
        lo, tg, hi = float(b["min"]), float(b["target"]), float(b["max"])
        if not (40 <= lo <= tg <= hi <= 180) or hi - lo > 30:
            iss.append(_issue("BGM-B03", f"bpm {lo}/{tg}/{hi} 不合规"))
    except (KeyError, TypeError, ValueError):
        iss.append(_issue("BGM-B03", "bpm 需要 min / target / max 数字"))
    ma = brief.get("mood_arc") or []
    try:
        segs = [(float(x["t0"]), float(x["t1"])) for x in ma]
        if len(ma) < 2 or not _covers(segs, dur) or any(not str(x.get("mood") or "").strip() for x in ma):
            iss.append(_issue("BGM-B04", "mood_arc 段数 / 覆盖 / mood 不合规"))
    except (KeyError, TypeError, ValueError):
        iss.append(_issue("BGM-B04", "mood_arc 每段要有 t0 / t1 / mood"))
    secs = brief.get("sections") or []
    try:
        segs = [(float(x["t0"]), float(x["t1"])) for x in secs]
        names_ok = all(x.get("name") in SECTION_NAMES for x in secs)
        if not (2 <= len(secs) <= 6) or not names_ok or not _covers(segs, dur):
            iss.append(_issue("BGM-B05", f"sections 数量 / 名称 / 覆盖不合规（names={[x.get('name') for x in secs]}）"))
    except (KeyError, TypeError, ValueError):
        iss.append(_issue("BGM-B05", "sections 每段要有 name / t0 / t1"))
        segs = []
    ec = brief.get("energy_curve") or []
    try:
        pts = [(float(t), float(v)) for t, v in ec]
        if len(pts) < 4 or any(pts[k + 1][0] <= pts[k][0] for k in range(len(pts) - 1)) or pts[0][0] > 1 \
                or pts[-1][0] < dur - 2 or any(not 0 <= v <= 1 for _, v in pts):
            iss.append(_issue("BGM-B06", "energy_curve 点数 / 递增 / 覆盖 / 取值不合规"))
    except (TypeError, ValueError):
        iss.append(_issue("BGM-B06", "energy_curve 要是 [[秒, 0–1], …]"))
    duck = brief.get("duck") or []
    try:
        dk = [(float(x["t0"]), float(x["t1"]), float(x.get("depth_db", 12))) for x in duck]
        if any(not (0 <= a < b <= dur + 0.5) or not 10 <= abs(d) <= 14 for a, b, d in dk):
            iss.append(_issue("BGM-B07", "duck 区间或深度不合规"))
    except (KeyError, TypeError, ValueError):
        iss.append(_issue("BGM-B07", "duck 每段要有 t0 / t1 / depth_db"))
        dk = []
    if timeline and duck:
        need = voiced_spans(timeline)
        tot = sum(b - a for a, b in need)
        cov = 0.0
        for a, b in need:
            for c, d, _ in dk:
                cov += max(0.0, min(b, d) - max(a, c))
        if tot > 0 and cov / tot < 0.8:
            iss.append(_issue("BGM-B07", f"有人声的镜头只覆盖了 {cov / tot:.0%}（要 ≥80%）"))
    elif timeline and not duck:
        from_tl = [s for s in timeline["shots"] if s["voice"]]
        if from_tl:
            iss.append(_issue("BGM-B07", "有人声镜头但 duck 为空"))
    inst = brief.get("instrumentation") or []
    if not (2 <= len(inst) <= 6) or any(not _ascii_en(str(x)) or VOCAL_RE.search(str(x)) for x in inst):
        iss.append(_issue("BGM-B08", f"instrumentation 不合规：{inst}"))
    sw = brief.get("style_words") or []
    named = [w for x in sw for w in _named(str(x))] + _sentence_case_ok(str(brief.get("caption_en") or ""))
    if not (2 <= len(sw) <= 8) or any(not _ascii_en(str(x)) for x in sw) or named:
        iss.append(_issue("BGM-B09", f"style_words / caption 不合规（疑似具名：{sorted(set(named))[:6]}）"))
    cap = str(brief.get("caption_en") or "")
    if not (40 <= len(cap) <= 450) or not _ascii_en(cap) or re.search(r"\b(vocals?|singing|singer|choir|lyrics)\b(?! *-?free)", cap, re.I) \
            and not re.search(r"\bno (?:vocals?|singing|choir|lyrics)|without (?:vocals?|singing)|instrumental", cap, re.I):
        iss.append(_issue("BGM-B10", "caption_en 长度 / 英文 / 人声词不合规"))
    neg = [str(x).lower() for x in brief.get("negative") or []]
    if len(neg) < 4 or not any("vocal" in x for x in neg) or any(not _ascii_en(x) for x in neg):
        iss.append(_issue("BGM-B11", f"negative 不合规：{neg}"))
    cc = brief.get("cue_change") or {}
    if not isinstance(cc, dict) or not isinstance(cc.get("has"), bool):
        iss.append(_issue("BGM-B12", "cue_change 要是 {has: 布尔, at_s, why}"))
    elif cc["has"]:
        try:
            at = float(cc["at_s"])
            if not 0 < at < dur or not any(abs(a - at) <= 2 for a, _ in segs):
                iss.append(_issue("BGM-B12", f"cue_change.at_s={at} 没有对应的段落起点"))
        except (KeyError, TypeError, ValueError):
            iss.append(_issue("BGM-B12", "cue_change.at_s 缺失"))
    ct = str(brief.get("clap_text") or "")
    if not (10 <= len(ct) <= 200) or not _ascii_en(ct):
        iss.append(_issue("BGM-B13", "clap_text 不合规"))
    if not isinstance(brief.get("loopable"), bool) or any(k in brief for k in ("tracks", "per_shot")):
        iss.append(_issue("BGM-B14", "loopable 要是布尔；不许逐镜曲目"))
    return iss


def lyrics_tags(brief: dict) -> str:
    """sections → ACE-Step 结构标签（纯器乐：每段 [Instrumental]）"""
    out = []
    for s in brief.get("sections") or []:
        out += [ACE_TAG.get(s.get("name"), "[Verse]"), "[Instrumental]"]
    return "\n".join(out)


if __name__ == "__main__":
    import argparse
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    ap = argparse.ArgumentParser()
    ap.add_argument("brief")
    ap.add_argument("--run")
    a = ap.parse_args()
    br = json.loads(Path(a.brief).read_text(encoding="utf-8"))
    tl = None
    if a.run:
        from bgm_timeline import episode_inputs  # noqa: PLC0415
        tl = episode_inputs(Path(a.run), int(br.get("episode")))["timeline"]
    res = check_brief(br, tl, br.get("episode"))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    raise SystemExit(1 if res else 0)

