"""NETFIX 11-01（K-OPS-N01..N05）：隧道监管 / 派单分区 / 看图内网入口 / 状态文件。真机注入测试见 tools/netfix/inject_test.py。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/netfix"))
import dispatch as D  # noqa: E402
import tunnel_supervisor as TS  # noqa: E402


# ---------------------------------------------------------------- K-OPS-N04 分区
def test_partition_is_disjoint_and_complete():
    assert D.check_partition() == []


def test_partition_check_catches_overlap_and_laptop_video():
    part = json.loads((ROOT / "config/netfix/partition.json").read_text(encoding="utf-8"))
    part["images"]["gpu36"] = part["images"]["gpu36"] + [1]
    part["video"]["laptop"] = [10]
    errs = D.check_partition(part)
    assert any("ep01" in e for e in errs) and any("laptop" in e for e in errs)


READY = {"episodes": {"1": {"shots": ["ep01-S1", "ep01-S2"]}, "2": {"shots": ["ep02-S1"]}, "10": {"shots": ["ep10-S1"]}}}


def test_control_only_is_partition_intersect_ready():
    f = D.control_for("gpu33", {"paused": False}, READY)
    assert f["only"] == ["ep01-S1", "ep01-S2"] and f["paused"] is False
    assert set(f["hold_lanes"]) == {"gpu36:0", "gpu36:1", "gpu36:2", "laptop:0"}
    assert D.control_for("laptop", {}, READY)["only"] == ["ep10-S1"]
    assert "paused" not in D.control_for("laptop", {"paused": True, "paused_by": "x"}, READY)   # 笔记本的 paused 就是全局开关，不改


def test_control_none_when_nothing_ready():
    assert D.control_for("gpu36", {}, {})["only"] == [D.NONE]          # 空 only = 全派，绝不能留空


def test_global_pause_follows_laptop_except_yield_markers():
    f = D.control_for("gpu36", {"paused": True, "paused_by": "总调度 fredw-2b"}, READY)
    assert f["paused"] is True and f["paused_by"].startswith("GLOBAL:")
    for by in ("SERVER_RESIDENT", "OFFLINE", "LAPTOP_IMAGES"):
        assert D.control_for("gpu36", {"paused": True, "paused_by": by}, READY)["paused"] is False


def test_no_two_producers_share_a_shot_or_lane():
    shots, lanes = {}, {}
    for h in ("gpu33", "gpu36", "laptop"):
        f = D.control_for(h, {}, READY)
        mine = set(D.partition()["lanes"][h])
        assert not (mine & set(f["hold_lanes"]))
        for s in f["only"]:
            if s != D.NONE:
                assert s not in shots, (s, h, shots.get(s))
                shots[s] = h
        for ln in mine:
            assert ln not in lanes
            lanes[ln] = h


def test_steal_plan_reports_unsafe():
    assert D.steal_plan({"gpu33": {"idle": True, "unstarted_eps": [2]}})["safe_now"] is False


# ---------------------------------------------------------------- K-OPS-N01 监管进程（假进程 / 假探测）
class FakeSup(TS.Supervisor):
    def __init__(self, tmp, relay=True):
        conf = json.loads(TS.CONF.read_text(encoding="utf-8"))
        conf["legacy_loops"] = []
        p = tmp / "conf.json"
        p.write_text(json.dumps(conf), encoding="utf-8")
        super().__init__(p, tmp)
        self.relay_ok, self.alive, self.spawned, self.killed, self.probe = relay, set(), [], [], {}
        self.t = 1000.0

    def check_relay(self):
        TS.tcp_ok = lambda *a, **k: self.relay_ok
        return super().check_relay()

    def adopt(self, h=None):
        pass

    def spawn(self, h, reason):
        pid = 100 + len(self.spawned)
        self.spawned.append((h, pid))
        self.alive.add(pid)
        self.hosts[h].update(pid=pid, since_t=TS.now(), state="connecting", hang=0, probe_t=0.0)

    def stop_host(self, h, reason):
        self.killed.append((h, self.hosts[h]["pid"], reason))
        self.alive.discard(self.hosts[h]["pid"])
        super().stop_host(h, reason)


def _patch(monkeypatch, s):
    monkeypatch.setattr(TS, "pid_alive", lambda pid: pid in s.alive)
    monkeypatch.setattr(TS, "kill", lambda pid: None)
    monkeypatch.setattr(TS, "probe_http", lambda port, to: s.probe.get(port, "ok"))


def test_relay_down_no_spawn_then_restore_immediate(monkeypatch, tmp_path):
    s = FakeSup(tmp_path, relay=False)
    _patch(monkeypatch, s)
    s.tick()
    assert s.spawned == [] and all(st["state"] == "relay_down" for st in s.hosts.values())
    for st in s.hosts.values():
        st["fails"], st["next_try_t"] = 4, TS.now() + 999     # 之前退避很久
    s.relay_ok = True
    s.tick()                                                   # 跳板恢复：退避清零、两台立刻起
    assert {h for h, _ in s.spawned} == {"gpu33", "gpu36"}
    s.tick()
    assert all(st["state"] == "up" for st in s.hosts.values())
    st = json.loads((tmp_path / "net_status.json").read_text(encoding="utf-8"))
    assert st["tunnels_up"] == st["tunnels_total"] == 6 and st["relay"]["up"] is True


def test_exit_backoff_then_respawn(monkeypatch, tmp_path):
    s = FakeSup(tmp_path)
    _patch(monkeypatch, s)
    s.tick()
    pid = s.hosts["gpu36"]["pid"]
    s.alive.discard(pid)                                       # ssh 退出
    s.tick()
    assert s.hosts["gpu36"]["state"] == "backoff" and s.hosts["gpu36"]["restarts"] == 1
    s.hosts["gpu36"]["next_try_t"] = 0
    s.tick()
    assert s.hosts["gpu36"]["pid"] not in (None, pid)


def test_hang_detected_and_killed_but_remote_down_is_not(monkeypatch, tmp_path):
    s = FakeSup(tmp_path)
    _patch(monkeypatch, s)
    s.tick()
    s.tick()
    assert s.hosts["gpu33"]["state"] == "up"
    for p in (18188, 18189, 18191):                            # 一条对端服务挂了：不杀隧道
        s.probe[p] = "remote_down" if p == 18188 else "ok"
    s.hosts["gpu33"]["probe_t"] = 0
    s.tick()
    assert s.killed == []
    for p in (18188, 18189, 18191):                            # 全部超时 = ssh 卡死
        s.probe[p] = "timeout"
    for _ in range(s.c["hang_rounds"]):
        assert not s.killed
        s.hosts["gpu33"]["probe_t"] = 0
        s.tick()
    assert s.killed and s.killed[0][0] == "gpu33"


def test_ssh_cmd_has_keepalive_and_tag():
    s = TS.Supervisor.__new__(TS.Supervisor)
    s.c = json.loads(TS.CONF.read_text(encoding="utf-8"))
    s.tag = "nsnetfix"
    cmd = " ".join(s.ssh_cmd("gpu36"))
    for k in ("ServerAliveInterval=10", "ConnectTimeout=20", "ExitOnForwardFailure=yes", "Tag=nsnetfix-gpu36",
              "Tag=nsnetfix-proxy-gpu36", "127.0.0.1:18288:127.0.0.1:8188", "127.0.0.1:18290:127.0.0.1:8190"):
        assert k in cmd
    assert "ServerAliveInterval" in s.c["relay"]["proxy_cmd"]


def test_all_render_ports_supervised_once():
    c = json.loads(TS.CONF.read_text(encoding="utf-8"))
    ports = [lp for h in c["hosts"].values() for lp, _ in h["forwards"]]
    assert len(ports) == len(set(ports))
    assert {18188, 18189, 18191, 18288, 18289, 18290} <= set(ports)


# ---------------------------------------------------------------- K-OPS-N03 看图内网入口
def test_vqa_lan_url_only_on_servers(monkeypatch):
    sys.path.insert(0, str(ROOT / "services/agent"))
    from ns_agent.vqa import client as C
    monkeypatch.setattr(C, "_local_up", lambda u: True)
    monkeypatch.delenv("OFFLINE_SELF", raising=False)
    monkeypatch.delenv("VQA_LAN", raising=False)
    assert C._lan_url() is None                                  # 笔记本不试
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    assert C._lan_url() == "http://10.0.0.36:8870"
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")                  # gpu36 自己用 127.0.0.1
    assert C._lan_url() is None


def test_lan_proxy_binds_internal_only():
    s = (ROOT / "tools/netfix/lan_proxy.sh").read_text(encoding="utf-8")
    assert "--bind 10.0.0.36" in s and "--allow 10.0.0.33" in s and "0.0.0.0" not in s


# ---------------------------------------------------------------- K-OPS-N05 状态文件字段
def test_status_doc_fields():
    for k in ("relay", "hosts.<h>", "servers.<h>", "tunnels_up / tunnels_total"):
        assert k in TS.STATUS_DOC
