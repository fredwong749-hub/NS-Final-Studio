"""K-OPS-Q31：剧本全局头 / 主线从现行导入记录自动推导；data_parity 的 pending_redo（CLEANUP 2026-11-01）。"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/agent", "packages/schema", "services/recipes", "services/render_router", "services/post", "tools/qa"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import import_sources as IS  # noqa: E402

HEAD = "# 剧\n\n**每条prompt统一前缀（角色锁）**\n\n```Plain Text\n【甲】占位\n```\n\n"


def _repo(tmp_path, files: dict, sources: list) -> Path:
    for rel, text in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    imp = tmp_path / "data/import/script_v2.json"
    imp.parent.mkdir(parents=True, exist_ok=True)
    imp.write_text(json.dumps({"sources": sources, "episodes": []}, ensure_ascii=False), encoding="utf-8")
    return imp


def sha(tmp_path, rel):
    return hashlib.sha256((tmp_path / rel).read_bytes()).hexdigest()


def test_latest_matching_source_wins(tmp_path):
    files = {"a.md": HEAD + "## ep01《一》\n", "b.md": HEAD + "## ep01《一》\n## ep02《二》\n", "frag.md": "## ep02《二》\n"}
    imp = _repo(tmp_path, files, [])
    srcs = [{"path": "a.md", "sha256": sha(tmp_path, "a.md"), "episodes": [1]},
            {"path": "b.md", "sha256": sha(tmp_path, "b.md"), "episodes": [1, 2]},
            {"path": "frag.md", "sha256": sha(tmp_path, "frag.md"), "episodes": [2]},     # 单集片段：没有全局头
            {"path": "old_ref.md", "sha256": "x", "episodes": []}]                        # 参考来源（没导入集）
    imp.write_text(json.dumps({"sources": srcs}), encoding="utf-8")
    assert [s["path"] for s in IS.current_sources(imp, tmp_path)] == ["frag.md", "b.md", "a.md"]
    assert IS.header_source(imp, tmp_path) == "b.md"           # 最新一份带全局头的
    assert IS.mainline(imp, tmp_path) == ["b.md"]               # 覆盖集数最多


def test_sha_mismatch_or_missing_falls_back(tmp_path):
    imp = _repo(tmp_path, {"a.md": HEAD + "## ep01《一》\n"}, [])
    imp.write_text(json.dumps({"sources": [{"path": "a.md", "sha256": "0" * 64, "episodes": [1]},
                                           {"path": "gone.md", "episodes": [1]}]}), encoding="utf-8")
    assert IS.current_sources(imp, tmp_path) == []
    assert IS.header_source(imp, tmp_path) is None and IS.mainline(imp, tmp_path) == []
    assert IS.current_sources(tmp_path / "none.json", tmp_path) == []


def test_script_header_uses_derived_then_config(tmp_path, monkeypatch):
    from ns_api import script_chat as S
    files = {"cur.md": HEAD + "## ep01《一》\n", "cfg.md": "# 配置回退\n\n```Plain Text\n【乙】占位\n```\n\n## ep01《一》\n"}
    imp = _repo(tmp_path, files, [])
    imp.write_text(json.dumps({"sources": [{"path": "cur.md", "sha256": sha(tmp_path, "cur.md"), "episodes": [1]}]}), encoding="utf-8")
    monkeypatch.setattr(S, "PRODUCTION_SCRIPT", imp)
    monkeypatch.setattr(S, "REPO", tmp_path)
    cfg = {"header_sources": ["cfg.md"], "registry": {}}
    head, src = S.script_header(cfg)
    assert src == "cur.md" and "【甲】" in head
    head, src = S.script_header({**cfg, "header_sources_mode": "config"})
    assert src == "cfg.md" and "【乙】" in head
    monkeypatch.setattr(S, "PRODUCTION_SCRIPT", tmp_path / "none.json")
    assert S.script_header(cfg)[1] == "cfg.md"


def test_real_repo_header_is_current_import():
    hs = IS.header_source()
    if hs is None:
        return
    srcs = IS.current_sources()
    assert hs in [s["path"] for s in srcs]
    assert "为他而骚" not in hs   # 不再是 60 集旧稿


def test_pending_redo_rule():
    import data_parity as DP
    at = "2026-11-01T18:24:39"
    assert DP.pending_redo({}, at) == "无当前首帧"
    old = {"active": {"image": 2}, "takes": [{"stage": "image", "n": 2, "created_at": "2026-11-01T10:00:00"}]}
    new = {"active": {"image": 3}, "takes": [{"stage": "image", "n": 3, "created_at": "2026-11-01T19:00:00"}]}
    assert DP.pending_redo(old, at).startswith("当前首帧 #2")
    assert DP.pending_redo(new, at) is None                      # 新首帧设为当前 → 自动转回比对
