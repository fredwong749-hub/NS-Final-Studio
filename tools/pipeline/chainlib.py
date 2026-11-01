"""链条契约共用：路径、读 config/pipeline/chain.yaml、按连接取规则（上游规则 + knowledge 规则）（CHAINSPEC 2026-10-31）。"""
from __future__ import annotations

import glob
import importlib
import sys
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "packages" / "schema", ROOT / "services" / "agent", ROOT / "services" / "recipes",
           ROOT / "services" / "api", ROOT / "tools" / "pipeline", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

CHAIN = ROOT / "config" / "pipeline" / "chain.yaml"
KNOWLEDGE_GLOB = "knowledge/rules/*.yaml"
WRITER_STATUSES = ("确认", "建议")     # 进写作提示词的 knowledge 条目状态（待验 / 闸门类不进）


@lru_cache(maxsize=1)
def chain() -> dict:
    return yaml.safe_load(CHAIN.read_text(encoding="utf-8"))


def rule_index() -> dict[str, dict]:
    return {r["id"]: r for r in chain().get("rules") or []}


def links_of(entry: dict) -> list[str]:
    v = entry.get("link")
    return [v] if isinstance(v, str) else list(v or [])


def knowledge_rules() -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(ROOT / KNOWLEDGE_GLOB))):
        try:
            data = yaml.safe_load(Path(f).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        for r in data.get("rules") or []:
            r = dict(r)
            r["_file"] = Path(f).relative_to(ROOT).as_posix()
            out.append(r)
    return out


def knowledge_for(link: str, *, writer_only: bool = False) -> list[dict]:
    rs = [r for r in knowledge_rules() if link in links_of(r)]
    if writer_only:
        rs = [r for r in rs if r.get("writer_text") and r.get("status") in WRITER_STATUSES]
    return rs


def rules_for(link: str) -> list[dict]:
    idx = rule_index()
    return [idx[i] for i in chain()["links"][link].get("rules") or [] if i in idx]


def resolve_ref(ref: str):
    """'module:attr' → 对象"""
    mod, _, attr = ref.partition(":")
    return getattr(importlib.import_module(mod), attr)


def rel(p: Path | str) -> str:
    p = Path(p)
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)
