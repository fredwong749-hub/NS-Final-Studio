"""SOP 阶段闸门（HARNESS-O 11-03，项目方 03:4x：“我需要一个 structure 的 infra 在做这个事情，需要 harness 的 system 在做这个事情”）。

每集只认一条阶段序列（docs/master/PIPELINE_SOP_V2.md 第 6–10 步）：
  剧本 → 导入闸门 → 资产就绪 → 提示词（编译 + preflight 都过）→ 出图 → 出图检测 → 尾帧 → 视频（必须先过 Q9）→ 整集预览
另一条：第 N+1 集要进“出图”，第 N 集的复盘 RETRO（tools/master/episode_retro.py）必须已经 done；写作阶段不挡。

对外：
  require(run, ep, stage, shot=None)   进入 stage 前调用；前面任一阶段没有通过证据 → 抛 SopGateError（enforce）
                                        或只记违规不抛（observe，见 config/pipeline/sop_gate.json observe_stages）
  filter_jobs(run, jobs, stage, rec)    asset_worker 出图分支用：挡掉没过闸门的作业（observe 时全放行、只记录）
  filter_video_specs(run, specs)        build_jobs 用：没过“视频”闸门的集不编视频作业
  vidgen_guard(run, vid_dir)            vidgen 用：服务器上没有笔记本证据 → 只记一条，不挡（笔记本侧 build_jobs / night 已挡）

只读命令：
  .venv/Scripts/python.exe tools/master/sop_gate.py status --run series10_v2 [--json]
  .venv/Scripts/python.exe tools/master/sop_gate.py check --run R --episode N --stage 出图 [--shot K]
  .venv/Scripts/python.exe tools/master/sop_gate.py probe-prompts --run R --episode N   # 逐镜编译 + preflight（不出图），写提示词证据
  .venv/Scripts/python.exe tools/master/sop_gate.py promote --run R [--apply]           # preparing → producing 的判定（--apply 才写 runs.json）

唯一阶段模型（PRODMERGE-O 11-03，PLAN_V2_MASTER v4 1-3）：网页 /api/sop/status（ns_api/sop.py）、/api/pipeline/status、RSI 计分板
（sentinel/scorecard.stage_of）、v2_live 都读 stage_view()；不再各自判阶段，stage_status.json 退役（没有写入方）。
成人镜（导入稿 shot.adult）在提示词 / 出图 / 出图检测 / 尾帧 / 视频记 pending_owner，不算阻断（L-128：只由项目方触发）。

证据全部复用现有产物，不另起平行状态：
  剧本 / 导入闸门 ← data/pipeline/runs/<run>/P4_epNN.md + autoflow_epNN.json（gate=ok 且 import=imported|reimported；reopened = 不过）
  资产就绪       ← data/pipeline/asset_jobs/<run>/_ready_epNN.json（episode_ready 写；ready 且 gaps=0）
  提示词         ← data/pipeline/sop_gate/<run>/epNN_prompts.json（probe-prompts 逐镜调唯一编译入口 build_first + preflight 写；导入稿 sha / 资产清单变了即过期）
  出图 / 检测 / 尾帧 ← data/renders/<run>/epNN/SN/takes.json（active image / last + postflight + Q9）——帧只记这一本账（ab 金样账不再认）
  视频           ← data/pipeline/runs/<run>/video/clips/epNN/epNN-SN__*.mp4
  整集预览       ← data/episodes/<run>/epNN*.mp4
违规记录：data/pipeline/sop_gate/violations.jsonl（master_check 读）。V1（legacy_unprefixed_run）不走 V2 SOP，直接放行。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGES = ["剧本", "导入闸门", "资产就绪", "提示词", "出图", "出图检测", "尾帧", "视频", "整集预览"]
SHOT_STAGES = {"提示词", "出图", "出图检测", "尾帧"}          # 可以按镜判；不给镜号 = 本集每一镜都要过
RETRO_FROM = STAGES.index("出图")                           # 第 N+1 集从“出图”起要第 N 集复盘 done
GATE_OK = {"ok"}
IMPORT_OK = {"imported", "reimported"}
PENDING_OWNER_STAGES = {"提示词", "出图", "出图检测", "尾帧", "视频"}   # 成人镜在这些阶段 = 等项目方触发，不算阻断
DEFAULT_CFG = {"enabled": True, "observe_stages": [], "prompt_probe": "build_first+preflight", "probe_lane": "gpu36:0",
               "probe_timeout_s": 900, "promote": {"auto": False, "stage": "出图"}}
# 旧网页 S1–S5 与本模型九阶段的对应（ns_api/sop.py、scorecard 显示用；判定只在这里）
LEGACY_STAGE = {"剧本": "S1", "导入闸门": "S1", "资产就绪": "S2", "提示词": "S3", "出图": "S3", "出图检测": "S3", "尾帧": "S3",
                "视频": "S4", "整集预览": "S5", "完成": "done"}


class SopGateError(RuntimeError):
    """前一阶段没有通过证据：不许进入本阶段（失败关闭）"""


# ------------------------------------------------------------------ 小工具
def _j(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):   # arch-ok: 证据文件缺 / 坏 = 没有证据（按不过算）
        return default


def config(root: Path = ROOT) -> dict:
    """真实仓库：配置读不到 = 默认全部 enforce（失败关闭）；测试夹具根目录（不是本仓库）没有配置 = 闸门不启用"""
    d = _j(root / "config/pipeline/sop_gate.json", None)
    if not isinstance(d, dict):
        return {**DEFAULT_CFG, "enabled": Path(root).resolve() == ROOT.resolve()}
    return {**DEFAULT_CFG, **d}


def _registry(root: Path) -> dict:
    return _j(root / "config/pipeline/runs.json", {}) or {}


def _runs():
    """按剧取路径的唯一入口 tools/autopilot/runs.py（导入稿 / 渲染根，K-OPS-F24；不在这里写死路径）"""
    if "_RUNS" not in globals():
        import importlib.util as _u
        sp = _u.spec_from_file_location("runs_for_sop_gate", ROOT / "tools/autopilot/runs.py")
        m = _u.module_from_spec(sp)
        sp.loader.exec_module(m)
        globals()["_RUNS"] = m
    return globals()["_RUNS"]


def _episodes_rel(run: str) -> Path:
    """整集成片 / 预览目录（相对仓库）：唯一口径 tools/series10_video/run_ctx.episodes_out（V1 legacy 沿用旧目录，其它剧 = data/episodes/<剧>）。
    A-G1 第 22 轮 P2：这里原来写死 "series10"，改为按 run 交给 run_ctx 判，不在 sop_gate 里另记一份 V1 目录名。
    run_ctx.py 随视频链（CUT_PLAN G4）入版；它还不在的树（sv-17 cut A、服务器镜像）退回同一规则的旧写法，cut B 后可删这个回退"""
    p = ROOT / "tools/series10_video/run_ctx.py"
    if not p.is_file():
        return Path("data/episodes") / ("series10" if is_legacy(run) else run)
    if "_RUN_CTX" not in globals():
        import importlib.util as _u
        sp = _u.spec_from_file_location("run_ctx_for_sop_gate", p)
        m = _u.module_from_spec(sp)
        sp.loader.exec_module(m)
        globals()["_RUN_CTX"] = m
    rc = globals()["_RUN_CTX"]
    return Path(rc.episodes_out(run)).relative_to(rc.ROOT)


def is_legacy(run: str, root: Path = ROOT) -> bool:
    return bool(run) and run == _registry(root).get("legacy_unprefixed_run")


def _run_dir(root: Path, run: str) -> Path:
    return root / "data/pipeline/runs" / run


def episodes_of(run: str, root: Path = ROOT) -> list[int]:
    """本剧已开工的集：autoflow_epNN.json 或导入稿里有的集"""
    eps = {int(m.group(1)) for f in _run_dir(root, run).glob("autoflow_ep*.json")
           if (m := re.match(r"autoflow_ep(\d+)\.json$", f.name))}
    doc = _j(_runs().import_path(run, root), {}) or {}
    eps |= {int(e.get("number")) for e in doc.get("episodes") or [] if e.get("number") is not None}
    return sorted(eps)


def _ep_shots(run: str, ep: int, root: Path) -> list[dict]:
    doc = _j(_runs().import_path(run, root), {}) or {}
    for e in doc.get("episodes") or []:
        if int(e.get("number") or -1) == int(ep):
            return list(e.get("shots") or [])
    return []


def shots_of(run: str, ep: int, root: Path = ROOT) -> list[int]:
    return sorted(int(s.get("index")) for s in _ep_shots(run, ep, root))


def adult_shots_of(run: str, ep: int, root: Path = ROOT) -> set[int]:
    """导入稿里带成人标记的镜（shot.adult）：只由项目方触发，阶段判定记 pending_owner"""
    return {int(s.get("index")) for s in _ep_shots(run, ep, root) if s.get("adult")}


def _af(root: Path, run: str, ep: int) -> dict:
    return _j(_run_dir(root, run) / f"autoflow_ep{ep:02d}.json", {}) or {}


def _stage_of(af: dict, sid: str) -> dict:
    return next((s for s in af.get("stages") or [] if s.get("id") == sid), {})


def retro_path(run: str, ep: int, root: Path = ROOT) -> Path:
    """复盘文件：主剧 docs/master/RETRO_epNN.md；别的剧 RETRO_<run>_epNN.md"""
    prim = _registry(root).get("primary")
    name = f"RETRO_ep{ep:02d}.md" if run == prim else f"RETRO_{run}_ep{ep:02d}.md"
    return root / "docs/master" / name


def retro_state(run: str, ep: int, root: Path = ROOT) -> str:
    """missing / draft / done（文件里 `retro_status: done` 那一行，episode_retro.py done 写）"""
    p = retro_path(run, ep, root)
    if not p.is_file():
        return "missing"
    m = re.search(r"retro_status:\s*(\w+)", p.read_text(encoding="utf-8"))
    return (m.group(1) if m else "draft")


# ------------------------------------------------------------------ 各阶段证据
def _ok(stage: str, ok: bool, why: str = "", **kw) -> dict:
    return {"stage": stage, "ok": bool(ok), "why": why, **kw}


def check_script(root: Path, run: str, ep: int) -> dict:
    p = _run_dir(root, run) / f"P4_ep{ep:02d}.md"
    if not p.is_file() or p.stat().st_size == 0:
        return _ok("剧本", False, f"没有 {p.relative_to(root).as_posix()}（P4 分镜还没交）")
    return _ok("剧本", True, "P4 在")


def check_import(root: Path, run: str, ep: int) -> dict:
    af = _af(root, run, ep)
    g, im = _stage_of(af, "gate"), _stage_of(af, "import")
    if g.get("status") in GATE_OK and im.get("status") in IMPORT_OK:
        return _ok("导入闸门", True, f"gate=ok import={im.get('status')} {im.get('at', '')}", sha=im.get("sha256"))
    code = _stage_of(af, "code")
    fails = code.get("fails")
    why = f"gate={g.get('status') or '无'} import={im.get('status') or '无'}"
    if fails:
        why += f"；代码判定 {fails} 项未过"
        det = code.get("detail")
        if isinstance(det, list) and det:
            why += f"（例：{str(det[0])[:70]}）"
    if af.get("next_action"):
        why += f"；{af['next_action']}"
    return _ok("导入闸门", False, why, sha=im.get("sha256"), earlier_import=bool(im.get("sha256")))


def check_assets(root: Path, run: str, ep: int) -> dict:
    r = _j(root / "data/pipeline/asset_jobs" / run / f"_ready_ep{ep:02d}.json", None)
    if not r:
        return _ok("资产就绪", False, "没有 episode_ready 结果（_ready_epNN.json）")
    if r.get("ready") and not r.get("gaps"):
        return _ok("资产就绪", True, f"episode_ready 全部就绪 {r.get('at', '')}", at=r.get("at"))
    return _ok("资产就绪", False, f"episode_ready 缺口 {r.get('gaps')} 个", at=r.get("at"))


def _prompt_file(root: Path, run: str, ep: int) -> Path:
    return root / "data/pipeline/sop_gate" / run / f"ep{ep:02d}_prompts.json"


def _manifest_path(root: Path, run: str) -> Path:
    reg = (_registry(root).get("runs") or {}).get(run) or {}
    return root / (reg.get("assets_manifest") or f"assets_v2/manifest.json")


# W38（11-04）：清单里每次写入都会刷新的字段——不进按集指纹（别集的资产作业一写清单就把本集证据判过期，ep01 因此反复卡在“提示词”）
MANIFEST_VOLATILE = ("updated_at",)
MANIFEST_SCOPED = ("characters", "scenes")


def _manifest_sha(root: Path, run: str, keys: list | None = None) -> str | None:
    """keys=None → 整个清单文件的 sha（旧口径，旧证据沿用）；keys=["characters/<cid>", "scenes/<sid>", ...] → 只对本集用到的
    人物 / 场景条目 + 其余顶层字段（去掉 updated_at）算 sha：别集的人物 / 场景变了不作废本集证据，本集用到的变了照样作废"""
    mp = _manifest_path(root, run)
    try:
        raw = mp.read_bytes()
    except OSError:     # arch-ok: 没有清单 = 指纹 None（与证据里的 None 相等，测试夹具用）
        return None
    if keys is None:
        return hashlib.sha256(raw).hexdigest()[:16]
    try:
        m = json.loads(raw.decode("utf-8"))
    except ValueError:  # arch-ok: 清单读不成 JSON = 按整文件 sha（失败关闭：与按集指纹对不上 → 证据过期）
        return hashlib.sha256(raw).hexdigest()[:16]
    want = {tuple(str(k).split("/", 1)) for k in keys if "/" in str(k)}
    sub = {k: v for k, v in m.items() if k not in MANIFEST_VOLATILE and k not in MANIFEST_SCOPED}
    for sec in MANIFEST_SCOPED:
        sub[sec] = {i: v for i, v in (m.get(sec) or {}).items() if (sec, i) in want}
        sub[sec].update({i: None for s, i in want if s == sec and i not in sub[sec]})   # 用到但清单里没有 = None（之后补上即过期）
    blob = json.dumps(sub, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "k:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def manifest_keys_for(root: Path, run: str, job: dict) -> list[str]:
    """编译出的作业实际用到的清单条目：人物 / 场景的 id、display_name 或其资产路径出现在作业（提示词 / 参考 / 资产引用 / 演员表）里"""
    try:
        m = json.loads(_manifest_path(root, run).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 没有清单 = 无条目（指纹仍会带上其余字段）
        return []
    text = json.dumps({k: job.get(k) for k in ("prompt", "refs", "asset_refs", "cast")}, ensure_ascii=False, default=str)
    out = []
    for sec in MANIFEST_SCOPED:
        for i, v in (m.get(sec) or {}).items():
            names = [i] + ([v["display_name"]] if isinstance(v, dict) and v.get("display_name") else [])
            if any(n and n in text for n in names):
                out.append(f"{sec}/{i}")
    return sorted(out)


def prompt_fingerprint(root: Path, run: str, ep: int, keys: list | None = None) -> dict:
    """提示词证据的有效条件：导入稿 sha（autoflow import 段）+ 资产清单 sha；任何一个变了，旧证据作废。
    keys（证据里的 manifest_keys）给了 → 清单只按本集用到的条目算（W38）"""
    return {"import_sha": _stage_of(_af(root, run, ep), "import").get("sha256"), "manifest_sha": _manifest_sha(root, run, keys)}


def check_prompts(root: Path, run: str, ep: int, shot: int | None = None) -> dict:
    ev = _j(_prompt_file(root, run, ep), None)
    if not ev:
        return _ok("提示词", False, "还没有逐镜编译 + preflight 证据（跑 sop_gate.py probe-prompts）", shots={})
    # W38：整文件指纹对得上（旧口径）或按集指纹对得上（证据带 manifest_keys + fingerprint_scoped）都算有效——
    # 别集资产作业写清单只刷新整文件 sha，不动本集用到的条目
    keys = ev.get("manifest_keys")
    scoped = prompt_fingerprint(root, run, ep, keys) if isinstance(keys, list) else None
    fresh = ev.get("fingerprint") == prompt_fingerprint(root, run, ep) or (
        scoped is not None and scoped in (ev.get("fingerprint"), ev.get("fingerprint_scoped")))
    if not fresh:
        return _ok("提示词", False, f"证据过期（{ev.get('at')} 之后导入稿或资产清单变了，重跑 probe-prompts）", shots={})
    rows = {int(k): v for k, v in (ev.get("shots") or {}).items()}
    want, pend = _want(run, ep, root, shot, rows)
    bad = [n for n in want if not (rows.get(n) or {}).get("ok")]
    tail = f"；成人镜 {','.join(map(str, pend))} 等项目方触发" if pend else ""
    if bad:
        eg = (rows.get(bad[0]) or {}).get("why") or "没有这一镜的证据"
        return _ok("提示词", False, f"{len(want) - len(bad)}/{len(want)} 镜过；镜{bad[0]}：{str(eg)[:90]}{tail}", shots=rows, bad=bad,
                   pending_owner=pend)
    if not want:
        return _ok("提示词", False, "导入稿里没有本集镜头" if not pend else f"本集只有成人镜{tail}", shots=rows,
                   pending_owner=pend)
    return _ok("提示词", True, f"{len(want)}/{len(want)} 镜编译 + preflight 过（{ev.get('at')}）{tail}", shots=rows, pending_owner=pend)


def _want(run: str, ep: int, root: Path, shot: int | None, rows) -> tuple[list[int], list[int]]:
    """本阶段要判的镜 + 记 pending_owner 的成人镜（不算阻断）"""
    allv = [shot] if shot else (shots_of(run, ep, root) or sorted(rows))
    adult = adult_shots_of(run, ep, root)
    return [n for n in allv if n not in adult], [n for n in allv if n in adult]


def _q9_pass(pf: dict) -> bool:
    """Q9 过 = pass；或 na 且看图模型真看过（evidence.model 有值 = 只记录项缺陷，config/vqa.json 定为不阻断）。
    W38（11-04）：原来只认 pass → 看图只报“只记录”缺陷（accessory_mismatch / posed_stiff 等）的首帧，producer 判过并定稿、
    视频编单（vqa.contract.q9_passed：pass / na）也认，唯独本闸门永远“出图检测”不过 → 尾帧全挡（ep01 S6）。
    没看成的 na（“只记录（没有本地看图结果）”，evidence 无 model）仍不过（失败关闭）"""
    q9 = next((i for i in pf.get("items") or [] if i.get("id") == "Q9"), None)
    if not q9:
        return False
    if q9.get("status") == "pass":
        return True
    return q9.get("status") == "na" and bool((q9.get("evidence") or {}).get("model"))


def shot_frames(root: Path, run: str, ep: int) -> dict[int, dict]:
    """每镜 {image, checked, last}：只读 takes.json（active image / last + postflight + Q9；帧只记这一本账，PRODMERGE-O）"""
    out: dict[int, dict] = {}
    base = Path(_runs().renders_dir(run, root)) / f"ep{ep:02d}"
    for tj in sorted(base.glob("S*/takes.json")):
        m = re.match(r"S(\d+)$", tj.parent.name)
        if not m:
            continue
        d = _j(tj, {}) or {}
        takes = d.get("takes") or []
        row = out.setdefault(int(m.group(1)), {"image": False, "checked": False, "last": False})
        ni = (d.get("active") or {}).get("image")
        t = next((x for x in takes if x.get("stage") == "image" and x.get("n") == ni), None)
        if t and t.get("file") and (root / "data" / t["file"]).exists():
            pf = t.get("postflight") or t.get("contract") or {}
            row["image"] = True
            row["checked"] = row["checked"] or (bool(pf.get("ok")) and _q9_pass(pf) and not t.get("master_reject"))
        nl = (d.get("locked") or {}).get("last")
        locked = nl is not None
        nl = nl if locked else (d.get("active") or {}).get("last")
        tl = next((x for x in takes if x.get("stage") == "last" and x.get("n") == nl), None)
        if tl and tl.get("file") and (root / "data" / tl["file"]).exists():
            pfl = tl.get("postflight") or tl.get("contract") or {}
            row["last"] = row["last"] or locked or bool(pfl.get("ok"))
    # L-185（总调度 11-04 06:3x）：视频走 i2va 只给首帧（L-088），尾帧“尽力、不阻断”——首帧已过检 且 尾帧尽力用尽（producer 账本
    # last:<镜> final=best_effort）→ 本镜按尾帧已过处理（last_best_effort=True），尾帧后台继续重出，产出后标待复核
    # 证据两路：本机 producer 账本 best_effort；或 takes.json 里已有 ≥ LAST_TRIES 版打过分的尾帧且没有一版过（视频机 gpu36 没有
    # gpu33 的账本，只有 relay 过来的 takes.json）
    led = _producer_ledger(root, run)
    for n, row in out.items():
        if row["last"] or not row["checked"]:
            continue
        tj = _j(base / f"S{n}" / "takes.json", {}) or {}
        lasts = [x for x in tj.get("takes") or [] if x.get("stage") == "last" and isinstance(x.get("postflight"), dict)
                 and x["postflight"].get("ok") is not None]
        if (led.get(f"last:ep{int(ep):02d}-S{n}") or {}).get("final") == "best_effort" or (
                len(lasts) >= LAST_TRIES and not any(x["postflight"].get("ok") for x in lasts)):
            row["last"] = True
            row["last_best_effort"] = True
    if _no_last(run, ep, root):        # L-197 A：本集视频只用首帧（I2VA），尾帧不需要 → 全镜按“尾帧已过”处理，不挡视频
        for row in out.values():
            row["last"], row["last_na"] = True, True
    return out


LAST_TRIES = 3          # = producer.MAX_TRIES（尾帧自动重出次数）


def _producer_ledger(root: Path, run: str) -> dict:
    """producer 账本（data/producer/runs/<剧>/attempts.json；V1 legacy = data/producer/attempts.json）；读不到 = {}（L-185 不放行）"""
    p = root / "data/producer" / ("attempts.json" if is_legacy(run, root) else f"runs/{run}/attempts.json")
    d = _j(p, {}) or {}
    return d.get("objects", d) if isinstance(d, dict) else {}


def _per_shot(stage: str, key: str, root: Path, run: str, ep: int, shot: int | None, what: str) -> dict:
    fr = shot_frames(root, run, ep)
    want, pend = _want(run, ep, root, shot, fr)
    tail = f"；成人镜 {','.join(map(str, pend))} 等项目方触发" if pend else ""
    if not want:
        return _ok(stage, False, ("本集只有成人镜" + tail) if pend else "导入稿里没有本集镜头", pending_owner=pend)
    bad = [n for n in want if not (fr.get(n) or {}).get(key)]
    if bad:
        return _ok(stage, False, f"{len(want) - len(bad)}/{len(want)} 镜{what}；缺 镜{','.join(map(str, bad[:8]))}{tail}", bad=bad,
                   pending_owner=pend)
    return _ok(stage, True, f"{len(want)}/{len(want)} 镜{what}{tail}", pending_owner=pend)


def check_images(root, run, ep, shot=None):
    return _per_shot("出图", "image", root, run, ep, shot, "有首帧")


def check_image_qc(root, run, ep, shot=None):
    return _per_shot("出图检测", "checked", root, run, ep, shot, "首帧过契约 + Q9")


def _no_last(run, ep, root) -> bool:
    """L-197 A：config/compile/run_style.json runs.<run>.video_mode（ns_agent.video_mode.no_last，唯一入口）"""
    _sys_paths(Path(root))
    from ns_agent import video_mode as VM
    return VM.no_last(run, ep, Path(root))


def check_lasts(root, run, ep, shot=None):
    if _no_last(run, ep, root):
        return _ok("尾帧", True, "L-197 A：本集视频只用首帧（I2VA），不出尾帧、不挡视频")
    return _per_shot("尾帧", "last", root, run, ep, shot, "有过契约的尾帧")


def check_video(root: Path, run: str, ep: int) -> dict:
    vid = _run_dir(root, run) / "video" / "clips" / f"ep{ep:02d}"
    want, pend = _want(run, ep, root, None, [])          # REVIEW-A P1④：成人镜 = 待项目方触发，不计入未通过（DoD 第 6 项）
    tail = f"；成人镜 {','.join(map(str, pend))} 等项目方触发" if pend else ""
    if not want:
        return _ok("视频", False, ("本集只有成人镜" + tail) if pend else "导入稿里没有本集镜头", pending_owner=pend)
    bad = [n for n in want if not list(vid.glob(f"ep{ep:02d}-S{n}__*.mp4"))]
    if bad:
        return _ok("视频", False, f"{len(want) - len(bad)}/{len(want)} 镜有片段；缺 镜{','.join(map(str, bad[:8]))}{tail}", bad=bad,
                   pending_owner=pend)
    return _ok("视频", True, f"{len(want)}/{len(want)} 镜有片段{tail}", pending_owner=pend)


_JST = None
_IMPORT_LOG_CACHE: dict = {}


def _jst():
    global _JST
    if _JST is None:
        from datetime import timedelta, timezone
        _JST = timezone(timedelta(hours=9))      # 项目时间一律 JST（不依赖本机时区）
    return _JST


def _parse_jst(s) -> float | None:
    """“2026-11-05T19:10:52” / “2026-11-05 19:10:52”（JST 朴素时间）→ epoch；认不出 = None"""
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(s).strip().replace(" ", "T")[:19]).replace(tzinfo=_jst()).timestamp()
    except ValueError:  # arch-ok: 读不到 = 按缺省判（导入时间未知 → 不放宽闸门；hold 到期按 6 h 兜底），调用方显式处理 None
        return None


def _import_events(root: Path, run: str) -> list[tuple[float, list]]:
    """producer 日志里的 imported_staged 事件 [(epoch, 集列表)]；按文件 mtime 缓存（日志只增）"""
    p = root / "data/producer" / f"runs/{run}/log.jsonl"
    try:
        st = p.stat()
    except OSError:  # arch-ok: 读不到 = 按缺省判（导入时间未知 → 不放宽闸门；hold 到期按 6 h 兜底），调用方显式处理 None
        return []
    key = (str(p), st.st_mtime_ns, st.st_size)
    hit = _IMPORT_LOG_CACHE.get(str(p))
    if hit and hit[0] == key:
        return hit[1]
    out = []
    try:
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if '"imported_staged"' not in ln:
                continue
            try:
                d = json.loads(ln)
            except ValueError:  # arch-ok: 读不到 = 按缺省判（导入时间未知 → 不放宽闸门；hold 到期按 6 h 兜底），调用方显式处理 None
                continue
            t = d.get("t") if isinstance(d.get("t"), (int, float)) else _parse_jst(d.get("ts"))
            if t and d.get("status") in (None, 200):
                out.append((float(t), list(d.get("episodes") or [])))
    except OSError:  # arch-ok: 读不到 = 按缺省判（导入时间未知 → 不放宽闸门；hold 到期按 6 h 兜底），调用方显式处理 None
        return []
    _IMPORT_LOG_CACHE[str(p)] = (key, out)
    return out


def current_import_at(root: Path, run: str, ep: int) -> float | None:
    """本集“当前剧本版本”最近一次导入的时间（epoch）：episode_run 小状态 / producer 日志 imported_staged / autoflow import 段，取最晚。
    没有任何记录 = None（调用方不加新鲜度条件，旧行为）"""
    ts: list[float] = []
    st = _j(_run_dir(root, run) / "episode_run" / f"ep{ep:02d}_state.json", {}) or {}
    t = _parse_jst((st.get("import") or {}).get("at"))
    if t:
        ts.append(t)
    ts += [t for t, eps in _import_events(root, run) if not eps or ep in eps]
    t = _parse_jst(_stage_of(_af(root, run, ep), "import").get("at"))
    if t:
        ts.append(t)
    return max(ts) if ts else None


def check_preview(root: Path, run: str, ep: int) -> dict:
    """整集预览：data/episodes/<剧>/epNN*.mp4 且必须是当前剧本版本之后拼的（成片 mtime >= 最近一次导入时间）。
    旧版剧本拼的预览不算“完成”（UI-STATUS 11-05：ep01 重导入后 v6 还显示“整集预览已拼好”）"""
    d = root / _episodes_rel(run)
    hit = sorted(d.glob(f"ep{ep:02d}*.mp4"))
    if not hit:
        return _ok("整集预览", False, "没有整集预览片")
    imp = current_import_at(root, run, ep)
    try:
        mt = hit[-1].stat().st_mtime
    except OSError:  # arch-ok: 读不到 = 按缺省判（导入时间未知 → 不放宽闸门；hold 到期按 6 h 兜底），调用方显式处理 None
        mt = None
    if imp and mt is not None and mt + 1 < imp:
        from datetime import datetime
        return _ok("整集预览", False, f"整集预览 {hit[-1].name} 是旧版剧本拼的（成片 {datetime.fromtimestamp(mt, _jst()):%m-%d %H:%M} 早于最近一次导入 "
                   f"{datetime.fromtimestamp(imp, _jst()):%m-%d %H:%M}），要重拼", stale_preview=True, file=hit[-1].name)
    return _ok("整集预览", True, hit[-1].name)


def evaluate(run: str, ep: int, root: Path = ROOT, shot: int | None = None) -> list[dict]:
    """九个阶段逐一判（不短路，status 要看全貌）。L-140（整集就绪才出图）：config whole_episode_prompts=true 时，
    提示词阶段永远按整集判（给了镜号也一样）——按镜进“出图”前，本集每个非成人镜都要编译 + preflight 过"""
    p_shot = None if config(root).get("whole_episode_prompts", True) else shot
    return [check_script(root, run, ep), check_import(root, run, ep), check_assets(root, run, ep),
            check_prompts(root, run, ep, p_shot), check_images(root, run, ep, shot), check_image_qc(root, run, ep, shot),
            check_lasts(root, run, ep, shot), check_video(root, run, ep), check_preview(root, run, ep)]


def current_stage(rows: list[dict]) -> tuple[str, str]:
    """第一个没过的阶段 = 本集所处阶段；全过 = 完成"""
    for r in rows:
        if not r["ok"]:
            return r["stage"], r["why"]
    return "完成", "九个阶段都有通过证据"


# ------------------------------------------------------------------ 闸门
def _log_violation(root: Path, rec: dict) -> None:
    p = root / "data/pipeline/sop_gate/violations.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def judge(run: str, ep: int, stage: str, shot: int | None = None, root: Path = ROOT) -> dict:
    """进 stage 前的判定（不抛）：{ok, missing: [阶段: 原因], retro}"""
    if stage not in STAGES:
        raise ValueError(f"不认识的阶段：{stage}（只认 {STAGES}）")
    if is_legacy(run, root):
        return {"ok": True, "missing": [], "note": "V1（legacy）不走 V2 SOP"}
    idx = STAGES.index(stage)
    rows = evaluate(run, int(ep), root, shot)[:idx]
    missing = [f"{r['stage']}：{r['why']}" for r in rows if not r["ok"]]
    retro = None
    if idx >= RETRO_FROM and int(ep) > 1:
        retro = retro_state(run, int(ep) - 1, root)
        if retro != "done":
            missing.append(f"第{int(ep) - 1}集复盘：{retro}（tools/master/episode_retro.py 生成并 done 后，第{int(ep)}集才能出图）")
    return {"ok": not missing, "missing": missing, "retro": retro}


def require(run: str, ep: int, stage: str, shot: int | None = None, root: Path = ROOT, by: str = "") -> dict:
    """进入 stage 前必须调用：前面阶段没有通过证据 → SopGateError（observe 阶段只记违规不抛）"""
    cfg = config(root)
    res = judge(run, ep, stage, shot, root)
    if res["ok"] or not cfg.get("enabled", True):
        return res
    retro_block = res.get("retro") not in (None, "done") and cfg.get("retro_enforce", True)
    mode = "observe" if stage in (cfg.get("observe_stages") or []) and not retro_block else "enforce"
    _log_violation(root, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": run, "episode": int(ep), "stage": stage,
                          "shot": shot, "mode": mode, "by": by or Path(sys.argv[0]).name, "missing": res["missing"]})
    res["mode"] = mode
    if mode == "enforce":
        raise SopGateError(f"SOP 闸门：{run} 第{int(ep)}集{'镜' + str(shot) if shot else ''}不能进入“{stage}”——"
                           + "；".join(res["missing"]))
    sys.stderr.write(f"[sop_gate observe] {run} ep{int(ep):02d} {stage}：" + "；".join(res["missing"])[:300] + "\n")
    return res


# ------------------------------------------------------------------ 闸门 + 退避（W8 / A1-5、A1-6：asset_worker 与 producer 共用的唯一实现，L-137）
# 事故 ISS-1103-033742-73be：observe 阶段每拍每个作业 / 每镜都调 require → violations.jsonl 每分钟几十条一模一样的违规。
# 做法：先 judge 只读判定（不写违规）；没过时只有“缺口签名”变了或退避到期才真正 require（写 1 条违规），期间沿用上次 mode
# （observe 照样放行、enforce 照样挡）。签名只用稳定键（A1-6）：阶段名 + 缺口阶段名 + 状态码（gate=reopened 之类）+ 闸门配置，
# 不含“第 N 次”、项数、时间、next_action 文案——这些每拍在变，签进去就等于没退避。
BACKOFF_S = (900, 1800)            # 第 1 次写违规后等 15 分钟，之后每 30 分钟一次 → 同一签名任意 30 分钟窗口 ≤ 2 条
BACKOFF_KEEP_S = 6 * 3600          # 过期 6 小时的签名条目清掉（状态文件不无限长）
_CODE_RE = re.compile(r"(?<![A-Za-z_])([a-z_]+=[^\s；;，,（）()：:]+)")


def missing_key(missing: list) -> list[str]:
    """缺口的稳定键：每条“阶段：原因”只取阶段名 + 原因里的状态码（gate=reopened / import=无 …），去掉计数、时间、文案"""
    out = set()
    for m in missing or []:
        s = str(m)
        head, _, why = s.partition("：")
        codes = sorted(set(_CODE_RE.findall(why)))
        out.add(head.strip() + (("|" + ",".join(codes)) if codes else ""))
    return sorted(out)


def backoff_sig(stage: str, missing: list, cfg: dict | None) -> str:
    cfg = cfg or {}
    cs = [bool(cfg.get("enabled", True)), stage in (cfg.get("observe_stages") or [])]
    raw = json.dumps({"stage": stage, "gaps": missing_key(missing), "cfg": cs}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def backoff_path(run: str, by: str, root: Path = ROOT) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{run}.{by or 'unknown'}")
    return root / "data/pipeline/sop_gate/backoff" / f"{safe}.json"


def _write_state(p: Path, st: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    t.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    for i in range(5):                          # Windows：os.replace 撞上读者会 PermissionError，稍等重试
        try:
            os.replace(t, p)
            return
        except PermissionError:
            if i == 4:
                raise
            time.sleep(0.05 * (i + 1))


STALE_BACKOFF_S = 120              # SLIM-CDE 11-05 E2：阻断原因是“提示词证据过期”时退避封顶 120 s（原 900 / 1800 s）
AUTO_PROBE_COOLDOWN_S = 300        # 同一集自动探针的最短间隔（也兼当“正在跑”的锁：探针一般 1–3 min 内写完证据）


def _is_stale_evidence(missing: list) -> bool:
    return any("证据过期" in str(m) for m in missing or [])


def auto_probe_stale(run: str, ep: int, root: Path = ROOT, missing: list | None = None, now: float | None = None) -> str | None:
    """SLIM-CDE 11-05 E2（K-OPS-I13 的自动化）：阻断原因是“提示词证据过期”→ 后台起一个 probe-prompts（和 episode_run 同一个命令，分离子进程，
    不占调用线程；CPU 编译 + preflight，不出图、不占 GPU）。证据一刷新，下一次 judge 当场放行（require_backoff 先判再看退避）。
    返回 "started" / "cooldown" / None（不适用 / 关闭）。开关 config/pipeline/sop_gate.json auto_probe_stale（默认 true；env NS_SOP_AUTO_PROBE=0 关）；
    只对真实仓库根生效（测试夹具的临时根不起子进程）"""
    if not _is_stale_evidence(missing) or os.environ.get("NS_SOP_AUTO_PROBE") == "0":
        return None
    try:
        if Path(root).resolve() != ROOT.resolve() or not config(root).get("auto_probe_stale", True):
            return None
    except OSError:  # arch-ok: 读不到 = 按缺省判（导入时间未知 → 不放宽闸门；hold 到期按 6 h 兜底），调用方显式处理 None
        return None
    now = time.time() if now is None else float(now)
    lock = root / "data/pipeline/sop_gate" / run / f"ep{int(ep):02d}_auto_probe.lock"
    try:
        if lock.exists() and now - lock.stat().st_mtime < AUTO_PROBE_COOLDOWN_S:
            return "cooldown"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
        import subprocess
        logf = open(root / "data/pipeline/sop_gate" / "auto_probe.log", "a", encoding="utf-8")
        kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "probe-prompts", "--run", run, "--episode", str(int(ep))],
                         cwd=str(root), stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
        sys.stderr.write(f"[sop_gate] 提示词证据过期 → 自动后台 probe-prompts {run} ep{int(ep):02d}（K-OPS-I13）\n")
        return "started"
    except OSError as e:  # arch-ok: 起不了探针 = 退回原行为（退避 + 人工），不影响判定
        sys.stderr.write(f"[sop_gate] auto probe 起不来：{e!r}\n"[:200])
        return None


def require_backoff(run: str, ep: int, stage: str, shot: int | None = None, root: Path = ROOT, by: str = "",
                    now: float | None = None, state_path: Path | None = None, key: str | None = None) -> dict:
    """带退避 + 去重计数的 require（不抛 SopGateError）。返回：
      {"allow": bool, "ok": judge 是否通过, "mode": observe|enforce|None, "missing": [...], "logged": 本次是否写了违规,
       "backoff": {"mode", "next_s", "logged", "suppressed"} | None, "cleared": 是否清掉了旧退避, "error": enforce 时的拒绝原因}
    状态文件默认 data/pipeline/sop_gate/backoff/<run>.<by>.json；条目键默认 “by|stage|epNN|签名”（与镜号无关：同一集同一缺口
    多镜只写 1 条）。key 给了就用固定键（asset_worker 沿用 <asset_jobs>/<run>/_sop_backoff.json 的 epNN 键：签名变了 = 新一轮）"""
    now = time.time() if now is None else float(now)
    sp = Path(state_path) if state_path else backoff_path(run, by, root)
    out = {"allow": True, "ok": False, "mode": None, "missing": [], "logged": False, "backoff": None, "cleared": False, "error": None}
    res = judge(run, ep, stage, shot, root)                              # 只读，不写违规
    out["missing"] = list(res.get("missing") or [])
    if res.get("ok"):
        out["ok"] = True
        if key:
            st = _j(sp, {}) or {}
            if st.pop(key, None) is not None:
                _write_state(sp, st)
                out["cleared"] = True
        return out
    cfg = config(root)
    if not cfg.get("enabled", True):
        return out
    stale = _is_stale_evidence(out["missing"])
    if stale:
        out["auto_probe"] = auto_probe_stale(run, ep, root, out["missing"], now)      # E2：先把证据补上，再谈退避
    sig = backoff_sig(stage, out["missing"], cfg)
    k = key or f"{by}|{stage}|ep{int(ep):02d}|{sig}"
    st = _j(sp, {}) or {}
    if not isinstance(st, dict):
        st = {}
    for kk in [kk for kk, v in st.items() if isinstance(v, dict) and kk != k and float(v.get("until") or 0) < now - BACKOFF_KEEP_S]:
        st.pop(kk, None)
    b = st.get(k) or {}
    same = b.get("sig") == sig
    if same and now < float(b.get("until") or 0):                        # 同一签名、退避中：只计数，不写违规、不重判
        b["suppressed"] = int(b.get("suppressed") or 0) + 1
        st[k] = b
        out["mode"] = b.get("mode")
        out["allow"] = b.get("mode") == "observe"
        if not out["allow"]:
            out["error"] = f"退避中（{b.get('missing_head', '')}）"
        out["backoff"] = {"mode": b.get("mode"), "next_s": round(float(b["until"]) - now), "suppressed": b["suppressed"],
                          "logged": int(b.get("logged") or 0)}
        _write_state(sp, st)
        return out
    n = int(b.get("logged") or 0) + 1 if same else 1
    try:                                                                 # 真正过闸门（写 1 条违规；enforce 抛错）
        r2 = require(run, ep, stage, shot=shot, root=root, by=by)
    except SopGateError as e:
        mode = "enforce"
        out.update(allow=False, error=str(e))
    else:
        if r2.get("ok"):                                                 # judge 与 require 之间刚好过了
            st.pop(k, None)
            _write_state(sp, st)
            out["ok"] = True
            return out
        mode = r2.get("mode") or "observe"
    wait = BACKOFF_S[min(n, len(BACKOFF_S)) - 1]
    if stale:
        wait = min(wait, STALE_BACKOFF_S)           # E2：证据过期是秒级可修的，不按 15–30 min 等
    repeats = (int(b.get("repeats") or 0) + int(b.get("suppressed") or 0) + 1) if same else 1
    st[k] = {"sig": sig, "by": by, "stage": stage, "episode": int(ep), "shot": shot, "mode": mode, "logged": n, "suppressed": 0,
             "repeats": repeats, "gaps": missing_key(out["missing"]), "missing_head": str((out["missing"] or [""])[0])[:120],
             "first": b.get("first") if same else time.strftime("%Y-%m-%dT%H:%M:%S"),
             "last_logged": time.strftime("%Y-%m-%dT%H:%M:%S"), "until": now + wait}
    _write_state(sp, st)
    out.update(mode=mode, logged=True, backoff={"mode": mode, "next_s": wait, "logged": n, "suppressed": 0})
    return out


def filter_jobs(run: str, jobs: list[dict], stage: str = "资产就绪", rec: dict | None = None, root: Path = ROOT) -> list[dict]:
    """asset_worker 出图分支：每个作业按自己的集过闸门；挡掉的写进 rec['sop_gate_blocked']"""
    out = []
    for j in jobs:
        try:
            require(run, int(j.get("episode") or 1), stage, root=root, by="asset_worker")
            out.append(j)
        except SopGateError as e:
            if rec is not None:
                rec.setdefault("sop_gate_blocked", []).append(f"{j.get('id')}: {e}"[:300])
    return out


def _shot_no(sid) -> int | None:
    m = re.search(r"S(\d+)$", str(sid))
    return int(m.group(1)) if m else None


def video_shots_ok(run: str, ep: int, root: Path = ROOT) -> list[int]:
    """本集能进“视频”的镜（逐镜判：该镜首帧过检 + 尾帧有当前版；提示词仍按整集 L-140）"""
    return [n for n in shots_of(run, ep, root) if judge(run, ep, "视频", n, root).get("ok")]


def filter_video_specs(run: str, specs: dict, root: Path = ROOT) -> dict:
    """build_jobs：没过“视频”闸门的镜不编视频作业。
    W38（项目方 11-04 04:3x“不等 11 镜齐，现在就出视频”）：原来按整集判——ep01 只要还有一镜没首帧，已有首尾帧的镜也一条视频都不编；
    改为逐镜 require(视频, shot)（没过的镜照记违规、不编），镜号取不到的按整集判（原口径）"""
    if is_legacy(run, root):
        return specs
    out = {}
    for sid, spec in specs.items():
        ep = int(getattr(spec, "episode", None) or (spec.get("episode") if isinstance(spec, dict) else 0) or 0)
        n = _shot_no(sid)
        try:
            require(run, ep, "视频", shot=n, root=root, by="build_jobs")
            out[sid] = spec
        except SopGateError as e:
            sys.stderr.write(f"[sop_gate] {e}\n")
    return out


def video_dispatch_ok(vid_rel: str, root: Path = ROOT) -> bool:
    """night.dispatch_hosts 开头：hosts.json 里分到机器的集逐个过“视频”闸门（没过的记违规）；一集都没过 = 本轮不派。
    （没过的集 build_jobs 的 filter_video_specs 已不编作业，这里是派单层的第二道）"""
    m = re.search(r"runs/([^/]+)/video", str(vid_rel).replace("\\", "/"))
    run = m.group(1) if m else ""
    if not run or is_legacy(run, root):
        return True
    eps = sorted({int(e) for e in (_j(root / vid_rel / "hosts.json", {}) or {})})
    ok = []
    for ep in eps:
        if video_shots_ok(run, ep, root):       # W38：有镜可进视频就派（作业已由 filter_video_specs 逐镜过滤）
            ok.append(ep)
            continue
        try:
            require(run, ep, "视频", root=root, by="night")
            ok.append(ep)
        except SopGateError as e:
            sys.stderr.write(f"[sop_gate] {e}\n")
    return bool(ok)


def vidgen_guard(run: str, vid_dir: Path, root: Path = ROOT) -> None:
    """vidgen（在服务器上跑）：本机有笔记本证据就按控制文件里的集过“视频”闸门；服务器镜像没有证据 = 不挡（笔记本 build_jobs / night 已挡）"""
    if not run or is_legacy(run, root) or not (_run_dir(root, run) / ("autoflow" + ".json")).exists():
        return
    eps = sorted({int(ep) for host_ctrl in Path(vid_dir).glob("control_*.json") for ep in (_j(host_ctrl, {}) or {}).get("eps") or []})
    # W38（11-04 04:4x gpu36 实测）：控制文件里的集逐个判，原来一集不过就抛 → 整个 vidgen 退出，连 ep01 可进视频的镜也不出。
    # 改为：有镜可进视频的集放行；没有的集照记违规（require_backoff 不抛）；控制文件里一集都没有可进的镜才抛（失败关闭）
    ok = [ep for ep in eps if video_shots_ok(run, ep, root)]
    for ep in eps:
        if ep not in ok:
            require_backoff(run, ep, "视频", root=root, by="vidgen")
    if eps and not ok:
        require(run, eps[0], "视频", root=root, by="vidgen")


# ------------------------------------------------------------------ 提示词证据（逐镜编译 + preflight，不出图）
def _sys_paths(root: Path) -> None:
    for p in ("packages/schema", "services/render_router", "services/agent", "services/recipes"):
        if str(root / p) not in sys.path:
            sys.path.insert(0, str(root / p))


def compile_preflight(run: str, ep: int, root: Path = ROOT, lane: str | None = None) -> dict[str, dict]:
    """本进程里逐镜调唯一编译入口 ns_agent.frame_job.build_first + ns_agent.gen_contract.preflight.check（PRODMERGE-O：
    不再经 golden_v2）。调用方须已按 runs.run_env(run) 设好进程环境（_probe_subprocess 起的子进程做这件事）。
    → {镜号: {ok, why, prompt_sha}}；成人镜只记 pending_owner（不编译出图作业，L-128）"""
    _sys_paths(root)
    from ns_schema.script import ScriptImport
    from ns_agent import frame_job as FJ
    from ns_agent.gen_contract import preflight as PF
    s = ScriptImport.model_validate(json.loads(_runs().import_path(run, root).read_text(encoding="utf-8")))
    e = next((x for x in s.episodes if int(x.number) == int(ep)), None)
    rows: dict[str, dict] = {}
    if e is None:
        return rows
    for sh in e.shots:
        n = str(int(sh.index))
        if getattr(sh, "adult", False):
            rows[n] = {"ok": None, "pending_owner": True, "why": "成人镜：只由项目方触发（L-128），不自动编译出图"}
            continue
        try:
            job = FJ.build_first(run, e, sh, s.globals)
            req = {k: job.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by", "route", "route_reasons")}
            req.update(kind="image", project=run, framing_project=run, shot_id=f"{run}-ep{int(ep):02d}-S{n}", lane=lane)
            pf = PF.check(req)
            rows[n] = {"ok": bool(pf.ok), "why": "；".join(pf.reasons())[:300],
                       "prompt_sha": hashlib.sha256((job.get("prompt") or "").encode("utf-8")).hexdigest()[:16],
                       "refs_sha": (job.get("compile_trace") or {}).get("refs_sha"),
                       "manifest_keys": manifest_keys_for(root, run, job)}
        except Exception as ex:  # noqa: BLE001  # arch-ok: 编译出错 = 这一镜没过（原因写进证据）
            rows[n] = {"ok": False, "why": f"编译出错：{type(ex).__name__}: {ex}"[:300]}
    return rows


def _probe_subprocess(run: str, ep: int, root: Path, cfg: dict) -> dict[str, dict]:
    """隔离进程跑 compile_preflight（按剧环境只设在子进程里，API / 常驻进程不被污染）"""
    py = root / ".venv/Scripts/python.exe"
    py = str(py) if py.is_file() else sys.executable
    env = {k: v for k, v in os.environ.items() if k not in _runs().RUN_ENV_KEYS}
    env.update(_runs().run_env(run, root))
    p = subprocess.run([py, "-X", "utf8", str(Path(__file__).resolve()), "_probe-one", "--run", run, "--episode", str(int(ep)),
                        "--lane", str(cfg.get("probe_lane") or "")], cwd=root, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=int(cfg.get("probe_timeout_s") or 900), env=env)
    m = re.search(r"PROBE_ROWS (\{.*\})", p.stdout or "")
    if not m:
        tail = [x for x in ((p.stdout or "") + (p.stderr or "")).strip().splitlines() if x.strip()]
        why = (tail[-1] if tail else f"探针退出码 {p.returncode}")[:300]
        return {str(n): {"ok": False, "why": why} for n in shots_of(run, ep, root)}
    return json.loads(m.group(1))


def probe_prompts(run: str, ep: int, root: Path = ROOT, runner=None) -> dict:
    """逐镜 build_first + preflight（不出图），写证据文件。runner(run, ep, root, cfg) → rows（测试注入；默认隔离子进程）"""
    cfg = config(root)
    rows = (runner or _probe_subprocess)(run, ep, root, cfg)
    # W38：每镜都编译成功且带了 manifest_keys → 按集指纹；有一镜没带（编译出错 / 旧探针 / 测试注入）→ 整文件指纹（旧口径，失败关闭）
    keyed = [r for r in rows.values() if isinstance(r, dict) and not r.get("pending_owner")]
    keys = sorted({k for r in keyed for k in r.get("manifest_keys") or []}) \
        if keyed and all(isinstance(r.get("manifest_keys"), list) for r in keyed) else None
    ev = {"schema": "nsfs.sop_gate.prompts/2", "run": run, "episode": ep, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
          "probe": "build_first+preflight", "fingerprint": prompt_fingerprint(root, run, ep), "shots": rows}
    if keys is not None:
        # 按集指纹（不含 updated_at / 别集条目）= 同一输入两遍字节一致（冒烟 G7 幂等）；整文件 sha 每次清单写入都变，不再写进证据。
        # fingerprint_scoped 同值照写：hf-20261104-01 rev2 的服务器只从这个字段认按集指纹
        ev["manifest_keys"] = keys
        ev["fingerprint"] = ev["fingerprint_scoped"] = prompt_fingerprint(root, run, ep, keys)
    p = _prompt_file(root, run, ep)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return ev


# ------------------------------------------------------------------ 唯一阶段视图（网页 / 计分板 / 步骤条都读这里）
def stage_view(run: str, root: Path = ROOT) -> dict:
    """{run, legacy, episodes: [{episode, stage, stage_index, legacy_stage, why, passed, pending_owner, retro}],
    stage: 全剧最靠前的阶段, counts: {阶段: 集数}}——各页面只做显示，不再自己判阶段"""
    if is_legacy(run, root):
        return {"run": run, "legacy": True, "stages": STAGES, "episodes": [], "stage": None, "legacy_stage": None, "counts": {}}
    eps = []
    for r in status(run, root):
        idx = STAGES.index(r["stage"]) if r["stage"] in STAGES else len(STAGES)
        pend = sorted({n for x in r["rows"] for n in (x.get("pending_owner") or [])})
        eps.append({"episode": r["episode"], "stage": r["stage"], "stage_index": idx, "legacy_stage": LEGACY_STAGE.get(r["stage"]),
                    "why": r["why"], "passed": r["passed"], "pending_owner": pend, "retro": r["retro"]})
    first = min(eps, key=lambda e: e["stage_index"], default=None)
    counts = {st: sum(1 for e in eps if e["stage"] == st) for st in STAGES + ["完成"]}
    return {"run": run, "legacy": False, "stages": STAGES, "episodes": eps, "stage": first["stage"] if first else None,
            "legacy_stage": first["legacy_stage"] if first else None, "counts": counts}


# ------------------------------------------------------------------ runs.json 状态机：preparing → producing
def promote_check(run: str, root: Path = ROOT) -> dict:
    """规则（与本模型阶段对齐）：status=preparing 的剧，只要有一集 judge(..., promote.stage=出图) 通过
    （剧本 → 导入闸门 → 资产就绪 → 提示词 都有证据、上一集复盘 done）→ 可以翻 producing。
    producing 之后 producer 每单仍按镜过 require(出图 / 尾帧)，没过的镜不派（不靠 status 一刀切）"""
    reg = (_registry(root).get("runs") or {}).get(run) or {}
    st = reg.get("status")
    stage = (config(root).get("promote") or {}).get("stage") or "出图"
    if st != "preparing":
        return {"run": run, "status": st, "promote": False, "why": f"status={st}，不是 preparing（只有 preparing 会被提升）", "episodes": []}
    ok_eps, why = [], []
    for ep in episodes_of(run, root):
        j = judge(run, ep, stage, root=root)
        if j["ok"]:
            ok_eps.append(ep)
        else:
            why.append(f"ep{ep:02d}：" + "；".join(j["missing"])[:200])
    return {"run": run, "status": st, "promote": bool(ok_eps), "episodes": ok_eps, "stage": stage,
            "why": (f"第 {ok_eps} 集已可进“{stage}”" if ok_eps else ("；".join(why) or "还没有任何一集开工"))}


def promote(run: str, root: Path = ROOT, by: str = "sop_gate", apply: bool = False) -> dict:
    """apply=True 且判定可提升 → runs.set_status(run, producing)（写 status_history）"""
    res = promote_check(run, root)
    if apply and res["promote"]:
        _runs().set_status(run, "producing", by=by, why=f"sop_gate.promote：{res['why']}", root=root)
        res["applied"] = True
    return res


# ------------------------------------------------------------------ status
def status(run: str, root: Path = ROOT) -> list[dict]:
    out = []
    for ep in episodes_of(run, root):
        rows = evaluate(run, ep, root)
        st, why = current_stage(rows)
        if st not in ("剧本", "导入闸门", "资产就绪", "提示词") and ep > 1 and retro_state(run, ep - 1, root) != "done":
            why = f"等第{ep - 1}集复盘 done；" + why
        out.append({"episode": ep, "stage": st, "why": why, "retro": retro_state(run, ep, root),
                    "passed": [r["stage"] for r in rows if r["ok"]], "rows": rows})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="每集当前阶段（只读）")
    s.add_argument("--run", required=True)
    s.add_argument("--json", action="store_true")
    c = sub.add_parser("check", help="判一次能不能进某阶段（只读，不记违规）")
    c.add_argument("--run", required=True)
    c.add_argument("--episode", type=int, required=True)
    c.add_argument("--stage", required=True, choices=STAGES)
    c.add_argument("--shot", type=int)
    p = sub.add_parser("probe-prompts", help="逐镜编译 + preflight（不出图），写提示词证据")
    p.add_argument("--run", required=True)
    p.add_argument("--episode", type=int, required=True)
    o = sub.add_parser("_probe-one", help="（内部）本进程逐镜 build_first + preflight，打印 PROBE_ROWS")
    o.add_argument("--run", required=True)
    o.add_argument("--episode", type=int, required=True)
    o.add_argument("--lane", default="")
    pr = sub.add_parser("promote", help="preparing → producing 判定（默认只读；--apply 才写 runs.json）")
    pr.add_argument("--run", required=True)
    pr.add_argument("--apply", action="store_true")
    pr.add_argument("--by", default="总调度")
    a = ap.parse_args(argv)
    if a.cmd == "_probe-one":
        print("PROBE_ROWS " + json.dumps(compile_preflight(a.run, a.episode, ROOT, a.lane or None), ensure_ascii=False))
        return 0
    if a.cmd == "promote":
        res = promote(a.run, ROOT, by=a.by, apply=a.apply)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["promote"] else 1
    if a.cmd == "status":
        rows = status(a.run)
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        for r in rows:
            print(f"ep{r['episode']:02d}  当前：{r['stage']:<5} 已过：{'→'.join(r['passed']) or '—'}  复盘：{r['retro']}")
            print(f"      卡在：{r['why']}")
        if not rows:
            print(f"{a.run} 还没有任何一集开工")
        return 0
    if a.cmd == "check":
        res = judge(a.run, a.episode, a.stage, a.shot)
        print(("可以进入" if res["ok"] else "不能进入") + f"“{a.stage}”" + ("" if res["ok"] else "：\n  " + "\n  ".join(res["missing"])))
        return 0 if res["ok"] else 1
    ev = probe_prompts(a.run, a.episode)
    ok = sum(1 for v in ev["shots"].values() if v["ok"])
    print(f"{a.run} ep{a.episode:02d} 提示词证据：{ok}/{len(ev['shots'])} 镜编译 + preflight 过 → {_prompt_file(ROOT, a.run, a.episode)}")
    for n, v in ev["shots"].items():
        if not v["ok"]:
            print(f"  镜{n}：{v['why'][:160]}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
