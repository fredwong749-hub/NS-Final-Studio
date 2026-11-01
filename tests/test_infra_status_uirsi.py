"""UIRSI r38（项目方 22:1x：“uiux加个实时连接状态”）：/api/infra/status 汇总 + GPU 缩略图先用笔记本上的同一张（K-UI-042）。"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import infra_status as I  # noqa: E402

NOW = 1_800_000_000.0
LOCAL = [{"id": "laptop:0", "label": "笔记本显卡出图", "ok": True, "ms": 5, "text": "在线", "tech": "http://127.0.0.1:18388"},
         {"id": "look", "label": "笔记本看图检查", "ok": False, "ms": None, "text": "没在运行", "tech": "127.0.0.1:8870"}]
RES = {"gpu33": {"health": {"at": "2027-01-15 08:00:00", "night_state_age_min": 2.0}}}
INTERNAL = re.compile(r":\d{4,5}|/api/|1\d{4}\b|ComfyUI|ssh")


def _texts(d: dict) -> list[str]:
    out = [d["summary"], d["relay"]["text"], *d["reconnect"]]
    out += [t["text"] for t in d["tunnels"]] + [t["name"] for t in d["tunnels"]]
    out += [s["text"] for s in d["servers"].values()] + [x["text"] for x in d["local"]]
    return out


def test_all_ok():
    wd = {"t": NOW - 10, "fails": {}, "_relay_down": False, "_relay_t": NOW - 10}
    d = I.build(NOW, wd, RES, LOCAL)
    assert d["level"] == "ok" and d["relay"]["ok"] and all(t["ok"] for t in d["tunnels"]) and len(d["tunnels"]) == 6
    assert not any(INTERNAL.search(x) for x in _texts(d))


def test_one_tunnel_rebuilding():
    wd = {"t": NOW - 10, "fails": {"18189": 4}, "_relay_down": False, "_relay_t": NOW - 10,
          "rebuilds": [{"t": NOW - 30, "port": 18189, "killed": []}], "open": {}}
    d = I.build(NOW, wd, RES, LOCAL)
    t = next(x for x in d["tunnels"] if x["port"] == 18189)
    assert d["level"] == "warn" and not t["ok"] and t["rebuilding"] and "正在自动重连" in t["text"] and t["name"] == "gpu33·卡1"
    assert any("gpu33·卡1" in r for r in d["reconnect"])
    assert not any(INTERNAL.search(x) for x in _texts(d))


def test_relay_down_explains_and_merges():
    wd = {"t": NOW - 10, "fails": {str(p): 6 for p in I.TUNNEL_CARDS}, "_relay_down": True, "_relay_t": NOW - 10,
          "open": {"A-RELAY": {"t": NOW - 600, "ts": "x"}}}
    d = I.build(NOW, wd, RES, LOCAL)
    assert d["level"] == "bad" and not d["relay"]["ok"] and d["relay"]["down_s"] == 600 and "10 分钟" in d["relay"]["text"]
    assert all("跳板断了" in t["text"] for t in d["tunnels"])
    assert d["reconnect"][0].startswith("跳板断了")
    assert "跳板" in d["summary"]


def test_watchdog_stale_is_reported():
    wd = {"t": NOW - 900, "fails": {}, "_relay_down": False, "_relay_t": NOW - 900}
    d = I.build(NOW, wd, RES, LOCAL)
    assert not d["watchdog"]["ok"] and d["level"] == "warn" and "看门狗" in d["reconnect"][0]


def test_route_registered():
    from ns_api.app import app  # noqa: PLC0415
    assert "/api/infra/status" in app.openapi()["paths"]


def test_gpu_thumb_uses_local_copy(tmp_path, monkeypatch):
    from ns_api import gpu_live as G  # noqa: PLC0415
    from ns_render import pipeline as P  # noqa: PLC0415
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    d = tmp_path / "renders" / "ep05" / "S3"
    (d / "takes").mkdir(parents=True)
    (d / "takes" / "image_008.png").write_bytes(b"\x89PNG fake")
    take = {"n": 8, "stage": "image", "file": "renders/ep05/S3/takes/image_008.png",
            "gen_contract": {"post": {"subject": "/root/x/ComfyUI/output/gpu0/ns_final/ep05-S3_image_v9_00002_.png"}}}
    (d / "takes.json").write_text(json.dumps({"takes": [take]}), encoding="utf-8")
    assert G._local_copy("ep05-S3_image_v9_00002_.png") == d / "takes" / "image_008.png"
    assert G._local_copy("ep05-S3_image_v9_00099_.png") is None
    assert G._local_copy("03S4_old_11_00001_.png") is None


def test_frontend_wiring():
    web = ROOT / "apps" / "web" / "src"
    top = (web / "v3" / "TopBarV3.tsx").read_text(encoding="utf-8")
    assert "<InfraChip />" in top
    gp = (web / "components" / "GpuPanel.tsx").read_text(encoding="utf-8")
    assert "<InfraPanel d={infra} compact />" in gp and "merged={allDown}" in gp
    assert "onError={() => setThumbBad(c.thumb!.src)}" in gp and "图在服务器上，笔记本还没有" in gp
    assert "laneReason(" in gp
    h = (web / "v3" / "InfraStatus.helpers.ts").read_text(encoding="utf-8")
    assert 'fetch("/api/infra/status")' in h and "r.status === 404" in h
