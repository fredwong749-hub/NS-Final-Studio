"""FACTORY D1 / SYSARCH 4-2 第 ① 步：唯一车道表 config/factory/hosts.json + 读取入口 tools/factory/hosts.py。
一致性比对（现存其它车道表 vs hosts.json）现在只报不挡：不一致打印出来（pytest -s 可见），第 ③ 步再收紧成断言。"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/factory"))
import hosts as H  # noqa: E402


def test_schema_and_fail_closed(tmp_path):
    d = H.load()
    assert set(d["hosts"]) >= {"gpu33", "gpu36", "laptop"}
    with pytest.raises(H.HostsError):
        H.load(tmp_path / "missing.json")
    with pytest.raises(H.HostsError):
        H.lane_url("gpu99:0", from_host="laptop")
    assert 2 in d["hosts"]["gpu33"].get("broken_gpus", [])              # gpu33 GPU2 坏卡永不用
    assert "gpu33:2" not in H.lanes(enabled=None)


def test_lane_url_server_vs_laptop_and_aliases(monkeypatch):
    """K-OPS-Y02：服务器环境（OFFLINE_SELF / 别名）下是本机端口，笔记本是隧道端口，服务器之间不互连"""
    assert H.lane_url("gpu36:0", from_host="gpu36") == "http://127.0.0.1:8188"
    assert H.lane_url("gpu36:0", from_host="laptop") == "http://127.0.0.1:18288"
    assert H.lane_url("gpu33:3", from_host="gpu33") == "http://127.0.0.1:8191"
    assert H.lane_url("gpu33:3", from_host="gpu36").endswith(":8191")    # gpu36 的 aliases 含 gpu33（打分别名同源）
    with pytest.raises(H.HostsError):
        H.lane_url("gpu36:0", from_host="gpu33")
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    assert H.lane_url("gpu36:1") == "http://127.0.0.1:8189"


def test_aliases_match_resident_restart_contract():
    """aliases 与 ops/offline/resident_restart.sh 的 OFFLINE_ALIASES 同源（K-OPS-Y02）"""
    sh = (ROOT / "ops/offline/resident_restart.sh").read_text(encoding="utf-8")
    m = re.search(r"OFFLINE_ALIASES=\$\(\[ \$SELF = (\w+) \] && echo (\w+)\)", sh)
    assert m, "resident_restart.sh 的 OFFLINE_ALIASES 写法变了，hosts.json aliases 要跟着核对"
    assert H.aliases(m.group(1)) == [m.group(2)]


def _drift() -> list[str]:
    out = []
    d = H.load()
    # ① producer IMAGE_LANES（隧道端口）
    s = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    m = re.search(r"IMAGE_LANES = \{(.+?)\}", s, re.S)
    if m:
        for ln, port in re.findall(r'"(gpu\d\d:\d)": "http://127.0.0.1:(\d+)"', m.group(1)):
            try:
                if H.lane_url(ln, from_host="laptop") != f"http://127.0.0.1:{port}":
                    out.append(f"producer IMAGE_LANES {ln}={port} ≠ hosts.json")
            except H.HostsError as e:
                out.append(f"producer IMAGE_LANES {ln}: {e}")
    # ② resident_sync LANES（本机端口）
    s = (ROOT / "tools/autopilot/resident_sync.py").read_text(encoding="utf-8")
    m = re.search(r"^LANES = (\{.+\})", s, re.M)
    if m:
        for host, mp in json.loads(m.group(1)).items():
            for g, port in mp.items():
                rec = d["hosts"][host]["lanes"].get(f"{host}:{g}")
                if not rec or int(rec["comfy_port"]) != int(port):
                    out.append(f"resident_sync LANES {host}:{g}={port} ≠ hosts.json")
    # ③ vidlab lanes.json（输出目录）
    p = ROOT / "config/vidlab/lanes.json"
    if p.exists():
        for host, rec in (json.loads(p.read_text(encoding="utf-8")).get("hosts") or {}).items():
            for port, g in (rec.get("ports") or {}).items():
                ln = d["hosts"][host]["lanes"].get(f"{host}:{g}")
                want = (rec.get("comfy_output") or "").replace("{gpu}", str(g))
                if not ln or ln.get("comfy_output") != want or int(ln["comfy_port"]) != int(port):
                    out.append(f"vidlab lanes {host}:{g} ≠ hosts.json")
    # ④ render_endpoints.json lanes（隧道端口）
    p = ROOT / "config/render_endpoints.json"
    if p.exists():
        for ln, rec in (json.loads(p.read_text(encoding="utf-8")).get("lanes") or {}).items():
            try:
                if ln.startswith("gpu") and H.lane_url(ln, from_host="laptop") != rec.get("url"):
                    out.append(f"render_endpoints {ln}={rec.get('url')} ≠ hosts.json")
            except H.HostsError as e:
                out.append(f"render_endpoints {ln}: {e}")
    return out


def test_other_lane_tables_drift_report_only():
    """第 ① 步只报不挡：把不一致写下来给 SYSARCH 第 ② 步逐个改读者用"""
    drift = _drift()
    print("hosts drift:", drift)
    assert isinstance(drift, list)
