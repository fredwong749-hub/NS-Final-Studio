"""NETFIX 11-01（K-OPS-N01..N05）：隧道监管 / 派单分区 / 看图内网入口 / 状态文件。真机注入测试见 tools/netfix/inject_test.py。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/netfix"))
import dispatch as D  # noqa: E402
import tunnel_supervisor as TS  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_override(monkeypatch, tmp_path):
    """不读真机的临时覆盖状态（data/netfix/override_state.json）"""
    monkeypatch.setattr(D, "OVERRIDE_STATE", tmp_path / "_none_state.json")
    monkeypatch.setattr(D, "OVERRIDE", tmp_path / "_none_ov.json")


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
        conf["hosts"] = {"gpu33": {"forwards": [[18188, 8188], [18189, 8189], [18191, 8191]], "probe_http": [18188, 18189, 18191]},
                         "gpu36": {"forwards": [[18288, 8188], [18289, 8189], [18290, 8190]], "probe_http": [18288, 18289, 18290]}}
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
    s.tag, s.route_bad_until = "nsnetfix", {}
    s.relay = {"routes": {"hk": {"up": True}, "direct": {"up": True}}}
    base = " ".join(s.ssh_cmd("base"))                                   # r2 底座：只转发两台 sshd，连跳板本身
    assert "127.0.0.1:22360:10.0.0.36:22" in base and "127.0.0.1:22330:10.0.0.33:22" in base and base.endswith(" 194relay-hk")
    cmd = " ".join(s.ssh_cmd("gpu36-l0"))
    for k in ("-F config/netfix/ssh_config", "ExitOnForwardFailure=yes", "Tag=nsnetfix-gpu36-l0",
              "127.0.0.1:18288:127.0.0.1:8188", "127.0.0.1:8871:127.0.0.1:8870"):
        assert k in cmd
    assert cmd.endswith(" gpu36-t")                                      # 内层连接在底座里直连 sshd，不在跳板握手
    assert "18290" in " ".join(s.ssh_cmd("gpu36-l2")) and "18288" not in " ".join(s.ssh_cmd("gpu36-l2"))   # 按道一条连接
    assert s.ssh_cmd("gpu33-cmd")[-1] == "gpu33-t" and "ssh_config.wsl" in " ".join(s.ssh_cmd("gpu33-cmd"))
    s.relay["routes"]["hk"]["up"] = False                               # 香港入口不通 → 底座走直连
    assert s.ssh_cmd("base")[-1] == "194relay"
    s.relay["routes"]["hk"]["up"], s.route_bad_until["hk"] = True, TS.now() + 600   # 判坏期内也走直连
    assert s.ssh_cmd("base")[-1] == "194relay"
    cfg = (ROOT / "config/netfix/ssh_config").read_text(encoding="utf-8")
    for k in ("ServerAliveInterval 10", "HostName sz194.instameta.org", "ProxyJump hkjump", "47.243.63.181", "Host gpu36-t", "Port 22360"):
        assert k in cfg
    kh = (ROOT / "config/netfix/known_hosts").read_text(encoding="utf-8")
    assert "47.243.63.181 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILK2j0d1APVCsA/83SyC14RShKARYBGvBDLCRqdoOHqC" in kh   # 指纹 SHA256:IrIRIa+uc…（keyscan 核对）


def test_base_backoff_follows_ops_rule(tmp_path):
    """运维 FONG-QUICK：底座快速失败 15 s 起翻倍、最多 300 s；跑够 60 s 再断重置 15 s"""
    s = TS.Supervisor.__new__(TS.Supervisor)
    s.c = json.loads(TS.CONF.read_text(encoding="utf-8"))
    s.route_fails, s.route_bad_until, s.dir = {}, {}, tmp_path
    st = {"fails": 0, "route": "hk"}
    s.hosts = {"base": st}
    s.log = lambda *a: None
    waits = []
    for _ in range(7):
        st["_last_up_s"] = 5
        s.schedule("base")
        waits.append(st["_wait"])
    assert waits == [15, 30, 60, 120, 240, 300, 300]
    st["_last_up_s"] = 3600
    s.schedule("base")
    assert st["_wait"] == 15


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
    for k in ("relay", "hosts.<连接名>", "servers.<h>", "tunnels_up / tunnels_total", "dispatch_mode"):
        assert k in TS.STATUS_DOC


# ---------------------------------------------------------------- K-OPS-N06 临时覆盖：笔记本代派 + 逐台交还
def test_override_laptop_takes_server_eps_and_servers_stop():
    ph = {"gpu33": "laptop", "gpu36": "server"}
    lap = D.control_for("laptop", {}, READY, ph=ph)
    assert lap["only"] == ["ep01-S1", "ep01-S2", "ep10-S1"]               # gpu33 的 ep01 归笔记本，gpu36 的 ep02 不动
    assert "gpu33:0" not in lap["hold_lanes"] and "gpu36:0" in lap["hold_lanes"]
    assert D.control_for("gpu33", {}, READY, ph=ph)["only"] == [D.NONE]
    assert D.control_for("gpu36", {}, READY, ph=ph)["only"] == ["ep02-S1"]
    for p in ("laptop", "draining"):                                      # 交还中两边都不派该台的集
        assert D.control_for("gpu33", {}, READY, ph={"gpu33": p, "gpu36": "server"})["only"] == [D.NONE]
    assert "ep01-S1" not in D.control_for("laptop", {}, READY, ph={"gpu33": "draining", "gpu36": "server"})["only"]


def test_reconcile_hands_back_only_after_assets_ready_and_leases_done(monkeypatch, tmp_path):
    for name, val in (("OVERRIDE", tmp_path / "ov.json"), ("OVERRIDE_STATE", tmp_path / "st.json"), ("ASSETS_READY", tmp_path / "ar.json"),
                      ("LEASES", tmp_path / "leases"), ("CONTROL", tmp_path / "control.json"), ("READY", tmp_path / "ready.json")):
        monkeypatch.setattr(D, name, val)
    pushed = []
    monkeypatch.setattr(D, "push_server_control", lambda h: pushed.append(h) or {"rc": 0})   # 不碰真服务器
    D.js(D.OVERRIDE, {"active": True, "laptop_hold": ["gpu36:2"]})
    D.js(D.READY, READY)
    D.js(D.OVERRIDE_STATE, {"hosts": {"gpu33": {"phase": "laptop"}, "gpu36": {"phase": "laptop"}}})
    D.js(D.LEASES / "first_ep02-S1.json", {"until": 9e12})
    assert D.reconcile()["phases"] == {"gpu33": "laptop", "gpu36": "laptop"}
    D.js(D.ASSETS_READY, {"gpu36": {"ready": True}})
    assert D.reconcile()["phases"]["gpu36"] == "draining"
    assert D.reconcile()["phases"]["gpu36"] == "draining"                # ep02 还有在途租约
    assert "ep02-S1" not in D.jl(D.CONTROL)["only"]
    D.js(D.LEASES / "first_ep02-S1.json", {"until": 0})
    assert D.reconcile()["phases"] == {"gpu33": "laptop", "gpu36": "server"}
    assert pushed.count("gpu36") >= 2                                    # draining 和 server 各推一次（服务器侧阶段跟上）
    D.js(D.LEASES / "first_ep01-S1.json", {"until": 9e12, "pid": 999999})   # 持有者已死的租约不算在途
    assert D.live_leases([1]) == []


def test_timeouts_while_ssh_moves_data_is_not_hang(monkeypatch, tmp_path):
    s = FakeSup(tmp_path)
    _patch(monkeypatch, s)
    s.tick()
    s.tick()
    io = {"v": 0}
    monkeypatch.setattr(TS, "io_bytes", lambda pid: io["v"])
    for p in (18188, 18189, 18191):
        s.probe[p] = "timeout"
    for _ in range(s.c["hang_rounds"] + 2):                    # 跳板慢、隧道在传图：探测全超时但字节在涨
        io["v"] += 100000
        s.hosts["gpu33"]["probe_t"] = 0
        s.tick()
    assert s.killed == [] and s.hosts["gpu33"]["ports"]["18188"]["why"] == "busy"


# ---------------------------------------------------------------- K-OPS-N07 ssh 闸门（WSL 主连接复用）
import rssh as RS  # noqa: E402


def test_rssh_rewrites_only_command_calls_to_servers():
    new = RS.rewrite(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-i", "C:/k", "gpu36", "nvidia-smi"])
    assert new[:4] == RS.WSL[:4] and any(x in new for x in RS.POOL["gpu36"]) and "ProxyCommand=false" in new
    assert new[-2:] == ["gpu36", "nvidia-smi"] and "C:/k" not in new
    assert RS.rewrite(["ssh", "root@gpu33", "ls"])[-2:] == ["gpu33", "ls"]
    for argv in (["ssh", "-N", "-L", "1:127.0.0.1:2", "gpu36"], ["ssh", "-M", "gpu36", "x"], ["ssh", "-O", "check", "gpu36"],
                 ["ssh", "gpu99", "ls"], ["ssh", "194relay", "ls"], ["scp", "a", "gpu33:/b"], ["ssh", "gpu33"],
                 ["ssh", "-o", "ProxyCommand=x", "-W", "h:22", "gpu33"], "ssh gpu33 ls", ["python", "gpu33"]):
        assert RS.rewrite(argv) is None, argv


def test_rssh_safety_valve(monkeypatch):
    monkeypatch.setenv("NS_SSH_SHIM", "off")
    assert RS.enabled() is False


def test_no_new_direct_ssh_outside_allowlist():
    """静态检查（K-OPS-N07）：直接 subprocess 起 ssh 的文件只能是下列已登记的（它们经 venv shim 自动复用主连接）；新增要么用 rssh.run，要么登记"""
    import re
    allow = set((ROOT / "config/netfix/ssh_callers.txt").read_text(encoding="utf-8").split())
    pat = re.compile(r"""\[\s*["'](ssh|scp)(\.exe)?["']|ssh\.exe["']""")
    found = set()
    for base in ("tools", "services", "packages", "ops"):
        for p in (ROOT / base).rglob("*.py"):
            if "netfix" in p.parts or "__pycache__" in p.parts:
                continue
            try:
                if pat.search(p.read_text(encoding="utf-8", errors="ignore")):
                    found.add(p.relative_to(ROOT).as_posix())
            except OSError:
                pass
    assert not (found - allow), f"新增直接调 ssh 的文件（改用 tools/netfix/rssh.run 或登记 config/netfix/ssh_callers.txt）：{sorted(found - allow)}"
