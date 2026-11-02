"""叙事质量的代码判定（RSI 线 3 第 3 轮，总调度 11-02：27 条代码判定只管“合格”，管不到“好”——能代码化的叙事质量补进来）。

每条只用剧本原文的字段做确定性判断，不评价内容好坏的“品味”，只量结构信号；阈值先在第一季 / 第二季已有稿上跑分布再定
（tools/script_rsi/narrative_code.py dist）。规则 K-WRT-N01–N07（knowledge/rules/writer_hollywood.yaml），测试 tests/test_narrative_code.py。

  N01 不空镜        每镜要有动作或信息变化：有台词 / 独白，或分拍里至少一段写了看得见的变化动作（不只“保持 / 静止 / 凝视 / 定住”）
  N02 潜台词承载    有台词的镜，同镜分拍写了与台词并行的身体 / 视线信号（视线= / 表情= / 手 / 呼吸），且台词不直说情绪
  N03 钩子前 5 秒   镜1 的前 5 秒里出现台词，或出现“变化类”动作（响 / 亮 / 停 / 推 / 抓 / 撞 / 打开 / 掉落 / 出现…）
  N04 转折位        全集时长 35%–75% 区间里，至少一镜出现新的在画人物入画，或“揭示类”动作（亮起 / 出现 / 发现 / 看见 / 打开 / 掉出…）
  N05 结尾悬念类型   末镜结尾类型（问句 / 揭示 / 中断 / 视线外指 / 其它）在相邻 3 集里不重复（整季判，单集给类型）
  N06 景别节奏       不连续 3 镜同一景别
  N07 表演节拍到秒   每镜分拍（或 **表演节拍**）按 ≤2 秒切段且覆盖到镜长
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIZES = ["大特写", "中近景", "中全景", "特写", "近景", "中景", "全景", "远景"]
STATIC = re.compile(r"保持|静止|凝视|定住|不动|停留|凝固|静静")
CHANGE = re.compile(r"响|亮|停|推|抓|撞|打开|拉开|掉|落|出现|转身|抬|按|递|拿起|放下|扣|握|松开|起身|走|跑|伸|摔|碎|闪|震|弹")
# N04 词表按第二季 ep01–10 实际写法对齐（SCRIPTWRITER 11-02 提供）：补 震了一下 / 抽出 / 递到 / 放到 / 走近 / 停在…身侧 / 开口 / 叫住 / 划掉 / 拿起
REVEAL = re.compile(r"亮起|出现|发现|看见|看到|打开|掉出|露出|显示|弹出|推开|揭开|认出|震了|震动|抽出|抽走|递到|放到|走近|停在.{0,4}身侧|开口|叫住|划掉|拿起|入画|走进")
BODY = re.compile(r"视线=|表情=|手|指|呼吸|喉|睫|嘴角|肩")
EMO_DIRECT = re.compile(r"(很|好|非常|特别|太|真)(生气|愤怒|难过|伤心|害怕|紧张|开心|高兴|委屈|心动|激动|失望|痛苦|讨厌)|我(爱|恨)你")
BEAT = re.compile(r"(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)\s*秒｜([^；]*)")


def _field(block: str, label: str) -> str:
    for ln in block.split("\n"):
        if ln.startswith(f"**{label}**"):
            return ln.split("：", 1)[1] if "：" in ln else ""
    return ""


def _beats(block: str) -> list[tuple[float, float, str]]:
    src = _field(block, "表演节拍") or _field(block, "分拍")
    return [(float(a), float(b), t.strip()) for a, b, t in BEAT.findall(src)]


def _size(block: str) -> str | None:
    t = _field(block, "机位与景别") or block.split("\n", 1)[0].split("：", 1)[-1]
    head = t[:60]
    return next((s for s in SIZES if s in head), None)


def ending_type(block: str, shot) -> str:
    """末镜结尾类型：看最后两拍 + **下镜** 行 + 最后一句台词。先判视线外指（最具体），再判揭示 / 问句组合，最后才算中断"""
    beats = _beats(block)
    tail = " ".join(t for _a, _b, t in beats[-2:]) + " " + _field(block, "下镜")
    lines = [d.text for d in shot.dialogue] + ([shot.voiceover.text] if shot.voiceover and shot.voiceover.text else [])
    q = bool(lines) and bool(re.search(r"[？?]\s*$", lines[-1].strip()))
    rv = bool(REVEAL.search(tail))
    gaze = bool(re.search(r"视线.{0,10}(画外|门缝|门|窗|远处|身后|反光|光)|看向(门|窗|画外|远处)|抬眼看|望向", tail))
    if q and rv:
        return "reveal+question"
    if q:
        return "question"
    if gaze and not rv:
        return "gaze_out"
    if rv:
        return "reveal"
    if re.search(r"没有|停在|未|悬|半空|欲|还没|停住|顿住", tail):
        return "interrupted"
    return "other"


def episode_checks(shots: list, blocks: list[str]) -> dict:
    """→ {N0x: {"ok": bool, "value": 数值, "detail": 说明}}（N05 只给类型，整季判）"""
    out = {}
    empty = []
    for s, b in zip(shots, blocks):
        has_speech = bool(s.dialogue) or bool(s.voiceover and s.voiceover.text)
        beats = _beats(b)
        moving = [t for _a, _b, t in beats if CHANGE.search(t) and not (STATIC.search(t) and not CHANGE.search(t.replace("停", "")))]
        if not has_speech and not moving:
            empty.append(s.index)
    out["N01"] = {"ok": not empty, "value": 1 - len(empty) / max(1, len(shots)), "detail": f"空镜：{empty or '无'}"}
    sp_shots = [(s, b) for s, b in zip(shots, blocks) if s.dialogue]
    supported = [s.index for s, b in sp_shots if any(BODY.search(t) for _a, _b, t in _beats(b))
                 and not any(EMO_DIRECT.search(d.text) for d in s.dialogue)]
    ratio = len(supported) / len(sp_shots) if sp_shots else 1.0
    out["N02"] = {"ok": ratio >= 0.8, "value": round(ratio, 3), "detail": f"台词镜 {len(sp_shots)}，有身体 / 视线信号承载且不直说情绪 {len(supported)}"}
    b1 = _beats(blocks[0]) if blocks else []
    hook = bool(shots and shots[0].dialogue) or any(a < 5 and CHANGE.search(t) for a, _b, t in b1)
    out["N03"] = {"ok": hook, "value": int(hook), "detail": "镜1 前 5 秒有台词或变化动作" if hook else "镜1 前 5 秒没有台词也没有变化动作"}
    total = sum(int(s.duration or 0) for s in shots)
    t0, seen, turn = 0, set(), []
    for s, b in zip(shots, blocks):
        names = {c.name for c in (s.cast or []) if c.presence == "在画"}
        mid = (t0 + int(s.duration or 0) / 2) / max(1, total)
        if 0.35 <= mid <= 0.75 and ((names - seen and seen) or any(REVEAL.search(t) for _a, _b, t in _beats(b))):
            turn.append(s.index)
        seen |= names
        t0 += int(s.duration or 0)
    out["N04"] = {"ok": bool(turn), "value": int(bool(turn)), "detail": f"35%–75% 区间的转折镜：{turn or '无'}"}
    out["N05"] = {"ok": True, "value": ending_type(blocks[-1], shots[-1]) if shots else "other", "detail": "结尾类型（整季判重复）"}
    sizes = [_size(b) for b in blocks]
    runs3 = [shots[i].index for i in range(2, len(sizes)) if sizes[i] and sizes[i] == sizes[i - 1] == sizes[i - 2]]
    out["N06"] = {"ok": not runs3, "value": 1 - len(runs3) / max(1, len(shots)), "detail": f"连续 3 镜同景别（第 3 镜）：{runs3 or '无'}"}
    coarse = []
    for s, b in zip(shots, blocks):
        bt = _beats(b)
        if not bt or any(e - a > 2.25 for a, e, _t in bt) or max(e for _a, e, _t in bt) < int(s.duration or 0) - 0.25:
            coarse.append(s.index)
    out["N07"] = {"ok": not coarse, "value": 1 - len(coarse) / max(1, len(shots)), "detail": f"分拍没按 ≤2 秒切到镜长的镜：{coarse or '无'}"}
    return out


def season_endings(types: dict[int, str]) -> dict:
    """N05：相邻 3 集结尾类型不重复（other 不计重复）"""
    eps = sorted(types)
    bad = [eps[i] for i in range(2, len(eps)) if types[eps[i]] != "other" and types[eps[i]] in (types[eps[i - 1]], types[eps[i - 2]])]
    return {"ok": not bad, "types": types, "repeats_at": bad}


def _episode_material(text: str, ep: int):
    sys.path[:0] = [str(ROOT / "packages" / "schema"), str(ROOT / "services" / "agent")]
    from ns_agent.importer.script_md import import_script
    import tempfile
    spec = __import__("importlib.util").util.spec_from_file_location("rubric_code", ROOT / "tools" / "script_rsi" / "rubric_code.py")
    RC = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(RC)
    chunk = RC.episode_chunk(text, ep)
    _head, blocks = RC.split_blocks(chunk)
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "e.md"
        f.write_text(text, encoding="utf-8")
        e = next(x for x in import_script(f).episodes if x.number == ep)
    return sorted(e.shots, key=lambda s: s.index), blocks


def cmd_dist(a) -> int:
    """在第一季（现行导入稿各集来源）和第二季（run 目录最好稿）上跑分布"""
    import importlib.util as iu
    spec = iu.spec_from_file_location("hollywood", ROOT / "tools" / "script_rsi" / "hollywood.py")
    H = iu.module_from_spec(spec)
    spec.loader.exec_module(H)
    rows = {"S1": {}, "S2": {}}
    srcs = H.RC.episode_sources()
    for ep in range(1, 11):
        text, _ = H.RC.assemble(H.RL, [ep], srcs)
        sh, bl = _episode_material(text, ep)
        rows["S1"][ep] = episode_checks(sh, bl)
    run = ROOT / "data/pipeline/runs/series10_s2"
    from ns_api import script_chat as SC
    for ep in range(1, 11):
        for name in (f"P4_ep{ep:02d}.final.md", f"P4_ep{ep:02d}.md"):
            p = run / name
            if p.exists():
                t = p.read_text(encoding="utf-8")
                if not name.endswith(".final.md"):
                    header, _ = SC.script_header(registry={})
                    t = header + "\n---\n\n" + t[t.find("## ep"):]
                sh, bl = _episode_material(t, ep)
                rows["S2"][ep] = episode_checks(sh, bl)
                break
    summary = {}
    for season, eps in rows.items():
        summary[season] = {k: {"pass": sum(1 for r in eps.values() if r[k]["ok"]), "n": len(eps),
                               "values": [r[k]["value"] for r in eps.values()]} for k in ("N01", "N02", "N03", "N04", "N06", "N07")}
        summary[season]["N05"] = season_endings({ep: r["N05"]["value"] for ep, r in eps.items()})
    out = ROOT / "data/rsi/narrative_dist.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    import os
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps({"summary": summary, "rows": {s: {str(k): v for k, v in e.items()} for s, e in rows.items()}},
                              ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, out)
    print(json.dumps(summary, ensure_ascii=False, default=str)[:4000])
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    for _p in (ROOT / "packages" / "schema", ROOT / "services" / "agent", ROOT / "services" / "api", ROOT / "tools" / "pipeline"):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dist")
    a = ap.parse_args(argv)
    return cmd_dist(a)


if __name__ == "__main__":
    sys.exit(main())
