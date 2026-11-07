# 11-07：视频页全黑——当前版本视频常驻回拉线；一台失败不影响另一台、开关能停
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/autopilot"))
import resident_sync as RS


def test_pulls_every_host_and_survives_failure(monkeypatch):
    monkeypatch.delenv("NS_ACTIVE_VIDEOS", raising=False)
    seen = []

    def pull(h, quiet=False):
        assert quiet
        seen.append(h)
        if h == RS.HOSTS[0]:
            raise OSError("ssh down")
    RS.active_videos_thread(every_s=1, sleep=lambda s: None, ticks=2, pull_fn=pull)
    assert seen == list(RS.HOSTS) * 2


def test_switch_off(monkeypatch):
    monkeypatch.setenv("NS_ACTIVE_VIDEOS", "off")
    seen = []
    RS.active_videos_thread(every_s=1, sleep=lambda s: None, ticks=3, pull_fn=lambda h, quiet=False: seen.append(h))
    assert seen == []
