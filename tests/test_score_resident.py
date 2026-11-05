"""AUDIT-PERF 提案 A：full_score 的常驻打分开关 / 退回旧子进程。"""
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/gen_contract"))
import remote_score as RS  # noqa: E402


def _load_resident(monkeypatch, env):
    """从 _FULL 脚本里取出 _RES / _resident 定义单独执行"""
    src = RS._FULL
    a = src.index("_RES = {}")
    b = src.index("    except Exception as e:\n        _RES[kind] = False")
    end = src.index("return None\n", b) + len("return None\n")
    ns = {"json": json, "os": __import__("os")}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    exec(src[a:end], ns)
    return ns


def test_switch_off_returns_none(monkeypatch):
    monkeypatch.delenv("NS_SCORE_RESIDENT", raising=False)
    ns = _load_resident(monkeypatch, {})
    assert ns["_resident"]("idm", "score", {}) is None and ns["_RES"] == {}


def test_dead_port_falls_back(monkeypatch):
    ns = _load_resident(monkeypatch, {"NS_SCORE_RESIDENT": "1", "NS_SCORE_SRV_PORT_IDM": "1"})
    assert ns["_resident"]("idm", "score", {}) is None
    assert ns["_RES"]["idm"] is False and "idm_error" in ns["_RES"]


def test_resident_ok(monkeypatch):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            b = json.dumps({"items": {"x": 1}, "path": self.path}).encode()
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ns = _load_resident(monkeypatch, {"NS_SCORE_RESIDENT": "1", "NS_SCORE_SRV_PORT_HAND": str(srv.server_port)})
    out = ns["_resident"]("hand", "hands", {"items": []})
    srv.shutdown()
    assert out["path"] == "/hands" and ns["_RES"]["hand"] is True


def test_resident_env_prefix(monkeypatch):
    monkeypatch.setenv("NS_SCORE_RESIDENT", "1")
    assert RS._resident_env() == "NS_SCORE_RESIDENT=1 "
    monkeypatch.setenv("NS_SCORE_RESIDENT", "0")
    assert RS._resident_env() == ""
    monkeypatch.delenv("NS_SCORE_RESIDENT")
    cfg = json.loads((ROOT / "config/pipeline/score_resident.json").read_text(encoding="utf-8"))
    assert (RS._resident_env() != "") == bool(cfg["enabled"])


def test_refactored_scripts_keep_cli_entry():
    for rel, fn in (("tools/series10_imggen/score_remote.py", "def score("), ("tools/series10_imggen/hands_remote.py", "def detect(")):
        t = (ROOT / rel).read_text(encoding="utf-8")
        assert fn in t and "def main()" in t and '__name__ == "__main__"' in t
