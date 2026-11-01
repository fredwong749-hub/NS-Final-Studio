"""导演层：按剧本节拍给每镜补“运镜 / 转场 / 剪辑点 / 节奏”（DIRECTOR loop，总调度 fredw-2b 派，2026-11-02；规则 K-EDT-811–815）。

只读剧本里写作方已经写好的格式字段，不写也不评价剧本内容：
  link（接力 / 同场换机位 / 换场）、link_carry（动作｜… / 视线｜… / 环境｜… / 位置｜…）、music_cue 的“强度 0–3”（写作方的情绪节拍）、
  cast 的左右站位、dialogue / voiceover、motion_prompt 开头的运镜句、scene_id、duration。
产出 = 每镜一份“导演规格”（director 字段），给两处用：
  1. 编译器（首帧 + Pika 提示词）：camera.clause_en（一种运镜、小幅、Pika 做得到）、eyeline.frame_dir（视线方向写画内方向）；
  2. 合成（ns_post.assemble）：transition_in、j_cut_s / l_cut_s、cut.target_s（随强度变的刀长）、cut.out（在动作中段出刀）。
Pika 能力边界：config/prompts/hollywood_pika_reference.md（P3 / P10 / P16：景别由首帧定、推近只写小幅、大动作不叠运镜；
RCA_r1 C16：视频比首帧再远 ≥1 档 11/55 → 不用拉远）。

  python tools/director/cut_plan.py epNN [--script S]      → data/director/epNN_cut_plan.json + 写作格式 lint
  python tools/director/cut_plan.py lint [epNN …]          → 只跑写作格式 lint（K-WRT-801–803）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "data" / "import" / "script_v2.json"
OUT = ROOT / "data" / "director"
VERSION = "dir-v1-2026-11-02"

# K-EDT-811：Pika 做得到的运镜（一种、小幅；不写 slowly / 缓慢——项目方 v1 原话“节奏有点慢……画面也很慢”）
MOVES = {
    "static": "The camera holds a static shot.",
    "push_small": "The camera pushes in with small amplitude.",
    "truck_small": "The camera trucks {dir} with small amplitude.",
    "pan_small": "The camera pans {dir} with small amplitude.",
}
BANNED_MOVES = re.compile(r"pull out|拉远|zoom out|arc|环绕|shake|手持晃|POV|roll|旋转", re.I)
SLOW_WORDS = re.compile(r"缓慢|缓缓|慢慢推|slowly|slow push", re.I)
BIG_ACTION = re.compile(r"站起|起身|走向|走到|走开|转身|推门|开门|关门|披上|脱下|抖开|蹲|跑|扑|拥抱|抱住|倒在")
TIME_JUMP = re.compile(r"次日|第二天|翌日|几天后|一周后|当晚|清晨|天亮|深夜时分|过了")
# K-EDT-813：情绪强度 → 目标刀长（秒）
PACE = {0: (3.0, 4.5), 1: (3.0, 4.5), 2: (2.5, 3.5), 3: (1.5, 2.5)}
J_CUT_S, L_CUT_S, DISSOLVE_S, SOUND_LEAD_S = 0.3, 0.4, 0.4, 0.4


def _load_list(v):
    if isinstance(v, str):
        try:
            import ast
            return ast.literal_eval(v)
        except (ValueError, SyntaxError):
            return []
    return v or []


def intensity(shot: dict) -> int | None:
    m = re.search(r"强度\s*([0-3])", str(shot.get("music_cue") or ""))
    return int(m.group(1)) if m else None


def camera_of(motion: str) -> str:
    body = re.sub(r"^[A-Za-z0-9_]+，", "", motion or "")
    m = re.match(r"^[^，,]*", body)
    return (m.group(0) if m else "").strip()


def speaking(shot: dict) -> list[str]:
    return [d.get("speaker") for d in _load_list(shot.get("dialogue")) if isinstance(d, dict) and d.get("speaker")]


def cast_x(shot: dict) -> dict:
    return {c.get("name"): c.get("x") for c in _load_list(shot.get("cast")) if isinstance(c, dict) and c.get("presence") == "在画"}


def plan_episode(ep: dict) -> list[dict]:
    shots = sorted(ep.get("shots") or [], key=lambda s: int(s["index"]))
    out = []
    for i, s in enumerate(shots):
        prev = shots[i - 1] if i else None
        nxt = shots[i + 1] if i + 1 < len(shots) else None
        link = str(s.get("link") or "")
        carry_kind = str(s.get("link_carry") or "").split("｜")[0]
        motion = str(s.get("motion_prompt") or "")
        cam_src = camera_of(motion)
        lvl = intensity(s)
        spk = speaking(s)
        big = bool(BIG_ACTION.search(motion))
        why = []
        # ---- 运镜（K-EDT-811）
        if big:
            move, why_m = "static", "本镜有大动作：不叠运镜（Pika P10 大动作变软；一镜一个主动作）"
        elif spk:
            move, why_m = ("push_small" if (lvl or 0) >= 2 else "static"), "对白镜：固定或小幅推近，保脸部清晰和口型（Pika P10）"
        elif i == 0 or link == "换场":
            move, why_m = "static", "开场 / 换场第一镜：固定机位交代空间（景别由首帧定，Pika P3）"
        elif (lvl or 0) >= 3:
            move, why_m = "push_small", "情绪高点：小幅推近（推近幅度只写小，Pika P16）"
        else:
            move, why_m = ("push_small" if re.search(r"push|推", cam_src) else "static"), "沿用写作方运镜，统一为小幅"
        if re.search(r"truck|横移", cam_src) and not big:
            move = "truck_small"
        clause = MOVES[move].format(dir="right" if re.search(r"right|右", cam_src) else "left")
        cam_flags = []
        if BANNED_MOVES.search(cam_src):
            cam_flags.append(f"写作方运镜“{cam_src}”超出 Pika 稳定范围（拉远 / 环绕 / 晃动），导演层改为 {move}")
        if SLOW_WORDS.search(cam_src):
            cam_flags.append("运镜写了“缓慢”：去掉（节奏要求），幅度改写“小幅”")
        # ---- 转场（K-EDT-812）+ J/L-cut（K-EDT-814）
        detail = f"{s.get('scene_detail') or ''}{s.get('img_prompt') or ''}"
        if i == 0:
            tr = {"type": "开场", "s": 0.0}
        elif link == "换场":
            tr = ({"type": "叠化", "s": DISSOLVE_S} if TIME_JUMP.search(detail)
                  else {"type": "声音先行", "s": SOUND_LEAD_S})
        elif carry_kind == "动作":
            tr = {"type": "动作匹配切", "s": 0.0}
        elif carry_kind == "视线":
            tr = {"type": "视线匹配切", "s": 0.0}
        else:
            tr = {"type": "硬切", "s": 0.0}
        j = l = 0.0
        if i and tr["type"] != "叠化":
            if tr["type"] == "声音先行":
                j = SOUND_LEAD_S
            elif spk and not speaking(prev):
                j = J_CUT_S                      # 下一镜开口：声音先进，画面后切
            elif speaking(prev) and not spk and link != "换场":
                l = L_CUT_S                      # 上一句的尾音盖到听者反应镜
        # ---- 节奏 / 剪辑点（K-EDT-813）
        lo, hi = PACE.get(lvl if lvl is not None else 1, PACE[1])
        if i == 0:
            hi = min(hi, 3.0)
            lo = min(lo, 2.0)
        cut_out = ("on_action" if (nxt and str(nxt.get("link_carry") or "").startswith("动作")) else
                   ("after_line" if spk else "on_motion_peak"))
        # ---- 视线（K-EDT-815）
        xs = cast_x(s)
        eyeline = {}
        for name, x in xs.items():
            if x in ("左", "右") and len(xs) >= 2:
                eyeline[name] = "toward frame-right" if x == "左" else "toward frame-left"
        flags = list(cam_flags)
        if prev and link != "换场":
            px = cast_x(prev)
            both = [n for n in xs if n in px and xs[n] in ("左", "右") and px[n] in ("左", "右")]
            if len(both) >= 2 and any(xs[n] != px[n] for n in both):
                flags.append("越轴：同场相邻镜两人左右互换（K-WRT-104 / 180° 规则）→ 合成按硬切处理，写作方需标 HARD CUT 或改站位")
        out.append({"shot": f"ep{int(ep['number']):02d}-S{int(s['index'])}", "index": int(s["index"]),
                    "beat": {"link": link, "carry": carry_kind, "intensity": lvl, "speaking": spk, "big_action": big},
                    "camera": {"move": move, "clause_en": clause, "source": cam_src, "why": why_m},
                    "transition_in": tr, "j_cut_s": j, "l_cut_s": l,
                    "cut": {"target_s": [lo, hi], "out": cut_out},
                    "eyeline": eyeline, "flags": flags})
    return out


# ---------------------------------------------------------------- 写作格式 lint（K-WRT-801–803；只查格式，不评价内容）
def lint_episode(ep: dict) -> list[dict]:
    res = []
    shots = sorted(ep.get("shots") or [], key=lambda s: int(s["index"]))
    lv = [intensity(s) for s in shots]
    for s in shots:
        sid = f"ep{int(ep['number']):02d}-S{int(s['index'])}"
        cam = camera_of(str(s.get("motion_prompt") or ""))
        if not cam or not re.search(r"camera|static|tracking|shot|推|摇|移|跟", cam, re.I):
            res.append({"id": "K-WRT-801", "shot": sid, "msg": "motion 第一句没有运镜（一种运镜 + 幅度），例：camera push in 小幅推近"})
        elif BANNED_MOVES.search(cam):
            res.append({"id": "K-WRT-801", "shot": sid, "msg": f"运镜“{cam}”超出 Pika 稳定范围：不用拉远 / 环绕 / 晃动"})
        elif SLOW_WORDS.search(cam):
            res.append({"id": "K-WRT-801", "shot": sid, "msg": f"运镜“{cam}”写了缓慢：改写幅度（小幅 / 中幅），不写速度"})
        if str(s.get("link") or "") == "接力" and str(s.get("link_carry") or "").split("｜")[0] in ("", "无", "—"):
            res.append({"id": "K-WRT-802", "shot": sid, "msg": "衔接写了“接力”但没写接什么：link_carry 写 动作｜… / 视线｜… / 环境｜… / 位置｜…"})
        if intensity(s) is None:
            res.append({"id": "K-WRT-803", "shot": sid, "msg": "【配乐】没写“强度 0–3”（导演层按强度定刀长、配乐按强度起伏）"})
    known = [x for x in lv if x is not None]
    if known and len(set(known)) < 2:
        res.append({"id": "K-WRT-803", "shot": f"ep{int(ep['number']):02d}", "msg": f"整集【配乐】强度只有一档（{known[0]}）：情绪节拍至少两档，高点镜写 3"})
    return res


def load_script(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def episode(script: dict, n: int) -> dict:
    e = next((x for x in script.get("episodes") or [] if int(x.get("number")) == n), None)
    if not e:
        raise SystemExit(f"剧本里没有 ep{n:02d}")
    return e


def write_plan(n: int, script_path: Path = SCRIPT) -> dict:
    sc = load_script(script_path)
    e = episode(sc, n)
    plan = {"schema": "nsfs.cut_plan/1", "version": VERSION, "episode": n, "script": str(script_path.relative_to(ROOT)).replace("\\", "/")
            if script_path.is_relative_to(ROOT) else str(script_path), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "shots": plan_episode(e), "writer_lint": lint_episode(e)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"ep{n:02d}_cut_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("what", nargs="+", help="epNN … 或 lint [epNN …]")
    ap.add_argument("--script", default=str(SCRIPT))
    a = ap.parse_args(argv)
    sp = Path(a.script)
    sp = sp if sp.is_absolute() else ROOT / sp
    if a.what[0] == "lint":
        sc = load_script(sp)
        eps = [int(x[2:]) for x in a.what[1:]] or [int(e["number"]) for e in sc.get("episodes") or []]
        tot = 0
        for n in eps:
            for r in lint_episode(episode(sc, n)):
                print(r["id"], r["shot"], r["msg"])
                tot += 1
        print(f"共 {tot} 条")
        return
    for w in a.what:
        p = write_plan(int(w[2:]), sp)
        tr = {}
        for s in p["shots"]:
            tr[s["transition_in"]["type"]] = tr.get(s["transition_in"]["type"], 0) + 1
        print(f"ep{p['episode']:02d}: {len(p['shots'])} 镜；转场 {tr}；J {sum(1 for s in p['shots'] if s['j_cut_s'])} / "
              f"L {sum(1 for s in p['shots'] if s['l_cut_s'])}；导演改运镜 {sum(1 for s in p['shots'] if s['flags'])} 镜；"
              f"写作 lint {len(p['writer_lint'])} 条 → data/director/ep{p['episode']:02d}_cut_plan.json")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------- 配乐跟情绪节拍（K-EDT-804）
def merge_music_intensity(cues: list[dict], script_shots: list[dict]) -> list[dict]:
    """BGM 时间轴（data/music/series10/epNN.json cues，bgm10 生成）保留时间和描述，强度改用剧本【配乐】的“强度 0–3”
    （写作方的情绪节拍）；剧本强度变了而时间轴在该镜没有 cue → 补一条（升 = swell、降到 0 = drop、其余 continue）。
    根因（film_score ep01_v2 S3.4）：bgm10 写出的 5 条 cue 全是强度 2，剧本写的 1/1/1/2/2/3/1 被时间轴覆盖（music.resolve_cues 优先级 1）。"""
    lv = {int(s["index"]): intensity(s) for s in script_shots}
    by_shot = {int(c.get("shot") or 0): dict(c) for c in cues}
    out, last = [], None
    for idx in sorted(lv):
        x = lv[idx]
        c = by_shot.pop(idx, None)
        if c is not None:
            if x is not None:
                c["intensity_json"] = c.get("intensity")
                c["intensity"] = x
                if c.get("action") == "continue" and last is not None and x > last:
                    c["action"] = "swell"
                elif x == 0:
                    c["action"] = "drop"
            c["src_intensity"] = "script" if x is not None else "json"
            out.append(c)
        elif x is not None and last is not None and x != last:
            out.append({"shot": idx, "offset_s": 0.0, "action": "swell" if x > last else ("drop" if x == 0 else "continue"),
                        "intensity": x, "text": f"导演层补：剧本强度 {last}→{x}", "src_intensity": "script"})
        if x is not None:
            last = x
    out += list(by_shot.values())
    return sorted(out, key=lambda c: int(c.get("shot") or 0))
