"""跨机借道（lane_relay）：默认关；白名单；黑名单道；producer 接线（hold / 训练锁）；代理端到端（假上游）"""
import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import lane_relay as LR  # noqa: E402

OK = lambda ln: True  # noqa: E731
CFG = {"enabled": True, "consumer_host": "gpu33",
       "lanes": {"gpu36:0": {"listen_port": 28288, "upstream": "http://127.0.0.1:18288"},
                 "gpu36:1": {"listen_port": 28289, "upstream": "http://127.0.0.1:18289"},
                 "gpu33:2": {"listen_port": 28290, "upstream": "http://127.0.0.1:18190"},
                 "gpu36:3": {"listen_port": 28291, "upstream": "http://evil.example:80"}}}


def test_shipped_config_matches_l193():
    # L-193（项目方 11-05 选 B）：首帧跨两台开；只借 gpu36:0，且只在 gpu33 消费
    assert LR.load_cfg().get("enabled") is True
    lanes = LR.consumer_lanes(host="gpu33")
    assert set(lanes) == {"gpu36:0"}
    assert LR.consumer_lanes(host="gpu36") == {}


def test_broken_config_is_off(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{bad", encoding="utf-8")
    assert LR.load_cfg(p) == {"enabled": False}
    assert LR.load_cfg(tmp_path / "none.json") == {"enabled": False}


def test_consumer_lanes_filters():
    got = LR.consumer_lanes(CFG, "gpu33", OK)
    assert got == {"gpu36:0": "http://127.0.0.1:28288"}      # gpu36:1 / gpu33:2 黑名单，gpu36:3 上游非回环
    assert LR.consumer_lanes(CFG, "gpu36", OK) == {}           # 只给 consumer_host
    assert LR.consumer_lanes(CFG, None, OK) == {}              # 不知道本机 = 不借
    assert LR.consumer_lanes({**CFG, "enabled": False}, "gpu33", OK) == {}
    assert LR.consumer_lanes(CFG, "gpu33", lambda ln: False) == {}   # hosts.json 里不是 image 道 = 不借


def test_allowlist():
    for m, p in [("POST", "/prompt"), ("GET", "/history/abc-123"), ("GET", "/view?filename=a.png"), ("POST", "/upload/image"), ("GET", "/queue")]:
        assert LR.allowed(m, p)
    for m, p in [("POST", "/api/userdata/x"), ("GET", "/models/checkpoints"), ("POST", "/manager/reboot"), ("GET", "/../etc/passwd"),
                 ("DELETE", "/prompt"), ("POST", "/history"), ("GET", "/extensions")]:
        assert not LR.allowed(m, p)


def test_reverse_cmd_binds_loopback():
    tun = {"ssh_exe": "ssh", "ssh_opts": ["-N"], "ssh_config": "cfg"}
    c = LR.reverse_cmd({"listen_port": 28288, "ssh_target": "gpu33-t"}, tun)
    assert "-R" in c and c[c.index("-R") + 1] == "127.0.0.1:28288:127.0.0.1:28288" and c[-1] == "gpu33-t"


def test_proxy_end_to_end():
    seen = []

    class Up(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append(("GET", self.path))
            b = b'{"queue_running":[],"queue_pending":[]}'
            self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)  # noqa: E702

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n)
            seen.append(("POST", self.path, body))
            b = b'{"prompt_id":"p1"}'
            self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)  # noqa: E702

    up = HTTPServer(("127.0.0.1", 0), Up)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    px = LR.serve_proxy(0, f"http://127.0.0.1:{up.server_port}", {})
    base = f"http://127.0.0.1:{px.server_address[1]}"
    try:
        assert json.loads(urllib.request.urlopen(base + "/queue").read())["queue_running"] == []
        r = urllib.request.urlopen(urllib.request.Request(base + "/prompt", data=b'{"prompt":{}}', method="POST"))
        assert json.loads(r.read())["prompt_id"] == "p1" and seen[-1][2] == b'{"prompt":{}}'
        try:
            urllib.request.urlopen(urllib.request.Request(base + "/manager/reboot", data=b"x", method="POST"))
            raise AssertionError("should be 403")
        except urllib.error.HTTPError as e:
            assert e.code == 403
        assert all(x[1] != "/manager/reboot" for x in seen)       # 被拒的请求没到上游
    finally:
        px.shutdown(); up.shutdown()  # noqa: E702


def test_proxy_upstream_down_is_502():
    px = LR.serve_proxy(0, "http://127.0.0.1:1", {})
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{px.server_address[1]}/queue")
        raise AssertionError("should be 502")
    except urllib.error.HTTPError as e:
        assert e.code == 502
    finally:
        px.shutdown()


def test_serve_off_does_nothing():
    assert LR.serve({"enabled": False}) == 0
    assert LR.serve({"enabled": True, "lanes": {"gpu36:1": {"listen_port": 1, "upstream": "http://127.0.0.1:2"}}}) == 2


def test_producer_wiring(monkeypatch, tmp_path):
    """开借道时：gpu36:0 进 lanes，不被 hold，不查训练锁；gpu36:1 / 坏卡仍 hold"""
    import producer as PR
    monkeypatch.setattr(LR, "consumer_lanes", lambda *a, **k: {"gpu36:0": "http://127.0.0.1:28288"})
    pr = PR.Producer(PR.Paths(), train_locks_fn=lambda srv: None, lock_now_fn=lambda ln: True)
    assert pr.lanes["gpu36:0"] == "http://127.0.0.1:28288" and pr.relay_lanes == {"gpu36:0"}
    pr.lane_probe = lambda url: {"ok": True, "n": 0, "agents": []}
    out = pr.probe_lanes({"hold_lanes": ["gpu36:0", "gpu36:1", "gpu33:2"], "dispatch_by": {"host": "gpu33"}})
    assert out["gpu36:0"]["free"] is True
    assert out["gpu36:1"]["free"] is False
