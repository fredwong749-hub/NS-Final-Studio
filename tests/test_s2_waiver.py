"""S2 一次性豁免：只对登记的集 / 项有效；必须 by=owner + 原话；撤销后失效"""
import json

from ns_agent.state_timeline import waived


def _cfg(tmp_path, w):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "s2_waivers.json").write_text(json.dumps({"waivers": w}), encoding="utf-8")


def test_only_listed_episode_and_item(tmp_path):
    _cfg(tmp_path, [{"episode": 2, "skip": ["plate"], "owner_quote": "跳过底图", "by": "owner"}])
    assert waived(tmp_path, 2, "plate") and not waived(tmp_path, 3, "plate") and not waived(tmp_path, 2, "look")


def test_requires_owner_quote_and_not_revoked(tmp_path):
    _cfg(tmp_path, [{"episode": 2, "skip": ["plate"], "owner_quote": "", "by": "owner"},
                    {"episode": 4, "skip": ["plate"], "owner_quote": "x", "by": "agent"},
                    {"episode": 5, "skip": ["plate"], "owner_quote": "x", "by": "owner", "revoked": True}])
    assert not any(waived(tmp_path, n, "plate") for n in (2, 4, 5))


def test_no_file_no_waiver(tmp_path):
    assert waived(tmp_path, 2, "plate") is None


def test_malformed_waiver_file_means_no_waiver(tmp_path):
    """封板修复：根不是对象、waivers 为 null、条目不是对象 → 都按没有豁免处理，不崩"""
    (tmp_path / "config").mkdir()
    p = tmp_path / "config" / "s2_waivers.json"
    for body in ("[1, 2]", '{"waivers": null}', '{"waivers": ["x", 3]}', '"x"'):
        p.write_text(body, encoding="utf-8")
        assert waived(tmp_path, 2, "plate") is None
    p.write_text(json.dumps({"waivers": ["x", {"episode": 2, "skip": ["plate"], "owner_quote": "跳过底图",
                                                 "by": "owner"}]}), encoding="utf-8")
    assert waived(tmp_path, 2, "plate")
