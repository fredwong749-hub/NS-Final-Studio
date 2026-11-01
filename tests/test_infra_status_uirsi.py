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


# ---------------------------------------------------------------- r39：NETFIX 为主、派单模式、顶栏短字
def _ns(**kw):
    base = {"t": NOW - 5, "relay": {"up": True, "checked_t": NOW - 5, "last_ok_t": NOW - 5},
            "hosts": {h: {"state": "up", "since_t": NOW - 600, "restarts": 0,
                          "ports": {str(p): {"remote": 8188, "ok": True, "why": "ok"} for p, (hh, _) in I.TUNNEL_CARDS.items() if hh == h}}
                      for h in ("gpu33", "gpu36")},
            "servers": {"gpu33": {"sync_age_min": 12.0}},
            "dispatch_mode": {"override_active": True, "phases": {"gpu33": "laptop", "gpu36": "laptop"}}}
    base.update(kw)
    return base


def test_netfix_preferred_and_dispatch_text():
    wd = {"t": NOW - 900, "fails": {"18189": 99}, "_relay_down": True, "_relay_t": NOW - 900}   # 看门狗过期、说法也旧
    d = I.build(NOW, wd, RES, LOCAL, _ns())
    assert d["source"] == "netfix" and d["level"] == "ok" and d["relay"]["ok"] and all(t["ok"] for t in d["tunnels"])
    assert d["dispatch"]["override"] and d["dispatch"]["text"] == "现在由笔记本统一派图（服务器资产补推中），gpu33 / gpu36 推完后自动交还"
    assert "最后一次同步 12 分钟前" in d["servers"]["gpu33"]["text"]
    assert not any("看门狗" in r for r in d["reconnect"])
    assert not any(INTERNAL.search(x) for x in _texts(d) + [d["dispatch"]["text"]])


def test_netfix_connecting_and_remote_down():
    ns = _ns()
    ns["hosts"]["gpu36"].update(state="connecting", restarts=2)
    for p in ns["hosts"]["gpu36"]["ports"].values():
        p.update(ok=False, why="timeout")
    ns["hosts"]["gpu33"]["ports"]["18189"].update(ok=False, why="remote_down")
    ns["dispatch_mode"] = {"override_active": True, "phases": {"gpu33": "draining", "gpu36": "laptop"}}
    d = I.build(NOW, {}, RES, LOCAL, ns)
    t36 = [t for t in d["tunnels"] if t["host"] == "gpu36"]
    assert all("正在自动重连" in t["text"] and t["rebuilding"] for t in t36)
    assert "出图程序没响应" in next(t for t in d["tunnels"] if t["port"] == 18189)["text"]
    assert any("gpu36" in r and "重连" in r for r in d["reconnect"])
    assert "gpu33 正在交还" in d["dispatch"]["text"] and "gpu36 推完后自动交还" in d["dispatch"]["text"]
    assert d["level"] == "warn"


def test_netfix_stale_falls_back_to_watchdog():
    wd = {"t": NOW - 10, "fails": {}, "_relay_down": False, "_relay_t": NOW - 10}
    d = I.build(NOW, wd, RES, LOCAL, _ns(t=NOW - 600))
    assert d["source"] == "watchdog" and d["dispatch"] is None


def test_r39_topbar_short_texts():
    web = ROOT / "apps" / "web" / "src"
    inf = (web / "v3" / "InfraStatus.tsx").read_text(encoding="utf-8")
    assert '`${n - bad}/${n}`' in inf and '"跳板断"' in inf
    rt = (web / "components" / "RenderTasks.tsx").read_text(encoding="utf-8")
    assert "在办 {c.rendering} · 排队 {c.queued ?? c.pending}" in rt and "渲染任务" in rt   # 按钮字“渲染任务”保留（UIAUDIT flows 按它找）
    top = (web / "v3" / "TopBarV3.tsx").read_text(encoding="utf-8")
    assert "prodOn || (offline && !infraOn)" in top
    gl = (ROOT / "services" / "api" / "ns_api" / "gpu_live.py").read_text(encoding="utf-8")
    assert "ComfyUI 离线（" not in gl and "这张卡的出图程序没响应" in gl


def test_netfix_per_lane_hosts_real_structure():
    """AUDIT 00:23 P1：NETFIX 00:0x 起每张卡一条 ssh，hosts 键是 gpu33-l0 … gpu36-l2（server 字段 = 服务器）；
    按端口找连接，不能因为主机名对不上就全报“断了、自动重连没在运行”。why=busy = 连接通、卡在忙"""
    lanes = {"gpu33-l0": ("gpu33", 18188), "gpu33-l1": ("gpu33", 18189), "gpu33-l3": ("gpu33", 18191),
             "gpu36-l0": ("gpu36", 18288), "gpu36-l1": ("gpu36", 18289), "gpu36-l2": ("gpu36", 18290)}
    hosts = {k: {"state": "up", "since_t": NOW - 600, "restarts": 0, "server": srv,
                 "ports": {str(p): {"remote": 8188, "ok": True, "why": "ok", "checked_t": NOW - 5}}} for k, (srv, p) in lanes.items()}
    hosts["gpu33-l0"]["ports"]["18188"].update(ok=False, why="busy")
    hosts["gpu36-l1"].update(state="connecting", restarts=3)
    hosts["gpu36-l1"]["ports"]["18289"].update(ok=False, why="timeout")
    ns = _ns(hosts=hosts)
    d = I.build(NOW, {}, RES, LOCAL, ns)
    by = {t["port"]: t for t in d["tunnels"]}
    assert sum(t["ok"] for t in d["tunnels"]) == 5 and not by[18289]["ok"]
    assert by[18188]["ok"] and "卡在忙" in by[18188]["text"]
    assert "正在自动重连" in by[18289]["text"] and by[18289]["rebuilding"]
    assert d["level"] == "warn" and "全断" not in d["summary"] and "gpu36·卡1" in d["summary"]
    assert any("gpu36·卡1" in r and "重连" in r for r in d["reconnect"])
    assert not any("没人在管" in x or "没在运行" in x for x in [t["text"] for t in d["tunnels"]] + d["reconnect"])
