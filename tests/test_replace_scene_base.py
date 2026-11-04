"""tools/pipeline/replace_scene_base.py：dry-run 不写、apply 写清单且旧 entry 进 replaced[]、清单被并发改则拒绝"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
_s = importlib.util.spec_from_file_location("rsb_t", ROOT / "tools" / "pipeline" / "replace_scene_base.py")
RSB = importlib.util.module_from_spec(_s)
_s.loader.exec_module(RSB)
AJ = RSB.AJ


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / "assets_v2/scenes/s1").mkdir(parents=True)
    old = tmp_path / "assets_v2/scenes/s1/s1_base_old.png"
    old.write_bytes(b"OLD")
    new = tmp_path / "src.png"
    new.write_bytes(b"NEW")
    mp = tmp_path / "assets_v2/manifest.json"
    mp.write_text(json.dumps({"scenes": {"s1": {"base": {"file": "assets_v2/scenes/s1/s1_base_old.png", "sha256": AJ._sha(b"OLD"), "picked_by": "fred"}}}}), encoding="utf-8")
    monkeypatch.setattr(AJ, "manifest_path", lambda root, run: mp)
    return tmp_path, mp


def test_dry_run_writes_nothing(env):
    root, mp = env
    before = mp.read_bytes()
    r = RSB.plan_replace(root, "r", "s1", "src.png", "L1", "me")
    assert r["apply"] is False and mp.read_bytes() == before and not (root / r["new"]["file"]).exists()


def test_apply_keeps_history(env):
    root, mp = env
    r = RSB.plan_replace(root, "r", "s1", "src.png", "L1", "me", "n", apply=True, push=False)
    b = json.loads(mp.read_text(encoding="utf-8"))["scenes"]["s1"]["base"]
    assert b["file"].endswith("s1_base_L1.png") and b["sha256"] == AJ._sha(b"NEW")
    assert b["replaced"][0]["file"].endswith("s1_base_old.png") and (root / b["replaced"][0]["file"]).read_bytes() == b"OLD"
    assert r["manifest_sha_after"]


def test_same_sha_and_concurrent_change_rejected(env, monkeypatch):
    root, mp = env
    (root / "same.png").write_bytes(b"OLD")
    with pytest.raises(AJ.RegisterError):
        RSB.plan_replace(root, "r", "s1", "same.png", "x", "me")
    real = AJ._read_manifest

    def racing(p):
        d, sha = real(p)
        mp.write_text(mp.read_text(encoding="utf-8") + " ", encoding="utf-8")   # 读完后别人改了清单
        return d, sha
    monkeypatch.setattr(AJ, "_read_manifest", racing)
    with pytest.raises(AJ.RegisterError):
        RSB.plan_replace(root, "r", "s1", "src.png", "L1", "me", apply=True, push=False)
