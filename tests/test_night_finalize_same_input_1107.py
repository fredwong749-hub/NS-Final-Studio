"""逻辑纪律补丁 v3 §2b：finalize 入口自检——合成输入指纹（入选内容签名 + 配乐）与上次成功版相同 → 跳过、不占版本号。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/series10_video"))
import night as N  # noqa: E402


def _st(tmp_path, input_sig):
    final = tmp_path / "ep01_v5.mp4"
    final.write_bytes(b"x")
    return {"eps": {"1": {"status": "rendering", "assembled_n": 5, "final": str(final), "assembled_input_sig": input_sig}}}


def test_same_input_skips_without_version(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "ep_sig", lambda ep, host: "SIG")
    monkeypatch.setattr(N, "log", lambda *a, **k: None)
    args = ["assemble", "--no-bgm"]
    sig = N.assembly_input_sig(1, "gpu33", args, None)
    st = _st(tmp_path, sig)
    assert N.same_input_skip(1, "gpu33", st, args, None) is True
    x = st["eps"]["1"]
    assert x["status"] == "assembled" and x["assembled_n"] == 5


def test_changed_input_does_not_skip(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "ep_sig", lambda ep, host: "SIG")
    monkeypatch.setattr(N, "log", lambda *a, **k: None)
    st = _st(tmp_path, "old")
    assert N.same_input_skip(1, "gpu33", st, ["assemble", "--no-bgm"], None) is False
    assert st["eps"]["1"]["status"] == "rendering"
