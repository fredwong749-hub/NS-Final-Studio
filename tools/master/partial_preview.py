"""W46 部分预览（总调度 04:2x 令：“有几镜拼几镜，先出 ep01 预览”）。在 gpu33 的隔离副本里跑，只读生产素材、只写一个产物目录。

每拍（默认 300 s）：
 1. 把生产仓库 data/renders/<剧>/epNN/ 与 <剧>/video/（state / manifest，不含 clips 以外的写入）镜像进副本（cp -a，只增改不删）；
 2. 数本集 takes.json active.video（只认本剧前缀、文件在）；
 3. ≥ MIN_SHOTS 镜且比上次拼时多 ≥ STEP 镜（第一次 = 达到 MIN_SHOTS）→ 副本里跑
    tools/assemble_series.py epNN --preview --partial --no-pull --no-bgm --out-name epNN_preview_partial_HHMM
    （缺视频的镜 = 黑场 + 镜号字样；只给预览，不进成片）；
 4. 产物 mp4 + .srt + _manifest.json 装到生产 data/episodes/<剧>/_partial/（**子目录**：sop_gate.check_preview 只认
    data/episodes/<剧>/epNN*.mp4 顶层，部分预览不会被当成“整集预览”放行复盘 / 第 N+1 集出图）。
状态：<副本>/data/_w46_partial/state.json（每次拼的镜数 / 时长 / 路径），总调度 / 笔记本读它写 V2_LIVE。

    python tools/master/partial_preview.py --prod /root/work/fredw/offline_20261101/repo --ep 1 [--loop] [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
import runs as _RUNS  # noqa: E402
MIN_SHOTS, STEP = 3, 2


def _jl(p: Path, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _js(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def mirror(prod: Path, run: str, ep: int) -> None:
    """生产 → 副本：本集渲染目录 + 视频 state（cp -a 覆盖同名，不删副本多出的）"""
    for rel in (_RUNS.renders_dir(run, ROOT).relative_to(ROOT).as_posix() + f"/ep{ep:02d}", f"data/pipeline/runs/{run}/video"):
        src = prod / rel
        if not src.is_dir():
            continue
        (ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cp", "-a", str(src) + "/.", str(ROOT / rel)], check=True, timeout=600)


def video_shots(run: str, ep: int, root: Path = ROOT) -> list[str]:
    out = []
    base = _RUNS.renders_dir(run, root) / f"ep{ep:02d}"
    for tj in sorted(base.glob("S*/takes.json"), key=lambda p: int(p.parent.name[1:]) if p.parent.name[1:].isdigit() else 0):
        d = _jl(tj, {}) or {}
        n = (d.get("active") or {}).get("video")
        t = next((x for x in d.get("takes") or [] if x.get("stage") == "video" and x.get("n") == n), None)
        f = str((t or {}).get("file") or "").replace("\\", "/")
        if t and f.startswith(f"renders/{run}/") and (root / "data" / f).is_file():
            out.append(f"ep{ep:02d}-{tj.parent.name}")
    # vidgen 出完先落 state_<host>.json（done / best_effort + file），register_takes 下一拍才进 takes.json → 两边都算（assemble_series.plan 同口径）
    for stp in (root / "data/pipeline/runs" / run / "video").glob("state_*.json"):
        for sid, r in ((_jl(stp, {}) or {}).get("shots") or {}).items():
            if not sid.startswith(f"ep{ep:02d}-") or r.get("status") not in ("done", "best_effort") or sid in out:
                continue
            x = next((x for x in r.get("renders") or [] if x.get("variant") == r.get("chosen") and x.get("file")), None)
            if x and (root / x["file"]).is_file():
                out.append(sid)
    return sorted(out, key=lambda s: int(s.split("-S")[1]))


def due(n: int, last_n: int | None, force: bool = False) -> bool:
    if force:
        return n > 0
    if n < MIN_SHOTS:
        return False
    return last_n is None or n >= last_n + STEP


def tick(prod: Path, run: str, ep: int, force: bool = False) -> dict:
    sp = ROOT / "data/_w46_partial/state.json"
    st = _jl(sp, {}) or {}
    mirror(prod, run, ep)
    shots = video_shots(run, ep)
    res = {"at": time.strftime("%F %T"), "video_shots": shots, "n": len(shots), "last_n": st.get("last_n")}
    if not due(len(shots), st.get("last_n"), force):
        res["skip"] = f"视频 {len(shots)} 镜（≥{MIN_SHOTS} 才拼，之后每多 {STEP} 镜更新）"
        st["last_check"] = res
        _js(sp, st)
        return res
    name = f"ep{ep:02d}_preview_partial_{time.strftime('%H%M')}"
    out_dir = ROOT / "data/episodes" / run / "_partial"
    t0 = time.time()
    env = {**os.environ, "NS_RUN": run, "PYTHONUTF8": "1"}
    r = subprocess.run([sys.executable, "tools/assemble_series.py", f"ep{ep:02d}", "--preview", "--partial", "--no-pull", "--no-bgm",
                        "--out-dir", str(out_dir), "--out-name", name], cwd=str(ROOT), env=env, capture_output=True, text=True,
                       timeout=3600)
    res.update(rc=r.returncode, build_s=round(time.time() - t0, 1), tail=(r.stdout + r.stderr)[-600:])
    mp4 = out_dir / f"{name}.mp4"
    if r.returncode == 0 and mp4.is_file():
        dst = prod / "data/episodes" / run / "_partial"
        dst.mkdir(parents=True, exist_ok=True)
        for f in (mp4, out_dir / f"{name}.srt", out_dir / f"{name}_manifest.json"):
            if f.is_file():
                tmp = dst / (f.name + ".tmp")
                shutil.copyfile(f, tmp)
                os.replace(tmp, dst / f.name)
        man = _jl(out_dir / f"{name}_manifest.json", {}) or {}
        res.update(output=str(dst / mp4.name), duration_s=man.get("duration_s"), video_shots_built=man.get("video_shots"),
                   placeholder_shots=man.get("placeholder_shots"))
        st["last_n"] = len(shots)
        st.setdefault("builds", []).append({k: res.get(k) for k in ("at", "n", "video_shots", "output", "duration_s", "build_s")})
    st["last_check"] = res
    _js(sp, st)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", required=True, help="生产仓库根（只读素材；产物写 data/episodes/<剧>/_partial/）")
    ap.add_argument("--run", default="series10_v2")
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--every", type=int, default=300)
    ap.add_argument("--force", action="store_true", help="有 1 镜视频就拼一次（试跑）")
    a = ap.parse_args(argv)
    prod = Path(a.prod).resolve()
    if prod == ROOT.resolve():
        raise SystemExit("partial_preview 必须在隔离副本里跑（--prod 指生产仓库，ROOT 是副本）")
    while True:
        try:
            print(json.dumps(tick(prod, a.run, a.ep, a.force), ensure_ascii=False), flush=True)
        except Exception as e:  # noqa: BLE001  # arch-ok: 一拍失败只记，下拍再试
            print(json.dumps({"at": time.strftime("%F %T"), "error": repr(e)[:300]}, ensure_ascii=False), flush=True)
        if not a.loop:
            return 0
        a.force = False
        time.sleep(a.every)


if __name__ == "__main__":
    raise SystemExit(main())
