"""逻辑纪律补丁 v3 §2a：ep_sig 只看入选 take 的文件内容，状态 / renders 条数变化不得改变签名。
复现（11-07）：ep01-S2 chosen=v1 不变，但 vidgen 把 v1 挪进 superseded、renders 换了一批 → 旧 ep_sig 变 → reopen_changed 重合成。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/series10_video"))
import night as N  # noqa: E402


def _shots(tmp_path, status, renders_extra):
    clip = tmp_path / "clips/ep01-S2__v1.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    if not clip.exists():
        clip.write_bytes(b"same-clip-bytes")
    v1 = {"variant": "v1", "file": str(clip)}
    return {"ep01-S2": {"status": status, "chosen": "v1",
                        "renders": ([v1] if not renders_extra else [{"variant": "s2", "file": "x.mp4"}]),
                        "superseded": ([] if not renders_extra else [v1])}}


def test_sig_ignores_status_and_render_count(tmp_path, monkeypatch):
    a = _shots(tmp_path, "done", False)
    b = _shots(tmp_path, "rendering", True)          # 状态变了、v1 挪进 superseded、renders 换了 —— 入选内容没变
    seq = iter([a, b])
    monkeypatch.setattr(N, "ep_shots", lambda ep, host: next(seq))
    assert N.ep_sig(1, "gpu33") == N.ep_sig(1, "gpu33")


def test_sig_changes_when_chosen_content_changes(tmp_path, monkeypatch):
    a = _shots(tmp_path, "done", False)
    monkeypatch.setattr(N, "ep_shots", lambda ep, host: a)
    s1 = N.ep_sig(1, "gpu33")
    (tmp_path / "clips/ep01-S2__v1.mp4").write_bytes(b"different-bytes!")
    N._SHA_MEMO.clear() if hasattr(N, "_SHA_MEMO") else None
    assert N.ep_sig(1, "gpu33") != s1
