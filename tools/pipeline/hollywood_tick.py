"""好莱坞质感分的自动打分拍（METRICS-F 11-03，总调度裁定 ISS-1103-023132-1c46 ①：不再手动跑）。

每拍（由 tools/factory/autoflow_resident.py 调；独立于 asset_worker 主流程，不改它的作业状态）：
  1. 发现本剧所有“已过检查”的图：资产作业 candidates（passed / contract_ok）、金样作业 slots（state=passed）、
     已登记的金样首帧（data/pipeline/golden/<run>/epNN/SNN.json）、阶段 A 账本 data/ab/v2_assets/<run>/<job>/takes.jsonl（passed）；
  2. 去掉已打过分的（metrics/hollywood_epNN.jsonl 里有 scores）和失败满 max_attempts 次的 → 待打队列（低优先级）；
  3. 只在本地看图服务空闲（两边 /health 都 queue=0、inflight=0）时打，每拍最多 max_per_tick 张，每张打前再探一次空闲：
     Q9 / 出图检查一来排队就让路，不挤占；
  4. 结果追加到 data/pipeline/runs/<run>/metrics/hollywood_epNN.jsonl（episode_metrics 只读这个文件）。
看图只走 tools/pipeline/vlm_pool.generate（只认本机地址 / 自家 gpu36 隧道，K-REV-V01），图不出外网。
开关：config/pipeline/hollywood_score.json（enabled / max_per_tick / max_attempts / wait_s / require_idle）。

  python tools/pipeline/hollywood_tick.py status [--run R]      # 待打多少、看图服务是否空闲
  python tools/pipeline/hollywood_tick.py score-episode --run R --episode N [--force]   # 逐镜打正片首帧（+look_metrics）
  python tools/pipeline/hollywood_tick.py once [--run R] [--force]   # 手工跑一拍（--force 不等空闲，只给排查用）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/agent", "tools/pipeline"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

CFG_PATH = "config/pipeline/hollywood_score.json"
DEFAULTS = {"enabled": False, "max_per_tick": 1, "max_attempts": 2, "wait_s": 300, "max_pixels": 1400000, "require_idle": True,
            "lock_stale_s": 1800}
LABEL = "hollywood_score"
KEYS_OLD = ("composition", "lighting", "texture", "performance", "consistency")
KEYS = KEYS_OLD + ("exposure", "depth", "grade", "ai_look")
RUBRIC = (
    "你是电影画面质量评审。只看这一张图，按下面 9 项各打 1–10 分（10 = 好莱坞院线级）：\n"
    "composition 构图（主体位置、景别选择、画面平衡）；lighting 光线（光比、方向、层次、是否有电影感）；"
    "texture 质感（皮肤 / 材质真实度、没有塑料感 / 坏块 / 低清）；performance 表演（表情、姿态、眼神是否可信、有情绪）；"
    "consistency 一致性（五官 / 服装 / 场景与常识一致，没有畸形或多余肢体）；"
    "exposure 曝光（高光是否溢出成死白、暗部是否死黑；大面积死白背景或细节被吃掉要明显扣分，层次完整 = 高分）；"
    "depth 景深层次（前中后景分离、主体清楚而背景有虚化 / 明暗层次；全画面一样清楚、像平面贴图要扣分）；"
    "grade 调色与胶片感（色调统一、有意图的调色、高光柔和滚落、像胶片印片；中性灰白目录感 / 数码硬边要扣分）；"
    "ai_look 去 AI 感（10 = 像真人实拍；1 = AI 美颜 / 瓷娃娃 / 塑料皮肤 / 发丝白边 / 过度锐化）。\n"
    "要严格：普通商业图 5–6 分，只有真正院线剧照才给 8 以上。\n"
    "只输出一个 JSON 对象，不要别的文字：{\"composition\": n, \"lighting\": n, \"texture\": n, \"performance\": n, \"consistency\": n, "
    "\"exposure\": n, \"depth\": n, \"grade\": n, \"ai_look\": n, \"note\": \"一句话\"}"
)
SYSTEM = "你是严谨的电影画面评审，只输出 JSON。"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def load_cfg(root: Path = ROOT) -> dict:
    p = root / CFG_PATH
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except OSError:
        return dict(DEFAULTS)
    except ValueError as e:
        return {**DEFAULTS, "enabled": False, "_config_error": f"{p}: {e}"}
    return {**DEFAULTS, **{k: v for k, v in d.items() if not k.startswith("_")}}


def _jlines(p: Path) -> list[dict]:
    out = []
    if not p.is_file():
        return out
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ln)
        except ValueError:      # arch-ok: 追加写偶发坏行只跳过
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _jload(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def norm_file(f) -> str | None:
    """统一成相对 data/ 的路径（takes 口径）：'data/review_pages/x.png' → 'review_pages/x.png'"""
    if not f or not isinstance(f, str):
        return None
    s = f.replace("\\", "/")
    if s.startswith("data/"):
        s = s[5:]
    return s or None


def ledger(root: Path, run: str, ep: int) -> Path:
    return root / "data" / "pipeline" / "runs" / run / "metrics" / f"hollywood_ep{ep:02d}.jsonl"


def discover(root: Path, run: str) -> list[dict]:
    """本剧所有已过检查的图（去重，按 file）"""
    seen: dict[str, dict] = {}

    def add(file, source, ep, **extra):
        f = norm_file(file)
        if not f or not ep or f in seen:
            return
        seen[f] = {"file": f, "source": source, "episode": int(ep), **extra}

    jobs_dir = root / "data" / "pipeline" / "asset_jobs" / run
    jobs = [j for j in (_jload(f, None) for f in sorted(jobs_dir.glob("*.json")) if not f.name.startswith("_"))
            if isinstance(j, dict) and str(j.get("schema", "")).startswith("nsfs.asset_job")] if jobs_dir.is_dir() else []
    for j in jobs:
        ep = j.get("episode") or (j.get("episodes") or [None])[0]
        kind = j.get("kind") or "?"
        for c in j.get("candidates") or []:
            if c.get("passed") or c.get("contract_ok"):
                add(c.get("file"), kind if kind != "face" else "cast_face", ep, job=j.get("id"))
        for s in j.get("slots") or []:
            if s.get("state") == "passed":
                add(s.get("review_file") or s.get("file"), "golden", ep, job=j.get("id"), shot=(j.get("spec") or {}).get("shot"))
        if kind == "sheet":
            for r in _jlines(root / "data" / "ab" / "v2_assets" / run / str(j.get("id")) / "takes.jsonl"):
                if r.get("passed"):
                    add(r.get("file"), "sheet", ep, job=j.get("id"))
    gdir = root / "data" / "pipeline" / "golden" / run
    if gdir.is_dir():
        for f in sorted(gdir.glob("ep*/S*.json")):
            sel = _jload(f, {}) or {}
            add(sel.get("file"), "golden_registered", sel.get("episode"), shot=sel.get("shot"))
    return list(seen.values())


def ledger_state(root: Path, run: str, eps: set[int]) -> dict[str, dict]:
    """{file: {scored: bool, attempts: n}}"""
    st: dict[str, dict] = {}
    for ep in eps:
        for r in _jlines(ledger(root, run, ep)):
            f = norm_file(r.get("file"))
            if not f:
                continue
            s = st.setdefault(f, {"scored": False, "attempts": 0})
            s["attempts"] += 1
            if isinstance(r.get("scores"), dict):
                s["scored"] = True
    return st


def pending(root: Path, run: str, cfg: dict) -> list[dict]:
    items = discover(root, run)
    st = ledger_state(root, run, {i["episode"] for i in items})
    out = []
    for i in items:
        s = st.get(i["file"], {"scored": False, "attempts": 0})
        if s["scored"] or s["attempts"] >= int(cfg.get("max_attempts") or 2):
            continue
        if not (root / "data" / i["file"]).is_file():
            continue
        out.append({**i, "attempts": s["attempts"]})
    out.sort(key=lambda x: (x["source"] != "golden_registered", x["source"] != "golden", x["episode"], x["file"]))   # 登记首帧 > 金样 > 资产
    return out


def vlm_idle(probe=None) -> tuple[bool, dict]:
    """两边 /health 都空（queue=0、inflight 全 0）才算空闲；一边都探不到 = 不空闲（没服务可用）"""
    import vlm_pool as VP
    probe = probe or VP.health
    info, online, busy = {}, 0, 0
    for ep in VP.endpoints():
        h = probe(ep["url"])
        if not h:
            info[ep["url"]] = "offline"
            continue
        online += 1
        load = int(h.get("queue") or 0) + sum(int(v or 0) for v in (h.get("inflight") or {}).values())
        busy += load
        info[ep["url"]] = {"queue": h.get("queue"), "inflight": h.get("inflight"), "loaded": h.get("loaded")}
    return (online > 0 and busy == 0), info


def parse_scores(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        d = None   # 模型回的不是合法 JSON = 本次无分（显式 None，由调用方记 bad）
    if not isinstance(d, dict):
        return None
    sc = {}
    for k in KEYS:
        v = d.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 1 <= float(v) <= 10:
            if k in KEYS_OLD:
                return None
            continue        # 新 4 项缺失 = 旧 5 项记录 / 模型漏项，向后兼容
        sc[k] = float(v)
    return {"scores": sc, "mean": round(sum(sc.values()) / len(sc), 2), "note": str(d.get("note") or "")[:120]}


def production_first_frames(root: Path, run: str, ep: int) -> list[dict]:
    """正片首帧：epNN/SNN/takes.json 的 active.image 对应的文件（renders_dir 口径）；没有 = missing"""
    import importlib.util
    sp = importlib.util.spec_from_file_location("ap_runs_h0", ROOT / "tools" / "autopilot" / "runs.py")    # 口径同 tools/autopilot/runs.py
    RUNS = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(RUNS)
    rd = RUNS.renders_dir(run, root) / f"ep{ep:02d}"
    out = []
    shots = sorted((d for d in rd.glob("S*") if d.is_dir() and re.fullmatch(r"S\d+", d.name)), key=lambda d: int(d.name[1:])) if rd.is_dir() else []
    for sd in shots:
        tj = _jload(sd / "takes.json", {}) or {}
        n = (tj.get("active") or {}).get("image")
        take = next((t for t in tj.get("takes") or [] if t.get("stage") == "image" and t.get("n") == n), None) if n is not None else None
        f = norm_file((take or {}).get("file"))
        item = {"file": f, "source": "production_first", "episode": ep, "shot": sd.name, "take": n}
        if not f or not (root / "data" / f).is_file():
            item["missing"] = True
        out.append(item)
    return out


def score_one(root: Path, run: str, item: dict, cfg: dict, generate=None) -> dict:
    if generate is None:
        import vlm_pool as VP
        generate = lambda req: VP.generate(req, wait_s=float(cfg.get("wait_s") or 300), label=LABEL)   # noqa: E731
    img = root / "data" / item["file"]
    res = generate({"system": SYSTEM, "text": RUBRIC, "images": [{"path": str(img), "max_pixels": int(cfg.get("max_pixels") or 1400000)}]})
    rec = {"at": _now(), "run": run, "episode": item["episode"], "source": item["source"], "file": item["file"], "job": item.get("job"),
           "shot": item.get("shot"), "take": item.get("take"), "model": res.get("model"), "via": res.get("via"), "seconds": res.get("seconds"),
           "raw": (res.get("text") or "")[:600], "error": res.get("error"), "by": "tools/pipeline/hollywood_tick.py"}
    parsed = parse_scores(res.get("text") or "")
    if item.get("source") == "production_first":
        try:
            import look_metrics as LM
            rec["look"] = LM.measure(img)
        except Exception as e:  # noqa: BLE001  确定性指标失败不影响看图分
            rec["look_error"] = repr(e)[:160]
    if parsed:
        rec.update(parsed)
    elif not rec["error"]:
        rec["error"] = "看图模型输出不是 1–10 的评分 JSON"
    lp = ledger(root, run, item["episode"])
    if item.get("source") == "reference_compare":      # 参考对照（raw vs post 等）不进 hollywood_epNN.jsonl，不影响集均值
        lp = lp.parent / "hollywood_ref.jsonl"
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# ---------- 单实例锁（独立于 asset_worker 的 worker.lock） ----------
def lock_path(root: Path) -> Path:
    return root / "data" / "factory" / "hollywood_tick.lock"


def acquire_lock(root: Path, stale_s: float) -> bool:
    lk = lock_path(root)
    lk.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lk, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        try:
            if time.time() - lk.stat().st_mtime > stale_s:       # 陈旧锁（上一份被整棵进程树带走）→ 接管
                lk.unlink()
                return acquire_lock(root, stale_s)
        except OSError:
            pass
        return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def release_lock(root: Path) -> None:
    try:
        lock_path(root).unlink()
    except OSError:
        pass


def active_runs(root: Path) -> list[str]:
    try:
        import asset_worker as AW     # 与阶段 A 同口径：runs.json 里 preparing / active / producing 的剧
        return sorted(AW.active_runs(root).keys())
    except Exception:  # noqa: BLE001  读不出 = 一部都不做
        return []


def tick(root: Path = ROOT, runs: list[str] | None = None, cfg: dict | None = None, probe=None, generate=None, force: bool = False) -> dict:
    """一拍；返回本拍记录（给 resident 心跳）。不抛异常给调用方以外的东西：出错写进 rec['errors']"""
    cfg = cfg or load_cfg(root)
    rec = {"at": _now(), "enabled": bool(cfg.get("enabled")), "scored": [], "failed": [], "pending": 0, "idle": None, "skipped": None, "errors": []}
    if cfg.get("_config_error"):
        rec["errors"].append(cfg["_config_error"])
    if not cfg.get("enabled"):
        rec["skipped"] = "开关关着（config/pipeline/hollywood_score.json enabled=false）"
        return rec
    if not acquire_lock(root, float(cfg.get("lock_stale_s") or 1800)):
        rec["skipped"] = "另一份 hollywood_tick 在跑"
        return rec
    try:
        runs = runs if runs is not None else active_runs(root)
        todo: list[tuple[str, dict]] = []
        for run in runs:
            try:
                todo += [(run, i) for i in pending(root, run, cfg)]
            except Exception as e:  # noqa: BLE001  一部剧发现失败不影响别的剧
                rec["errors"].append(f"{run}: {e!r}"[:200])
        rec["pending"] = len(todo)
        if not todo:
            return rec
        budget = int(cfg.get("max_per_tick") or 1)
        for run, item in todo:
            if len(rec["scored"]) + len(rec["failed"]) >= budget:
                break
            if cfg.get("require_idle", True) and not force:
                idle, info = vlm_idle(probe)
                rec["idle"] = info
                if not idle:
                    rec["skipped"] = "本地看图服务忙 / 不在，让路给出图检查（Q9）"
                    break
            try:
                r = score_one(root, run, item, cfg, generate)
            except Exception as e:  # noqa: BLE001  一张失败只记
                rec["failed"].append({"run": run, "file": item["file"], "error": repr(e)[:200]})
                continue
            (rec["scored"] if r.get("scores") else rec["failed"]).append({"run": run, "file": item["file"], "mean": r.get("mean"), "error": r.get("error")})
        rec["pending"] = len(todo) - len(rec["scored"]) - len(rec["failed"])
    finally:
        release_lock(root)
    return rec


def score_episode(root: Path, run: str, ep: int, cfg: dict, force: bool = False, generate=None, probe=None) -> int:
    """逐镜打正片首帧；本地看图空闲才打（--force 不等）；缺图的镜只记 missing"""
    done = {(r.get("shot"), r.get("take")) for r in _jlines(ledger(root, run, ep))
            if r.get("source") == "production_first" and isinstance(r.get("scores"), dict)}
    for it in production_first_frames(root, run, ep):
        if not re.fullmatch(r"S\d+", str(it.get("shot"))):     # 只认正片镜
            continue
        if not force and (it["shot"], it.get("take")) in done:
            print(json.dumps({"shot": it["shot"], "take": it.get("take"), "skipped": "同 take 已有有效打分（--force 重打）"}, ensure_ascii=False))
            continue
        if it.get("missing"):
            print(json.dumps({"shot": it["shot"], "missing": True}, ensure_ascii=False))
            continue
        if not force and cfg.get("require_idle", True) and not vlm_idle(probe)[0]:
            print(json.dumps({"shot": it["shot"], "skipped": "看图服务忙 / 不在"}, ensure_ascii=False))
            continue
        try:
            r = score_one(root, run, it, cfg, generate)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"shot": it["shot"], "error": repr(e)[:200]}, ensure_ascii=False))
            continue
        print(json.dumps({"shot": it["shot"], "take": it.get("take"), "mean": r.get("mean"), "scores": r.get("scores"),
                          "look": r.get("look"), "error": r.get("error")}, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["status", "once", "score-episode"])
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--run")
    ap.add_argument("--force", action="store_true", help="不等看图服务空闲（只给排查用）")
    ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    root = Path(a.root)
    cfg = load_cfg(root)
    runs = [a.run] if a.run else active_runs(root)
    if a.cmd == "status":
        idle, info = vlm_idle()
        print(f"enabled={cfg.get('enabled')} max_per_tick={cfg.get('max_per_tick')} 看图空闲={idle} {json.dumps(info, ensure_ascii=False)}")
        for run in runs:
            items = pending(root, run, cfg)
            by = {}
            for i in items:
                by[i["source"]] = by.get(i["source"], 0) + 1
            print(f"{run}: 待打 {len(items)} {by}")
        return 0
    if a.cmd == "score-episode":
        return score_episode(root, a.run or "series10_v2", a.episode, cfg, force=a.force)
    rec = tick(root, runs, cfg, force=a.force)
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
