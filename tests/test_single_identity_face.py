"""BAKEOFF P1（11-01）：每个角色只有一张身份脸——出图用的那张 == 契约打分对的那张。

出图：ns_agent.asset_refs.face_of（plan_for 的 face 槽）；旧提交入口 imggen.ALAN_FACE / image_jobs.EXTRA_FACES。
打分：tools/gen_contract/remote_score.local_faces → face_refs（按内容哈希放到机器上）。"""
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen_contract"))
sys.path.insert(0, str(ROOT / "services" / "agent"))

import remote_score as RS  # noqa: E402
from ns_agent import asset_refs as AR  # noqa: E402

PROJECT = "series10_v1"


def _sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def test_every_character_scored_against_generation_face():
    scored = RS.local_faces(PROJECT)
    for cid in RS.FACE_CHARS:
        gen = AR.face_of(PROJECT, cid)
        assert gen, f"{cid} 没有身份脸"
        assert scored.get(cid) == gen, f"{cid}：出图 {gen} ≠ 打分 {scored.get(cid)}"


def test_identity_face_is_owner_registered_file():
    import json
    man = json.loads((ROOT / "data/assets/identity_refs/manifest.json").read_text(encoding="utf-8"))["chars"]
    for cid in RS.FACE_CHARS:
        gen = AR.face_of(PROJECT, cid)
        assert _sha(gen) == man[cid]["sha256"], f"{cid}：出图用的身份脸与 identity_refs/manifest.json 登记的不是同一张"


def test_no_hardcoded_server_faces():
    """不许再有手写的机器路径身份脸表（旧 REFS 里 ch_a_lan 指向机器上不存在的文件、林晚多一张旧母版取高者）"""
    assert not hasattr(RS, "REFS")
    src = (ROOT / "tools/gen_contract/remote_score.py").read_text(encoding="utf-8")
    assert "@master" not in src.split("FACE_CHARS")[1]


def test_legacy_submitters_use_same_alan_face():
    gen = AR.face_of(PROJECT, "ch_a_lan")
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    import image_jobs as IJ
    run = ROOT / "data/pipeline/runs" / PROJECT
    rel = os.path.normpath(str((run / IJ.EXTRA_FACES["阿岚"]).relative_to(ROOT))).replace("\\", "/")
    assert rel == gen
    src = (ROOT / "tools/series10_imggen/imggen.py").read_text(encoding="utf-8")
    assert f'ALAN_FACE = ROOT / "{gen}"' in src


def test_face_refs_paths_are_content_addressed(monkeypatch, tmp_path):
    monkeypatch.setattr(RS, "_known_path", lambda host: tmp_path / "known.json")
    sent = []

    class R:
        stdout, stderr = "ok", ""
    monkeypatch.setattr(RS, "ssh", lambda host, cmd, stdin=None, timeout=900: sent.append(stdin) or R())
    refs = RS.face_refs("gpu33", PROJECT)
    for cid, p in refs.items():
        assert p.endswith(f"id_{_sha(AR.face_of(PROJECT, cid))[:16]}.png")
    assert len(sent) == 1
    RS.face_refs("gpu33", PROJECT)                  # 已知 → 不再传
    assert len(sent) == 1
