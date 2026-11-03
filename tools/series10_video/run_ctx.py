"""视频链按剧取路径（MERGE-VID-O 11-03，L-137：V2 并回 V1 视频链；ISS-1103-024206-3737）。

build_jobs / vidgen / night / deploy / sync / upscale_preview / episode_report / score_clip 以前写死 data/pipeline/runs/series10_v1/video。
现在一律经这里取“当前剧”：
  - 命令行 --run <剧> / --run=<剧>，或环境变量 NS_RUN（night 给子进程设 NS_RUN，服务器上 vidgen 由 deploy start 带 --run 起）；
  - 笔记本上都没给 → tools/autopilot/runs.py current_run（NS_RUN / runs.json primary），与 ns_agent.run_paths 同一口径；
  - 服务器镜像目录（没有 tools/autopilot/runs.py）都没给 → VideoRunError（失败关闭，不默认第一季）。
校验（失败关闭）：剧名只许 [A-Za-z0-9_-]；笔记本上必须是 runs.json 登记的剧，且在 config/pipeline/video_policy.json scope_runs 里
（这部剧的视频政策 = V1 原样的 Pika / recipes / H3 / lint；没登记就不许出视频）。
路径：视频目录 data/pipeline/runs/<剧>/video（V1 = series10_v1 原目录不变）。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class VideoRunError(RuntimeError):
    """视频链认不出 / 不认这部剧（没给剧、没登记、没有视频政策）：失败关闭"""


def _runs_mod():
    p = ROOT / "tools" / "autopilot" / "runs.py"
    if not p.is_file() or not (ROOT / "config" / "pipeline" / "runs.json").is_file():
        return None
    if "runs" in sys.modules and Path(getattr(sys.modules["runs"], "__file__", "") or "").resolve() == p.resolve():
        return sys.modules["runs"]
    if "_RUNS" not in globals():
        import importlib.util as _u   # noqa: PLC0415
        sp = _u.spec_from_file_location("runs_for_video_ctx", p)
        m = _u.module_from_spec(sp)
        sp.loader.exec_module(m)
        globals()["_RUNS"] = m
    return globals()["_RUNS"]


def arg_run(argv: list[str] | None = None) -> str | None:
    a = list(sys.argv[1:] if argv is None else argv)
    for i, x in enumerate(a):
        if x == "--run" and i + 1 < len(a):
            return a[i + 1]
        if x.startswith("--run="):
            return x.split("=", 1)[1]
    return None


def strip_run(argv: list[str]) -> list[str]:
    out, skip = [], False
    for i, x in enumerate(argv):
        if skip:
            skip = False
            continue
        if x == "--run":
            skip = i + 1 < len(argv)
            continue
        if not x.startswith("--run="):
            out.append(x)
    return out


def scope_runs() -> list[str]:
    try:
        return list(json.loads((ROOT / "config/pipeline/video_policy.json").read_text(encoding="utf-8")).get("scope_runs") or [])
    except (OSError, ValueError) as e:
        raise VideoRunError(f"读不到 config/pipeline/video_policy.json（{e}）：视频政策缺失，失败关闭") from e


def resolve(argv: list[str] | None = None, *, server: bool | None = None) -> str:
    """当前视频链在做的剧。server=None：按有没有 runs.py 判断（服务器镜像目录没有）"""
    run = arg_run(argv) or os.environ.get("NS_RUN")
    R = _runs_mod()
    if server is None:
        server = R is None
    if not run:
        if server or R is None:
            raise VideoRunError("视频链必须显式指定剧：--run <剧> 或 NS_RUN（服务器侧不默认第一季，L-137 / I-16）")
        run = R.current_run(ROOT)
    if not run or not _NAME.match(run):
        raise VideoRunError(f"剧名不合法：{run!r}")
    if R is not None and not server:
        if run not in ((R.registry(ROOT).get("runs") or {})):
            raise VideoRunError(f"{run} 不在 config/pipeline/runs.json 登记表里（失败关闭）")
        if run not in scope_runs():
            raise VideoRunError(f"{run} 不在 config/pipeline/video_policy.json scope_runs：这部剧没有视频政策，不出视频（失败关闭）")
    return run


def vid_rel(run: str) -> str:
    return f"data/pipeline/runs/{run}/video"


def run_dir(run: str) -> Path:
    return ROOT / "data/pipeline/runs" / run


def vid_dir(run: str) -> Path:
    return ROOT / vid_rel(run)


def is_legacy(run: str) -> bool:
    R = _runs_mod()
    return bool(R is None or R.is_legacy(run, ROOT))


def renders_dir(run: str) -> Path:
    """本剧渲染根（takes.json 所在）：tools/autopilot/runs.renders_dir（V1 = data/renders，其它 = data/renders/<剧>）"""
    R = _runs_mod()
    if R is None:
        raise VideoRunError("服务器镜像目录没有 runs.py，不能解析渲染目录")
    return Path(R.renders_dir(run, ROOT))


def script_path(run: str) -> Path:
    R = _runs_mod()
    if R is None:
        raise VideoRunError("服务器镜像目录没有 runs.py，不能解析导入稿")
    return Path(R.script_path(run, ROOT))


def episodes_out(run: str) -> Path:
    """整集成片目录：V1 = data/episodes/series10（原样），其它剧 = data/episodes/<剧>"""
    return ROOT / "data/episodes" / ("series10" if is_legacy(run) else run)


def music_dir(run: str) -> Path:
    """集级 BGM 目录（ns_post.run_media.music_dir：V2 = data/music/<剧>，先校验曲库；legacy = data/music/series10）"""
    p = str(ROOT / "services" / "post")
    if p not in sys.path:
        sys.path.insert(0, p)
    from ns_post import run_media as RM   # noqa: PLC0415
    return RM.music_dir(run, ROOT)


def child_env(run: str) -> dict:
    """子进程环境：钉住剧（NS_RUN），ns_render.pipeline / run_paths / register_takes 都按它取 renders / 导入稿"""
    return {**os.environ, "PYTHONUTF8": "1", "NS_RUN": run}
