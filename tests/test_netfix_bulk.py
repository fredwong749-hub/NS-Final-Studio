"""W21 NETFIX-BULK（ISS-1103-150939，运维 FONG-QUICK：大文件不要走 -t）：出图道独立香港连接 / known_hosts 指纹核对 / full_score 独立上传与回退。"""
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/netfix"))
sys.path.insert(0, str(ROOT / "tools/gen_contract"))
import hostkey as HK  # noqa: E402
import tunnel_supervisor as TS  # noqa: E402

NEW = ROOT / "config/netfix/tunnels.hk.json"
LANES = ("gpu33-l0", "gpu33-l1", "gpu33-l3", "gpu36-l0", "gpu36-l1", "gpu36-l2")   # W-INFRA 11-06：L-194 gpu36-l2 回归


def _sup(conf=NEW):
    s = TS.Supervisor.__new__(TS.Supervisor)
    s.c = json.loads(Path(conf).read_text(encoding="utf-8"))
    s.tag, s.route_bad_until, s.route_fails = "nsnetfix", {}, {}
    s.relay = {"routes": {"hk": {"up": True}, "direct": {"up": True}}}
    s.hosts = {h: {"state": "up", "fails": 0} for h in s.c["hosts"]}
    s.log = lambda *a: None
    return s


def _eff(cmd, key):
    """ssh 同名 -o 先出现的生效"""
    for i, x in enumerate(cmd[:-1]):
        if x == "-o" and cmd[i + 1].startswith(key + "="):
            return cmd[i + 1].split("=", 1)[1]


# ---------------------------------------------------------------- 出图道 route=hk
def test_new_conf_lanes_are_independent_hk():
    c = json.loads(NEW.read_text(encoding="utf-8"))
    for h in LANES:
        assert c["hosts"][h].get("route") == "hk" and "via" not in c["hosts"][h] and "base" not in c["hosts"][h]
    for h, v in c["hosts"].items():
        if h.endswith("-vqa") or "-cmd" in h:
            assert v.get("via") == "t" and v.get("base") == "base-a"     # 看图 + 命令主连接留在底座
    assert c["max_connecting"] <= 2
    old = json.loads(TS.CONF.read_text(encoding="utf-8"))
    assert sorted(lp for v in c["hosts"].values() for lp, _ in v["forwards"]) == \
        sorted(lp for v in old["hosts"].values() for lp, _ in v["forwards"])   # 端口一个不少


def test_ssh_cmd_route_hk_lane():
    s = _sup()
    for h in LANES:
        cmd = s.ssh_cmd(h)
        host = s.c["hosts"][h]["ssh_host"]
        assert cmd[-1] == f"{host}-hk"                                  # 独立香港连接，不经 -t 底座
        assert _eff(cmd, "ServerAliveInterval") == "15" and _eff(cmd, "ServerAliveCountMax") == "3"   # 运维：15 s × 3
        assert "-F" in cmd and f"Tag=nsnetfix-{h}" in " ".join(cmd) and "ExitOnForwardFailure=yes" in cmd
        assert s.is_lane(h)
    assert s.ssh_cmd("gpu36-vqa")[-1] == s.c["hosts"]["gpu36-vqa"]["ssh_host"] + "-t" and not s.is_lane("gpu36-vqa")   # PSM 11-05：8871 改转 gpu33:8870
    assert s.ssh_cmd("gpu33-cmd")[-1] == "gpu33-t" and not s.is_lane("gpu33-cmd")
    assert s.ssh_cmd("base-a")[-1] == "194relay-hk" and not s.is_lane("base-a")
    s.route_bad_until["hk"] = TS.now() + 600                            # 香港路被判坏 → 道临时走直连
    s.relay["routes"]["hk"]["up"] = False
    assert s.ssh_cmd("gpu33-l0")[-1] == "gpu33"


def test_lane_backoff_follows_ops_rule():
    s = _sup()
    st = s.hosts["gpu33-l0"]
    st["route"] = "hk"
    waits = []
    for _ in range(7):
        st["_last_up_s"] = 5
        s.schedule("gpu33-l0")
        waits.append(st["_wait"])
    assert waits == [15, 30, 60, 120, 240, 300, 300]
    st["_last_up_s"] = 3600
    s.schedule("gpu33-l0")
    assert st["_wait"] == 15
    assert s.route_fails == {}                                          # 道失败不把整条香港路判坏（只算底座）


def test_adopt_kills_stale_t_lane_and_keeps_hk_one(monkeypatch):
    s = _sup()
    s.legacy_done = True
    s.hosts = {h: {"state": "stopped", "pid": None} for h in s.c["hosts"]}
    fw = " ".join(f"-L 127.0.0.1:{lp}:127.0.0.1:{rp}" for lp, rp in s.c["hosts"]["gpu33-l0"]["forwards"])
    fw1 = " ".join(f"-L 127.0.0.1:{lp}:127.0.0.1:{rp}" for lp, rp in s.c["hosts"]["gpu33-l1"]["forwards"])
    procs = [(101, "ssh.exe", f"ssh.exe -F x -o Tag=nsnetfix-gpu33-l0 {fw} gpu33-t"),
             (102, "ssh.exe", f"ssh.exe -F x -o Tag=nsnetfix-gpu33-l1 {fw1} gpu33-hk")]
    killed = []
    monkeypatch.setattr(TS, "list_procs", lambda *a, **k: procs)
    monkeypatch.setattr(TS, "kill", lambda pid: killed.append(pid))
    monkeypatch.setattr(TS, "pid_alive", lambda pid: True)
    s.adopt()
    assert killed == [101]                                              # 经底座的旧道：杀掉按新配置重起
    assert s.hosts["gpu33-l1"]["pid"] == 102 and s.hosts["gpu33-l1"]["route"] == "hk"   # 已是独立香港连接：认领不打断


def test_plan_lists_lane_respawns_only(tmp_path):
    (tmp_path / "net_status.json").write_text(json.dumps({"hosts": {"base-a": {"state": "up"}, "base-b": {"state": "up"}}}))
    out = TS.plan(NEW, TS.CONF, tmp_path)
    resp = [ln.split()[1].rstrip(":") for ln in out if ln.startswith("RESPAWN")]
    keep = [ln.split()[1] for ln in out if ln.startswith("KEEP")]
    if json.loads(TS.CONF.read_text(encoding="utf-8"))["hosts"]["gpu33-l0"].get("via") == "t":   # 生产配置还没切
        assert sorted(resp) == sorted(LANES)
    assert "gpu36-vqa" in keep and "gpu33-cmd" in keep and "base-a" in keep
    assert not any(ln.startswith(("ADD", "REMOVE")) for ln in out)


# ---------------------------------------------------------------- known_hosts 指纹核对
def _key():
    blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes(range(32))
    b64 = base64.b64encode(blob).decode()
    fp = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return b64, fp


def test_hostkey_fingerprint_matches_registered_hkjump():
    kh = (ROOT / "config/netfix/known_hosts").read_text(encoding="utf-8")
    ln = next(x for x in kh.splitlines() if x.startswith("47.243.63.181 ssh-ed25519 "))
    assert HK.fingerprint(ln.split()[2]) == "SHA256:IrIRIa+ucfx1CxhkWG4lEsDI58vb1EZ03/rOR7uPHtY"   # = ssh_config 头部登记


def test_hostkey_refuses_mismatch_and_writes_nothing(tmp_path):
    b64, fp = _key()
    kh = tmp_path / "known_hosts"
    kh.write_text("gpu33 ssh-ed25519 AAAA\n")
    before = kh.read_bytes()
    scan = f"# 1.2.3.4:22 SSH-2.0-OpenSSH_9.6\n1.2.3.4 ssh-ed25519 {b64}\n"
    r = HK.verify_and_add("1.2.3.4", "ed25519", "SHA256:IrIRIa+ucfx1CxhkWG4lEsDI58vb1EZ03/rOR7uPHtY", scan, kh)
    assert not r["ok"] and r["action"] == "refused" and r["level"] == "P0" and r["fingerprints"] == [fp]
    assert kh.read_bytes() == before                                     # 不一致：一个字节都不写
    r = HK.verify_and_add("1.2.3.4", "ed25519", fp, "", kh)              # keyscan 没拿到 → 也拒绝
    assert r["action"] == "refused" and kh.read_bytes() == before
    r = HK.verify_and_add("1.2.3.4", "ed25519", fp, scan, kh)            # 一致 → 追加一行
    assert r["action"] == "added" and kh.read_text().endswith(f"1.2.3.4 ssh-ed25519 {b64}\n")
    r = HK.verify_and_add("1.2.3.4", "ed25519", fp, scan, kh)            # 再跑 → 不重复写
    assert r["action"] == "already_present" and kh.read_text().count(b64) == 1


def test_ssh_config_hk_hosts_use_git_ssh_not_proxyjump():
    cfg = (ROOT / "config/netfix/ssh_config").read_text(encoding="utf-8")
    for h in ("gpu33-hk", "gpu36-hk"):
        blk = cfg.split(f"Host {h}")[1].split("\nHost ")[0]
        assert "ProxyJump" not in blk and "ProxyCommand /usr/bin/ssh" in blk and "hkjump" in blk and "194relay-hk" in blk
    assert "StrictHostKeyChecking yes" in cfg and "StrictHostKeyChecking no" not in cfg


# ---------------------------------------------------------------- full_score 上传路径
class _FakeRssh:
    def __init__(self, rc):
        self.rc, self.calls = rc, []

    def bulk_put(self, host, files, remote_dir, timeout=600):
        self.calls.append((host, files, remote_dir))
        if self.rc is None:
            return None
        return subprocess.CompletedProcess(["sftp"], self.rc, b"", b"Connection closed" if self.rc else b"")


@pytest.fixture
def rs(monkeypatch, tmp_path):
    import remote_score as RS
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG fake")
    sent = []

    def fake_ssh(host, cmd, stdin=None, timeout=900):
        sent.append((cmd, stdin))
        if cmd.startswith("rm -rf"):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"items": {}, "local": {}}) + "\n", "")

    monkeypatch.setattr(RS, "ssh", fake_ssh)
    monkeypatch.setattr(RS, "face_refs", lambda host, project=None: {})
    monkeypatch.setattr(RS, "_known_path", lambda host: tmp_path / "known.json")
    monkeypatch.setattr(RS, "_hb_start", lambda *a: None)
    monkeypatch.setattr(RS, "srv_repo", lambda host: "/srv/repo")
    monkeypatch.setattr(RS, "comfy_py", lambda host: "/py")
    monkeypatch.setenv("NS_BULK_MIN_BYTES", "1")                     # 测试图很小：门槛降到 1 字节
    return RS, img, sent


def _payload(sent):
    # W-INFRA 11-06：打分命令现带环境前缀（NS_SCORE_RESIDENT=1 python3 …，FIX-SCORE36），按“去掉 VAR=val 前缀后以 python3 开头”匹配
    import re
    return json.loads(next(stdin for cmd, stdin in sent if re.match(r"^(?:\w+=\S*\s+)*python3", cmd)))


def test_full_score_uploads_via_independent_conn(rs, monkeypatch):
    RS, img, sent = rs
    fr = _FakeRssh(0)
    monkeypatch.setattr(RS, "_rssh", lambda: fr)
    d = RS.full_score("gpu33", [{"id": "S01/a:1", "file": str(img)}])
    assert d["upload"]["mode"] == "sftp-hk" and fr.calls and fr.calls[0][0] == "gpu33"
    it = _payload(sent)["items"][0]
    assert "b64" not in it and it["host_path"].startswith(RS.R + "/up/fsu_")   # 图不再塞进主连接 stdin
    assert any(cmd == f"rm -rf {d['upload']['dir']}" for cmd, _ in sent)       # 打完删掉


@pytest.mark.parametrize("rc", [255, None])
def test_full_score_upload_failure_falls_back_to_b64(rs, monkeypatch, rc):
    RS, img, sent = rs
    monkeypatch.setattr(RS, "_rssh", lambda: _FakeRssh(rc))
    d = RS.full_score("gpu33", [{"id": "S01/a:1", "file": str(img)}])
    it = _payload(sent)["items"][0]
    assert it["b64"] == base64.b64encode(img.read_bytes()).decode() and not it.get("host_path")   # 原路径
    assert d["upload"]["mode"] == ("b64_fallback" if rc else "b64")            # 如实记，不冒充独立连接
    if rc:
        assert "rc=255" in d["upload"]["why"]


def test_full_score_upload_exception_falls_back(rs, monkeypatch):
    RS, img, sent = rs

    class Boom:
        def bulk_put(self, *a, **k):
            raise OSError("sftp.exe missing")
    monkeypatch.setattr(RS, "_rssh", lambda: Boom())
    d = RS.full_score("gpu33", [{"id": "a", "file": str(img)}])
    assert d["upload"]["mode"] == "b64_fallback" and "b64" in _payload(sent)["items"][0]


def test_full_score_host_path_items_skip_upload(rs, monkeypatch):
    RS, img, sent = rs
    fr = _FakeRssh(0)
    monkeypatch.setattr(RS, "_rssh", lambda: fr)
    d = RS.full_score("gpu33", [{"id": "a", "host_path": "/root/out/a.png"}])
    assert fr.calls == [] and d["upload"]["mode"] == "none"
    assert _payload(sent)["items"][0]["host_path"] == "/root/out/a.png"


def test_full_score_small_batch_stays_on_stdin(rs, monkeypatch):
    """小批（< NS_BULK_MIN_BYTES）不多开一条跳板连接：仍走原 base64-stdin"""
    RS, img, sent = rs
    fr = _FakeRssh(0)
    monkeypatch.setattr(RS, "_rssh", lambda: fr)
    monkeypatch.setenv("NS_BULK_MIN_BYTES", str(10 << 20))
    d = RS.full_score("gpu33", [{"id": "a", "file": str(img)}])
    assert fr.calls == [] and d["upload"]["mode"] == "b64" and "b64" in _payload(sent)["items"][0]
    assert RS.BULK_MIN_BYTES == 1 << 20
