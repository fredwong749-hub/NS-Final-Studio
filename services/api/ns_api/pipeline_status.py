"""各集生产进度矩阵（NAVFLOW-F 11-03，项目方 L-146：顶部步骤条 + 每集 × 每步的矩阵；状态一律从后端取，前端不猜）。

    GET /api/pipeline/status?run=  → {run, title, episodes_total, steps:[{id,label}],
                                      episodes:[{episode, cells:{step:{state, plain, why}}, stage, plain, why, retro}],
                                      done:{step: 完成集数}, lit:{step: 这一步能不能亮（上一步至少一集通过）}}

唯一的阶段判定来源 = tools/master/sop_gate.py 的 status()（HARNESS-O）：九个阶段
    剧本 → 导入闸门 → 资产就绪 → 提示词 → 出图 → 出图检测 → 尾帧 → 视频 → 整集预览
这里只把九个阶段折成界面上的六步（不另判）：
    ①剧本 = 剧本 + 导入闸门   ②资产 = 资产就绪   ③分镜 = 提示词（编译 + preflight）
    ④出图 = 出图 + 出图检测 + 尾帧   ⑤视频 = 视频   ⑥成片 = 整集预览
格子状态：done（✓ 这一步的所有阶段都有通过证据）/ doing（● 上一步已过、这一步还没全过）/ blocked（⚠ 这一步卡住：sop_gate 的原因里
有“失败 / 拒绝 / 交总调度 / reopened / 补丁”）/ todo（· 还没到这一步）。
文案两层（REVIEW-D P1）：plain = 给项目方看的一句大白话（“卡在哪一步、在等什么”，不出现代码编号 / 文件名 / 命令），页面只显示它；
why = sop_gate 原文，只给开发者（接口里保留，页面不显示）。
sop_gate 读不到（模块缺 / 抛错）→ 503，不自己猜。导入用 importlib.spec_from_file_location，不往 sys.path 插路径。
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

ROOT = Path(__file__).resolve().parents[3]
SOP_GATE_FILE = ROOT / "tools" / "master" / "sop_gate.py"
router = APIRouter(tags=["pipeline-status"])

STEPS = [("script", "剧本", ["剧本", "导入闸门"]),
         ("assets", "资产", ["资产就绪"]),
         ("board", "分镜", ["提示词"]),
         ("frames", "出图", ["出图", "出图检测", "尾帧"]),
         ("video", "视频", ["视频"]),
         ("cut", "成片", ["整集预览"])]
BLOCK_WORDS = ("失败", "拒绝", "交总调度", "reopened", "补丁", "没过", "不过", "坏", "超过")
_gate_mod = None


def _gate():
    """tools/master/sop_gate.py 按文件路径加载一次（不改 sys.path）"""
    global _gate_mod
    if _gate_mod is None:
        spec = importlib.util.spec_from_file_location("ns_tools_master_sop_gate", SOP_GATE_FILE)
        if spec is None or spec.loader is None:
            raise FileNotFoundError(str(SOP_GATE_FILE))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _gate_mod = mod
    return _gate_mod


def _registry() -> dict:
    try:
        return json.loads((ROOT / "config" / "pipeline" / "runs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HTTPException(503, "剧目登记表读不到，请告诉总调度") from e


def _lib_row(run: str) -> dict:
    """剧本库接口同一口径（script_library）：剧名、总集数；读不到 → {}"""
    try:
        from ns_api import script_library as SL
        lib = SL.library()
        for row in (lib.get("current") or []) + (lib.get("history") or []):
            if row.get("run") == run:
                return row
    except Exception:  # noqa: BLE001  剧本库慢 / 坏 → 用 run 名 / 默认集数，不挡矩阵
        pass
    return {}


def _title(run: str) -> str:
    return _lib_row(run).get("title") or run


def _episodes_total(run: str, reg: dict) -> int:
    """总集数：剧本库（故事线定的集数）> 导入稿里有的集 > 登记表 episodes_total > 默认 10"""
    n = int(_lib_row(run).get("episodes") or 0)
    if n:
        return n
    try:
        G = _gate()
        doc = G._j(G._runs().import_path(run, ROOT), {}) or {}
        n = len(doc.get("episodes") or [])
        if n:
            return n
    except Exception:  # noqa: BLE001
        pass
    r = (reg.get("runs") or {}).get(run) or {}
    return int(r.get("episodes_total") or 10)


# ---------------------------------------------------------------- 大白话（只认 sop_gate 原文里的数字和几个关键词，不把原文透出去）
_FRAC = re.compile(r"(\d+)\s*/\s*(\d+)\s*镜")
_N_FAIL = re.compile(r"代码判定\s*(\d+)\s*项未过")
_N_GAP = re.compile(r"缺口\s*(\d+)\s*个")
_RETRO = re.compile(r"等第(\d+)集复盘")


def _frac(why: str) -> tuple[int, int] | None:
    m = _FRAC.search(why or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def plain(stage: str, ok: bool, why: str, ep: int) -> str:
    """一个阶段 → 一句给项目方看的话。规则：只说“卡在哪、在等什么”，不出现文件名 / 代码编号 / 命令 / 英文状态词。"""
    w = why or ""
    if stage == "剧本":
        return "剧本写好了" if ok else f"第 {ep} 集剧本还在写"
    if stage == "导入闸门":
        if ok:
            return "剧本已通过检查并导入"
        if "gate=无" in w or "无 import=无" in w:
            return "剧本写好后等系统检查"
        m = _N_FAIL.search(w)
        n = f" {m.group(1)} 处" if m else "几处"
        if "交总调度" in w:
            return f"第 {ep} 集剧本还有{n}要改，系统自动修了多次没修好，已交总调度处理"
        if "reopened" in w or "补丁" in w or m:
            return f"第 {ep} 集剧本还有{n}要改，系统正在自动修"
        return f"第 {ep} 集剧本在等系统检查通过"
    if stage == "资产就绪":
        if ok:
            return "人物和场景的资产都齐了"
        m = _N_GAP.search(w)
        if m:
            return f"还差 {m.group(1)} 项资产（身份脸 / 造型 / 场景），系统在出候选"
        return "等剧本导入后检查人物和场景的资产"
    if stage == "提示词":
        f = _frac(w)
        if not ok and "证据过期" in w:
            return "新稿或新资产出来了，画面说明要重新核对，系统在重跑"
        if ok:
            return "每一镜的画面说明都准备好了"
        if "只有成人镜" in w:
            return "本集只有成人镜头，要在自有机器上出"
        if "没有本集镜头" in w:
            return "剧本导入后才有镜头"
        if f:
            return f"{f[1]} 镜里 {f[0]} 镜的画面说明准备好了，其余还在补资料" if f[0] else f"{f[1]} 镜的画面说明还在等资料齐全"
        return "在等系统给每一镜准备画面说明"
    if stage in ("出图", "出图检测", "尾帧"):
        what = {"出图": "首帧", "出图检测": "首帧检查", "尾帧": "尾帧"}[stage]
        f = _frac(w)
        if ok:
            return f"{what}全部完成"
        if "只有成人镜" in w:
            return "本集只有成人镜头，要在自有机器上出"
        if f:
            return f"{what}完成 {f[0]}/{f[1]} 镜，其余在出"
        return f"等上一步通过后出{what}"
    if stage == "视频":
        f = _frac(w)
        if ok:
            return "视频全部出来了"
        if f:
            return f"视频出了 {f[0]}/{f[1]} 镜，其余在排队"
        return "等首帧和尾帧都定稿后出视频"
    if stage == "整集预览":
        if not ok and "旧版剧本拼的" in w:
            return "旧版剧本拼的整集预览已作废，等视频全部通过后重新拼"
        return "整集预览已拼好" if ok else "等视频全部通过后系统自动拼整集"
    return f"{stage}这一步完成了" if ok else f"{stage}这一步还没通过，系统在处理"


def plain_episode(ep: int, stage: str, why: str, rows_by_stage: dict[str, dict]) -> str:
    """集级一句话：停在哪一步 + 那一步的大白话；前面有“等第 N 集复盘”就先说这个"""
    if stage == "完成":
        return "这一集全部完成"
    m = _RETRO.search(why or "")
    head = f"要等第 {m.group(1)} 集复盘完成才能继续；" if m else ""
    r = rows_by_stage.get(stage) or {}
    return head + f"停在“{stage}”：" + plain(stage, False, r.get("why") or "", ep)


def fold(rows: list[dict], ep: int = 0, live: dict | None = None) -> dict:
    """九阶段行 → 六步格子（纯函数，tests 用）：{step: {state, plain, why}}"""
    by = {r["stage"]: r for r in rows}
    cells: dict[str, dict] = {}
    prev_done = True
    for sid, _label, stages in STEPS:
        parts = [(s, by.get(s) or {"ok": False, "why": "还没有判定"}) for s in stages]
        ok = all(p["ok"] for _s, p in parts)
        first_bad = next(((s, p) for s, p in parts if not p["ok"]), None)
        why = (first_bad[1].get("why") if first_bad else "") or ""
        if ok:
            state, text = "done", plain(parts[-1][0], True, parts[-1][1].get("why") or "", ep)
        elif not prev_done:
            state, why, text = "todo", "", "还没到这一步"
            if sid == "video" and live and (live.get("video_rendering") or live.get("video_new") or live.get("video_ready")):
                # 视频按镜流水：有的镜首帧已定稿，出图机已在渲染 / 已出新片，不必等整集首帧齐才显示“在出”
                n = int(live.get("video_new") or 0)
                state = "doing"
                k = int(live.get("video_ready") or 0)
                text = (f"视频已出 {n} 镜，其余在出图机上按镜陆续出" if n else
                        "视频在出图机上渲染，首帧陆续定稿后加入" if live.get("video_rendering") else
                        f"已有 {k} 镜首尾帧定稿，视频由出图机按镜陆续出（本机还没收到回传）")
        else:
            state = "blocked" if any(wd in why for wd in BLOCK_WORDS) else "doing"
            text = plain(first_bad[0], False, why, ep)   # type: ignore[index]  first_bad 在 not ok 时必有
        cells[sid] = {"state": state, "plain": text, "why": why}
        prev_done = ok
    return cells


# ---------------------------------------------------------------- 实时证据（UI-STATUS 11-05）：九阶段账本落后于现实时，用“下游已有新产物 / 机器在线”校正显示
def _now() -> float:
    import time
    return time.time()


def _take_epoch(s) -> float | None:
    from datetime import datetime, timedelta, timezone
    try:
        return datetime.fromisoformat(str(s)[:19]).replace(tzinfo=timezone(timedelta(hours=9))).timestamp()
    except ValueError:  # arch-ok: 显示层：读不到 = 不校正，显示原值
        return None


def _takes_since(G, run: str, ep: int, stage: str, since: float | None) -> int:
    """本集有几镜的 <stage>（image / video）take 是 since（最近一次导入）之后生成且过契约的；since=None → 0"""
    if not since:
        return 0
    try:
        base = Path(G._runs().renders_dir(run, ROOT)) / f"ep{ep:02d}"
        n = 0
        for tj in base.glob("S*/takes.json"):
            d = json.loads(tj.read_text(encoding="utf-8"))
            if any(t.get("stage") == stage and (_take_epoch(t.get("created_at")) or 0) >= since
                   and (t.get("postflight") or {}).get("ok") is not False and t.get("file") for t in d.get("takes") or []):
                n += 1
        return n
    except Exception:  # noqa: BLE001  读不到 = 不校正  # arch-ok: 显示层：读不到 = 不校正，显示原值
        return 0


def _iso_jst(t) -> str | None:
    from datetime import datetime, timedelta, timezone
    return datetime.fromtimestamp(t, timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S") if t else None


def producer_state(run: str) -> dict:
    """producer 心跳（data/producer/runs/<run>/heartbeat.json，出图机同步回来）：{alive, age_s}；读不到 = alive False, age_s None"""
    try:
        hb = json.loads((ROOT / "data" / "producer" / "runs" / run / "heartbeat.json").read_text(encoding="utf-8"))
        age = max(0.0, _now() - float(hb["t"]))
        return {"alive": age < 600 and not hb.get("paused"), "age_s": int(age), "paused": bool(hb.get("paused"))}
    except (OSError, ValueError, KeyError, TypeError):  # arch-ok: 显示层：读不到 = 不校正，显示原值
        return {"alive": False, "age_s": None, "paused": False}


def resident_state() -> dict:
    """笔记本写作 / 资产常驻（autoflow_resident）心跳：{alive, age_s}；超过 10 分钟没心跳 = 没在跑（它停了，剧本推进 / 资产作业就不自动走）"""
    try:
        hb = json.loads((ROOT / "data" / "factory" / "autoflow_resident.json").read_text(encoding="utf-8"))
        age = max(0.0, _now() - float(hb["t"]))
        return {"alive": age < 600, "age_s": int(age)}
    except (OSError, ValueError, KeyError, TypeError):  # arch-ok: 显示层：读不到 = 不校正，显示原值
        return {"alive": False, "age_s": None}


def _night_rendering(run: str, ep: int) -> bool:
    """video/night_state.json 在 30 分钟内更新过，且本集状态是 rendering"""
    p = ROOT / "data" / "pipeline" / "runs" / run / "video" / "night_state.json"
    try:
        if _now() - p.stat().st_mtime > 1800:
            return False
        return (json.loads(p.read_text(encoding="utf-8")).get("eps", {}).get(str(ep)) or {}).get("status") == "rendering"
    except (OSError, ValueError):  # arch-ok: 显示层：读不到 = 不校正，显示原值
        return False


def live_adjust(G, run: str, ep: int, rows: list[dict]) -> tuple[list[dict], dict]:
    """九阶段行 + 实时证据 → (校正后的行, live)。不改 sop_gate 的闸门判定，只改页面显示：
    ① 提示词证据只是“过期”（导入稿 / 清单指纹变了），但本版导入之后已经有首帧出来 = 出图机的闸门放行过，显示为已通过；
    ② 视频：本版导入之后已有新视频 take、或视频机 night 正在渲染 → live 里带上，fold 据此把“视频”显示为在出"""
    imp = None
    try:
        imp = G.current_import_at(ROOT, run, ep)
    except Exception:  # noqa: BLE001  # arch-ok: 显示层：读不到 = 不校正，显示原值
        pass
    out = [dict(r) for r in rows]
    by = {r["stage"]: r for r in out}
    pr = by.get("提示词")
    if pr and not pr["ok"] and "证据过期" in (pr.get("why") or "") and _takes_since(G, run, ep, "image", imp) > 0:
        pr["ok"] = True
        pr["why"] = "出图机已按本版稿出图（提示词证据指纹过期，下游已有新首帧）"
    try:
        ready = sum(1 for v in G.shot_frames(ROOT, run, ep).values() if v.get("image") and v.get("checked") and v.get("last"))
    except Exception:  # noqa: BLE001  # arch-ok: 显示层：读不到 = 不校正，显示原值
        ready = 0
    live = {"import_at": imp, "video_ready": ready if producer_state(run)["alive"] else 0, "video_new": _takes_since(G, run, ep, "video", imp), "video_rendering": _night_rendering(run, ep)}
    return out, live


@router.get("/api/pipeline/status")
def pipeline_status(run: str | None = None):
    reg = _registry()
    run = run or reg.get("primary")
    if not run or run not in (reg.get("runs") or {}):
        raise HTTPException(404, "没有这部剧")
    try:
        G = _gate()
        rows = G.status(run, ROOT)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001  sop_gate 不可用 → 不猜
        raise HTTPException(503, f"阶段判定暂时读不到：{type(e).__name__}") from e
    total = _episodes_total(run, reg)
    started = {int(r["episode"]): r for r in rows}
    eps = []
    for n in range(1, max(total, max(started, default=0)) + 1):
        r = started.get(n)
        if r:
            rows, live = live_adjust(G, run, n, r["rows"])
            stage, why = G.current_stage(rows)
            if r["why"].startswith("等第") and "；" in r["why"]:           # “等第 N 集复盘”前缀沿用 sop_gate 的
                why = r["why"].split("；", 1)[0] + "；" + why
            eps.append({"episode": n, "cells": fold(rows, n, live), "stage": stage, "why": why,
                        "plain": plain_episode(n, stage, why, {x["stage"]: x for x in rows}), "retro": r.get("retro"),
                        "import_at": _iso_jst(live.get("import_at"))})
        else:
            eps.append({"episode": n, "cells": {sid: {"state": "todo", "plain": "还没到这一步", "why": ""} for sid, _l, _s in STEPS},
                        "stage": "剧本", "why": "", "plain": f"第 {n} 集还没开始写", "retro": None, "import_at": None})
    done = {sid: sum(1 for e in eps if e["cells"][sid]["state"] == "done") for sid, _l, _s in STEPS}
    lit = {}
    prev = None
    for sid, _l, _s in STEPS:
        lit[sid] = True if prev is None else done[prev] > 0
        prev = sid
    return {"run": run, "title": _title(run), "episodes_total": total,
            "steps": [{"id": sid, "label": label} for sid, label, _s in STEPS],
            "episodes": eps, "done": done, "lit": lit, "producer": producer_state(run), "resident": resident_state()}
