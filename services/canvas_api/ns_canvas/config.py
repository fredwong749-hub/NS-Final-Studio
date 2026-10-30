"""运行配置（环境变量；gpu3 上见 deploy/nsfs-canvas-bridge.env）。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RootCfg:
    label: str          # URL 里用的短名
    kind: str           # takes（renders_gpu3，take 布局）或 weita（微型测试布局，只读对照）
    path: Path
    data_dir: Path | None = None   # Take.file 相对的 data/ 目录；默认 path.parent


@dataclass
class Settings:
    queue_dir: Path                 # rerender_queue.jsonl / rerender_events.jsonl 所在目录（= renders_gpu3）
    roots: list[RootCfg]            # 默认项目（weita = 为他而骚）的来源，按优先级
    cache_dir: Path                 # 尾帧、缩略图缓存
    script_json: Path | None = None # 默认项目的剧本导入 JSON（列镜号、算总镜数）
    ffmpeg: str = "ffmpeg"
    # —— 项目进度 / 系列控制 / GPU ——
    renders_base: Path | None = None        # renders_gpu3 根；新项目在 <base>/<slug>/epXX/…
    default_slug: str = "weita"             # 这个 slug 映射到 renders_base 根（现有路径不动）
    series_out: Path | None = None          # 默认项目的系列渲染器工作目录（ns-studio/data/run/weita）
    bench_csv: Path | None = None           # golden/bench.csv（实测每镜 GPU 秒）
    music_dir: Path | None = None           # data/music（epXX.wav）
    projects_root: Path | None = None       # 新剧 projects/<slug>/data/import/script_v2.json（笔记本布局，gpu3 镜像在 checkout 内同路径）
    lock_dir: Path = Path("/root/.local/state/NS-Studio")
    nvidia_smi: str = "nvidia-smi"
    comfy: dict[int, str] = field(default_factory=dict)   # GPU 号 → ComfyUI URL
    faulty_gpus: tuple[int, ...] = (2,)

    @property
    def base(self) -> Path:
        return self.renders_base or self.queue_dir

    @classmethod
    def from_env(cls) -> "Settings":
        repo = Path(__file__).resolve().parents[3]
        default = repo / "data" / "renders_gpu3"
        roots = []
        # NSC_ROOTS="label|kind|path;label|kind|path"
        for part in filter(None, os.environ.get("NSC_ROOTS", "").split(";")):
            label, kind, path = part.split("|", 2)
            roots.append(RootCfg(label.strip(), kind.strip(), Path(path.strip())))
        if not roots:
            roots = [RootCfg("renders_gpu3", "takes", default)]
        q = Path(os.environ.get("NSC_QUEUE_DIR", roots[0].path))
        script = os.environ.get("NSC_SCRIPT_JSON", str(repo / "data" / "import" / "script_v2.json"))
        env = lambda k: Path(os.environ[k]) if os.environ.get(k) else None
        comfy = {}
        # NSC_COMFY="0=http://127.0.0.1:8188;1=http://127.0.0.1:8189;3=http://127.0.0.1:8191"
        for part in filter(None, os.environ.get("NSC_COMFY", "").split(";")):
            g, url = part.split("=", 1)
            comfy[int(g)] = url.strip()
        return cls(queue_dir=q, roots=roots,
                   cache_dir=Path(os.environ.get("NSC_CACHE_DIR", q / ".bridge_cache")),
                   script_json=Path(script) if script else None,
                   ffmpeg=os.environ.get("NSC_FFMPEG", "ffmpeg"),
                   renders_base=env("NSC_RENDERS_BASE") or roots[0].path,
                   default_slug=os.environ.get("NSC_DEFAULT_SLUG", "weita"),
                   series_out=env("NSC_SERIES_OUT"),
                   bench_csv=env("NSC_BENCH_CSV") or (repo / "golden" / "bench.csv"),
                   music_dir=env("NSC_MUSIC_DIR") or (repo / "data" / "music"),
                   projects_root=env("NSC_PROJECTS_ROOT") or (repo / "projects"),
                   lock_dir=env("NSC_LOCK_DIR") or Path("/root/.local/state/NS-Studio"),
                   nvidia_smi=os.environ.get("NSC_NVIDIA_SMI", "nvidia-smi"),
                   comfy=comfy,
                   faulty_gpus=tuple(int(x) for x in os.environ.get("NSC_FAULTY_GPUS", "2").split(",") if x.strip()))
