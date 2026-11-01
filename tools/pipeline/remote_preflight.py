"""离线 / 远端运行前的依赖自检（WORKFLOW 11-01，规则 K-OPS-W02 / W03；docs/AUTOPILOT.md §离线自检）。

起因（11-01 离线交接，night.log 与 data/_offline_pull 实查）：
  - 服务器副本缺 / 坏设定图 → preflight I3 一直挡；拉回笔记本时 7 张截断的设定图按“新者为准”覆盖了笔记本好图，
    asset_refs.sheet_crop 读图抛 OSError: image file is truncated（tests/test_gen_contract.py 5 例因此失败）；
  - 服务器没有 NS_TTS_PYTHON → ep04 合成失败（night.log 11-01 11:11:15 TtsUnavailable）；
  - night.py 卡住没有任何报警。

检查项（每项 pass / fail / warn / skip，任何 fail → 退出码 1）：
  A1 资产图齐全且读得全：config/recipes/asset_refs.json 每个项目的身份脸 faces、sheets_chosen.json 里的每张图、
     item_map 指向的单品图（存在 + PIL 完整解码；截断 / 0 字节 = fail）
  A2 首帧作业参考图：<run>/assets/first_frame_jobs.json 里 refs / asset_refs 引到的图都在、读得全
  T1 配音解释器：config/voices.json speech_python（环境变量 NS_TTS_PYTHON 或 default）存在；--deep 时真的 import sherpa_onnx
  T2 声音表系列：voices.json series 与项目一致（night.py voices_ready 同一判定）
  H1 night.py 心跳（--runtime）：night.pid 进程活着而 night_state.json 超过 --stall-min 分钟没更新 = 卡住（fail）
  H2 producer 心跳（--runtime）：data/producer/heartbeat.json 的 t 超过 --stall-min 分钟 = 卡住（fail）

用法：
  .venv/Scripts/python.exe tools/pipeline/remote_preflight.py                    # 打包 / 交给服务器前，在笔记本上查
  python tools/pipeline/remote_preflight.py --root /root/work/fredw/offline_20261101/repo --deep   # 服务器副本上查（同一脚本）
  .venv/Scripts/python.exe tools/pipeline/remote_preflight.py --runtime          # 运行中巡检：加查 night / producer 是否卡住
结果写 data/autopilot/remote_preflight/latest.json（--root 指向别处时写到那个根下）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def file_problem(p: Path) -> str | None:
    """文件完整性：不存在 / 0 字节 / 图片解码不全 / JSON 解析不了 → 原因；好 → None（merge_pull 也用它）"""
    if not p.is_file():
        return "不存在"
    if p.stat().st_size == 0:
        return "0 字节"
    suf = p.suffix.lower()
    try:
        if suf in IMG_EXT:
            from PIL import Image
            with Image.open(p) as im:
                im.load()
        elif suf == ".json":
            json.loads(p.read_text(encoding="utf-8"))
        elif suf in (".mp4", ".mov"):          # 判据同 UIAUDIT trunc_scan.py：没有 moov 盒 = 没写完 / 传一半
            if b"moov" not in p.read_bytes():
                return "读不全：mp4 无 moov 盒"
    except Exception as e:  # noqa: BLE001
        return f"读不全：{type(e).__name__}: {str(e)[:80]}"
    return None


def _img_strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _img_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _img_strings(v)
    elif isinstance(o, str) and o.lower().endswith(IMG_EXT):
        yield o


def _rp(root: Path, s: str) -> Path:
    p = Path(s)
    return p if p.is_absolute() else root / s


def _jl(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def check_images(root: Path, cid: str, name: str, paths: list[str]) -> dict:
    bad = []
    for s in sorted(set(paths)):
        why = file_problem(_rp(root, s))
        if why:
            bad.append(f"{s}：{why}")
    if not paths:
        return {"id": cid, "name": name, "status": "warn", "detail": "没有找到要查的图"}
    return {"id": cid, "name": name, "status": "fail" if bad else "pass",
            "detail": f"{len(set(paths)) - len(bad)}/{len(set(paths))} 张完好", "bad": bad}


def asset_paths(root: Path) -> dict[str, list[str]]:
    """项目 → 要查的资产图（身份脸 + 选定设定图 + 单品映射图）"""
    cfg = _jl(root / "config/recipes/asset_refs.json", {}) or {}
    out = {}
    for proj, c in (cfg.get("projects") or {}).items():
        paths = [f for faces in (c.get("faces") or {}).values() for f in faces]
        if c.get("sheets_file"):
            sf = _rp(root, c["sheets_file"])
            if not sf.is_file():
                paths.append(c["sheets_file"])       # 选定设定图表本身缺 = fail
            else:
                paths += list(_img_strings(_jl(sf, {})))
        paths += list(_img_strings(c.get("item_map") or {}))
        paths += scene_paths(root, c)
        out[proj] = paths
    return out


SCENE_TRASH = {"trash", "_trash", "rejected"}


def scene_paths(root: Path, c: dict) -> list[str]:
    """场景参考底图（preflight I5 读的；FACTORY 11-02 报：清单漏了 assets/scenes，ep02-S1/S2 在服务器上被 I5“sk_elevator 没有参考底图”挡）。
    asset_refs.scene_ref 取 assets/scenes/<目录>/ 下“最新的一张”（不进 trash / rejected），所以把这些目录下的有效图都列上，
    服务器与笔记本同一组图才会选中同一张；再加 shot_looks.json scene_overrides 指向的图、config/scene_aliases.json 指向的目录"""
    base = root / "assets/scenes"
    out = []
    if base.is_dir():
        for f in base.rglob("*"):
            if f.is_file() and f.suffix.lower() in IMG_EXT and not (SCENE_TRASH & set(f.parts)):
                out.append(f.relative_to(root).as_posix())
    sl = _jl(_rp(root, c.get("shot_looks_file", "")), {}) if c.get("shot_looks_file") else {}
    for v in ((sl or {}).get("scene_overrides") or {}).values():
        if isinstance(v, str) and v.lower().endswith(IMG_EXT) and v != "none":
            out.append(v if v.startswith("assets/") else f"assets/scenes/{v}")
    return sorted(set(out))


def job_ref_paths(root: Path) -> dict[str, list[str]]:
    cfg = _jl(root / "config/recipes/asset_refs.json", {}) or {}
    out = {}
    for proj, c in (cfg.get("projects") or {}).items():
        f = _rp(root, c.get("run_dir", "")) / "assets/first_frame_jobs.json"
        if not f.is_file():
            continue
        d = _jl(f, {}) or {}
        jobs = d.get("jobs") if isinstance(d, dict) else d
        paths = []
        for j in jobs or []:
            paths += [s for s in _img_strings({"r": j.get("refs"), "a": j.get("asset_refs")})
                      if "/cache/" not in s.replace("\\", "/")]     # 缓存缩放图出图时现做，不算依赖
        out[proj] = paths
    return out


def speech_python(root: Path) -> tuple[str | None, dict]:
    v = _jl(root / "config/voices.json", {}) or {}
    sec = v.get("speech_python") or {}
    for c in (os.environ.get(sec.get("env") or "NS_TTS_PYTHON"), sec.get("default")):
        if c and Path(c).exists():
            return c, v
    return None, v


def check_tts(root: Path, deep: bool) -> dict:
    py, v = speech_python(root)
    sec = v.get("speech_python") or {}
    if not py:
        return {"id": "T1", "name": "配音解释器", "status": "fail",
                "detail": f"{sec.get('env') or 'NS_TTS_PYTHON'} 未设且 default {sec.get('default')} 不存在（整集合成会 TtsUnavailable）"}
    if deep:
        try:
            r = subprocess.run([py, "-I", "-c", "import sherpa_onnx;print(sherpa_onnx.__version__)"],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                return {"id": "T1", "name": "配音解释器", "status": "fail", "detail": f"{py} import sherpa_onnx 失败：{r.stderr.strip()[-160:]}"}
            return {"id": "T1", "name": "配音解释器", "status": "pass", "detail": f"{py}（sherpa_onnx {r.stdout.strip()}）"}
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"id": "T1", "name": "配音解释器", "status": "fail", "detail": f"{py} 起不来：{e}"}
    return {"id": "T1", "name": "配音解释器", "status": "pass", "detail": f"{py}（存在；--deep 才实跑 import）"}


def check_voice_series(root: Path, projects: list[str]) -> dict:
    v = _jl(root / "config/voices.json", {}) or {}
    s = v.get("series")
    ok = s in projects
    return {"id": "T2", "name": "声音表系列", "status": "pass" if ok else "fail",
            "detail": f"voices.json series = {s!r}；登记项目 {projects}" + ("" if ok else "（night.py voices_ready 不放行，不会合成对白）")}


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":                       # Windows 上 os.kill(pid, 0) 会结束进程，不能用
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259              # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def check_night(root: Path, run_dir: str, stall_min: float, now: float) -> dict:
    v = _rp(root, run_dir) / "video"
    pidf, st = v / "night.pid", v / "night_state.json"
    # 心跳以 night_state.json 的更新时间为准（每轮 loop_once 末尾写）；night.pid 可能是旧的（11-01 实测：night.py 16:04 重启，
    # night.pid 仍是 05:43 的 18588），pid 只作说明
    try:
        pid = int(pidf.read_text().strip())
    except (OSError, ValueError):
        pid = 0
    if not st.exists():
        return {"id": "H1", "name": "night.py 心跳", "status": "skip", "detail": "没有 night_state.json（没跑过）"}
    age = (now - st.stat().st_mtime) / 60
    note = f"night.pid={pid} {'活着' if pid_alive(pid) else '不在 / 已过期'}"
    return {"id": "H1", "name": "night.py 心跳", "status": "fail" if age > stall_min else "pass",
            "detail": f"night_state.json {age:.1f} 分钟前更新（卡住线 {stall_min:g} 分钟；超线 = 卡住或已退出）；{note}",
            "age_min": round(age, 1)}


def check_producer(root: Path, stall_min: float, now: float) -> dict:
    hb = _jl(root / "data/producer/heartbeat.json")
    if not hb:
        return {"id": "H2", "name": "producer 心跳", "status": "skip", "detail": "没有 heartbeat.json"}
    if hb.get("paused"):
        return {"id": "H2", "name": "producer 心跳", "status": "warn", "detail": "producer 暂停中"}
    age = (now - float(hb.get("t") or 0)) / 60
    alive = pid_alive(int(hb.get("pid") or 0))
    st = "fail" if age > stall_min or not alive else "pass"
    return {"id": "H2", "name": "producer 心跳", "status": st,
            "detail": f"pid {hb.get('pid')} {'活着' if alive else '不在'}；心跳 {age:.1f} 分钟前（卡住线 {stall_min:g} 分钟）", "age_min": round(age, 1)}


def run(root: Path, *, deep: bool = False, runtime: bool = False, stall_min: float = 30.0, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    rows = []
    assets = asset_paths(root)
    for proj, paths in assets.items():
        rows.append({**check_images(root, "A1", f"资产图（{proj}）", paths), "project": proj})
    for proj, paths in job_ref_paths(root).items():
        rows.append({**check_images(root, "A2", f"首帧作业参考图（{proj}）", paths), "project": proj})
    rows.append(check_tts(root, deep))
    rows.append(check_voice_series(root, list(assets)))
    if runtime:
        cfg = _jl(root / "config/recipes/asset_refs.json", {}) or {}
        for proj, c in (cfg.get("projects") or {}).items():
            rows.append({**check_night(root, c.get("run_dir", ""), stall_min, now), "project": proj})
        rows.append(check_producer(root, stall_min, now))
    verdict = "fail" if any(r["status"] == "fail" for r in rows) else "pass"
    return {"schema": "nsfs.remote_preflight/1", "root": str(root), "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            "verdict": verdict, "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--deep", action="store_true", help="实跑配音解释器 import sherpa_onnx")
    ap.add_argument("--runtime", action="store_true", help="加查 night.py / producer 是否卡住")
    ap.add_argument("--stall-min", type=float, default=30.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    root = Path(a.root)
    res = run(root, deep=a.deep, runtime=a.runtime, stall_min=a.stall_min)
    out = Path(a.out) if a.out else root / "data/autopilot/remote_preflight/latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, out)
    for r in res["rows"]:
        print(f"[{r['status']:4}] {r['id']} {r['name']}：{r['detail']}")
        for b in (r.get("bad") or [])[:12]:
            print(f"        - {b}")
    print(f"结论：{res['verdict']}（{out}）")
    return 1 if res["verdict"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
