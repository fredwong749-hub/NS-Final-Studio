"""L-201（项目方 11-06）：video_mode.shots 逐镜 I2VA；尾帧固定开头允许机位 / 景别跟落幅走"""
import json
from pathlib import Path

from ns_agent import video_mode as VM

ROOT = Path(__file__).resolve().parents[1]


def _root(tmp_path, vm):
    p = tmp_path / "config/compile"
    p.mkdir(parents=True)
    (p / "run_style.json").write_text(json.dumps({"runs": {"r": {"video_mode": vm}}}), encoding="utf-8")
    return tmp_path


def test_shot_list_turns_on_i2va_for_listed_shot_only(tmp_path):
    r = _root(tmp_path, {"mode": "i2va", "from_episode": 2, "shots": ["ep01-S1"]})
    assert VM.no_last("r", 1, r, shot="ep01-S1") is True
    assert VM.no_last("r", 1, r, shot="ep01-S3") is False
    assert VM.no_last("r", 1, r) is False
    assert VM.no_last("r", 2, r, shot="ep02-S1") is True


def test_env_force_off_wins(tmp_path, monkeypatch):
    r = _root(tmp_path, {"mode": "i2va", "from_episode": 2, "shots": ["ep01-S1"]})
    monkeypatch.setenv("NS_VIDEO_MODE", "fl2va")
    assert VM.no_last("r", 1, r, shot="ep01-S1") is False


def test_live_config_no_shot_list_after_l203():
    """L-203 撤回 L-201 ②：线上 video_mode 不再逐镜 I2VA（mode fl2va、无 shots）；逐镜名单逻辑只在上面的 mock 测试里保留"""
    vm = json.loads((ROOT / "config/compile/run_style.json").read_text(encoding="utf-8"))["runs"]["series10_v2"]["video_mode"]
    assert vm["mode"] == "fl2va" and not vm.get("shots")
    assert VM.no_last("series10_v2", 1, ROOT, shot="ep01-S1") is False


def test_last_frame_keep_follows_end_framing():
    s = (ROOT / "config/compile/bible_series10_v2.toml").read_text(encoding="utf-8")
    line = next(x for x in s.splitlines() if x.startswith("last_frame_keep"))
    assert "机位与景别按" in line and "机位、景别、光线、人物身份" not in line
