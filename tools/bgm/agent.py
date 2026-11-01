"""BGM agent（链接 P4-BGM）：每集 写作模型 brief → 本地 ACE-Step 候选 → 自动度量 + 系统闸门 → 审听模型挑选 → 不过就调整重出（≤3 轮）→ 交付。

    .venv/Scripts/python.exe tools/bgm/agent.py --run data/pipeline/runs/series10_v1 --eps 1-10 [--force-brief] [--rerun]
    .venv/Scripts/python.exe tools/bgm/agent.py --run ... --eps 3 --status

产物（每集）：
  data/music/series10/epNN.wav          选中的整集配乐（48 kHz 24-bit 立体声，−16 LUFS，真峰 ≤ −1 dBTP）
  data/music/series10/epNN.json         合成用（ns_post.music.find_music 格式：cues、shot_starts、duck、model、seed…）
  data/music/series10/epNN/meta.json    brief、模型、种子、全部候选度量、每轮决定与理由
  data/music/series10/epNN/cands/*.flac 全部候选（同响度，界面一键换用）
  data/music/series10/epNN/brief.json   写作模型的 brief（+ brief.report.json）
内容判断（brief、挑哪条、怎么改）全部由写作 / 审听模型做；系统只做度量、闸门（人声 / 削波 / 静音 / 时长）、调度与记录。
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
import deliver as D  # noqa: E402
import plain as PL  # noqa: E402
import remote as RM  # noqa: E402
from brief import ROOT, ep_dir, load_cfg, make_brief  # noqa: E402
from brief_schema import VOCAL_RE, _named, lyrics_tags  # noqa: E402

LOG = ROOT / "data" / "music" / "series10" / "agent.log"


def log(*a):
    line = f"{time.strftime('%H:%M:%S')} " + " ".join(str(x) for x in a)
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def jload(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def jsave(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def public(brief: dict) -> dict:
    return {k: v for k, v in brief.items() if not k.startswith("_")}


# ------------------------------------------------------------------ 候选参数（格式化 brief 字段，不改内容）
def caption_of(brief: dict, override: str | None = None) -> str:
    cap = (override or brief["caption_en"]).strip()
    extra = f" Instrumentation: {', '.join(brief['instrumentation'])}. Style: {', '.join(brief['style_words'])}."
    tail = " Instrumental only, no vocals."
    s = cap + (extra if len(cap) + len(extra) + len(tail) <= 500 else "") + tail
    return s[:510]


def seed_for(ep: int, rnd: int, k: int) -> int:
    return int(hashlib.sha256(f"bgm10-ep{ep}-r{rnd}-c{k}".encode()).hexdigest()[:7], 16)


def score_gen(gen: dict) -> dict | None:
    """打分机（CPU：CLAP + Demucs）。与生成机不同时返回它的连接参数；同一台返回 None"""
    sh = gen.get("score_host")
    if not sh or sh == gen["host"]:
        return None
    return {**gen, "host": sh, "workdir": gen.get("score_workdir") or gen["workdir"],
            "python": gen.get("score_python") or gen["python"]}


def build_candidates(ep: int, brief: dict, rnd: int, n: int, gen_dur: float, adjust: dict) -> list[dict]:
    b = brief["bpm"]
    tgt = float(adjust.get("bpm_target") or b["target"])
    tgt = min(max(tgt, float(b["min"])), float(b["max"]))
    bpms = [tgt, tgt, round((float(b["min"]) + tgt) / 2), round((tgt + float(b["max"])) / 2)]
    if adjust.get("fix_bpm"):
        bpms = [tgt] * 4
    neg = list(dict.fromkeys([*brief["negative"], *adjust.get("negative_add", [])]))
    cap = caption_of(brief, adjust.get("caption_en"))
    if adjust.get("caption_suffix"):
        cap = (cap[:-len(" Instrumental only, no vocals.")] + " " + adjust["caption_suffix"] + " Instrumental only, no vocals.")[:510]
    out = []
    for k in range(n):
        out.append({"id": f"r{rnd}_c{k + 1}", "round": rnd, "caption": cap, "lyrics": lyrics_tags(brief),
                    "bpm": int(round(bpms[k % len(bpms)])), "keyscale": brief.get("key") or "",
                    "timesignature": brief.get("time_signature") or 4, "duration": gen_dur,
                    "seed": seed_for(ep, rnd, k), "negative": ", ".join(neg)})
    return out


# ------------------------------------------------------------------ 系统闸门（只看可测项：人声 / 削波 / 静音 / 时长 / 明显反向）
def gate(m: dict, brief: dict, cfg: dict) -> tuple[bool, list[str], list[str]]:
    g, fails, flags = cfg["gates"], [], []
    if not m or m.get("error"):
        return False, ["error: " + str((m or {}).get("error"))[:120]], flags
    if m["vocal_rel_db"] > g["vocal_rel_db_max"] or (m["vocal_rel_db"] > g["vocal_rel_db_soft"] and m["p_vocal"] > g["p_vocal_max"]):
        fails.append(f"vocals（vocal_rel_db {m['vocal_rel_db']}，p_vocal {m['p_vocal']}）")
    if m["clip_ratio"] > g["clip_ratio_max"]:
        fails.append(f"clipping（{m['clip_ratio']:.4f}）")
    if m["longest_gap_s"] > g["longest_gap_s_max"]:
        fails.append(f"silence_gap（{m['longest_gap_s']} s）")
    if m["duration_s"] < float(brief["duration_s"]) - g["duration_short_s"]:
        fails.append(f"too_short（{m['duration_s']} s < {brief['duration_s']} s）")
    if m["clap"] < g["clap_min"]:
        fails.append(f"clap_low（{m['clap']}）")
    if m.get("energy_r", 0) < g["energy_r_min"]:
        fails.append(f"energy_inverse（r={m.get('energy_r')}）")
    if not m.get("tempo_ok"):
        flags.append(f"tempo_off（实测 {m['tempo_bpm']}，brief {brief['bpm']['min']}–{brief['bpm']['max']}）")
    if m.get("energy_r", 0) < cfg["soft"]["energy_r_good"]:
        flags.append(f"energy_weak（r={m.get('energy_r')}）")
    return not fails, fails, flags


def composite(m: dict) -> float:
    """排序参考（审听模型不选时的兜底），只用度量"""
    return round(m["clap"] + 0.15 * m.get("energy_r", 0) + (0.05 if m.get("tempo_ok") else 0) - 0.01 * max(0, m["vocal_rel_db"] + 30), 4)


# ------------------------------------------------------------------ 审听模型
def review(ep: int, brief: dict, table: list[dict], cfg: dict) -> dict:
    system = (ROOT / cfg["prompts"]["review"]).read_text(encoding="utf-8")
    rows = [{k: c[k] for k in ("id", "round", "seed", "bpm_param", "gate_pass", "gate_fail", "flags", "model")}
            | {"metrics": {k: v for k, v in c["metrics"].items() if k != "normalised"}} for c in table]
    user = (f"本集 ep{ep:02d} 的配乐 brief：\n```json\n{json.dumps(public(brief), ensure_ascii=False, indent=1)}\n```\n\n"
            f"候选度量表（{len(rows)} 条；gate_pass=false 的不能选）：\n```json\n{json.dumps(rows, ensure_ascii=False, indent=1)}\n```")
    passing = {c["id"] for c in table if c["gate_pass"]}
    last_err = ""
    for attempt in range(2):
        res = L.chat(system, user + last_err, cfg=cfg, max_tokens=int(cfg["llm"]["max_tokens_review"]),
                     meta={"link": "P4-BGM", "episode": ep, "step": "review", "attempt": attempt})
        try:
            d = L.extract_json(res["content"])
        except ValueError as e:
            last_err = f"\n\n上一次输出不是 JSON（{e}），只输出 JSON。"
            continue
        pick = d.get("pick")
        if pick is not None and pick not in passing:
            last_err = f"\n\n上一次 pick={pick} 不在闸门通过的候选里（可选：{sorted(passing) or '无'}），重新输出。"
            continue
        d["_model"], d["_usd"], d["_raw"] = res["model"], round(res["usd"], 5), res["content"]
        return d
    return {"pick": None, "reason": f"审听模型两次输出都不合格：{last_err.strip()}", "retry": None, "_invalid": True}


def retry_adjust(review_d: dict, table: list[dict], brief: dict) -> dict:
    """审听模型给的调整（校验格式）+ 由闸门失败项推出的确定性调整"""
    adj, notes = {}, []
    r = review_d.get("retry") or {}
    cap = str(r.get("caption_en") or "").strip()
    if cap:
        bad = _named(cap.split(" ", 1)[1] if " " in cap else "") or (VOCAL_RE.search(cap) and not
                                                                        "no vocal" in cap.lower() and "instrumental" not in cap.lower())
        if 40 <= len(cap) <= 450 and not bad:
            adj["caption_en"] = cap
            notes.append("caption ← 审听模型")
        else:
            notes.append(f"审听模型的 caption 不合格式（{bad or len(cap)}），不用")
    try:
        if r.get("bpm_target"):
            adj["bpm_target"] = float(r["bpm_target"])
            notes.append(f"bpm_target ← {adj['bpm_target']}")
    except (TypeError, ValueError):
        pass
    neg = [str(x) for x in (r.get("negative_add") or []) if isinstance(x, str) and len(x) < 60]
    fails = " ".join(" ".join(c["gate_fail"]) for c in table)
    if "vocals" in fails:
        neg += ["humming", "singing", "voice", "choir", "vocal chops"]
        adj["caption_suffix"] = "Pure instrumental arrangement with no voice of any kind."
        notes.append("人声被淘汰 → 加 negative 与纯器乐句")
    if "silence_gap" in fails:
        adj["caption_suffix"] = (adj.get("caption_suffix", "") + " A continuous sustained bed with no silent breaks.").strip()
        notes.append("静音段 → 要求连续铺底")
    if any("tempo_off" in " ".join(c["flags"]) for c in table):
        adj["fix_bpm"] = True
        notes.append("速度偏离 → 全部候选用 bpm_target")
    adj["negative_add"] = list(dict.fromkeys(neg))
    adj["_notes"] = notes
    return adj


# ------------------------------------------------------------------ 主流程
def run_episode(run_dir: Path, ep: int, cfg: dict, *, force_brief: bool = False, rerun: bool = False) -> dict:
    d = ep_dir(cfg, ep)
    meta_p = d / "meta.json"
    state = jload(meta_p, {}) or {}
    if state.get("status") == "delivered" and not rerun and not force_brief:
        log(f"ep{ep:02d} 已交付（{state['chosen']['id']}），跳过；--rerun 重做")
        return state
    brief = make_brief(run_dir, ep, force=force_brief, cfg=cfg, log=log)
    gen = cfg["generation"]
    gen_dur = round(max(float(brief["duration_s"]), float(brief["_timeline"].get("target_duration_s") or 0)) + float(gen["tail_s"]), 1)
    if rerun or state.get("brief_sha") != brief["_input_sha256"]:
        state = {"episode": ep, "brief_sha": brief["_input_sha256"], "brief": public(brief), "writer": brief["_writer"],
                 "rounds": [], "candidates": [], "status": "running", "gen_duration_s": gen_dur,
                 "prompts": cfg["prompts"], "gates": cfg["gates"]}
    adjust: dict = state.get("next_adjust") or {}
    start_round = len(state["rounds"]) + 1
    for rnd in range(start_round, int(gen["max_rounds"]) + 1):
        n = int(gen["candidates_round1"] if rnd == 1 else gen["candidates_retry"])
        cands = build_candidates(ep, brief, rnd, n, gen_dur, adjust)
        todo = cands
        results: dict = {}
        gen_info = []
        sgen = score_gen(gen)
        for attempt in range(4):           # 让道 / 生成失败的候选再投（最多 4 次）
            job_id = f"ep{ep:02d}_r{rnd}_{int(time.time())}"
            job = {"id": job_id, "episode": ep, "gen": gen, "out": cfg["output"], "tempo_tol": cfg["soft"]["tempo_tol"],
                   "brief": {k: brief[k] for k in ("duration_s", "bpm", "energy_curve", "instrumentation", "clap_text", "loopable")},
                   "candidates": todo, "score": sgen is None}
            found = RM.find_job(gen, ep, rnd, todo)   # 断点续跑：同一批候选（id + 种子 + caption）已在远端 → 接着做，不重投
            if found:
                job_id, jst = found
                job["id"] = job_id
                log(f"ep{ep:02d} 第 {rnd} 轮：接上远端已有作业 {job_id}（{jst}）")
            else:
                jst = "running"
                log(f"ep{ep:02d} 第 {rnd} 轮：投 {len(todo)} 条候选（{job_id}）")
                RM.submit(gen, job, d)
            if jst == "running":
                res = RM.wait(gen, job, log=log)
                if not res.get("ok"):
                    raise RuntimeError(f"ep{ep:02d} 远端失败：{res.get('error')}\n{res.get('trace', '')[-800:]}")
            else:
                res = RM.read_json(gen["host"], f"{gen['workdir']}/jobs/{job_id}/result.json") or {"ok": True}
            g = res.get("gen") or RM.read_json(gen["host"], f"{gen['workdir']}/jobs/{job_id}/gen.json") or {}
            gen_err = {cid: x["error"] for cid, x in (g.get("cands") or {}).items() if x.get("error")}
            metrics = res.get("metrics") or {}
            src = gen
            made = [c for c in todo if c["id"] not in gen_err and c["id"] not in (g.get("yielded") or [])]
            if made and not all(c["id"] in metrics for c in made):
                if sgen is None:
                    raise RuntimeError(f"ep{ep:02d} {job_id}：有候选没有度量")
                src = sgen
                sst = RM.job_state(sgen, job_id, made)
                if sst == "scored":
                    sres = RM.read_json(sgen["host"], f"{sgen['workdir']}/jobs/{job_id}/result.json")
                else:
                    if sst != "running":
                        log(f"ep{ep:02d} {job_id}：{len(made)} 条候选拷到 {sgen['host']} 打分")
                        RM.copy_between(gen, sgen, job_id, [f"{c['id']}.raw.wav" for c in made])
                        RM.submit(sgen, dict(job, candidates=made, score=True), d, cmd="score")
                    sres = RM.wait(sgen, dict(job, candidates=made), log=log)
                if not sres.get("ok"):
                    raise RuntimeError(f"ep{ep:02d} 打分失败：{sres.get('error')}\n{sres.get('trace', '')[-800:]}")
                metrics = sres.get("metrics") or {}
            gen_info.append({"job": job_id, "device": g.get("device"), "gpu": g.get("gpu"), "tier": g.get("tier"),
                             "lm": g.get("lm"), "load_s": g.get("load_s"), "vram_peak_mb": g.get("vram_peak_mb"),
                             "yielded": g.get("yielded"), "seconds": res.get("seconds"), "scored_on": src["host"]})
            for cid, m in metrics.items():
                results[cid] = (m, job_id, g)
                if "error" not in m:
                    raw = d / "cands" / f"{cid}.src.flac"
                    RM.get(src["host"], f"{src['workdir']}/jobs/{job_id}/{cid}.flac", raw)
                    # 交付响度：两遍 loudnorm 到 −16 LUFS / −1 dBTP（整体增益够不到时 ffmpeg 自动透明限幅），候选之间 A/B 同响度
                    m["delivery"] = D.loudnorm(raw, d / "cands" / f"{cid}.flac", cfg["output"]["lufs"], cfg["output"]["true_peak_db"])
                    raw.unlink(missing_ok=True)
            for cid, e in gen_err.items():   # 生成本身失败（超时 / 显存）= 基础设施问题：记下来，同一批参数重投，不占审听轮次
                results[cid] = ({"error": f"generation: {e}"[:300]}, job_id, g)
            todo = [c for c in todo if c["id"] in (g.get("yielded") or []) or c["id"] in gen_err]
            if not todo:
                break
            log(f"ep{ep:02d} 让道 / 生成失败：{len(todo)} 条候选重投（{list(gen_err.values())[:1]}）")
        if not any("error" not in m for m, _, _ in results.values()):
            state.setdefault("infra_failures", []).append({"round": rnd, "gen": gen_info, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                           "errors": {k: v[0].get("error") for k, v in results.items()}})
            jsave(meta_p, state)
            raise RuntimeError(f"ep{ep:02d} 第 {rnd} 轮生成全部失败（基础设施，不算审听轮次；重跑本集会接着做）")
        table_new = []
        for c in cands:
            if c["id"] not in results:
                continue
            m, job_id, g = results[c["id"]]
            ok, fails, flags = gate(m, brief, cfg)
            tier = (g or {}).get("tier") or {}
            table_new.append({"id": c["id"], "round": rnd, "seed": c["seed"], "bpm_param": c["bpm"], "caption": c["caption"],
                              "negative": c["negative"], "job": job_id, "device": (g or {}).get("device"), "gpu": (g or {}).get("gpu"),
                              "model": f"ACE-Step 1.5 {tier.get('model')}（{tier.get('steps')} 步"
                                       f"{'，int8' if tier.get('quant') else ''}{'，LM 1.7B' if (g or {}).get('lm') else ''}）",
                              "metrics": m, "gate_pass": ok, "gate_fail": fails, "flags": flags,
                              "composite": composite(m) if "error" not in m else None,
                              "file": f"data/music/series10/ep{ep:02d}/cands/{c['id']}.flac" if "error" not in m else None})
        state["candidates"] = [x for x in state["candidates"] if x["round"] != rnd] + table_new
        for c in table_new:
            log(f"ep{ep:02d} {c['id']} pass={c['gate_pass']} clap={c['metrics'].get('clap')} voc={c['metrics'].get('vocal_rel_db')} "
                f"tempo={c['metrics'].get('tempo_bpm')} r={c['metrics'].get('energy_r')} fail={c['gate_fail']} flags={c['flags']}")
        rv = review(ep, brief, state["candidates"], cfg)
        rec = {"round": rnd, "generated": [c["id"] for c in table_new], "gen": gen_info, "adjust_used": adjust,
               "review": {k: v for k, v in rv.items() if k != "_raw"}, "review_raw": rv.get("_raw"),
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        state["rounds"].append(rec)
        if rv.get("pick"):
            rec["decision"] = f"审听模型选 {rv['pick']}"
            D.deliver(ep, state, cfg, rv["pick"], rv.get("reason") or "", "review_llm")
            jsave(meta_p, state)
            try:
                state = PL.plain_episode(ep, cfg, log=log) or state
            except Exception as e:  # noqa: BLE001
                log(f"ep{ep:02d} 人话理由没生成（界面回退）：{e}")
            state.pop("next_adjust", None)
            jsave(meta_p, state)
            log(f"ep{ep:02d} ✔ 选 {rv['pick']}：{rv.get('reason')}")
            return state
        adjust = retry_adjust(rv, table_new, brief)
        rec["decision"] = f"本轮不选（{rv.get('reason')}）→ 下一轮调整：{adjust.get('_notes')}"
        state["next_adjust"] = adjust
        jsave(meta_p, state)
        log(f"ep{ep:02d} 第 {rnd} 轮不选：{rv.get('reason')} → {adjust.get('_notes')}")
    pool = [c for c in state["candidates"] if c["gate_pass"]]
    if pool:
        best = max(pool, key=lambda c: c["composite"])
        why = (f"审听模型 {gen['max_rounds']} 轮都没有选；按系统度量综合分（clap + 0.15·energy_r + 速度命中）取闸门通过里最高的 "
               f"{best['id']}（composite {best['composite']}），记为兜底，待项目方试听")
        state["rounds"][-1]["decision"] += f"；兜底：{why}"
        D.deliver(ep, state, cfg, best["id"], why, "fallback_metrics")
        jsave(meta_p, state)
        try:
            state = PL.plain_episode(ep, cfg, log=log) or state
        except Exception as e:  # noqa: BLE001
            log(f"ep{ep:02d} 人话理由没生成（界面回退）：{e}")
        state["needs_owner_listen"] = True
        log(f"ep{ep:02d} 兜底交付 {best['id']}")
    else:
        state["status"] = "needs_owner"
        log(f"ep{ep:02d} ✘ {gen['max_rounds']} 轮没有候选通过闸门，不交付（合成继续 --no-bgm）")
    jsave(meta_p, state)
    return state


def parse_eps(s: str) -> list[int]:
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--eps", default="1-10")
    ap.add_argument("--force-brief", action="store_true")
    ap.add_argument("--rerun", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_cfg()
    eps = parse_eps(a.eps)
    if a.status:
        for ep in eps:
            st = jload(ep_dir(cfg, ep) / "meta.json", {}) or {}
            print(ep, st.get("status"), (st.get("chosen") or {}).get("id"), len(st.get("candidates") or []))
        return 0
    bad = 0
    for ep in eps:
        try:
            run_episode(ROOT / a.run, ep, cfg, force_brief=a.force_brief, rerun=a.rerun)
        except Exception as e:  # noqa: BLE001
            bad += 1
            log(f"ep{ep:02d} 失败：{type(e).__name__}: {e}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
