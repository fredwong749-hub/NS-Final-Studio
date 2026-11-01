"""PROMPT（2026-10-31）：按写作规则 sysimpl-v2 让写作模型（abliteration，用途 script_write）重写 ep02 各镜 H3 提示词层。

只重写提示词层（按秒分拍、视线、表情、对方反应、开头衔接、结尾留动作、速度）；剧情与台词由剧本决定，台词用
packages/schema/ns_schema/llm_output_check.py 校验逐字一致；时间轴 / 槽位用 ns_recipes.lint.lint_timeline（strict）校验。
系统不写也不评内容：不合格只把机检错误原样回给写作模型重写（最多 --rounds 轮），仍不合格的镜标 needs_writer。

输出（不覆盖生产数据）：data/ab/prompt_v2/ep02/
  S<n>.fl2va.txt   写作模型原文（四块，FL2VA）
  S<n>.i2va.txt    只给首帧用（系统确定性转换：I2VA 第一行、删 Picture 2 句）
  S<n>.ref2va.txt  Ref2VA 六段（<Picture k> = 在画露脸角色的脸部参考，按 manifest 的 ref_order）
  S<n>.beats.txt   **分拍** / **下镜** 行（Shot Spec 用）
  manifest.json    每镜时长 / 帧数 / 校验结果 / 参考图顺序；ledger.json 调用记账；raw_*.md 原始回复
用法：.venv/Scripts/python.exe tools/prompt_v2/rewrite_ep02.py [--shots S1,S2] [--rounds 2] [--dry]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/api", "services/recipes", "packages/schema", "services/render_router"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import llm_config as LC  # noqa: E402
from ns_api import script_chat as SC  # noqa: E402
from ns_recipes import lint as L  # noqa: E402
from ns_recipes import prompt as PR  # noqa: E402
from ns_recipes.spec_import import parse_beats, rules_version  # noqa: E402
from ns_schema.llm_output_check import check_writer_output  # noqa: E402
from ns_schema.shot_spec import ShotSpec, frames_for_seconds  # noqa: E402

OUT = ROOT / "data" / "ab" / "prompt_v2" / "ep02"
SPECS = ROOT / "data" / "recipes_out" / "ep02"
NAMES = {"林晚": ["林晚", "Lin Wan", "Linwan"], "顾沉": ["顾沉", "Gu Chen"], "陈宇": ["陈宇", "Chen Yu"]}
BUDGET_USD = 10.0
STYLE = "Live-action, cinematic, shallow depth of field"

TASK = """# 本次任务（PROMPT 系统任务，只改提示词层）
项目方看了 ep02 v1 成片，原话：“镜头切换生硬…镜头 1 和镜头 2 之间的 transition 非常生硬，不连贯”“每个镜头里面的眼神互动、表情互动都没有描写好”“MiniMax H3 的官方说明是按秒来计算动作的…时间轴也没有写好”“整个片子里的节奏很慢”。
请按上面规则末尾的「附录：系统可实现性规则 v2」重写 ep02 每一镜的 **分拍**、**下镜** 和 **H3提示词**。
- 只重写提示词层：按秒分拍、每拍视线 / 表情 / 对方反应、开头衔接句、结尾仍在进行的动作、正常偏快的动作速度。
- 剧情、人物、站位、道具、场景、光线以每镜给出的 img / motion / 对白 为准，不新增事件和人物；对白原文逐字逐标点不变，每镜对白句数不变；🎙 独白不进 H3。
- 每镜的人物 EN 外貌短语、EN 服装短语、VOICE 声线短语逐字照抄下面给的（规则 H3-X1/X3）。
- 每镜镜长（秒）已给出：分拍从 0 写到这个镜长；H3 对齐句里的 S.SS 照抄给出的值。
- 相邻镜头的衔接：本镜开头衔接句接上一镜你写的 **下镜** 动作（换场镜除外）。
同时处理总调度转来的写作请求（docs/ep02_iter/writer_requests.md，项目方已批“改成正常节奏”），只在下面这些字段里体现：
- W1：人物表 VOICE 声线短语的语速改成自然语速（林晚现为 soft slow pace、顾沉现为 measured slow pace，陈宇照此检查），音色、音区不变；H3 里说话人首次出现的句子逐字用修订后的 VOICE。动作量按正常速度在镜长内做完，并留出最后约 1 秒仍在进行的动作。
- W3：技术原因——H3 正文里 flush / flushed / blush 类词，在只给首帧和 Pika 模式下会被画成大面积圆形红斑，并随时间越来越红（实测 S2 脸颊红色像素占比 0.5–0.67，没写这类词的镜头 ≤0.08）。这类措辞改不改、怎么改由你决定。
- W5：技术原因——官方 §4.7 要求 non_diegetic_music 只写乐器、速度、节奏、强弱，不写“providing a … background layer”这类解释配乐作用的话。请按此重写各镜 non_diegetic_music（与【配乐】cue 一致）。
- overall_soundscape 仍与给出的【H3 audio】逐字相同。
输出格式（只输出这些，不写解释；每镜一段，镜之间不用 ---）：
## VOICE修订
林晚=<修订后的 VOICE 声线短语>
顾沉=<…>
陈宇=<…>
### <镜 id>
**分拍**：<…>
**下镜**：<…>
**H3提示词**：
```text
<四块>
```
"""


def load_specs() -> list[ShotSpec]:
    return [ShotSpec.model_validate_json((SPECS / f"ep02-S{i}.spec.json").read_text(encoding="utf-8")) for i in range(1, 12)]


def compiled(n: int) -> dict:
    return json.loads((ROOT / f"data/renders/ep02/S{n}/compiled.json").read_text(encoding="utf-8"))


def shot_pack(s: ShotSpec, prev: ShotSpec | None) -> str:
    c = compiled(s.index)
    frames = frames_for_seconds(s.duration_s)
    sec = frames / 24
    rows = [f"### {s.id}", f"- 镜长：{sec:.2f} 秒（剧本 **时长** {s.duration_s:g} 秒，{frames} 帧；对齐句 S.SS = {sec:.2f}）",
            f"- img：{(c.get('visual_spec') or {}).get('script_ref', {}).get('img') or c.get('image_body')}",
            f"- motion：{s.motion.text}",
            f"- 衔接：{s.continuity.link or ''}｜承：{s.continuity.from_prev or ''}"
            + (f"（上一镜 {prev.id} 的结束状态：{prev.motion.end_state}）" if prev else ""),
            f"- 运镜：{s.camera.move}"]
    for ch in s.characters_on_screen:
        rows.append(f"- 人物 {ch.name}（{ch.presence}｜{ch.screen_x or ''}｜{ch.depth or ''}）：EN外貌短语 = {ch.en_phrase}"
                    f"｜EN服装 = {ch.look}｜VOICE = {ch.voice_phrase}")
    for i, d in enumerate(s.audio.dialogue, 1):
        rows.append(f"- 对白{i}：（{d.speaker}{'，画外' if d.off_screen else ''}）“{d.text}”")
    if s.audio.voiceover:
        rows.append("- 本镜有 🎙 独白（不进 H3，镜内画面里林晚嘴唇闭合）")
    rows.append(f"- sound【H3 audio】（overall_soundscape 逐字照抄）：{s.audio.soundscape_en}")
    rows.append(f"- 【配乐】cue：{s.audio.music_cue}")
    old = (OUT / "old" / f"S{s.index}.sent.txt")
    if old.exists():
        rows.append("- v1 实际送出的 H3（供参考它写到的动作和画面；格式按新规则重写）：\n```text\n"
                    + old.read_text(encoding="utf-8").strip() + "\n```")
    return "\n".join(rows)


def save_old_prompts():
    """v1 成片每镜实际送出的提示词（takes.json），存档对照"""
    (OUT / "old").mkdir(parents=True, exist_ok=True)
    tl = json.loads((ROOT / "data/episodes/ep02_v1.timeline.json").read_text(encoding="utf-8"))
    for sh in tl["shots"]:
        n = sh["shot"].split("-")[1]
        stem = Path(sh["file"]).stem.replace("_dj", "")
        tk = json.loads((ROOT / f"data/renders/ep02/{n}/takes.json").read_text(encoding="utf-8"))
        items = tk if isinstance(tk, list) else tk.get("takes", tk)
        items = items if isinstance(items, list) else list(items.values())
        hit = next((t for t in items if isinstance(t, dict) and stem in json.dumps(t)), None)
        if hit and hit.get("prompt"):
            (OUT / "old" / f"{n}.sent.txt").write_text(hit["prompt"], encoding="utf-8")


SHOT_RE = re.compile(r"^###\s*(ep02-S\d+)\s*$", re.M)


def parse_reply(text: str) -> dict[str, dict]:
    out = {}
    marks = list(SHOT_RE.finditer(text))
    for i, m in enumerate(marks):
        seg = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        beats = re.search(r"\*\*分拍\*\*[:：]\s*(.+)", seg)
        nxt = re.search(r"\*\*下镜\*\*[:：]\s*(.+)", seg)
        h3 = re.search(r"\*\*H3提示词\*\*[:：]?\s*```(?:text)?\s*\n(.*?)```", seg, re.S)
        out[m.group(1)] = {"beats": beats.group(1).strip() if beats else "", "to_next": nxt.group(1).strip() if nxt else "",
                           "h3": h3.group(1).strip() if h3 else ""}
    return out


VOICE_RE = re.compile(r"^##\s*VOICE修订\s*$(.*?)(?=^###|\Z)", re.M | re.S)


def parse_voice(text: str) -> dict[str, str]:
    m = VOICE_RE.search(text or "")
    out = {}
    for ln in (m.group(1) if m else "").splitlines():
        mm = re.match(r"^\s*[-*]?\s*(林晚|顾沉|陈宇)\s*[=＝:：]\s*(.+?)\s*$", ln)
        if mm:
            out[mm.group(1)] = mm.group(2).strip().rstrip("。.")
    return out


VOICES: dict[str, str] = {}


def check(s: ShotSpec, item: dict) -> list[str]:
    errs = []
    for d in s.audio.dialogue:
        v = VOICES.get(d.speaker)
        if v and not d.off_screen and v.lower() not in (item.get("h3") or "").lower():
            errs.append(f"说话人 {d.speaker} 首次出现的句子没有逐字用修订后的 VOICE：{v}（H3-X3）")
    h3 = item.get("h3") or ""
    if not h3:
        return ["没有 H3提示词 代码块"]
    _first, f = PR.split_fields(h3)
    body = f.get("integrated_multimodal_description") or ""
    for k in PR.FIELDS:
        if not f.get(k):
            errs.append(f"缺字段 {k}")
    if f.get("overall_soundscape", "").strip() != (s.audio.soundscape_en or "").strip():
        errs.append("overall_soundscape 与【H3 audio】不逐字相同（QW-S1）")
    vis = {c.name for c in s.visible}
    r = check_writer_output(body, dialogue=[d.text for d in s.audio.dialogue], names=NAMES,
                            on_screen_anchors={c.name: [c.en_phrase] for c in s.visible if c.en_phrase},
                            absent_phrases={c.name: [c.en_phrase] for c in s.characters_on_screen
                                            if c.presence != "在画" and c.en_phrase})   # 局部 / 画外（导入器 H3-X4）
    errs += [f"{e['rule']}：{e['detail']}" for e in r.errors]
    frames = frames_for_seconds(s.duration_s)
    for i in L.lint_timeline(h3, frames / 24, sexes=[x for x in (L._sex(c.en_phrase) for c in s.faces) if x],
                             strict=True, faces=bool(s.faces)):
        if i["level"] == "error":
            errs.append(f"{i['code']}：{i['message']}")
    bs = parse_beats(item.get("beats") or "")
    if not bs:
        errs.append("**分拍** 行没解析出任何一拍（格式 0–2秒｜动作｜视线=…｜表情=…｜反应=…）")
    elif bs[-1].t1 < frames / 24 - 0.7:
        errs.append(f"**分拍** 只写到 {bs[-1].t1:g} 秒，镜长 {frames / 24:.2f} 秒")
    if not item.get("to_next"):
        errs.append("缺 **下镜** 行")
    _ = vis
    return errs


def warns(s: ShotSpec, h3: str) -> list[dict]:
    frames = frames_for_seconds(s.duration_s)
    return [i for i in L.lint_timeline(h3, frames / 24, sexes=[x for x in (L._sex(c.en_phrase) for c in s.faces) if x],
                                       strict=True, faces=bool(s.faces)) if i["level"] == "warn"]


def call(system: str, user: str, ledger: list, *, reasoning: bool | None = None, max_tokens: int = 24000) -> str:
    rv = LC.resolve("script_write", {"params": {"reasoning": reasoning}} if reasoning is not None else None)
    spent = sum(x.get("usd") or 0 for x in ledger)
    if spent >= BUDGET_USD:
        raise SystemExit(f"预算用完：已花 ${spent:.3f}")
    t0 = time.time()
    r = LC.complete_text(rv, system, user, max_tokens=max_tokens)
    u = r.get("usage") or {}
    pr = LC.model_pricing("abliteration").get(rv["model"]) or {}
    usd = (u.get("prompt_tokens", 0) * pr.get("prompt", 0) + u.get("completion_tokens", 0) * pr.get("completion", 0)) if pr else None
    ledger.append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "model": rv["model"], "usage": u, "usd": usd,
                   "secs": round(time.time() - t0, 1), "finish": r.get("finish")})
    (OUT / "ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"call {rv['model']} {u} ${usd} {r.get('finish')}", flush=True)
    return r["content"]


def ref2va_text(s: ShotSpec, h3: str, frames: int) -> tuple[str, list[str]]:
    spec = s.model_copy(deep=True)
    spec.h3.text = h3
    slots = [{"role": "identity", "character": c.name} for c in spec.faces if c.face_visible is not False and c.en_phrase]
    pr = PR.build_ref2va(spec, {"prompt": {"style_lead": STYLE}}, frames, slots)
    return pr["text"], [x["character"] for x in slots]


def write_outputs(specs, items, results):
    man = {"rules_version": rules_version(), "made": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": "tools/prompt_v2/rewrite_ep02.py",
           "note": "只改提示词层（PROMPT）；台词逐字由 llm_output_check 校验。i2va = 只给首帧；ref2va 的 <Picture k> 按 ref_order 放各角色脸部裁切参考图（k 从 1 起）。",
           "shots": {}}
    for s in specs:
        it = items.get(s.id)
        if not it:
            continue
        n = s.index
        frames = frames_for_seconds(s.duration_s)
        h3 = it["h3"]
        (OUT / f"S{n}.fl2va.txt").write_text(h3 + "\n", encoding="utf-8")
        _first, f = PR.split_fields(h3)
        body, _notes = PR.to_i2va_body(f.get("integrated_multimodal_description", ""))
        i2va = (f"{PR.I2VA_LINE}\n\nintegrated_multimodal_description: {body}\n\n"
                f"overall_soundscape: {f.get('overall_soundscape', '')}\n\nnon_diegetic_music: {f.get('non_diegetic_music') or 'N/A'}")
        (OUT / f"S{n}.i2va.txt").write_text(i2va + "\n", encoding="utf-8")
        ref, order = ref2va_text(s, h3, frames)
        (OUT / f"S{n}.ref2va.txt").write_text(ref + "\n", encoding="utf-8")
        (OUT / f"S{n}.beats.txt").write_text(f"**分拍**：{it['beats']}\n**下镜**：{it['to_next']}\n", encoding="utf-8")
        man["shots"][s.id] = {"seconds": round(frames / 24, 2), "frames": frames, "script_seconds": s.duration_s,
                              "status": "ok" if not results.get(s.id) else "needs_writer",
                              "errors": results.get(s.id) or [], "warns": warns(s, h3),
                              "words": len(re.sub(r"<d>.*?</d>", " ", body).split()),
                              "ref_order": order, "dialogue": [d.text for d in s.audio.dialogue],
                              "files": {k: f"data/ab/prompt_v2/ep02/S{n}.{k}.txt" for k in ("fl2va", "i2va", "ref2va", "beats")}}
    (OUT / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--recheck", action="store_true", help="不调用模型，只用已存 raw 重新解析 / 校验 / 输出")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    save_old_prompts()
    specs = load_specs()
    want = {f"ep02-{x}" for x in a.shots.split(",")} if a.shots else {s.id for s in specs}
    cfg = SC.load_config()
    system, _parts = SC.build_system_prompt(cfg, context=None, appendix_budget=0)
    assert "rules_addendum_version: sysimpl-v2" in system
    system += "\n\n" + TASK
    packs = "\n\n".join(shot_pack(s, specs[i - 1] if i else None) for i, s in enumerate(specs) if s.id in want)
    user = "ep02 各镜资料如下（按顺序）。请按任务要求输出每一镜。\n\n" + packs
    (OUT / "request_user.md").write_text(user, encoding="utf-8")
    if a.dry:
        print(len(system), len(user))
        return
    ledger = json.loads((OUT / "ledger.json").read_text(encoding="utf-8")) if (OUT / "ledger.json").exists() else []
    items: dict = json.loads((OUT / "items.json").read_text(encoding="utf-8")) if (OUT / "items.json").exists() else {}
    by_id = {s.id: s for s in specs}
    if not a.recheck:
        reply = call(system, user, ledger)
        (OUT / f"raw_r0_{time.strftime('%H%M%S')}.md").write_text(reply, encoding="utf-8")
        items.update({k: v for k, v in parse_reply(reply).items() if k in want})
        if parse_voice(reply) and not items.get("_voice"):   # VOICE 修订以第一次整集重写为准
            items["_voice"] = parse_voice(reply)
    VOICES.update(items.get("_voice") or {})
    results = {sid: check(by_id[sid], items.get(sid) or {}) for sid in want}
    for rnd in range(1, a.rounds + 1):
        bad = {k: v for k, v in results.items() if v}
        if not bad or a.recheck:
            break
        fix = ["【格式返修】下面几镜的机检没过。只重写这几镜（同样格式，### 镜 id 开头），只改被点名的地方，剧情与台词不变：", ""]
        for sid, errs in bad.items():
            fix.append(f"### {sid} 机检错误：")
            fix += [f"- {e}" for e in errs]
            fix.append("你上一版：")
            it = items.get(sid) or {}
            fix.append(f"**分拍**：{it.get('beats', '')}\n**下镜**：{it.get('to_next', '')}\n**H3提示词**：\n```text\n{it.get('h3', '')}\n```")
            fix.append("")
        if VOICES:
            fix.append("（VOICE 修订沿用你上一版：" + "；".join(f"{k}={v}" for k, v in VOICES.items()) + "）")
        fix.append("资料（同上）：\n\n" + "\n\n".join(shot_pack(by_id[sid], specs[by_id[sid].index - 2] if by_id[sid].index > 1 else None)
                                                    for sid in bad))
        reply = call(system, "\n".join(fix), ledger)
        (OUT / f"raw_r{rnd}_{time.strftime('%H%M%S')}.md").write_text(reply, encoding="utf-8")
        got = parse_reply(reply)
        for sid in bad:
            if sid in got and got[sid].get("h3"):
                items[sid] = got[sid]
        results = {sid: check(by_id[sid], items.get(sid) or {}) for sid in want}
    (OUT / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    write_outputs([s for s in specs if s.id in items], items, results)
    (OUT / "voice_revision.json").write_text(json.dumps(VOICES, ensure_ascii=False, indent=1), encoding="utf-8")
    spent = sum(x.get("usd") or 0 for x in ledger)
    print(json.dumps({k: (len(v) if v else "ok") for k, v in sorted(results.items())}, ensure_ascii=False), f"spent ${spent:.4f}")


if __name__ == "__main__":
    main(sys.argv[1:])
