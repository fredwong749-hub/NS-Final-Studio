"""PROMPT（2026-10-31，方案 C）：把总调度写的 ep02 导演版分镜（data/pipeline/runs/ep02_claude_director_v1/ep02_director_cut.md）
交给写作模型（abliteration，用途 script_write）转写成系统 P4 剧本分镜格式（script_chat_rules §2 + sysimpl-v2），
然后系统做确定性的事：校验（validate_qwen_script、台词逐字、时间轴 lint）→ Shot Spec → 配方编译出 Ref2VA 六段 / I2VA 提示词。

系统不写内容：中文 img / motion、H3 英文都由写作模型按导演稿转写；不合格只把机检错误回给写作模型。不导入生产剧本。
输出：data/pipeline/runs/ep02_claude_director_v1/
  P4_ep02.md（写作模型产出）、raw/、validate.json、specs/、prompts/S<n>.ref2va.txt / S<n>.i2va.txt、plans/、report.json
用法：.venv/Scripts/python.exe tools/prompt_v2/director_to_p4.py [--rounds 2] [--recheck]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/api", "services/recipes", "packages/schema", "services/render_router", "tools/prompt_v2"):
    sys.path.insert(0, str(ROOT / p))

import rewrite_ep02 as RW  # noqa: E402
from ns_api import script_chat as SC  # noqa: E402
from ns_recipes import compiler as C  # noqa: E402
from ns_recipes import lint as L  # noqa: E402
from ns_recipes import prompt as PR  # noqa: E402
from ns_recipes import registry as R  # noqa: E402
from ns_recipes import spec_import as SI  # noqa: E402
from ns_schema.llm_output_check import check_writer_output  # noqa: E402
from ns_schema.shot_spec import frames_for_seconds, missing_fields  # noqa: E402

RUN = ROOT / "data" / "pipeline" / "runs" / "ep02_claude_director_v1"
CUT = RUN / "ep02_director_cut.md"
CUR = ROOT / "data" / "staging_v3" / "为他而骚_ep02_补全候选_PROMPTv2_20261031.md"
# 现版 ep02 台词（逐字，顺序）——导演稿声明“台词沿用当前 ep02 逐字不改”
DIALOGUE = [("顾沉", "方案第三页，数据错了。"), ("林晚", "对不起，我马上改——"), ("顾沉", "不用急。我陪你。"), ("顾沉", "冷。"),
            ("林晚", "那我……明天还您。"), ("顾沉", "明天。外套，别洗。"), ("陈宇", "这么大的外套？公司发的？"),
            ("林晚", "同事借的。明天还。")]
DURS = [4, 5, 5, 6, 8, 5, 7, 8, 10]
NAMES = RW.NAMES

TASK = """# 本次任务（PROMPT 系统任务：格式转写）
项目方要求总调度写了一版 ep02 导演版分镜（用户消息里的【导演稿】）。请把它转写成上面规则第 2 节的剧本分镜格式（从 `## ep02《深夜外套》` 开始，结尾单独一行 `---`），供系统出片做实验（不导入生产剧本）。
- 内容一律以导演稿为准：9 镜、每镜时长、景别 / 机位 / 运镜、按秒分拍、视线、表情、反应、声音、配乐 cue、转场，逐镜对应，不增删事件、不加人物；导演稿去掉了独白，本稿不写 🎙。
- 对白逐字逐标点照抄导演稿的引号内文字，说话人照抄。镜9 按导演稿保留两位说话人（陈宇、林晚），H3 里用 (S1)、(S2)；这是导演稿的实验设计。
- 集头（剧情 / 出场人物 / 用到的场景 / 造型 / 配乐）和人物表、场景 id 照抄用户消息给的【现版 ep02 集头】（逐字），出场人物和场景按本稿实际用到的写。
- 每镜都写附录 v1 / v2 的 **分拍**（按导演稿的秒数）、**下镜**（写导演稿的“转场出”和结尾仍在进行的动作）、**镜头运动**；H3提示词按 sysimpl-v2 写（`At 00:SS.mmm,` 分拍；每拍视线 / 表情 / 对方反应；台词拍听者 lips closed；开头衔接句；结尾仍在进行的动作；FL2VA 末句单独成句）。
- H3 正文把导演稿的景别、机位、运镜幅度写成官方运镜句（The camera … with small amplitude …）；导演稿里镜内的景别变化（如特写上摇到近景、焦点从倒影拉回）写成同一个连续镜头里的运镜，不写 [Shot 2]、不写 cut。
- 导演稿要求“脸颊不写泛红”：H3 里不写 flush / blush。
"""


def call(system, user, ledger):
    # 推理 token 会吃光输出上限（实测 3 次 24000 全被截断，推理 19–24k）→ 转写任务关推理
    return RW.call(system, user, ledger, reasoning=False, max_tokens=32000)


def checks(md: str) -> dict:
    out = {"dialogue": None, "shots": {}}
    specs = SI.specs_from_markdown_text(md, 2) if hasattr(SI, "specs_from_markdown_text") else None
    if specs is None:
        tmp = RUN / "P4_ep02.md"
        tmp.write_text(md, encoding="utf-8")
        specs = SI.specs_from_markdown(tmp, 2)
    got = [(d.speaker, d.text) for s in specs for d in s.audio.dialogue]
    want = [t for _, t in DIALOGUE]
    out["dialogue"] = {"ok": [t for _, t in got] == want, "got": [t for _, t in got], "want": want}
    errs = []
    if not out["dialogue"]["ok"]:
        errs.append(f"对白与导演稿 / 现版 ep02 不逐字一致：应为 {want}，写成 {[t for _, t in got]}")
    if len(specs) != 9:
        errs.append(f"镜数 {len(specs)}，导演稿是 9 镜")
    for s in specs:
        e = []
        if s.index <= len(DURS) and s.duration_s != DURS[s.index - 1]:
            e.append(f"时长 {s.duration_s:g} 秒，导演稿是 {DURS[s.index - 1]} 秒")
        h3 = s.h3.text or ""
        _f, f = PR.split_fields(h3)
        body = f.get("integrated_multimodal_description") or ""
        r = check_writer_output(body, dialogue=[d.text for d in s.audio.dialogue], names=NAMES,
                                on_screen_anchors={c.name: [c.en_phrase] for c in s.visible if c.en_phrase},
                                absent_phrases={c.name: [c.en_phrase] for c in s.characters_on_screen
                                                if c.presence != "在画" and c.en_phrase})
        e += [f"{x['rule']}：{x['detail']}" for x in r.errors]
        sexes = [x for x in (L._sex(c.en_phrase) for c in s.faces) if x]
        e += [f"{i['code']}：{i['message']}" for i in L.lint_timeline(h3, frames_for_seconds(s.duration_s) / 24, sexes=sexes,
                                                                        strict=True, faces=bool(s.faces)) if i["level"] == "error"]
        if re.search(r"\b(flush\w*|blush\w*)\b", body, re.I):
            e.append("H3 里写了 flush / blush（导演稿要求脸颊不写泛红）")
        out["shots"][s.id] = e
        errs += [f"镜{s.index}：{x}" for x in e]
    out["errors"] = errs
    out["specs"] = specs
    return out


def validate_md(path: Path) -> dict:
    r = subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), str(ROOT / "tools/validate_qwen_script.py"), str(path), "--json"],
                       capture_output=True, cwd=ROOT, timeout=900, env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    d = json.loads(r.stdout.decode("utf-8"))
    (RUN / "validate.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"blocking": d.get("blocking"), "warnings": d.get("warnings"), "counts": d.get("counts")}


def compile_all(specs) -> dict:
    reg = R.load()
    (RUN / "prompts").mkdir(exist_ok=True)
    (RUN / "plans").mkdir(exist_ok=True)
    rows = {}
    rc_ref = "two_person_ref2va"
    for s in specs:
        s.source.rules_version = SI.rules_version()
        (RUN / "specs").mkdir(exist_ok=True)
        (RUN / "specs" / f"{s.id}.spec.json").write_text(s.model_dump_json(indent=1, by_alias=True), encoding="utf-8")
        auto = C.compile_shot(s, reg)
        # Ref2VA 六段：所有镜都按 two_person_ref2va 的参考图设置编译（单人镜也用脸部裁切做 <Picture N>）
        ref = C.compile_shot(s, reg, recipe_id=rc_ref)
        # I2VA：同一正文按官方 Case 2 转换（只给首帧）
        frames = frames_for_seconds(s.duration_s)
        i2 = PR.build_base(s, {"prompt": {}}, "i2va", frames)
        n = s.index
        (RUN / "prompts" / f"S{n}.ref2va.txt").write_text(ref["prompt"]["text"] + "\n", encoding="utf-8")
        (RUN / "prompts" / f"S{n}.i2va.txt").write_text(i2["text"] + "\n", encoding="utf-8")
        (RUN / "plans" / f"S{n}.auto.plan.json").write_text(json.dumps(auto, ensure_ascii=False, indent=1), encoding="utf-8")
        (RUN / "plans" / f"S{n}.ref2va.plan.json").write_text(json.dumps(ref, ensure_ascii=False, indent=1), encoding="utf-8")
        lint_ref = [f"{i['level']}:{i['code']}" for i in ref.get("lint", [])]
        lint_i2 = [f"{i['level']}:{i['code']}" for i in L.lint_prompt(i2["text"], "i2va", {"prompt": {}}, s, frames)]
        rows[s.id] = {"seconds": s.duration_s, "frames": frames, "auto_recipe": auto["recipe"]["id"], "auto_mode": auto.get("mode"),
                      "auto_status": auto["status"], "ref2va_status": ref["status"],
                      "ref_slots": [(x.get("character"), x.get("path")) for x in (ref.get("ref_slots") or [])],
                      "lint_ref2va": lint_ref, "lint_i2va": lint_i2,
                      "missing": [f"{m.rule}:{m.severity}" for m in missing_fields(s) if m.severity in ("block", "warn")],
                      "dialogue": [(d.speaker, d.text) for d in s.audio.dialogue]}
    return rows


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--recheck", action="store_true", help="不重写首稿，从现有 P4_ep02.md 开始校验 / 返修")
    ap.add_argument("--extra-from", default=None, help="返修轮号起点（续跑时避免覆盖 raw）")
    a = ap.parse_args(argv)
    (RUN / "raw").mkdir(parents=True, exist_ok=True)
    md_path = RUN / "P4_ep02.md"
    ledger_p = RUN / "ledger.json"
    ledger = json.loads(ledger_p.read_text(encoding="utf-8")) if ledger_p.exists() else []
    RW.OUT = RUN   # 记账写到本 run
    cur = CUR.read_text(encoding="utf-8")
    head = cur[cur.index("## ep02"): cur.index("**镜1｜img")]
    user = ("【导演稿】\n" + CUT.read_text(encoding="utf-8") + "\n\n【现版 ep02 集头（造型 / 配乐 / 人物表 / 场景表照抄）】\n" + head
            + "\n\n【现版 ep02 镜1（格式参考，只看格式）】\n" + cur[cur.index("**镜1｜img"): cur.index("**镜2｜img")])
    system, _ = SC.build_system_prompt(SC.load_config(), context=None, appendix_budget=0)
    system += "\n\n" + TASK
    msgs_user = user
    if not a.recheck:
        md = call(system, msgs_user, ledger)
        (RUN / "raw" / f"r0_{time.strftime('%H%M%S')}.md").write_text(md, encoding="utf-8")
        md_path.write_text(md, encoding="utf-8")
    md = md_path.read_text(encoding="utf-8")
    ck = checks(md)
    ALLOW = {"QW-E2", "H3-D7"}   # 9 镜、镜9 两位说话人 = 导演稿的实验设计

    def val_errs():
        validate_md(md_path)
        d = json.loads((RUN / "validate.json").read_text(encoding="utf-8"))
        out = []
        for ep in d.get("episodes", []):
            out += [f"集头 [{i['rule_id']}] {i['detail']}" for i in ep.get("issues", []) if i["level"] == "block" and i["rule_id"] not in ALLOW]
            for sh in ep.get("shots", []):
                out += [f"镜{sh['index']} [{i['rule_id']}] {i['detail']}" for i in sh["issues"]
                        if i["level"] == "block" and i["rule_id"] not in ALLOW]
        return out
    ck["errors"] += val_errs()
    start = int(a.extra_from) if a.extra_from else 1
    for rnd in range(start, start + a.rounds):
        if not ck["errors"]:
            break
        fix = ("【格式返修】下面是机检错误。请重新输出完整的这一集（`## ep02` 到 `---`），只改被点名的地方，内容仍以导演稿为准。\n"
               "说话句逐字照这个格式（H3-D2/X3）：`the on-screen 34-year-old East Asian man with a low restrained voice, natural pace (S1) says: <d>[Chinese] 台词</d>`"
               "——人物表的 VOICE 短语整段逐字照抄（例：with a low restrained voice, natural pace；不要改写成 in a … voice at a … pace），编号紧贴在 says 前；"
               "画外台词写 `… (S1) says in an off-screen voiceover: <d>…</d> while his lips remain completely closed.`；"
               "**人物** 行局部项的第三格只写 左 / 中 / 右（例：林晚（局部｜手｜左）、顾沉（局部｜肩｜右）），不写 前 / 后。\n"
               + "\n".join(f"- {e}" for e in ck["errors"][:40]) + "\n\n你上一版：\n" + md + "\n\n" + user)
        md = call(system, fix, ledger)
        (RUN / "raw" / f"r{rnd}_{time.strftime('%H%M%S')}.md").write_text(md, encoding="utf-8")
        md_path.write_text(md, encoding="utf-8")
        ck = checks(md)
        ck["errors"] += val_errs()
    v = validate_md(md_path)
    rows = compile_all(ck["specs"])
    rep = {"made": time.strftime("%Y-%m-%d %H:%M:%S"), "errors": ck["errors"], "dialogue": ck["dialogue"], "validate": v,
           "shots": rows, "spent_usd": round(sum(x.get("usd") or 0 for x in ledger), 4)}
    (RUN / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"errors": len(ck["errors"]), "dialogue_ok": ck["dialogue"]["ok"], "validate": v,
                      "spent": rep["spent_usd"],
                      "shots": {k: (r["auto_recipe"], r["ref2va_status"], [x for x in r["lint_ref2va"] if x.startswith("error")])
                                for k, r in rows.items()}}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
