"""当前版本视频必拉（K-OPS-W24）+ 额外剧 producer 常驻（K-OPS-W25）。全部假 ssh / 临时目录，不碰服务器。"""
import io
import json
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
sys.path.insert(0, str(ROOT / "tools/netfix"))
import resident_sync as RS  # noqa: E402


def test_active_video_paths():
    doc = {"active": {"video": 2, "image": 5}, "takes": [
        {"n": 1, "stage": "video", "file": "renders/ep01/S1/takes/video_001.mp4"},
        {"n": 2, "stage": "video", "file": "renders/ep01/S1/takes/video_002.mp4"},
        {"n": 2, "stage": "image", "file": "renders/ep01/S1/takes/image_002.png"}]}
    assert RS.active_video_paths(doc) == ["data/renders/ep01/S1/takes/video_002.mp4"]
    assert RS.active_video_paths({"active": {"image": 1}, "takes": []}) == []


def _tar(files: dict) -> bytes:
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode="w") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return b.getvalue()


def test_pull_active_videos_size_checked(monkeypatch, tmp_path):
    monkeypatch.setattr(RS, "ROOT", tmp_path)
    monkeypatch.setattr(RS, "log", lambda *a: None)
    good, bad = "data/renders/ep01/S1/takes/v2.mp4", "data/renders/ep01/S2/takes/v1.mp4"
    have = "data/renders/ep01/S3/takes/v1.mp4"
    (tmp_path / have).parent.mkdir(parents=True)
    (tmp_path / have).write_bytes(b"123")
    av = {good: 5, bad: 4, have: 3}
    monkeypatch.setattr(RS, "remote_active_videos", lambda h: av)

    def fake_ssh(h, cmd, data=None, **k):
        assert "tar cf" in cmd and have.encode() not in data           # 本机已有且大小对的不拉
        return _tar({good: b"abcde", bad: b"xy"})                       # bad 截断
    monkeypatch.setattr(RS, "ssh", fake_ssh)
    r = RS.pull_active_videos("gpu33")
    assert r["missing"] == 2 and r["got"] == 1 and r["verified"] == 1 and r["bad"] == [bad]
    assert (tmp_path / good).read_bytes() == b"abcde" and not (tmp_path / bad).exists()
    assert RS.pull_active_videos("gpu33", dry=True)["todo"] == [bad]


def test_pull_includes_active_videos_in_need_mp4():
    src = (ROOT / "tools/autopilot/resident_sync.py").read_text(encoding="utf-8")
    body = src.split("def pull(host: str) -> dict:", 1)[1].split("\ndef ", 1)[0]
    assert "remote_active_videos(host)" in body and "need_mp4.add(rel)" in body


def test_ensure_runs_wired_and_script():
    src = (ROOT / "tools/autopilot/resident_sync.py").read_text(encoding="utf-8")
    loop = src.split("def loop(", 1)[1].split("\ndef ", 1)[0]
    assert "ensure_runs(h)" in loop
    sh = (ROOT / "ops/offline/ensure_runs.sh").read_text(encoding="utf-8")
    assert "serve --run $run" in sh and "serve.pid" in sh and "$OFF/STOP" in sh
    assert "/producer.pid" not in sh.replace("producer.pid 是 producer 自己的锁文件", "")   # producer.pid 是 producer 自己的 JSON 锁，不能占
    rr = (ROOT / "ops/offline/resident_restart.sh").read_text(encoding="utf-8")
    assert "ensure_runs.sh $SELF stop" in rr and rr.rstrip().endswith("ensure_runs.sh $SELF")


def test_run_control_follows_partition():
    """K-OPS-W25 修订：非主剧临时 control 按 partition.json ∩ 该剧已准备好的集自动生成，不靠人记"""
    part = {"images": {"gpu33": [1, 3], "gpu36": [2]}, "lanes": {"gpu33": ["gpu33:0"], "gpu36": ["gpu36:0"], "laptop": ["laptop:0"]},
            "retired_lanes": ["gpu36:2"]}
    ready = {"episodes": [1, 2, 3]}
    import dispatch as D  # noqa: F401  (run_control_for 自己加路径)
    import types
    fake = {1: ["s2/ep01-S1", "s2/ep01-S2"], 2: ["s2/ep02-S1"], 3: ["ep03-S1"]}
    orig = D.ready_shots
    try:
        D.ready_shots = lambda r: fake
        c33 = RS.run_control_for("gpu33", "s2", part=part, ready=ready)
        c36 = RS.run_control_for("gpu36", "s2", part=part, ready=ready)
    finally:
        D.ready_shots = orig
    assert c33["only"] == ["ep01-S1", "ep01-S2", "ep03-S1"] and c36["only"] == ["ep02-S1"]
    assert c33["hold_lanes"] == ["gpu36:0", "gpu36:2", "laptop:0"] and RS.TEMP_CTL_BY in c33["dispatch_by"]["by"]
    assert not set(c33["only"]) & set(c36["only"])                     # 两台不重叠
    assert isinstance(types, object)


def test_lanes_and_roots_from_hosts():
    """SYSARCH 4-2 ②（K-OPS-W26）：道 / 端口 / 服务器根 / venv 读 hosts.json；gpu36:2 死口不在"""
    sys.path.insert(0, str(ROOT / "tools/factory"))
    import hosts as H
    assert RS.LANES["gpu36"] == {str(r["gpu"]): int(r["comfy_port"]) for r in H.lanes("gpu36", role="image").values()}
    assert "2" in RS.LANES["gpu36"] and "2" not in RS.LANES["gpu33"]   # L-194（11-05）：gpu36:2 回归出图 / 视频道；gpu33:2 坏卡永不用
    assert RS.R == H.server_root("gpu33") and RS.PY["gpu36"] == H.python("gpu36")
    src = (ROOT / "tools/autopilot/resident_sync.py").read_text(encoding="utf-8")
    assert '"/root/work/fredw/offline_20261101"' not in src and "8190" not in src


def test_required_data_includes_extra_runs():
    """K-OPS-W28：push 清单把每部在产的非主剧算进去（第二季造型设定图 / 登记 / 导入稿）"""
    src = (ROOT / "tools/autopilot/resident_sync.py").read_text(encoding="utf-8")
    body = src.split("def required_data() -> set[str]:", 1)[1].split("\ndef ", 1)[0]
    assert "run_required_data(run)" in body and 'list_runs(status="producing")' in body
    fn = src.split("def run_required_data(", 1)[1].split("\ndef ", 1)[0]
    assert "IJ.load_import(run)" in fn and "chain_files(run, key)" in fn and "resolution_layers.yaml" in fn
