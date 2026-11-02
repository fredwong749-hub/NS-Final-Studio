"""
项目上下文（T42）：一部剧 = 一个项目目录。第一部《为他而骚》仍在仓库根目录（slug "weita"，默认项目），
第二部起放进 projects/<slug>/（docs/SOP_production.md §1）：

    projects/<slug>/
      project.json        本项目设置（向导写入：剧名、状态、LoRA 计划、成人内容开关、人物、关口记录）
      script/             原始剧本三件套（只读原件）+ 之后 gpu3 交回的 v3
      config/             visual_bible.toml（由模板生成）、face_reference.json、adult_overrides.json、voices.json
      assets/             characters/<id>/{refs,plates,expressions,items,looks}、style/
      data/               import/、looks/、renders/、renders_gpu3/、music/、episodes/、orchestrator/
      previews/  docs/
    projects/registry.json  项目登记（slug → 剧名 / 目录 / 状态）

本模块只算路径、读写登记表，不导入渲染/编译代码（编排器和测试都能轻量使用）。
项目根目录的布局与仓库根一致，所以渲染/装配子进程只要设 NS_PROJECT_ROOT=<项目目录> 就会读写该项目
（pipeline/refs/grade/compiler/looks/ns_post 的 ROOT 默认值支持这个环境变量，见 CHANGELOG 2026-10-30 T42）。
"""
from __future__ import annotations

from ns_api import run_paths as _RP   # K-OPS-F24：渲染根目录按当前剧（V1 已归档，不在网页显示）
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SLUG = "weita"
DEFAULT_NAME = "为他而骚"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,40}$")
_lock = threading.RLock()


def projects_dir() -> Path:
    """NS_PROJECTS_DIR 可改（测试用临时目录）；默认 <仓库>/projects"""
    return Path(os.environ.get("NS_PROJECTS_DIR") or REPO / "projects")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def write_json(p: Path, obj) -> None:
    """原子写：先写临时文件再替换，断电/崩溃不会留下半个 JSON"""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


@dataclass(frozen=True)
class ProjectContext:
    slug: str
    name: str
    root: Path                      # 项目根（默认项目 = 仓库根）
    is_default: bool = False
    gpu3_subdir: str = ""           # gpu3 桥上的子目录：默认项目为空（data/renders_gpu3/epXX），新项目 = slug
    extra: dict = field(default_factory=dict, compare=False, hash=False)

    # ---- 目录
    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def script_dir(self) -> Path:
        return REPO / "script play lib" if self.is_default else self.root / "script"

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def renders(self) -> Path:
        return _RP.renders_root(self.root)

    @property
    def import_dir(self) -> Path:
        return self.data_dir / "import"

    @property
    def script_json(self) -> Path:
        # 渲染流水线 / 造型库都按这个名字读当前导入结果（ns_render.pipeline.SCRIPT_JSON）
        return self.import_dir / "script_v2.json"

    @property
    def looks_dir(self) -> Path:
        return self.data_dir / "looks"

    @property
    def episodes_out(self) -> Path:
        return self.data_dir / "episodes"

    @property
    def orchestrator_dir(self) -> Path:
        return self.data_dir / "orchestrator"

    @property
    def renders_gpu3_dirs(self) -> list[Path]:
        """笔记本上的 gpu3 镜像位置（只读）。新项目按 SOP 放 projects/<slug>/data/renders_gpu3，
        桥的约定是 data/renders_gpu3/<slug>/ —— 两处都认，先存在的优先。"""
        if self.is_default:
            return [REPO / "data" / "renders_gpu3"]
        return [self.data_dir / "renders_gpu3", REPO / "data" / "renders_gpu3" / self.gpu3_subdir]

    @property
    def renders_gpu3(self) -> Path:
        dirs = self.renders_gpu3_dirs
        return next((d for d in dirs if d.is_dir()), dirs[0])

    @property
    def music_dirs(self) -> list[Path]:
        if self.is_default:
            return [REPO / "data" / "music"]
        return [self.data_dir / "music", REPO / "data" / "music" / self.gpu3_subdir]

    # ---- 文件
    @property
    def project_json(self) -> Path:
        return self.root / ("project.json" if not self.is_default else "data/orchestrator/project.json")

    @property
    def visual_bible(self) -> Path:
        return self.config_dir / "visual_bible.toml"

    @property
    def face_reference(self) -> Path:
        return self.config_dir / "face_reference.json"

    @property
    def adult_overrides(self) -> Path:
        return self.config_dir / "adult_overrides.json"

    def settings(self) -> dict:
        return read_json(self.project_json, {})

    def save_settings(self, data: dict) -> dict:
        data = {**data, "updated_at": now()}
        write_json(self.project_json, data)
        return data

    def env(self) -> dict[str, str]:
        """子进程环境：让 pipeline/compiler/looks/ns_post 的 ROOT 指向本项目（默认项目不设）"""
        env = dict(os.environ)
        if not self.is_default:
            env["NS_PROJECT_ROOT"] = str(self.root)
        else:
            env.pop("NS_PROJECT_ROOT", None)
        return env

    def rel(self, p: Path) -> str:
        return p.resolve().relative_to(self.root.resolve()).as_posix()

    def resolve_inside(self, rel: str) -> Path:
        """项目内相对路径 → 绝对路径；越界（../）抛 ValueError"""
        p = (self.root / rel).resolve()
        if not p.is_relative_to(self.root.resolve()):
            raise ValueError("路径越界")
        return p


def default_project() -> ProjectContext:
    return ProjectContext(slug=DEFAULT_SLUG, name=DEFAULT_NAME, root=REPO, is_default=True, gpu3_subdir="")


# ------------------------------------------------------------------ 登记表

def registry_path() -> Path:
    return projects_dir() / "registry.json"


def load_registry() -> dict:
    reg = read_json(registry_path(), {"version": 1, "projects": []})
    reg.setdefault("projects", [])
    return reg


def _entry_ctx(e: dict) -> ProjectContext:
    root = Path(e["root"])
    if not root.is_absolute():
        root = projects_dir() / root
    return ProjectContext(slug=e["slug"], name=e["name"], root=root, gpu3_subdir=e.get("gpu3_subdir") or e["slug"],
                          extra={"status": e.get("status", "draft"), "created_at": e.get("created_at")})


def list_projects() -> list[ProjectContext]:
    with _lock:
        return [default_project()] + [_entry_ctx(e) for e in load_registry()["projects"]]


def get_project(slug: str | None) -> ProjectContext:
    if not slug or slug == DEFAULT_SLUG:
        return default_project()
    for e in load_registry()["projects"]:
        if e["slug"] == slug:
            return _entry_ctx(e)
    raise KeyError(slug)


def slugify(name: str, taken: set[str]) -> str:
    """剧名多为中文：取 ASCII 部分，没有就用 drama-NN"""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30]
    if not base or not SLUG_RE.match(base):
        base = "drama"
    slug, i = base, 2
    if base == "drama":
        slug = f"drama-{i:02d}"
    while slug in taken or slug == DEFAULT_SLUG:
        slug = f"{base}-{i:02d}"
        i += 1
    return slug


PROJECT_SUBDIRS = ("script", "config", "assets/characters", "assets/style", "data/import", "data/looks",
                   "data/renders", "data/renders_gpu3", "data/music", "data/episodes", "data/orchestrator",
                   "previews", "docs")


def create_project(name: str, slug: str | None = None) -> ProjectContext:
    name = name.strip()
    if not name:
        raise ValueError("剧名不能为空")
    with _lock:
        reg = load_registry()
        taken = {e["slug"] for e in reg["projects"]}
        if any(e["name"] == name for e in reg["projects"]) or name == DEFAULT_NAME:
            raise ValueError(f"已有同名项目：{name}")
        if slug:
            if not SLUG_RE.match(slug) or slug in taken or slug == DEFAULT_SLUG:
                raise ValueError(f"项目代号不可用：{slug}（小写字母/数字/-/_，且不能重复）")
        else:
            slug = slugify(name, taken)
        root = projects_dir() / slug
        for sub in PROJECT_SUBDIRS:
            (root / sub).mkdir(parents=True, exist_ok=True)
        entry = {"slug": slug, "name": name, "root": slug, "gpu3_subdir": slug, "status": "draft", "created_at": now()}
        reg["projects"].append(entry)
        write_json(registry_path(), reg)
        ctx = _entry_ctx(entry)
        ctx.save_settings({"slug": slug, "name": name, "status": "draft", "created_at": entry["created_at"],
                           "adult_content": True, "lora_plan": {}, "characters": {}, "gates": {}})
        return ctx


def set_status(slug: str, status: str) -> None:
    with _lock:
        reg = load_registry()
        for e in reg["projects"]:
            if e["slug"] == slug:
                e["status"] = status
        write_json(registry_path(), reg)
