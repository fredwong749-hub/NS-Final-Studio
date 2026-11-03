"""MIGRATE-O 11-03（PLAN_V2_MASTER v4 阶段一 1-1 / L-141）：H3 镜内 At 时间码 → 自然英文时间顺序的确定性迁移器。

L-141：`At MM:SS.mmm` 只用于切镜（`[Shot N] At 00:03.500, the camera cuts to …`）；镜内分拍写
“In the first two seconds, … Then, around the third second, … as the shot ends”。旧稿镜内还在用 At，补丁环让 LLM 每轮改 14 行收敛不了
（第 1 集补 10 轮还剩 4 镜）。本模块只做格式迁移，不调 LLM：

  * 读每一镜的 **分拍** 和 H3 integrated_multimodal_description 行；
  * 镜内 At（`At 00:SS.mmm,` / `At the N-second mark,`）按 **分拍** 第 2… 拍起点改写成 `Then, around the <序数> second,`
    （序数 = 该拍起点所在的第几秒，与 ns_recipes.lint._ord_word 同一规则，必要时顺延保证严格递增）；
  * 第一拍补 / 校正 `In the first <N> seconds,`（N = **分拍** 第一拍止）；最后一拍缺 `as the shot ends` 时补上；
  * 切镜 `[Shot N] At …,` 原样保留，并检查严格递增；
  * 拍数对不上 **分拍**（镜内标记数 ≠ 分拍数 − 1）、切镜不递增 → 这一镜不动，记为 needs_llm（交补丁环）；
  * 迁移后自检：台词 <d>…</d> 逐字不变、去掉时间标记后正文逐字不变（标记后首字母大小写除外）、H3 行以外一个字节不变、
    lint RL-T8 / RL-T9 为 0；任何一条不满足 → 这一镜回退为原文。

接入（autoflow_agent）：writer_out 的 P4 整集稿（chain_step / intake_full_p4，含 L-150 整集返修稿）和补丁环成稿（post_step）
在校验前先过 apply_file：有镜内 At 才动；原稿先复制进 data/_quarantine/l141_migrate_<日期>/<run>/，审计写 <run>/l141_migrate.jsonl。

命令行（dry-run 默认，不写文件）：
  python tools/script_rsi/l141_migrate.py <P4.md> [--write --run-dir <run>]
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/recipes", "packages/schema"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from ns_recipes import lint as L  # noqa: E402
from ns_recipes.spec_import import parse_beats  # noqa: E402

SHOT_SPLIT = re.compile(r"(?=^\*\*镜\d+｜)", re.M)
SHOT_NO = re.compile(r"^\*\*镜(\d+)｜")
BEATS_LINE = re.compile(r"^\*\*分拍\*\*[：:](.*)$", re.M)
DUR_LINE = re.compile(r"^\*\*时长\*\*[：:]\s*(\d+(?:\.\d+)?)", re.M)
H3_LINE = re.compile(r"^((?:integrated_multimodal_description|detailed_description):[ \t]*)(.*)$", re.M)
D_RE = re.compile(r"<d>.*?</d>", re.S)
ANCHOR_END = re.compile(r"established by Picture 1\b[^.!?]*[.!?]\s+")
SENT_END = re.compile(r"[.!?]\s+")
LOWER_OK = {"The", "His", "Her", "She", "He", "Their", "They", "Both", "A", "An", "It", "Its", "Each", "One"}
# 时间标记（自检剥离用）：切镜 At / 镜内 At / At the N-second mark / 自然语言分拍 / In the first … / as the shot ends
MARK_RE = re.compile("|".join(f"(?:{p})" for p in (
    r"\bAt \d{1,2}:\d{2}(?:\.\d{1,3})?,\s*", L.STAMP_NL_RE.pattern, L.NL_BEAT_RE.pattern, L.NL_FIRST_RE.pattern,
    r"\s*\bas the shot ends\b")))
AUDIT = "l141_migrate.jsonl"


def _num_word(x: float) -> str:
    if abs(x - round(x)) < 1e-6:
        w = next((w for w, i in L.NUM_WORDS.items() if i == round(x)), None)
        if w:
            return w
        return str(int(round(x)))
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _ord_word(k: int) -> str:
    return next((w for w, i in L.ORDINALS.items() if i == k), f"{k}th")


def _mask(s: str) -> str:
    """台词 <d>…</d> 换成等长占位（位置不变，正则不会命中台词里的字）"""
    return D_RE.sub(lambda m: "\x01" * len(m.group(0)), s)


def in_shot_marks(body: str) -> list[tuple[int, int, str]]:
    """镜内拍界标记（不在 [Shot N] 后面的 At、At the N-second mark、已有的自然语言分拍）→ [(start, end, kind)]"""
    mb = _mask(body)
    cut_pos = {m.start(2) - 3 for m in L.CUT_RE.finditer(mb)}
    out = [(m.start(), m.end(), "at") for m in L.STAMP_RE.finditer(mb) if m.start() not in cut_pos]
    out += [(m.start(), m.end(), "at") for m in L.STAMP_NL_RE.finditer(mb)]
    out += [(m.start(), m.end(), "nl") for m in L.NL_BEAT_RE.finditer(mb)]
    return sorted(out)


def has_in_shot_at(text: str) -> bool:
    return any(L.in_shot_timecodes(_mask(h.group(2))) for h in H3_LINE.finditer(text or ""))


def strip_marks(s: str) -> str:
    """去掉所有时间标记，标记后第一个字母小写，空白归一：迁移前后这个值必须逐字相等（内容一个字不改）"""
    s = MARK_RE.sub("\x00", s)
    s = re.sub(r"\x00\s*([A-Za-z])", lambda m: m.group(1).lower(), s)
    # 句首（锚点句后插 In the first … 时 The → the）：只放过句首字母的大小写
    s = re.sub(r"([.!?]\s+)([A-Za-z])", lambda m: m.group(1) + m.group(2).lower(), s)
    return re.sub(r"\s+", " ", s.replace("\x00", " ")).strip()


def lint_codes(body: str, beats, duration: float) -> list[dict]:
    """RL-T8 / RL-T9（ns_recipes.lint.timeline_alignment 原样，spec 只给 **分拍** 和镜长）"""
    sp = SimpleNamespace(motion=SimpleNamespace(beats=beats), duration_s=duration)
    return [i for i in L.timeline_alignment("integrated_multimodal_description: " + body, sp, strict=True)
            if i["code"] in ("RL-T8", "RL-T9") and i["level"] == "error"]


def migrate_body(body: str, beats) -> tuple[str | None, str]:
    """一镜 H3 正文 → (新正文, 说明)；不能确定性迁移 → (None, 原因)"""
    beats = sorted(beats, key=lambda b: b.t0)
    if not beats:
        return None, "剧本没有 **分拍**"
    mb = _mask(body)
    cuts = [int(m.group(2)) * 60 + float(m.group(3)) for m in L.CUT_RE.finditer(mb)]
    if any(b <= a for a, b in zip(cuts, cuts[1:])) or (cuts and cuts[0] <= 0):
        return None, f"切镜 At 不是严格递增：{cuts}"
    if any(int(m.group(1)) >= 2 for m in L.NEXT_CUT_RE.finditer(mb)):
        return None, "有 [Shot N≥2] 切镜没写 At 时间码"
    marks = in_shot_marks(body)
    if len(marks) != len(beats) - 1:
        return None, f"拍数对不上：H3 镜内 {len(marks) + 1} 拍，**分拍** {len(beats)} 拍"
    # 序数：⌊t0⌋+1（lint 同一规则），不递增时顺延；顺延后偏差 > NL_TOL_S 就不迁
    ords, prev = [], 0
    for b in beats[1:]:
        k = max(int(b.t0) + 1, prev + 1)
        if abs((k - 1) - b.t0) > L.NL_TOL_S + 1e-6:
            return None, f"分拍起点 {b.t0:g}s 排不出严格递增的序数"
        ords.append(k)
        prev = k
    out, pos = [], 0
    for (s, e, _kind), k in zip(marks, ords):
        before = body[:s].rstrip()
        lead = "Then" if (not before or before[-1] in ".!?\"”\x01>" or before.endswith("</d>")) else "then"
        out += [body[pos:s], f"{lead}, around the {_ord_word(k)} second, "]
        pos = e
    out.append(body[pos:])
    new = "".join(out)
    # 第一拍：In the first N seconds,
    mnew = _mask(new)
    fm = L.NL_FIRST_RE.search(mnew)
    first_mark = next(iter(m.start() for m in L.NL_BEAT_RE.finditer(mnew)), len(new))
    want_n = _num_word(beats[0].t1)
    if fm and fm.start() < first_mark:
        g = fm.group(1).lower()
        n = L.NUM_WORDS.get(g) or float(g)
        if abs(n - beats[0].t1) > L.NL_TOL_S + 1e-6:
            new = new[:fm.start(1)] + want_n + new[fm.end(1):]
    else:
        am = ANCHOR_END.search(mnew) or SENT_END.search(mnew)
        if not am or am.end() > first_mark:
            return None, "找不到锚点句结尾，没法放 In the first … seconds"
        i = am.end()
        nxt = re.match(r"([A-Z][a-z]*)\b", new[i:])
        rest = new[i:]
        if nxt and nxt.group(1) in LOWER_OK:
            rest = rest[0].lower() + rest[1:]
        new = new[:i] + f"In the first {want_n} seconds, " + rest
    # 最后一拍：… as the shot ends
    mnew = _mask(new)
    lm = list(L.NL_BEAT_RE.finditer(mnew))
    tail_at = lm[-1].end() if lm else 0
    if "as the shot ends" not in new[tail_at:].replace("\x01", " "):
        p2 = L.P2_SENT_RE.search(mnew.rstrip())
        stop = p2.start() if p2 else len(mnew.rstrip())
        ends = [m.start() for m in re.finditer(r"[.!?]", mnew[:stop]) if m.start() >= tail_at]
        if not ends:
            return None, "最后一拍找不到句末，没法补 as the shot ends"
        j = ends[-1]
        new = new[:j] + " as the shot ends" + new[j:]
    return new, f"镜内 {sum(1 for x in marks if x[2] == 'at')} 处 At → 自然语言（{len(beats)} 拍）"


def verify(old_body: str, new_body: str) -> str:
    """内容不变检查：台词逐字、去时间标记后正文逐字；不过 → 原因"""
    if D_RE.findall(old_body) != D_RE.findall(new_body):
        return "台词 <d>…</d> 变了"
    if strip_marks(old_body) != strip_marks(new_body):
        return "去掉时间标记后正文不一致"
    return ""


def migrate_text(text: str) -> tuple[str, list[dict]]:
    """整集 P4 文本 → (新文本, 逐镜记录)。只改有镜内 At 的镜头的 H3 行；其余一个字节不动"""
    parts = SHOT_SPLIT.split(text)
    recs = []
    for idx, blk in enumerate(parts):
        mno = SHOT_NO.match(blk)
        h = H3_LINE.search(blk)
        if not mno or not h:
            continue
        shot = int(mno.group(1))
        body = h.group(2)
        bad = L.in_shot_timecodes(_mask(body))
        if not bad:
            continue
        bm = BEATS_LINE.search(blk)
        beats = parse_beats(bm.group(1)) if bm else []
        dm = DUR_LINE.search(blk)
        dur = float(dm.group(1)) if dm else (beats[-1].t1 if beats else 0.0)
        before = [f"{i['code']} {i['message'][:80]}" for i in lint_codes(body, beats, dur)]
        rec = {"shot": shot, "at": len(bad), "beats": len(beats), "lint_before": before}
        new, why = migrate_body(body, beats)
        if new is not None:
            why2 = verify(body, new)
            after = [f"{i['code']} {i['message'][:80]}" for i in lint_codes(new, beats, dur)]
            if not why2 and after:
                why2 = "迁移后 RL-T8 / RL-T9 仍不为 0：" + "；".join(after)
            if why2:
                new, why = None, why2
        if new is None:
            rec.update(status="needs_llm", why=why, lint_after=before)
        else:
            rec.update(status="migrated", why=why, lint_after=[])
            blk = blk[:h.start(2)] + new + blk[h.end(2):]
            parts[idx] = blk
        recs.append(rec)
    return "".join(parts), recs


def apply_file(path: Path, run_dir: Path | None = None, *, by: str = "l141_migrate", write: bool = True,
               quarantine_root: Path | None = None) -> dict | None:
    """有镜内 At → 迁移；write=True 时原稿先复制进隔离区，再原地写新稿，追加审计。没有镜内 At → None（幂等）"""
    path = Path(path)
    old = path.read_text(encoding="utf-8")
    if not has_in_shot_at(old):
        return None
    new, recs = migrate_text(old)
    res = {"file": str(path), "by": by, "at": time.strftime("%F %T"), "changed": new != old,
           "migrated": [r["shot"] for r in recs if r["status"] == "migrated"],
           "needs_llm": [r["shot"] for r in recs if r["status"] == "needs_llm"], "shots": recs}
    if not write or new == old:
        return res
    run_dir = Path(run_dir) if run_dir else path.parent
    import os
    qroot = quarantine_root or Path(os.environ.get("NSFS_L141_QUARANTINE") or ROOT / "data" / "_quarantine")   # 测试指到 tmp
    qd = qroot / f"l141_migrate_{time.strftime('%Y%m%d')}" / run_dir.name
    qd.mkdir(parents=True, exist_ok=True)
    bak = qd / f"{path.name}.{time.strftime('%H%M%S')}.orig"
    n = 1
    while bak.exists():
        bak, n = qd / f"{path.name}.{time.strftime('%H%M%S')}_{n}.orig", n + 1
    bak.write_text(old, encoding="utf-8", newline="")
    if bak.read_text(encoding="utf-8") != old:          # 备份没落盘就不改原稿
        raise OSError(f"备份校验失败：{bak}")
    path.write_text(new, encoding="utf-8", newline="")
    res["backup"] = str(bak)
    with (run_dir / AUDIT).open("a", encoding="utf-8") as f:
        f.write(json.dumps({k: v for k, v in res.items()}, ensure_ascii=False) + "\n")
    return res


def summary(res: dict | None) -> str:
    if not res:
        return "无镜内 At"
    return (f"L-141 迁移：镜 {res['migrated'] or '无'} 已迁"
            + (f"；镜 {res['needs_llm']} 拍数 / 切镜对不上，交补丁环" if res["needs_llm"] else ""))


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--run-dir")
    a = ap.parse_args(argv)
    res = apply_file(Path(a.file), Path(a.run_dir) if a.run_dir else None, write=a.write, by="cli")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1) if res else "无镜内 At，不用迁移")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
