"""PROMPT（2026-10-31，项目方“镜头语言”实验）：为 run_chain 准备 ep02_cam_v1 的上游产物，使链条从 P3-P4（分镜）开始重跑。

剧情和台词以现有 ep02（已导入生产，data/recipes_out/ep02/*.spec.json）为准，只重新设计镜头，所以：
- P0 brief / P1 storyline：复用 CHAINSPEC 的 ep02_r3（同一套测试 brief），只把现有 ep02 的出场人物（陈宇）和场景对齐进 ep2 条目；
- P2 单集大纲：把现有 ep02 的镜头按场景 / 事件机械转写成节拍（summary = 现有 motion 的动作段原文，不改写）；
- P3 单集剧本：动作行 = 现有 motion 的动作段原文；台词 / 独白逐字照抄现有 ep02（S8 独白按句号切成几行以放进单镜上限，
  文字逐字不变、顺序不变）。
系统不写剧情；这里只是格式转写。输出 data/pipeline/runs/ep02_cam_v1/。
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "schema"))
from ns_schema.shot_spec import ShotSpec  # noqa: E402

R3 = ROOT / "data" / "pipeline" / "runs" / "ep02_r3"
OUT = ROOT / "data" / "pipeline" / "runs" / "ep02_cam_v1"
# 现有 ep02 说话人（剧本对白括号里写成“她慌 / 他”等代称，按 H3 说话人与镜内唯一说话的人对齐到登记名）
SPEAKER = {2: "顾沉", 3: "林晚", 4: "顾沉", 5: "顾沉", 6: "林晚", 7: "顾沉", 9: "陈宇", 10: "林晚"}
# 节拍分组（按场景与事件；每组 = 现有若干镜）
GROUPS = [("B1", [1], "setup"), ("B2", [2, 3, 4], "hook"), ("B3", [5, 6], "turn"), ("B4", [7], "reveal"),
          ("B5", [8], "tender"), ("B6", [9, 10], "payoff"), ("B7", [11], "cliffhanger")]
CAM_PREFIX = re.compile(r"^(?:lnwan01，)?\s*(?:camera\s+)?[a-z ]+?(?:shot|camera|in|out|left|right|up|down)\s*[^，]*，", re.I)


def action_of(s: ShotSpec) -> str:
    t = s.motion.text.split("——")[0]
    t = re.sub(r"^lnwan01，", "", t)
    t = CAM_PREFIX.sub("", t, count=1)
    return t.strip("，, ")


def split_vo(text: str, limit: int = 50) -> list[str]:
    parts = [p for p in re.split(r"(?<=[。？！])", text) if p.strip()]
    out, cur = [], ""
    for p in parts:
        if cur and len(re.sub(r"[\s，。、！？…—“”：；]", "", cur + p)) > limit:
            out.append(cur)
            cur = p
        else:
            cur += p
    if cur:
        out.append(cur)
    assert "".join(out) == text
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    specs = {i: ShotSpec.model_validate_json((ROOT / f"data/recipes_out/ep02/ep02-S{i}.spec.json").read_text(encoding="utf-8"))
             for i in range(1, 12)}
    shutil.copy2(R3 / "P0_brief.json", OUT / "P0_brief.json")
    sl = json.loads((R3 / "P1_storyline.json").read_text(encoding="utf-8"))
    ep = next(e for e in sl["episodes"] if e["episode"] == 2)
    chars = ["林晚", "顾沉", "陈宇"]
    scenes = []
    for s in specs.values():
        if s.scene.id not in scenes:
            scenes.append(s.scene.id)
    ep["characters"], ep["scenes"] = chars, scenes
    # 已登记角色的 VOICE 须逐字照抄登记（SL-10）：项目方 20:08 导入 PROMPTv2 后登记值是 natural pace
    vr = json.loads((ROOT / "data/ab/prompt_v2/ep02/voice_revision.json").read_text(encoding="utf-8"))
    for c in sl["characters"]:
        if c["name"] in vr:
            c["voice_phrase"] = vr[c["name"]]
    (OUT / "P1_storyline.json").write_text(json.dumps(sl, ensure_ascii=False, indent=1), encoding="utf-8")
    total = int(sum(s.duration_s for s in specs.values()))
    target = min(75, total)
    beats, sc_blocks = [], []
    for bid, idx, purpose in GROUPS:
        ss = [specs[i] for i in idx]
        cast = sorted({c.name for s in ss for c in s.characters_on_screen if c.presence in ("在画", "局部")}, key=chars.index)
        beats.append({"id": bid, "summary": "；".join(action_of(s) for s in ss), "scene_id": ss[0].scene.id,
                      "characters": cast, "est_s": max(2, round(sum(s.duration_s for s in ss) * target / total)),
                      "purpose": purpose, "has_dialogue": any(s.audio.dialogue for s in ss)})
    # 节拍秒数合计对齐 target（EO-04）
    diff = target - sum(b["est_s"] for b in beats)
    beats[max(range(len(beats)), key=lambda k: beats[k]["est_s"])]["est_s"] += diff
    outline = {"schema": "nsfs.episode_outline/1", "episode": 2, "title": ep["title"], "logline": ep["logline"],
               "intimate": ep["intimate"], "target_duration_s": target, "characters": chars, "scenes": scenes,
               "carry_in": "", "beats": beats, "carry_out": ep.get("carry_out", "")}
    (OUT / "P2_ep02_outline.json").write_text(json.dumps(outline, ensure_ascii=False, indent=1), encoding="utf-8")
    no = 0
    cur = None
    for bid, idx, _p in GROUPS:
        for i in idx:
            s = specs[i]
            if cur is None or cur["scene_id"] != s.scene.id:
                no += 1
                cur = {"no": no, "scene_id": s.scene.id, "beat_ids": [], "time": s.scene.time_of_day or "",
                       "characters": [], "lines": []}
                sc_blocks.append(cur)
            if bid not in cur["beat_ids"]:
                cur["beat_ids"].append(bid)
            for c in s.characters_on_screen:
                if c.presence in ("在画", "局部") and c.name not in cur["characters"]:
                    cur["characters"].append(c.name)
            cur["lines"].append({"kind": "action", "text": action_of(s)})
            for d in s.audio.dialogue:
                sp = SPEAKER[i]
                if sp not in cur["characters"]:
                    cur["characters"].append(sp)
                ln = {"kind": "dialogue", "speaker": sp, "text": d.text}
                if d.tone and d.tone not in (sp, "她", "他"):
                    ln["tone"] = d.tone
                cur["lines"].append(ln)
            if s.audio.voiceover:
                # P3 格式 SP-04：独白 text 不能带引号 → 只去掉引号字符（“别洗。” → 别洗。），其余逐字
                for part in split_vo(re.sub(r"[“”\"「」『』]", "", s.audio.voiceover.text)):
                    cur["lines"].append({"kind": "voiceover", "speaker": "林晚", "off_screen": "OS", "text": part})
            if s.audio.soundscape_zh:
                cur["lines"].append({"kind": "sound", "text": s.audio.soundscape_zh.split("；")[0]})
    for sc in sc_blocks:
        sc["characters"] = sorted(sc["characters"], key=chars.index)
    sp = {"schema": "nsfs.screenplay/1", "episode": 2, "title": ep["title"], "target_duration_s": target, "scenes": sc_blocks}
    (OUT / "P3_ep02_screenplay.json").write_text(json.dumps(sp, ensure_ascii=False, indent=1), encoding="utf-8")
    print(OUT, "target", target, "beats", len(beats), "scenes", len(sc_blocks))


if __name__ == "__main__":
    main()
