"""BGM brief：写作模型读本集 P3 / P4 + 时间轴 → nsfs.bgm_brief/1；校验不过带错误重写（≤ max_repair_rounds）。

    .venv/Scripts/python.exe tools/bgm/brief.py --run data/pipeline/runs/series10_v1 --ep 1 [--force]
产物：data/music/series10/epNN/brief.json（+ brief.report.json 每轮原文与问题）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm as L  # noqa: E402
from bgm_timeline import episode_inputs  # noqa: E402
from brief_schema import RULES, check_brief  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def load_cfg() -> dict:
    return json.loads((ROOT / "config" / "bgm.json").read_text(encoding="utf-8"))


def ep_dir(cfg: dict, ep: int) -> Path:
    d = ROOT / cfg["output"]["dir"] / f"ep{ep:02d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def system_prompt(cfg: dict) -> str:
    t = (ROOT / cfg["prompts"]["writer"]).read_text(encoding="utf-8")
    ex = (ROOT / cfg["prompts"]["example"]).read_text(encoding="utf-8").strip()
    rules = "\n".join(f"- {k}：{v}" for k, v in RULES.items())
    return t.replace("{{EXAMPLE}}", ex).replace("{{RULES}}", rules)


def user_message(inp: dict) -> str:
    tl = inp["timeline"]
    rows = ["| 镜 | 起点(秒) | 时长(秒) | 有人声 | 本镜【配乐】cue 原文 |", "|---|---|---|---|---|"]
    for s in tl["shots"]:
        rows.append(f"| {s['index']} | {s['start_s']:g} | {s['dur_s']:g} | "
                    f"{'是（' + '/'.join(s['voice_kinds']) + '）' if s['voice'] else '否'} | {s['music_cue'] or '—'} |")
    return "\n".join([
        f"本集：ep{inp['episode']:02d}，时间轴总长 duration_s = {tl['duration_s']:g} 秒（P3 目标时长 {tl.get('target_duration_s')} 秒，以时间轴为准）。",
        "", "【时间轴】", *rows, "",
        "【P4 分镜表】", inp["p4_text"], "",
        "【P3 单集剧本】", "```json", json.dumps(inp["p3"], ensure_ascii=False, indent=1), "```",
    ])


def input_sha(inp: dict, cfg: dict) -> str:
    h = hashlib.sha256()
    for part in (inp["p4_text"], json.dumps(inp["p3"], ensure_ascii=False, sort_keys=True), system_prompt(cfg)):
        h.update(part.encode("utf-8"))
    return h.hexdigest()


def make_brief(run_dir: Path, ep: int, *, force: bool = False, cfg: dict | None = None, log=print) -> dict:
    cfg = cfg or load_cfg()
    inp = episode_inputs(run_dir, ep)
    out = ep_dir(cfg, ep) / "brief.json"
    rep_p = out.with_name("brief.report.json")
    sha = input_sha(inp, cfg)
    if out.is_file() and not force:
        old = json.loads(out.read_text(encoding="utf-8"))
        if old.get("_input_sha256") == sha and not check_brief(old, inp["timeline"], ep):
            log(f"ep{ep:02d} brief：已有且输入未变、校验通过，复用")
            return old
    system = system_prompt(cfg)
    user = user_message(inp)
    rounds = []
    msgs_user = user
    brief = None
    for rnd in range(int(cfg["llm"]["max_repair_rounds"]) + 1):
        res = L.chat(system, msgs_user, cfg=cfg, max_tokens=int(cfg["llm"]["max_tokens_brief"]),
                     meta={"link": "P4-BGM", "episode": ep, "step": "brief", "round": rnd})
        txt = res["content"]
        try:
            obj = L.extract_json(txt)
            issues = check_brief(obj, inp["timeline"], ep)
        except ValueError as e:
            obj, issues = None, [{"rule": "BGM-B01", "level": "block", "msg": f"解析失败：{e}", "writer_text": RULES["BGM-B01"]}]
        rounds.append({"round": rnd, "model": res["model"], "purpose": res["purpose"], "usd": round(res["usd"], 5),
                       "finish": res["finish"], "issues": issues, "raw": txt})
        log(f"ep{ep:02d} brief 第 {rnd} 轮：{len(issues)} 个问题 {[i['rule'] for i in issues]}")
        if not issues:
            brief = obj
            break
        fix = "\n".join(f"- {i['rule']}：{i['msg']}（要求：{i['writer_text']}）" for i in issues)
        msgs_user = (user + "\n\n【上一版输出】\n```json\n" + (json.dumps(obj, ensure_ascii=False) if obj else txt[:6000])
                     + "\n```\n\n【校验没过，按下面逐条修正后重新输出完整 JSON】\n" + fix)
    rep = {"episode": ep, "input": {"p3": inp["p3_path"], "p4": inp["p4_path"]}, "timeline": inp["timeline"],
           "rounds": rounds, "status": "ok" if brief else "needs_writer", "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    rep_p.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    if not brief:
        raise RuntimeError(f"ep{ep:02d} brief 校验 {len(rounds)} 轮仍不过（{rep_p}）")
    brief["_input_sha256"] = sha
    brief["_writer"] = {"model": rounds[-1]["model"], "purpose": rounds[-1]["purpose"], "rounds": len(rounds),
                        "prompt": cfg["prompts"]["writer"]}
    brief["_timeline"] = inp["timeline"]
    out.write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    return brief


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--ep", type=int, required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    b = make_brief(ROOT / a.run, a.ep, force=a.force)
    print(json.dumps({k: v for k, v in b.items() if not k.startswith("_")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
