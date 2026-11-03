"""K-WRT-213（K211-F 11-03，REVIEW-B P1-2）：V2 剧每一镜都要标段落——【幻想段】/【现实段】——而且要和 P2 节拍 / P3 场景一致。
ep01 导入稿一镜都没标，三镜幻想段全按缺省现实段出图，fantasy_c 调色和 bolt_push_settle 运镜都没用上。

段落信息的单一来源 = P2 分集大纲 beats[].summary 里的【幻想段】/【现实段】（没标的节拍继承上一拍，开头缺省现实）→ P3 场景 scenes[].beat_ids →
P4 镜头：有台词的镜按 P3 台词原文锚定到场景；没台词的镜在相邻锚点之间按字二元组相似度挑场景（镜序与场景序单调）。全部确定性，不派 LLM。

  infer(text, p2, p3)         → 每镜 {shot, scene_no, segment, how, marked}
  check(text, p2, p3)         → 导入关口阻断：[QW-S1] 漏标；[QW-S2] 标了但和 P2/P3 不一致（台词锚定的镜 block，推断的镜 warn）
  apply_file(path, run_dir)   → 漏标的镜在 **场景** 行细节开头补【X段】（原稿先复制进 data/_quarantine/segment_fix_<日期>/<run>/，审计写 <run>/segment_fix.jsonl）
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = "segment_fix.jsonl"
SEG_RE = re.compile(r"【(幻想|现实)段?】|段落\s*[=：:]\s*(幻想|现实)")
SHOT_HEAD = re.compile(r"^\*\*镜(\d+)｜img\*\*")
SCENE_LINE = re.compile(r"^(\*\*场景\*\*\s*[：:]\s*)(sk_[a-z0-9_]+)?(\s*｜\s*)?(.*)$")
DLG_LINE = re.compile(r"^\*\*(对白|旁白|独白)\*\*")
QUOTE_RE = re.compile(r"[“\"]([^”\"]+)[”\"]")
MARK = {"fantasy": "【幻想段】", "reality": "【现实段】"}
NAME = {"fantasy": "幻想段", "reality": "现实段"}


def seg_of_text(t: str) -> str | None:
    m = SEG_RE.search(t or "")
    if not m:
        return None
    return "fantasy" if "幻想" in m.group(0) else "reality"


def _norm(s: str) -> str:
    return re.sub(r"[\s，。！？；：、“”‘’\"'…—\-·,.!?;:()（）【】\[\]]", "", s or "")


def _bigrams(s: str) -> set[str]:
    s = _norm(s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _sim(a: str, b: str) -> float:
    A, B = _bigrams(a), _bigrams(b)
    return len(A & B) / len(A | B) if A and B else 0.0


# ------------------------------------------------------------------ P2 / P3

def beat_segments(p2: dict) -> dict[str, str]:
    """P2 beats → {beat_id: fantasy|reality}；没标的继承上一拍，开头缺省 reality"""
    out, cur = {}, "reality"
    for b in p2.get("beats") or []:
        s = seg_of_text(b.get("summary") or "")
        if s:
            cur = s
        out[b.get("id")] = cur
    return out


def scene_segments(p2: dict, p3: dict) -> dict[int, str]:
    """P3 scenes → {scene_no: segment}：按 beat_ids 取（多个取第一个），场景自己的行里有标记以标记为准；都没有 → 继承上一场"""
    bs = beat_segments(p2)
    out, cur = {}, "reality"
    for sc in p3.get("scenes") or []:
        own = seg_of_text(" ".join(str(ln.get("text") or "") for ln in sc.get("lines") or []))
        segs = [bs[b] for b in sc.get("beat_ids") or [] if b in bs]
        cur = own or (segs[0] if segs else cur)
        out[int(sc.get("no"))] = cur
    return out


def scene_texts(p3: dict) -> dict[int, tuple[str, list[str]]]:
    """{scene_no: (全部文字, [台词原文])}"""
    out = {}
    for sc in p3.get("scenes") or []:
        lines = sc.get("lines") or []
        out[int(sc.get("no"))] = (" ".join(str(ln.get("text") or "") for ln in lines),
                                  [str(ln.get("text") or "") for ln in lines if ln.get("kind") == "dialogue"])
    return out


# ------------------------------------------------------------------ P4

def shot_blocks(text: str) -> list[dict]:
    """→ [{shot, start, end, lines}]（start / end 为行号区间，end 不含）"""
    lines = text.split("\n")
    heads = [(i, int(m.group(1))) for i, ln in enumerate(lines) for m in [SHOT_HEAD.match(ln)] if m]
    out = []
    for k, (i, n) in enumerate(heads):
        j = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        while j > i + 1 and lines[j - 1].strip() in ("", "---"):
            j -= 1
        out.append({"shot": n, "start": i, "end": j, "lines": lines[i:j]})
    return out


def block_dialogues(block: dict) -> list[str]:
    out = []
    for ln in block["lines"]:
        if DLG_LINE.match(ln):
            out += QUOTE_RE.findall(ln)
    return out


def block_marked(block: dict) -> str | None:
    """这一镜已标的段落（任何字段行里的【幻想段】/【现实段】/ 段落=），H3 代码块里的不算"""
    seg, fence = None, False
    for ln in block["lines"]:
        if ln.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        s = seg_of_text(ln)
        if s:
            seg = seg or s
    return seg


def _anchor(block: dict, texts: dict[int, tuple[str, list[str]]]) -> int | None:
    dl = [_norm(d) for d in block_dialogues(block) if _norm(d)]
    if not dl:
        return None
    for no in sorted(texts):
        cands = [_norm(x) for x in texts[no][1]]
        if all(any(d in c or c in d for c in cands) for d in dl):
            return no
    return None


def infer(text: str, p2: dict, p3: dict) -> list[dict]:
    """每镜 → {shot, scene_no, segment, how, marked}；how = dialogue（台词锚定）/ similar（相邻锚点间按相似度）/ marked（只有标记可用）"""
    segs, texts = scene_segments(p2, p3), scene_texts(p3)
    blocks = shot_blocks(text)
    nos = sorted(texts)
    if not blocks or not nos:
        return [{"shot": b["shot"], "scene_no": None, "segment": None, "how": None, "marked": block_marked(b)} for b in blocks]
    anchors: dict[int, int] = {}
    last = nos[0]
    for b in blocks:
        a = _anchor(b, texts)
        if a is not None and a >= last:
            anchors[b["shot"]], last = a, a
    out, prev = [], nos[0]
    for i, b in enumerate(blocks):
        if b["shot"] in anchors:
            no, how = anchors[b["shot"]], "dialogue"
        else:
            nxt = next((anchors[x["shot"]] for x in blocks[i + 1:] if x["shot"] in anchors), nos[-1])
            window = [n for n in nos if prev <= n <= nxt]
            body = "\n".join(ln for ln in b["lines"] if not ln.strip().startswith("```"))
            no = max(window, key=lambda n: (_sim(body, texts[n][0]), -n)) if window else prev
            how = "similar"
        prev = no
        out.append({"shot": b["shot"], "scene_no": no, "segment": segs.get(no, "reality"), "how": how, "marked": block_marked(b)})
    return out


def check(text: str, p2: dict, p3: dict) -> list[dict]:
    """导入关口：[QW-S1] 漏标 → block；[QW-S2] 标的和 P2/P3 推断不一致 → 台词锚定的镜 block、相似度推断的镜 warn"""
    out = []
    for r in infer(text, p2, p3):
        n = r["shot"]
        if not r["marked"]:
            want = NAME.get(r["segment"] or "reality")
            out.append({"shot": n, "code": "QW-S1", "level": "block",
                        "detail": f"镜{n} 没有段落标记：**场景** 行细节开头写 【{want}】（按 P2/P3 这一镜属 {want}；K-WRT-213）"})
        elif r["segment"] and r["marked"] != r["segment"]:
            out.append({"shot": n, "code": "QW-S2", "level": "block" if r["how"] == "dialogue" else "warn",
                        "detail": f"镜{n} 标了【{NAME[r['marked']]}】，但 P2/P3 对应场景 {r['scene_no']} 是 {NAME[r['segment']]}"
                                  f"（{'台词锚定' if r['how'] == 'dialogue' else '按相邻镜推断'}；K-WRT-213）"})
    return out


def fill(text: str, p2: dict, p3: dict) -> tuple[str, list[dict]]:
    """漏标的镜：**场景** 行 `sk_x｜细节` → `sk_x｜【X段】细节`（没有 **场景** 行 → 在 img 行后补一行 **段落**：X段）→ (新文本, 补了哪些)"""
    lines = text.split("\n")
    filled = []
    for r in reversed(infer(text, p2, p3)):          # 从后往前插行，行号不乱
        if r["marked"] or not r["segment"]:
            continue
        b = next(x for x in shot_blocks(text) if x["shot"] == r["shot"])
        mark = MARK[r["segment"]]
        done = False
        for i in range(b["start"], b["end"]):
            m = SCENE_LINE.match(lines[i])
            if m:
                head, sid, bar, detail = m.group(1), m.group(2) or "", m.group(3), m.group(4)
                lines[i] = f"{head}{sid}{'｜' if sid else ''}{mark}{detail.lstrip()}" if (sid or detail) else f"{head}{mark}"
                done = True
                break
        if not done:
            lines.insert(b["start"] + 1, f"**段落**：{NAME[r['segment']]}")
        filled.append({"shot": r["shot"], "segment": r["segment"], "how": r["how"], "scene_no": r["scene_no"]})
    return "\n".join(lines), sorted(filled, key=lambda x: x["shot"])


def load_upstream(run_dir: Path, ep: int) -> tuple[dict | None, dict | None]:
    p2, p3 = run_dir / f"P2_ep{ep:02d}_outline.json", run_dir / f"P3_ep{ep:02d}_screenplay.json"
    try:
        return (json.loads(p2.read_text(encoding="utf-8")) if p2.exists() else None,
                json.loads(p3.read_text(encoding="utf-8")) if p3.exists() else None)
    except ValueError:
        return None, None


def episode_of(text: str, default: int | None = None) -> int | None:
    m = re.search(r"^##\s*ep(\d+)", text, re.M)
    return int(m.group(1)) if m else default


def check_text(ep_md: str, run_dir: Path, episode: int) -> list[dict]:
    """导入关口用：P2 / P3 不在 → 不判（[]）"""
    p2, p3 = load_upstream(run_dir, episode)
    if not p2 or not p3:
        return []
    return check(ep_md, p2, p3)


def apply_file(path: Path, run_dir: Path, by: str = "autoflow", episode: int | None = None) -> dict:
    """漏标的镜补标；原稿先复制进 data/_quarantine/segment_fix_<日期>/<run>/<名>.<时分秒>.md，审计追加 <run>/segment_fix.jsonl。
    → {changed, filled, mismatch, error?}"""
    text = path.read_text(encoding="utf-8")
    ep = episode or episode_of(text)
    if ep is None:
        return {"changed": False, "error": "认不出集号（没有 ## epNN）"}
    p2, p3 = load_upstream(run_dir, ep)
    if not p2 or not p3:
        return {"changed": False, "error": f"P2 / P3 第 {ep} 集不在，段落补不了"}
    new, filled = fill(text, p2, p3)
    mismatch = [x for x in check(new, p2, p3) if x["code"] == "QW-S2"]
    if filled:
        tag = time.strftime("%H%M%S")
        qd = ROOT / "data" / "_quarantine" / f"segment_fix_{time.strftime('%Y%m%d')}" / run_dir.name
        qd.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, qd / f"{path.name}.{tag}.md")
        path.write_text(new, encoding="utf-8")
    rec = {"at": time.strftime("%F %T"), "by": by, "file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
           "episode": ep, "filled": filled, "mismatch": mismatch}
    try:
        with open(run_dir / AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[segment_fix] 审计记录写不进 {run_dir / AUDIT}：{e}", file=sys.stderr)
    return {"changed": bool(filled), "filled": filled, "mismatch": mismatch}
