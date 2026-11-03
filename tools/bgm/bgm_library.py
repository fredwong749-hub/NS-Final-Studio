"""V2 集级 BGM 写入方（MERGE-VID-O 11-03；L-118 剪辑锁定后整集配一条、L-131 只从曲库取、L-137 V2 并回 V1 链路）。

V1 的写入方是 tools/bgm/agent.py（ACE-Step 逐集生成候选 → 审听挑选）；资产包模式的剧（V2）配乐只许来自 config/music_v2.json 曲库
（ns_post.run_media.music_library：run 一致、逐条 sha256 校验），所以这里不生成，只做“按锁定时间轴把曲库曲目铺成整集一条”：

  1. 剪辑锁定（K-EDT-821，判定 = tools/director/edit_lock.check，同一套 L1–L5）：按剧存 data/director/runs/<剧>/edit_lock/epNN.json，
     锁定后的 BGM 请求 data/director/runs/<剧>/bgm_requests/epNN.json（不和 V1 的 data/director/edit_lock 混）；
  2. 每镜分段（gen_contract.style.segment_of：【幻想段】/【现实段】；没标 = 现实段）→ 连续同段合成一段 span；
     幻想段用 use=幻想段 的曲，现实段用 use=现实段 的曲（曲库顺序第一首；--track 可指定）；
  3. ffmpeg 每段循环 / 截到段长，段间交叉淡化（edit_lock.XFADE_S），尾部淡出 → 两遍 loudnorm（deliver.loudnorm，−16 LUFS / −1 dBTP）；
  4. 写 data/music/<剧>/epNN.wav + epNN.json（ns_post.music.find_music 格式 + library_track / library_sha256，
     run_media.check_episode_music 据此校验）+ epNN/meta.json（mode=library，界面换用走 deliver.choose → 这里）。
没锁定 → status=not_locked（不出 BGM，合成照 --no-bgm）；曲库不符 → V2MediaError（失败关闭，不退回 V1 的 data/music/series10）。

    .venv/Scripts/python.exe tools/bgm/bgm_library.py --run series10_v2 --ep 1 --timeline data/episodes/series10_v2/ep01_v2.timeline.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools" / "bgm", ROOT / "services" / "post", ROOT / "services" / "agent", ROOT / "tools" / "director"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import deliver as D  # noqa: E402

VERSION = "bgm-lib/1"
FADE_OUT_S = 2.0
FADE_IN_S = 0.5


class NotLibraryRun(RuntimeError):
    """legacy 剧（V1）的 BGM 走 tools/bgm/agent.py，不走曲库"""


def _rm():
    from ns_post import run_media as RM   # noqa: PLC0415
    return RM


def _el():
    import edit_lock as EL   # noqa: PLC0415
    return EL


def lock_dirs(run: str) -> tuple[Path, Path]:
    base = ROOT / "data" / "director" / "runs" / run
    return base / "edit_lock", base / "bgm_requests"


def script_shots(run: str, ep: int) -> dict[int, dict]:
    from ns_agent import run_paths as RP   # noqa: PLC0415
    m = RP.runs_module(ROOT)
    d = json.loads(Path(m.script_path(run, ROOT)).read_text(encoding="utf-8"))
    e = next((x for x in d.get("episodes") or [] if int(x.get("number")) == ep), None)
    if e is None:
        raise ValueError(f"{run} 导入稿里没有第 {ep} 集")
    return {int(s["index"]): s for s in e.get("shots") or []}


def check_lock(run: str, ep: int, tl_path: Path) -> dict:
    """edit_lock.check（L1–L5）按剧落盘；锁定 → 写本剧 BGM 请求。→ 锁定记录（含 bgm_request 路径）"""
    EL = _el()
    locks, reqs = lock_dirs(run)
    tl = json.loads(Path(tl_path).read_text(encoding="utf-8"))
    if int(tl.get("episode") or 0) != ep:
        raise ValueError(f"时间轴 {tl_path} 是第 {tl.get('episode')} 集，不是第 {ep} 集")
    lp = locks / f"ep{ep:02d}.json"
    prev = D.jload(lp, {}) or {}
    r = EL.check(tl, prev.get("last_sig"))
    hist = (prev.get("history") or [])[-19:] + [{"sig": r["sig"], "timeline": str(tl_path), "at": time.strftime("%F %T"),
                                                 "locked": r["locked"]}]
    out = {**r, "run": run, "last_sig": r["sig"], "timeline": str(tl_path), "history": hist}
    if r["locked"]:
        req = EL.bgm_request(tl, script_shots(run, ep), r["sig"])
        req["run"] = run
        D.jsave(reqs / f"ep{ep:02d}.json", req)
        out["bgm_request"] = str((reqs / f"ep{ep:02d}.json").relative_to(ROOT)).replace("\\", "/")
    D.jsave(lp, out)
    return out


def locked_request(run: str, ep: int) -> dict | None:
    locks, reqs = lock_dirs(run)
    lock, req = D.jload(locks / f"ep{ep:02d}.json"), D.jload(reqs / f"ep{ep:02d}.json")
    if not (lock and req and lock.get("locked") and lock.get("sig") == req.get("edit_sig")):
        return None
    return req


def segment_of(shot: dict) -> str:
    from ns_agent.gen_contract import style as ST   # noqa: PLC0415
    seg, _src = ST.segment_of(shot)
    return seg or "reality"


def pick_track(lib: dict, segment: str, track: str | None = None) -> dict:
    want = {"fantasy": "幻想段", "reality": "现实段"}[segment]
    if track and track in lib and lib[track].get("use") == want:
        return lib[track]
    t = next((t for t in lib.values() if t.get("use") == want), None)
    if t is None:
        raise _rm().V2MediaError(f"config/music_v2.json 没有 use={want} 的曲目")
    return t


def plan(run: str, ep: int, req: dict, shots: dict[int, dict], lib: dict, track: str | None = None) -> dict:
    """锁定时间轴 → 分段铺曲方案（纯计算，不碰文件）"""
    spans: list[dict] = []
    for s in req["shots"]:
        seg = segment_of(shots.get(int(s["index"])) or {})
        t0, t1 = float(s["start_s"]), float(s["start_s"]) + float(s["dur_s"])
        if spans and spans[-1]["segment"] == seg:
            spans[-1]["t1"] = round(t1, 3)
            spans[-1]["shots"].append(int(s["index"]))
            continue
        tr = pick_track(lib, seg, track)
        spans.append({"segment": seg, "track": tr["id"], "file": tr["file"], "sha256": tr["sha256"], "t0": round(t0, 3),
                      "t1": round(t1, 3), "shots": [int(s["index"])]})
    if not spans:
        raise ValueError(f"第 {ep} 集锁定时间轴没有镜头")
    total = float(req.get("duration_s") or spans[-1]["t1"])
    by_len: dict[str, float] = {}
    for sp in spans:
        by_len[sp["track"]] = by_len.get(sp["track"], 0.0) + sp["t1"] - sp["t0"]
    main = max(by_len, key=by_len.get)
    return {"run": run, "episode": ep, "duration_s": round(total, 3), "spans": spans, "library_track": main,
            "library_sha256": lib[main]["sha256"], "crossfade_s": float(req.get("crossfade_s") or 0.0) if len(spans) > 1 else 0.0,
            "edit_sig": req.get("edit_sig"), "shots": req["shots"]}


def render(pl: dict, dst: Path) -> None:
    """ffmpeg：每段循环 / 截到段长（后一段多留交叉淡化时长），acrossfade 串起来，尾部淡出，截到整集时长"""
    ff = D.ffmpeg()
    xf = float(pl["crossfade_s"])
    args = [ff, "-y", "-v", "error"]
    for k, sp in enumerate(pl["spans"]):
        dur = sp["t1"] - sp["t0"] + (xf if k < len(pl["spans"]) - 1 else 0.0)
        args += ["-stream_loop", "-1", "-t", f"{dur:.3f}", "-i", str(ROOT / sp["file"])]
    n = len(pl["spans"])
    fl, last = [], "[0:a]"
    for k in range(1, n):
        out = f"[x{k}]"
        fl.append(f"{last}[{k}:a]acrossfade=d={xf:.3f}:c1=tri:c2=tri{out}")
        last = out
    T = pl["duration_s"]
    fl.append(f"{last}afade=t=in:d={FADE_IN_S},afade=t=out:st={max(0.0, T - FADE_OUT_S):.3f}:d={FADE_OUT_S},"
              f"atrim=0:{T:.3f},aresample=48000[out]")
    args += ["-filter_complex", ";".join(fl), "-map", "[out]", "-ac", "2", "-c:a", "flac", str(dst)]
    r = subprocess.run(args, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 铺曲失败：{r.stderr[-400:]}")


def assembly_json(pl: dict, wav: Path, cfg: dict, level: dict) -> dict:
    """ns_post.music.find_music 读的 epNN.json（与 deliver.assembly_meta 同形）+ 曲库来源字段"""
    starts = [float(s["start_s"]) for s in pl["shots"]]
    durs = [float(s["dur_s"]) for s in pl["shots"]]

    def pos(t):
        return max((k + 1 for k, s in enumerate(starts) if s <= t + 1e-6), default=1)
    cues = [{"shot": pos(sp["t0"]), "start_s": sp["t0"], "offset_s": round(sp["t0"] - starts[pos(sp["t0"]) - 1], 3),
             "action": "enter" if k == 0 else "continue", "intensity": 2,
             "text": f"{'幻想段' if sp['segment'] == 'fantasy' else '现实段'}：曲库 {sp['track']}"} for k, sp in enumerate(pl["spans"])]
    return {"episode": pl["episode"], "version": VERSION, "run": pl["run"], "file": wav.name, "duration_s": pl["duration_s"],
            "episode_duration_s": pl["duration_s"], "shot_starts": starts, "shot_durations": durs, "cues": cues, "duck_spans": [],
            "duck": {"dialogue_db": cfg["output"]["duck_dialogue_db"], "vo_db": cfg["output"]["duck_vo_db"]},
            "library_track": pl["library_track"], "library_sha256": pl["library_sha256"],
            "library_spans": [{k: sp[k] for k in ("segment", "track", "sha256", "t0", "t1", "shots")} for sp in pl["spans"]],
            "crossfade_s": pl["crossfade_s"], "edit_sig": pl["edit_sig"], "model": "library", "seed": None,
            "candidate": pl["library_track"], "sha256": hashlib.sha256(wav.read_bytes()).hexdigest(), "loudness": level,
            "source": "config/music_v2.json（L-131）；tools/bgm/bgm_library.py（L-118 剪辑锁定后整集一条）",
            "created": time.strftime("%Y-%m-%dT%H:%M:%S")}


def deliver_episode(run: str, ep: int, *, track: str | None = None, by: str = "tools/bgm/bgm_library.py",
                    reason: str = "剪辑锁定后按曲库铺整集（L-118 / L-131）") -> dict:
    if D.is_legacy_run(run):
        raise NotLibraryRun(f"{run} 是 legacy 剧：BGM 走 tools/bgm/agent.py")
    RM = _rm()
    lib = RM.music_library(run, ROOT)             # sha 校验；不符 → V2MediaError
    od = RM.music_dir(run, ROOT)
    req = locked_request(run, ep)
    mp = od / f"ep{ep:02d}" / "meta.json"
    state = D.jload(mp, {}) or {}
    if req is None:
        state.update(mode="library", episode=ep, run=run, status="not_locked", at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        D.jsave(mp, state)
        return state
    if (state.get("status") == "delivered" and state.get("edit_sig") == req.get("edit_sig") and not track
            and (od / f"ep{ep:02d}.wav").is_file()):
        return state                                   # 同一份锁定剪辑已经配过：不重铺
    pl = plan(run, ep, req, script_shots(run, ep), lib, track)
    cfg = D.load_cfg()
    od.mkdir(parents=True, exist_ok=True)
    raw = od / f"ep{ep:02d}" / "library_raw.flac"
    raw.parent.mkdir(parents=True, exist_ok=True)
    render(pl, raw)
    wav = od / f"ep{ep:02d}.wav"
    tmp = od / f"ep{ep:02d}" / "library_norm.flac"
    level = D.loudnorm(raw, tmp, cfg["output"]["lufs"], cfg["output"]["true_peak_db"])
    D.flac_to_wav(tmp, wav)
    raw.unlink(missing_ok=True)
    tmp.unlink(missing_ok=True)
    D.jsave(od / f"ep{ep:02d}.json", assembly_json(pl, wav, cfg, level))
    prev = (state.get("chosen") or {}).get("id")
    state.update(mode="library", episode=ep, run=run, status="delivered", edit_sig=pl["edit_sig"],
                 candidates=[{"id": t["id"], "use": t.get("use"), "theme": t.get("theme"), "file": t["file"], "gate_pass": True}
                             for t in lib.values()])
    state["chosen"] = {"id": pl["library_track"], "by": by, "reason": reason, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "wav": str(wav.relative_to(ROOT)).replace("\\", "/"), "previous": prev, "spans": pl["spans"]}
    state.setdefault("history", []).append({k: v for k, v in state["chosen"].items() if k != "spans"})
    D.jsave(mp, state)
    RM.check_episode_music(run, ep, od, root=ROOT)   # 写完立刻按合成端的校验再查一遍（失败关闭）
    return state


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--ep", type=int, required=True)
    ap.add_argument("--timeline", help="合成时间轴（epNN_vN.timeline.json）：先按 L1–L5 判剪辑锁定")
    ap.add_argument("--track", help="现实段 / 幻想段指定曲库 id（不给 = 曲库顺序第一首）")
    a = ap.parse_args(argv)
    os.environ["NS_RUN"] = a.run
    out = {}
    if a.timeline:
        lk = check_lock(a.run, a.ep, Path(a.timeline))
        out["lock"] = {"locked": lk["locked"], "sig": lk["sig"], "fails": [c["id"] for c in lk["conds"] if not c["pass"]]}
    st = deliver_episode(a.run, a.ep, track=a.track)
    out.update(status=st.get("status"), track=(st.get("chosen") or {}).get("id"))
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
