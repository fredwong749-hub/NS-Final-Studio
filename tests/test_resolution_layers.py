"""解析层按 run 继承 + 登记（WORKFLOW 11-02，总调度 P0；K-OPS-W19）。
- 真实配置：series10_v1 与 series10_s2 的林晚身份脸都 = L-086 定的 lin_wan_face_hd_A_s202.png（走生产同一入口 face_of）；
- 临时目录：face first_hit（子季覆盖优先、否则父季）、item_map / quarantine 父先子后、按集排期不继承；
- 登记：asset_refs.py 里所有 data/looks 覆盖文件常量都在 config/policies/resolution_layers.yaml；
- S6 覆盖：登记的每个文件都在 sentinel.yaml S6 files（待 SENTINEL 并入，先 xfail strict）。"""
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/agent", "packages/schema", "services/render_router"):
    sys.path.insert(0, str(ROOT / p))
from ns_agent import asset_refs as AR  # noqa: E402

L086 = "assets/characters/lin_wan/refs/lin_wan/ar-c2351c9dcf.png"   # L-122（项目方 11-02 15:45 换脸，取代 L-086 的 hd_A_s202）；变量名保留
REG = yaml.safe_load((ROOT / "config/policies/resolution_layers.yaml").read_text(encoding="utf-8"))


def test_real_identity_face_both_runs():
    assert (ROOT / L086).exists()
    for run in ("series10_v1", "series10_s2"):
        assert AR.face_of(run, "lin_wan") == L086, run


def _cfg(monkeypatch, tmp_path):
    cfg = tmp_path / "asset_refs.json"
    cfg.write_text(json.dumps({"projects": {"s1": {"faces": {"lin_wan": ["f/base.png"], "gu": ["f/gu.png"]}},
                                            "s2": {"inherits": "s1"}}}), encoding="utf-8")
    monkeypatch.setattr(AR, "CFG", cfg)
    monkeypatch.setattr(AR, "ROOT", tmp_path)
    for f in ("f/base.png", "f/gu.png", "f/ov1.png", "f/ov2.png"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_bytes(b"x")


def test_face_override_first_hit(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path)
    ov = tmp_path / "face_overrides.json"
    monkeypatch.setattr(AR, "FACE_OVERRIDES", ov)
    ov.write_text(json.dumps({"s1": {"lin_wan": "f/ov1.png"}}), encoding="utf-8")
    assert AR.face_of("s2", "lin_wan") == "f/ov1.png"          # 子季没设 → 父季覆盖
    assert AR.face_of("s2", "gu") == "f/gu.png"                # 没有覆盖 → 继承的 config faces
    ov.write_text(json.dumps({"s1": {"lin_wan": "f/ov1.png"}, "s2": {"lin_wan": "f/ov2.png"}}), encoding="utf-8")
    assert AR.face_of("s2", "lin_wan") == "f/ov2.png"          # 子季自己设了 → 子季
    assert AR.face_of("s1", "lin_wan") == "f/ov1.png"          # 父季不受子季影响


def test_layered_and_none(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path)
    q = tmp_path / "q.json"
    q.write_text(json.dumps({"s1": {"lin_wan": {"A": ["x"]}}, "s2": {"lin_wan": {"D": ["y"]}}}), encoding="utf-8")
    monkeypatch.setattr(AR, "QUARANTINE", q)
    assert AR.quarantine("s2") == {"lin_wan": {"A": ["x"], "D": ["y"]}}
    assert AR.quarantine("s1") == {"lin_wan": {"A": ["x"]}}
    assert [list(x) for x in AR.overlay_layers(q, "s2")] == [["lin_wan"], ["lin_wan"]]
    ep = tmp_path / "ep.json"
    ep.write_text(json.dumps({"s1": {"lin_wan": {"3": "B"}}}), encoding="utf-8")
    monkeypatch.setattr(AR, "HUB_EP_LOOKS", ep)
    assert AR._hub(ep, "s2") == {}                             # 按集排期不继承
    assert AR._hub(ep, "s2", inherit=True) == {"lin_wan": {"3": "B"}}


def test_all_override_consts_registered():
    src = (ROOT / "services/agent/ns_agent/asset_refs.py").read_text(encoding="utf-8")
    consts = set(re.findall(r'^([A-Z_]+)\s*=\s*ROOT / "data" / "looks" / "[a-z_]+\.json"', src, re.M))
    registered = {x["const"] for x in REG["layers"]} | {"WARDROBE"}
    assert consts - registered == set(), "asset_refs.py 有覆盖文件未登记到 resolution_layers.yaml"
    for x in REG["layers"]:
        assert x["inherit"] in ("first_hit", "layered", "none")


def test_s6_covers_resolution_layers():
    s6 = yaml.safe_load((ROOT / "config/policies/sentinel.yaml").read_text(encoding="utf-8"))
    files = set(json.dumps(s6, ensure_ascii=False).split('"'))
    need = {x["path"] for x in REG["layers"]} | {x["path"] for x in REG["global"]}
    assert need <= files
