"""一集开工前的资产就绪检查（PIPELINE_SOP_V2.md 第 8 步）：一次列出全部缺口，退出码 0 = 全部就绪，1 = 有缺口。

  episode_ready.py --run series10_v2 --episode 1 [--json]

不自己写规则，全部调现成函数：
  身份脸 / 造型 / 单品图 / 场景底图（preflight I2–I5 的来源）→ ns_agent.asset_refs.resolve_shot（missing 清单，preflight 同一份）、face_of；造型排期 → episode_look_override。设定图：preflight.sheet_gaps（I3 同一份；⤴ 11-03 起 O4 也要设定图，ISS-1103-030746-664a）
  display_name → 资产清单 manifest（和 cast_table.char_ids 同一份）
  音色 → ns_post.run_media.voice_config（unvoiced = 没选定音色） + cast_table.speaker_cast
  adult 标记 → 导入稿每镜的 adult / adult_reasons（compiler 写的）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "services" / "agent", ROOT / "services" / "post"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

OWNER = {"face": "资产线（项目方挑选身份脸）", "name": "资产线（填清单 display_name）", "schedule": "资产线（POST /api/character-hub/{cid}/schedule）", "item": "资产线（单品图补 file/sha256，接进造型）",
         "scene": "资产线 → 项目方挑场景底图", "voice": "项目方挑配角音色", "look": "写手 / 资产线（造型表与清单对不上）",
         "script": "总调度（导入稿缺失）"}
SHEET_OWNER = "资产作业 {job}（asset_worker 出设定图 → 代选 / 亲审；W2 11-03：preflight I3 同口径）"


def resolve_cid(run: str, cid: str, name: str) -> str:
    """人物不在清单时 resolve_shot 用名字当 id → 换成人物表（cast_table）里的真 id；换不到原样"""
    if cid != name:
        return cid
    try:
        from ns_agent import cast_table as CT
        return ((CT.speaker_cast(run) or {}).get("names") or {}).get(name, cid)
    except Exception:
        return cid


def shot_registered_looks(run: str, cid: str, episode: int, shots) -> dict[int, str]:
    """W-PROD 11-07（K 块，ep03 祁念 O1 + 亲密镜 O2）：逐镜结构化登记（shot_looks.json 画布 overrides / 系统登记 shots）里
    该人物在本集各镜的造型 id → {镜号: 造型}；没登记的镜不进结果。一集两套造型（整集排期写不下）时用逐镜登记代替整集排期"""
    from ns_agent import asset_refs as AR
    ovs, reg = AR.shot_overrides(run)[0], AR.registry_looks(run)
    out: dict[int, str] = {}
    for i in shots or ():
        sid = f"ep{int(episode):02d}-S{int(i)}"
        lid = ((ovs.get(sid) or {}).get(cid) or {}).get("look")
        if not lid:
            r = (reg.get(sid) or {}).get(cid)
            lid = r.get("look") if isinstance(r, dict) else r
        if isinstance(lid, str) and lid:
            out[int(i)] = lid
    return out


def character_gaps(run: str, cid: str, name: str, episode: int, mchars: dict | None = None, shots=None) -> list[dict]:
    """一个人物在某集的人物级资产缺口（UIFIX-F 11-03：和 check() 同一份代码，网页“确认造型”入口也按它判断，不另写口径）：
    身份脸（AR.face_of）、清单 display_name、本集造型排期（AR.episode_look_override）。每项 {kind, who, what, cid, name}
    shots（本集该人物出场镜号）给了且每镜都有逐镜结构化登记（shot_registered_looks，造型在清单里）= 已排期，不报 schedule"""
    from ns_agent import asset_refs as AR
    if mchars is None:
        mchars = (AR.manifest(run) or {}).get("characters") or {}
    who = f"{name}（{cid}）"
    out: list[dict] = []

    def g(kind: str, what: str):
        out.append({"kind": kind, "who": who, "what": what, "cid": cid, "name": name})

    if not AR.face_of(run, cid):
        g("face", "没有身份脸")
    if not (mchars.get(cid) or {}).get("display_name"):
        g("name", "清单里没有 display_name")
    mlooks = (mchars.get(cid) or {}).get("looks") or {}
    per_shot = shot_registered_looks(run, cid, episode, shots) if shots else {}
    by_shot = bool(shots) and len(per_shot) == len(set(shots)) and all(v in mlooks for v in per_shot.values())
    if cid in mchars and mlooks and not AR.episode_look_override(run, cid, episode) and not by_shot:
        g("schedule", "本集造型排期还没写进 hub_episode_looks.json（出图前先做本集造型排期）")
    return out


def check(run: str, episode: int, root: Path = ROOT) -> dict:
    from ns_agent import asset_refs as AR
    from ns_agent import run_paths as RP          # 导入稿路径只有一个来源（runs.script_path），不在这里写死
    src = Path(RP.runs_module(root).script_path(run, root))
    if not src.is_file():
        return {"run": run, "episode": episode, "ready": False, "shots": [], "gaps": [
            {"kind": "script", "who": "-", "what": f"没有导入稿 {src}", "owner": OWNER["script"], "shots": []}]}
    doc = json.loads(src.read_text(encoding="utf-8"))
    ep = next((e for e in doc.get("episodes") or [] if int(e.get("number") or 0) == episode), None)
    if ep is None:
        return {"run": run, "episode": episode, "ready": False, "shots": [], "gaps": [
            {"kind": "script", "who": "-", "what": f"导入稿里没有第 {episode} 集", "owner": OWNER["script"], "shots": []}]}
    gaps: list[dict] = []

    def gap(kind, who, what, shots=(), owner=None):
        for g in gaps:
            if (g["kind"], g["who"], g["what"]) == (kind, who, what):
                g["shots"] = sorted(set(g["shots"]) | set(shots))
                if owner and g["owner"] == OWNER[kind]:     # W7（A2 F5）：明确的作业 owner 优先于缺省 owner，不论哪条先到
                    g["owner"] = owner
                return
        gaps.append({"kind": kind, "who": who, "what": what, "owner": owner or OWNER[kind], "shots": sorted(set(shots))})

    man = AR.manifest(run) or {}
    mchars = man.get("characters") or {}
    chars: dict[str, dict] = {}          # cid -> {name, looks, shots}
    scenes: dict[str, set] = {}
    shots_out = []
    for s in ep.get("shots") or []:
        idx = s.get("index")
        sr = AR.resolve_shot(run, ep, s)          # 与 preflight 的 asset_refs 同一个函数
        for c in sr.characters:
            d = chars.setdefault(c["character"], {"name": c["name"], "looks": set(), "shots": set()})
            d["shots"].add(idx)
            if c.get("look"):
                d["looks"].add(c["look"])
        if sr.scene_id:
            scenes.setdefault(sr.scene_id, set()).add(idx)
        for m in sr.missing:                      # 口径 = preflight：I3（造型未登记 / 没有设定图）、I4（资产缺图）、I5（场景缺图）；身份脸缺图归 I2，下面按人报
            if m["kind"] == "场景缺图":
                gap("scene", sr.scene_id or "?", m["detail"], [idx])
            elif m["kind"] in ("造型未登记", "资产缺图"):
                cn = m.get("character") or "?"      # 人物根本没进清单时，造型对不上只是后果，不重复报（身份脸缺口里已有）
                hit = next((c for c, d in chars.items() if cn in (d["name"], c) and c in mchars), None)
                if hit is not None:
                    sheet = re.search(r"造型(\S+) 没有设定图$", m.get("detail", ""))
                    # W7（A2 第 18 轮 F5）：造型没有任何单品图时 asset_refs 发“资产缺图 / 没有设定图”——缺的仍是设定图，
                    # 归 sheet 资产作业（和 sheet_gaps 同一 owner），不是写手
                    gap("look" if m["kind"] == "造型未登记" or sheet else "item", cn, m["detail"], [idx],
                        owner=SHEET_OWNER.format(job=f"sheet-{hit}-{sheet.group(1)}") if sheet else None)
        # ISS-1103-030746-664a：I3 设定图口径复用 preflight.sheet_gaps（同一份判定）；缺设定图 = look 缺口 → asset_jobs 排 sheet 作业
        from ns_agent.gen_contract import preflight as _PF
        for m in _PF.sheet_gaps(getattr(sr, "subject", None), getattr(sr, "zones", None), sr.characters, getattr(sr, "warnings", None)):
            if m.get("cid") in mchars:      # 缺口归资产作业（asset_jobs 按 look 缺口排 sheet-<cid>-<造型>），不是写手的事
                gap("look", m["character"], m["detail"], [idx], owner=SHEET_OWNER.format(job=f"sheet-{m['cid']}-{m.get('look') or '?'}"))
        shots_out.append({"index": idx, "adult": bool(s.get("adult")), "reasons": s.get("adult_reasons") or [],
                          "scene": sr.scene_id, "cast": [c["name"] for c in sr.characters]})
    for cid, d in sorted(chars.items()):
        for g in character_gaps(run, resolve_cid(run, cid, d["name"]), d["name"], episode, mchars, shots=d["shots"]):
            gap(g["kind"], g["who"], g["what"], d["shots"])
    # 音色：本集说话人（对白）→ 人物表 → run_media.voice_config
    speakers: dict[str, set] = {}
    for s in ep.get("shots") or []:
        for dl in s.get("dialogue") or []:
            if dl.get("speaker"):
                speakers.setdefault(dl["speaker"], set()).add(s.get("index"))
    voices = {}
    if speakers:
        try:
            from ns_agent import cast_table as CT
            from ns_post import run_media as RM
            names = (CT.speaker_cast(run) or {}).get("names") or {}
            cfg = RM.voice_config(run, root)
            for sp, shs in sorted(speakers.items()):
                cid = names.get(sp)
                if cid is None:
                    gap("voice", sp, "说话人不在人物表（P1 人物表 / 清单别名）里", shs)
                elif cid in (cfg.get("unvoiced") or {}):
                    gap("voice", f"{sp}（{cid}）", "还没有选定音色", shs)
                elif cid not in (cfg.get("characters") or {}):
                    gap("voice", f"{sp}（{cid}）", "音色配置里没有这个人", shs)
                else:
                    voices[sp] = cfg["characters"][cid]["voice"]
        except Exception as e:      # voice_config 对配置问题是失败关闭（V2MediaError），当缺口报
            gap("voice", "-", f"音色配置读不出来：{str(e)[:160]}", [])
    res = {"run": run, "episode": episode, "ready": not gaps, "gaps": gaps, "shots": shots_out,
           "cast": {cid: {"name": d["name"], "looks": sorted(d["looks"])} for cid, d in sorted(chars.items())},
           "scenes": sorted(scenes), "voices": voices}
    return res


# GOLDEN-O 11-03 按镜就绪辅助函数。L-140（项目方 03:1x）：不做按镜就绪，维持整集判定——以下函数未接入任何流程，只留作并入 V1 时参考。
# 不另写规则：缺口仍是上面 check() 算的那一份（resolve_shot = preflight I3/I4/I5 + character_gaps = I2 / 清单 / 排期），
# 这里只按每条缺口的 shots 归到镜。音色不挡首帧（首帧是画面，音色是配音阶段的事）；没写镜号的缺口（导入稿 / 音色配置读不出）挡全部镜。
FIRST_FRAME_KINDS = ("face", "name", "schedule", "look", "item", "scene", "script")


def shot_readiness(res: dict) -> list[dict]:
    """每镜：{index, ready, adult, cast, blockers[]}。adult 镜永远 ready=False（只能由项目方触发），blockers 写明原因"""
    out = []
    for s in res.get("shots") or []:
        idx = s.get("index")
        bl = [f"[{g['kind']}] {g['who']}：{g['what']}" for g in res.get("gaps") or []
              if g.get("kind") in FIRST_FRAME_KINDS and (not g.get("shots") or idx in g["shots"])]
        if s.get("adult"):
            bl.insert(0, "成人镜：只能由项目方触发，系统不出")
        out.append({"index": idx, "ready": not bl, "adult": bool(s.get("adult")), "cast": s.get("cast") or [], "blockers": bl})
    return out


def ready_shots(res: dict) -> list[int]:
    """可以出金样首帧的镜号（按镜就绪）"""
    rows = res.get("shot_ready") if res.get("shot_ready") is not None else shot_readiness(res)
    return [r["index"] for r in rows if r["ready"]]


def plain_lines(res: dict) -> list[str]:
    """给 next_action / 汇报用的大白话：每个缺口一行"""
    out = []
    for g in res["gaps"]:
        sh = f"（镜 {','.join(str(x) for x in g['shots'])}）" if g.get("shots") else ""
        out.append(f"{g['who']}：{g['what']}{sh}，由{g['owner']}补")
    return out


def render(res: dict) -> str:
    L = [f"== {res['run']} 第 {res['episode']} 集资产就绪检查：{'全部就绪' if res['ready'] else '有 %d 个缺口' % len(res['gaps'])} =="]
    for g in res["gaps"]:
        L.append(f"[{g['kind']}] {g['who']}：{g['what']}｜谁补：{g['owner']}｜镜 {','.join(str(x) for x in g.get('shots') or []) or '-'}")
    L.append("-- 出场人物（造型）：" + "；".join(f"{d['name']}{d['looks'] or ''}" for d in (res.get("cast") or {}).values()))
    L.append("-- 场景：" + "、".join(res.get("scenes") or []) + "；已选音色：" + "、".join(f"{k}→{v}" for k, v in (res.get("voices") or {}).items()))
    L.append("-- 每镜 adult：")
    for s in res["shots"]:
        L.append(f"   镜{s['index']:>2} adult={'是' if s['adult'] else '否'}" + (f" 原因：{'；'.join(map(str, s['reasons']))}" if s["adult"] else ""))
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = check(a.run, a.episode)
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else render(res))
    return 0 if res["ready"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
