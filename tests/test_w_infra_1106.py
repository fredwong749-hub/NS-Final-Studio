"""W-INFRA 11-06（夜间自主迭代，PLAN_OVERNIGHT_20261106 第 4 线）：
① 审图台脚本认本机：gpu33 真实主机名 gpu3 / gpu36 是 gpu6 → hosts.json hostname 映射（tools/factory/hosts.py resolve_self / CLI self）；
   review_instances.sh 显存不够只起放得下的（≥1）、返回 5，分发器照起；
② 隧道监管：底座保活放宽、内层 ConnectTimeout 放宽、备用底座连续失败进“冷却”退避（带抖动）、底座劣化时内层握手限流；
   puller 小文件镜像合并成每台一次调用；
③ 既有红的时区 / 模块名问题（见各测试文件自身）；
④ resident_restart.sh night-only 只换 night（干跑模式 NS_RR_DRY=1）。
全部临时目录 / 假命令，不连服务器、不起网络监听。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("tools/factory", "tools/netfix"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import hosts as H  # noqa: E402

GIT_BASH = r"C:\Program Files\Git\usr\bin\bash.exe"      # usr/bin 的才按传入 PATH 找命令（bin/bash.exe 会把 /usr/bin 插到最前，假命令失效）
BASH = GIT_BASH if os.name == "nt" and os.path.isfile(GIT_BASH) else shutil.which("bash")
PY = Path(sys.executable)


def _posix(p: Path) -> str:
    s = str(p).replace("\\", "/")
    return f"/{s[0].lower()}{s[2:]}" if len(s) > 2 and s[1] == ":" else s


# ================================================================ ① 本机身份映射
def test_resolve_self_maps_real_hostnames(monkeypatch):
    monkeypatch.delenv("OFFLINE_SELF", raising=False)
    monkeypatch.delenv("NS_FACTORY_HOST", raising=False)
    d = H.load()
    assert d["hosts"]["gpu33"]["hostname"] == "gpu3" and d["hosts"]["gpu36"]["hostname"] == "gpu6"
    assert H.resolve_self("gpu3") == "gpu33"
    assert H.resolve_self("GPU6.lan") == "gpu36"
    assert H.resolve_self("gpu33") == "gpu33"                      # 本身就是表键
    assert H.resolve_self("some-laptop") is None
    assert H.resolve_self("") is None
    # 别名不算身份：gpu36 的 aliases=[gpu33] 是“代跑”，不是“我是 gpu33”
    assert H.resolve_self("gpu6") == "gpu36"
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    assert H.resolve_self("gpu3") == "gpu36"                       # 环境契约优先


def test_hosts_cli_self():
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.pop("OFFLINE_SELF", None)
    env.pop("NS_FACTORY_HOST", None)
    r = subprocess.run([str(PY), str(ROOT / "tools/factory/hosts.py"), "self", "gpu3"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "gpu33"
    r = subprocess.run([str(PY), str(ROOT / "tools/factory/hosts.py"), "self", "nope"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 1 and r.stdout.strip() == ""


def test_review_scripts_resolve_self_through_hosts_py():
    for rel in ("tools/vqa/review_instances.sh", "tools/netfix/review_lan_proxy.sh"):
        sh = (ROOT / rel).read_text(encoding="utf-8")
        assert 'tools/factory/hosts.py" self' in sh and "SELF=${OFFLINE_SELF:-" in sh
        assert "SELF=${OFFLINE_SELF:-$(hostname -s)}" not in sh         # 旧写法：gpu33 本机 hostname=gpu3 → WRONG_HOST
    sh = (ROOT / "tools/vqa/review_instances.sh").read_text(encoding="utf-8")
    assert "VRAM_PARTIAL" in sh and "return 5" in sh and 'case "$SRC" in 0|5) start_router' in sh
    assert "pkill" not in sh and "kill -9" not in sh


FAKE_CURL = r"""#!/bin/sh
# 假 curl（按 pid 文件 / 状态文件答 /health；POST /generate = 加载）。VQA_BASE / FAKE_STATE 来自环境
url=""; for a in "$@"; do case "$a" in http://*) url=$a;; esac; done
port=$(echo "$url" | sed -e 's#http://127.0.0.1:##' -e 's#/.*##')
case "$url" in
  */health)
    if [ "$port" = 8870 ]; then
      if [ -f "$FAKE_STATE/old8870.alive" ] && [ ! -f "$VQA_BASE/retired_8870.log" ]; then echo '{"loaded": true, "gpu": 3, "served": 9}'; exit 0; fi
      [ -f "$VQA_BASE/router_8870.pid" ] && { echo '{"gpu": "router", "instances": 3}'; exit 0; }
      exit 1
    fi
    [ -f "$VQA_BASE/server_$port.pid" ] || exit 1
    if [ -f "$FAKE_STATE/$port.loaded" ]; then echo '{"loaded": true, "gpu": 3}'; else echo '{"loaded": false, "gpu": null}'; fi; exit 0;;
  */generate) mkdir -p "$FAKE_STATE"; touch "$FAKE_STATE/$port.loaded"; echo '{"text": "ok"}'; exit 0;;
  */free) mkdir -p "$FAKE_STATE"; touch "$FAKE_STATE/freed.$port"; exit 0;;
esac
exit 1
"""


def _fake_bin(tmp: Path, free_mib: int, hostname: str = "gpu3", live: bool = False) -> Path:
    """假命令：hostname → gpu3；python3 → 本 venv；nvidia-smi → 指定空闲显存；curl → 全不通（live=True：按 pid / 状态文件答）；
    setsid → 直接执行；ss → 按 FAKE_SS_PID 报 :8870 的监听进程"""
    b = tmp / "bin"
    b.mkdir(parents=True)
    py = str(PY).replace("\\", "/")
    scripts = {
        "hostname": f"#!/bin/sh\necho {hostname}\n",
        "python3": f'#!/bin/sh\nexec "{py}" "$@"\n',
        "nvidia-smi": ("#!/bin/sh\n"                                     # ComfyUI /free 之后（FAKE_STATE/freed.8191）按 FAKE_FREE_MIB_AFTER 报
                       "case \"$*\" in *memory.free*) if [ -n \"${FAKE_FREE_MIB_AFTER:-}\" ] && [ -f \"$FAKE_STATE/freed.8191\" ]; "
                       f"then echo $FAKE_FREE_MIB_AFTER; else echo {free_mib}; fi;; *) echo '100, 24000, 0';; esac\n"),
        "curl": FAKE_CURL if live else "#!/bin/sh\nexit 1\n",
        "setsid": '#!/bin/sh\nexec "$@"\n',
        # 两条都听 8870：先是内网代理（lan_proxy.py，pid 777，不是 server.py），再是旧单实例（Fable 复审：head -1 会挑错）
        "ss": ('#!/bin/sh\necho "LISTEN 0 128 10.0.0.33:8870 0.0.0.0:* users:((\\"python3\\",pid=777,fd=3))"\n'
               '[ -n "${FAKE_SS_PID:-}" ] && echo "LISTEN 0 128 127.0.0.1:8870 0.0.0.0:* users:((\\"python\\",pid=$FAKE_SS_PID,fd=3))"\nexit 0\n'),
    }
    for n, s in scripts.items():
        (b / n).write_text(s, encoding="utf-8", newline="\n")
        os.chmod(b / n, 0o755)
    return b


def _vqa_base(tmp: Path) -> Path:
    base = tmp / "vqa"
    (base / "venv/bin").mkdir(parents=True, exist_ok=True)
    (base / "venv/bin/python").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    os.chmod(base / "venv/bin/python", 0o755)
    (base / "models/Qwen3-VL-8B-Instruct").mkdir(parents=True, exist_ok=True)
    (base / "models/Qwen3-VL-8B-Instruct/config.json").write_text("{}", encoding="utf-8")
    return base


def _run_review(tmp: Path, args: list[str], free_mib: int, hostname: str = "gpu3", extra_env: dict | None = None, live: bool = False):
    b = _fake_bin(tmp, free_mib, hostname, live=live)
    base = _vqa_base(tmp)
    sep = ";" if os.name == "nt" else ":"                              # Windows 格式 PATH 交给 Git bash 自己转
    env = {**os.environ, "PATH": str(b) + sep + os.environ.get("PATH", ""), "VQA_BASE": _posix(base),
           "VQA_HB_DIR": _posix(tmp / "hb"), "VQA_STAGGER_S": "0", "VQA_SETTLE_S": "0", "VQA_FREE_WAIT_S": "0",
           "FAKE_STATE": _posix(tmp / "state"), "VQA_PROC": _posix(tmp / "proc"), "PYTHONIOENCODING": "utf-8", **(extra_env or {})}
    env.pop("OFFLINE_SELF", None)
    env.pop("NS_FACTORY_HOST", None)
    return subprocess.run([BASH, "tools/vqa/review_instances.sh", *args], cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=120)


@pytest.mark.skipif(not BASH, reason="需要 bash")
def test_review_instances_accepts_real_hostname_gpu3(tmp_path):
    r = _run_review(tmp_path, ["status"], free_mib=30000, hostname="gpu3")
    assert "WRONG_HOST" not in r.stdout, r.stdout + r.stderr
    assert r.returncode == 0 and "instances up" in r.stdout
    r = _run_review(tmp_path / "x", ["status"], free_mib=30000, hostname="gpu6")   # gpu36 本机 → 仍拒（审图位是 gpu33）
    assert r.returncode == 2 and "WRONG_HOST 本机=gpu36" in r.stdout


@pytest.mark.skipif(not BASH, reason="需要 bash")
def test_review_instances_partial_vram_starts_what_fits(tmp_path):
    r = _run_review(tmp_path, ["scale", "3"], free_mib=9000)          # 只够 1 个（7500 MiB/个）
    out = r.stdout + r.stderr
    assert "VRAM_PARTIAL" in out and "1/3" in out, out
    assert out.count("started instance") == 1 and out.count("SKIP :") == 2
    assert "started router" in out                                      # 分发器照起，用活着的实例
    assert r.returncode == 5
    r2 = _run_review(tmp_path / "full", ["scale", "3"], free_mib=30000)
    out2 = r2.stdout + r2.stderr
    assert out2.count("started instance") == 3 and "VRAM_PARTIAL" not in out2 and "SKIP" not in out2
    r3 = _run_review(tmp_path / "zero", ["scale", "2"], free_mib=3000)
    assert r3.returncode == 3 and "VRAM_TOO_LOW" in r3.stdout + r3.stderr


def _old_single(tmp: Path, pid: str = "1380652", ss: bool = True) -> dict:
    """gpu33:3 实况：旧单实例还占 :8870（pid 文件丢了）、/health 应答 loaded；/proc 里它的命令行是本仓库 server.py"""
    proc = tmp / "proc" / pid
    proc.mkdir(parents=True)
    (proc / "cmdline").write_bytes(b"/x/vqa/venv/bin/python\x00-u\x00/x/vqa/server.py\x00")
    (tmp / "proc/777").mkdir(parents=True, exist_ok=True)
    (tmp / "proc/777/cmdline").write_bytes(b"/usr/bin/python3\x00-u\x00/root/work/fredw/netfix/lan_proxy.py\x00")
    (tmp / "state").mkdir(parents=True, exist_ok=True)
    (tmp / "state/old8870.alive").write_text("1")
    return {"FAKE_SS_PID": pid} if ss else {}


@pytest.mark.skipif(not BASH, reason="需要 bash")
def test_handover_warms_new_instances_before_retiring_old_single(tmp_path):
    """PS-MASTER 11-06：旧单实例（6.5 GB）占 :8870、懒加载实例来单就 OOM。交接顺序：认回旧 pid → 起放得下的 → 预热（真加载）→
    停旧的 → 换分发器 → 显存回来再补实例"""
    r = _run_review(tmp_path, ["handover"], free_mib=16000, live=True, extra_env=_old_single(tmp_path))
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ADOPT old single :8870 pid 1380652" in out
    assert "VRAM_PARTIAL" in out and "SKIP :8878" in out                      # 16000 MiB：旧的在卡上时只放得下 2 个
    i_w1, i_w2 = out.index("WARMED :8876"), out.index("WARMED :8877")
    i_ret, i_router, i_w3 = out.index("retired old single :8870"), out.index("started router :8870"), out.index("WARMED :8878")
    assert i_w1 < i_w2 < i_ret < i_router < i_w3                              # 先加载好新实例，再退旧的、换分发器，最后补第 3 个
    assert out.count("WARMED :") == 3 and "WARM_FAIL" not in out and "HANDOVER_HOLD" not in out
    base = tmp_path / "vqa"
    assert not (base / "server_8870.pid").exists() and (base / "router_8870.pid").exists()
    assert (base / "server_8876.pid").exists() and (base / "server_8878.pid").exists()


@pytest.mark.skipif(not BASH, reason="需要 bash")
def test_handover_keeps_old_single_when_nothing_fits_or_unknown(tmp_path):
    # 一个都放不下 → 旧单实例一动不动（pid 文件认回但不杀）
    r = _run_review(tmp_path / "a", ["handover"], free_mib=3000, live=True, extra_env=_old_single(tmp_path / "a"))
    out = r.stdout + r.stderr
    assert r.returncode == 3 and "VRAM_TOO_LOW" in out and "retired" not in out and "started router" not in out
    assert (tmp_path / "a/vqa/server_8870.pid").read_text().strip() == "1380652"
    # :8870 根本没人 → 不是交接场景：照常起 3 个 + 预热 + 起分发器
    t2 = tmp_path / "b"
    r = _run_review(t2, ["handover"], free_mib=30000, live=True)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "ADOPT" not in out and out.count("WARMED :") == 3 and "started router :8870" in out, out
    # :8870 有人、pid 文件指向不存在的进程、ss 又查不到 → 不碰、不起实例
    t3 = tmp_path / "c"
    env = _old_single(t3, ss=False)
    _vqa_base(t3)
    (t3 / "vqa/server_8870.pid").write_text("999999")                           # pid 文件指向不存在的进程、ss 又查不到 → 不碰
    r = _run_review(t3, ["handover"], free_mib=30000, live=True, extra_env=env)
    out = r.stdout + r.stderr
    assert r.returncode == 6 and "OLD_SINGLE_UNKNOWN" in out and "started instance" not in out
    # scale 时 :8870 还是旧单实例 → 明说 PORT_BUSY，不悄悄失败
    t4 = tmp_path / "d"
    env = _old_single(t4)
    _vqa_base(t4)
    (t4 / "vqa/server_8870.pid").write_text("999999")
    r = _run_review(t4, ["scale", "1"], free_mib=30000, live=True, extra_env=env)
    assert "PORT_BUSY :8870" in r.stdout + r.stderr and "handover" in r.stdout



@pytest.mark.skipif(not BASH, reason="需要 bash")
def test_handover_today_state_lazy_instances_up_frees_comfy_before_warm(tmp_path):
    """Fable 复审 ②（今天真实状态）：3 个懒加载实例已在 + 旧单实例占 :8870 + 卡上 ComfyUI 还占着模型。start_instances need=0 不会碰 ComfyUI，
    warm 自己要先 POST /free 再量显存；否则 WARM_SKIP ×3 → 三个都被停 → HANDOVER_HOLD"""
    env = _old_single(tmp_path)
    base = _vqa_base(tmp_path)
    for p in (8876, 8877, 8878):
        (base / f"server_{p}.pid").write_text("999999")                                   # 假 curl：有 pid 文件 = 实例在（未加载）
    r = _run_review(tmp_path, ["handover"], free_mib=3000, live=True, extra_env={**env, "FAKE_FREE_MIB_AFTER": "16000"})
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ADOPT old single :8870 pid 1380652" in out                                   # ss 两条监听：跳过 lan_proxy（pid 777），认 server.py 的
    assert (tmp_path / "state/freed.8191").exists()                                       # 先让 GPU3 的 ComfyUI 卸模型
    assert "WARM_SKIP" not in out and "HANDOVER_HOLD" not in out and out.count("WARMED :") == 3
    assert "retired old single :8870" in out and "started router :8870" in out
    assert "started instance" not in out                                                 # 三个早就在，不重起


# ================================================================ ①b 审图卡上有看图进程就不派出图单 + 伸缩钩子失败退避
def _lro():
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import lane_roles_producer as LRO
    LRO._RESIDENT_CACHE.clear()
    return LRO


LR_CFG = {"enabled": True, "from_episode": 2,
          "phases": {"frames": {"image": ["gpu33:0", "gpu33:1", "gpu36:0", "gpu36:1"], "review": ["gpu33:3"], "video": ["gpu36:2"]},
                     "videos": {"image": [], "review": ["gpu33:3"], "video": ["gpu33:0", "gpu33:3", "gpu36:2"]}},
          "review": {"vqa_instances": 3, "lane": "gpu33:3", "port_base": 8870, "lan_url": "http://10.0.0.33:8870",
                     "vqa_instances_by_phase": {"frames": 3, "videos": 1}}}


def test_review_probe_urls_by_where_i_am(monkeypatch):
    LRO = _lro()
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    assert LRO.review_probe_urls(LR_CFG) == [f"http://127.0.0.1:{p}/health" for p in (8870, 8876, 8877, 8878)]
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    assert LRO.review_probe_urls(LR_CFG) == ["http://10.0.0.33:8870/health"]
    monkeypatch.delenv("OFFLINE_SELF", raising=False)
    monkeypatch.delenv("NS_FACTORY_HOST", raising=False)
    assert LRO.review_probe_urls(LR_CFG) == ["http://127.0.0.1:8871/health"]      # 笔记本：隧道 8871 → gpu33:8870


def test_resident_review_lane_excluded_even_for_ungoverned_episode(monkeypatch):
    """PS-MASTER 20:41 实况：ep01 不归 lane_roles 管（from_episode=2）→ last:ep01-S8 派到 gpu33:3 → 看图 OOM。
    看图进程在卡上（任一 /health 应答，加载没加载都算）→ 任何集都不派出图单到那张卡；没驻留 → 原样"""
    LRO = _lro()
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    free = ["gpu33:0", "gpu33:3", "gpu36:0"]
    up = {"http://127.0.0.1:8877/health"}                                            # 只有一个懒加载实例活着
    lanes, dropped = LRO.lanes_minus_resident_review(free, LR_CFG, now=1000.0, probe=lambda u: u in up)
    assert lanes == ["gpu33:0", "gpu36:0"] and dropped == "gpu33:3"
    # 缓存 30 s：同一窗口内不再探
    calls = []
    lanes, _ = LRO.lanes_minus_resident_review(free, LR_CFG, now=1010.0, probe=lambda u: calls.append(u) or False)
    assert lanes == ["gpu33:0", "gpu36:0"] and calls == []
    # 过期后重探：没人应答 → 放回
    lanes, dropped = LRO.lanes_minus_resident_review(free, LR_CFG, now=1100.0, probe=lambda u: False)
    assert lanes == free and dropped is None
    # 开关关 / lane_roles 关 → 不动
    LRO._RESIDENT_CACHE.clear()
    off = {**LR_CFG, "review": {**LR_CFG["review"], "block_renders_when_resident": False}}
    assert LRO.lanes_minus_resident_review(free, off, now=2000.0, probe=lambda u: True) == (free, None)
    assert LRO.lanes_minus_resident_review(free, {"enabled": False}, now=2000.0, probe=lambda u: True) == (free, None)
    # producer.lanes_allowed：ep01（不归管）也被挡，且 10 min 记一次 review_resident_hold
    import producer as PR
    pr = object.__new__(PR.Producer)
    pr._lr_cfg, pr._lr_phases, pr._lr_active = LR_CFG, {}, None
    ev = []
    pr.logf = lambda e, **kw: ev.append((e, kw))
    LRO._RESIDENT_CACHE["gpu33:3"] = {"t": PR.now(), "resident": True, "urls": []}
    assert pr.lanes_allowed({"id": "last:ep01-S8", "ep": 1}, free) == ["gpu33:0", "gpu36:0"]
    assert pr.lanes_allowed({"id": "last:ep01-S9", "ep": 1}, free) == ["gpu33:0", "gpu36:0"]
    assert [e for e, _ in ev] == ["review_resident_hold"] and ev[0][1]["lane"] == "gpu33:3"
    LRO._RESIDENT_CACHE["gpu33:3"] = {"t": PR.now(), "resident": False, "urls": []}
    assert pr.lanes_allowed({"id": "last:ep01-S8", "ep": 1}, free) == free


def test_review_scale_retry_backoff_doubles_until_cap(tmp_path):
    """PS-MASTER：review_scale 每 10 min rc=1 刷屏 → 连续失败 600 → 1200 → 2400 → 3600 封顶；成功归零"""
    LRO = _lro()
    assert [LRO.scale_retry_wait_s(n) for n in (0, 1, 2, 3, 4, 9)] == [600, 600, 1200, 2400, 3600, 3600]
    rc_box = {"rc": 1}
    runs = []

    def runner(cfg, root, n, timeout_s):
        runs.append(n)
        return rc_box["rc"], "PORT_BUSY :8870"

    t = 1_800_000_000.0
    out = LRO.review_scale_tick(LR_CFG, tmp_path, "frames", runner=runner, now=t, wait=True)
    assert out["launched"] and LRO.read_scale(tmp_path)["fails"] == 1 and len(runs) == 1
    LRO._write_scale(tmp_path, {**LRO.read_scale(tmp_path), "done_t": t})                   # 固定“完成时刻”，用 now 推进
    assert LRO.review_scale_tick(LR_CFG, tmp_path, "frames", runner=runner, now=t + 599)["skipped"] == "retry_wait"
    LRO.review_scale_tick(LR_CFG, tmp_path, "frames", runner=runner, now=t + 601, wait=True)
    assert LRO.read_scale(tmp_path)["fails"] == 2 and len(runs) == 2
    LRO._write_scale(tmp_path, {**LRO.read_scale(tmp_path), "done_t": t + 601})
    assert LRO.review_scale_tick(LR_CFG, tmp_path, "frames", runner=runner, now=t + 601 + 1199)["skipped"] == "retry_wait"   # 第 2 次失败后等 1200
    LRO.review_scale_tick(LR_CFG, tmp_path, "frames", runner=runner, now=t + 601 + 1201, wait=True)
    assert LRO.read_scale(tmp_path)["fails"] == 3 and len(runs) == 3
    rc_box["rc"] = 0
    LRO._write_scale(tmp_path, {**LRO.read_scale(tmp_path), "done_t": t + 2000})
    LRO.review_scale_tick(LR_CFG, tmp_path, "frames", runner=runner, now=t + 2000 + 2401, wait=True)
    rec = LRO.read_scale(tmp_path)
    assert rec["ok"] and rec["fails"] == 0 and len(runs) == 4
    assert LRO.review_scale_tick(LR_CFG, tmp_path, "frames", runner=runner, now=t + 9000)["skipped"] == "already"


# ================================================================ ② 隧道监管稳健性
import tunnel_supervisor as TS  # noqa: E402


def _eff(cmd, key):
    """ssh 同名 -o 先出现的生效"""
    for i, x in enumerate(cmd[:-1]):
        if x == "-o" and cmd[i + 1].startswith(key + "="):
            return cmd[i + 1].split("=", 1)[1]


def _sup(conf: dict | None = None):
    s = TS.Supervisor.__new__(TS.Supervisor)
    s.c = conf or json.loads(TS.CONF.read_text(encoding="utf-8"))
    s.tag, s.route_bad_until, s.route_fails = "nsnetfix", {}, {}
    s.relay = {"routes": {"hk": {"up": True}, "direct": {"up": True}}}
    s.hosts = {h: {"state": "up", "fails": 0, "pid": 1, "ports": {}, "restarts": 0, "hang": 0, "probe_t": 0.0, "next_try_t": 0.0,
                   "since_t": None, "up_since_t": None, "last_restart": None} for h in s.c["hosts"]}
    s.log = lambda *a: None
    return s


def test_ssh_cmd_base_keepalive_and_inner_connect_timeout():
    s = _sup()
    for b in s.bases():
        cmd = s.ssh_cmd(b)
        assert (_eff(cmd, "ServerAliveInterval"), _eff(cmd, "ServerAliveCountMax")) == ("15", "6")   # 原 ssh_opts 10×3=30 s 太紧
    for h, hc in s.c["hosts"].items():
        if hc.get("via") == "t" and hc.get("kind") != "wsl_mux":
            cmd = s.ssh_cmd(h)
            assert _eff(cmd, "ConnectTimeout") == "45" and _eff(cmd, "ServerAliveInterval") == "15"
    conf = json.loads(TS.CONF.read_text(encoding="utf-8"))
    assert conf["base_keepalive"] == [15, 6] and conf["inner_connect_timeout_s"] == 45 and conf["standby_wait_s"] == 900
    assert conf["max_connecting_inner_degraded"] == 2 and 0 < conf["backoff_jitter"] <= 0.5


def test_backoff_jitter_only_slower_never_faster(monkeypatch):
    s = _sup()
    for w in (15, 300, 3):
        for _ in range(50):
            j = s.jitter(w)
            assert w <= j <= w * 1.25 + 1e-9
    s.c["backoff_jitter"] = 0
    assert s.jitter(15) == 15


def test_standby_base_cooldown_only_when_pure_hot_spare(monkeypatch):
    """base-b：没有内层挂它 + 连续 4 次活不过 60 s → 每次多等 900 s；base-a 不在 / 有内层要挂它 / 跑够 60 s → 不冷却"""
    s = _sup()
    monkeypatch.setattr(TS, "now", lambda: 1000.0)
    st = s.hosts["base-b"]
    st.update(pid=None, state="backoff", route="direct")
    for x in s.hosts.values():
        x.pop("base", None)                                  # 全部内层挂 base-a（配置默认）
    waits = []
    for _ in range(6):
        st["_last_up_s"] = 30
        s.schedule("base-b")
        waits.append(round(st["next_try_t"] - 1000.0))
    # 前 3 次只有规则退避（15/30/60 × ≤1.25）；第 4 次起加 900 冷却
    assert waits[0] <= 19 and waits[1] <= 38 and waits[2] <= 75
    assert all(w >= 900 for w in waits[3:]), waits
    # 跑够 60 s 再断 → 重置、不冷却
    st["_last_up_s"] = 3600
    s.schedule("base-b")
    assert st["next_try_t"] - 1000.0 < 19 and st["_short_fails"] == 0
    # base-a 不在：base-b 是唯一希望 → 不冷却
    st["_short_fails"] = 10
    s.hosts["base-a"]["state"] = "backoff"
    assert s.standby_cooldown("base-b", st) == 0.0
    s.hosts["base-a"]["state"] = "up"
    assert s.standby_cooldown("base-b", st) == 900.0
    # 有内层已经挂在 base-b（REHOME 过来的）→ 不冷却
    s.hosts["gpu36-l1"]["base"] = "base-b"
    assert s.standby_cooldown("base-b", st) == 0.0
    # base-a（全部内层的首选）永远不算热备
    s.hosts["base-a"].update(_short_fails=10)
    assert s.standby_cooldown("base-a", s.hosts["base-a"]) == 0.0
    # 规则本身不变（运维 FONG-QUICK：_wait 15 → 300 翻倍）
    assert st["_wait"] == 15


def test_base_down_wakes_standby_from_cooldown(monkeypatch, tmp_path):
    """base-a 断：base-b 若在冷却（next_try_t 远）→ 立刻改到 15 s 后（仍守 15 s 下限）"""
    s = _sup()
    s.dir = tmp_path
    monkeypatch.setattr(TS, "pid_alive", lambda pid: False)
    monkeypatch.setattr(TS, "kill", lambda pid: None)
    monkeypatch.setattr(TS, "now", lambda: 1000.0)
    s.check_relay = lambda: True
    s.probe_round = lambda h: None
    s.write_status = lambda: None
    s.conf_path = tmp_path / "x.json"                        # 不是生产配置：不跑 dispatch / puller 那段
    for h, x in s.hosts.items():
        x.update(pid=None, state="backoff", next_try_t=5000.0, since_t=None)
    s.hosts["base-a"].update(pid=77, state="up", since_t=900.0)
    s.hosts["base-b"].update(pid=None, state="backoff", next_try_t=1000.0 + 1200)   # 冷却中
    s.tick()
    assert s.hosts["base-a"]["state"] == "backoff"
    assert s.hosts["base-b"]["next_try_t"] == 1015.0


def test_inner_handshake_limited_when_base_degraded(monkeypatch, tmp_path):
    s = _sup()
    s.dir = tmp_path
    monkeypatch.setattr(TS, "pid_alive", lambda pid: pid is not None)
    s.check_relay = lambda: True
    s.probe_round = lambda h: None
    s.write_status = lambda: None
    s.conf_path = tmp_path / "x.json"
    spawned = []
    s.spawn = lambda h, reason: (spawned.append(h), s.hosts[h].update(pid=100 + len(spawned), state="connecting", since_t=TS.now()))
    inner = [h for h, hc in s.c["hosts"].items() if hc.get("via") == "t"]
    for h in inner:
        s.hosts[h].update(pid=None, state="backoff", next_try_t=0.0)
    s.hosts["base-a"].update(state="up", pid=1, degraded=True)
    s.hosts["base-b"].update(state="backoff", pid=None, next_try_t=float("inf"))
    s.tick()
    assert len(spawned) == 2, spawned                        # 底座劣化：同时握手 ≤ max_connecting_inner_degraded=2（原 8）
    s.hosts["base-a"]["degraded"] = False
    s.tick()
    assert len(spawned) == s.c["max_connecting_inner"]       # 恢复后放开到 8


# ================================================================ ② puller 小文件镜像合并成一次调用
def test_puller_mirror_fetch_one_call_per_host(monkeypatch):
    import io
    import tarfile
    import puller as P
    calls = []

    def fake_remote(host, cmd, data=None, timeout=600):
        calls.append((host, cmd, data))
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            for rel, body in (("data/producer/registry.json", b'{"a":1}'), ("data/producer/runs/v2/registry.json", b"[1]")):
                ti = tarfile.TarInfo(rel)
                ti.size = len(body)
                tf.addfile(ti, io.BytesIO(body))
        return subprocess.CompletedProcess(["x"], 0, buf.getvalue(), b"")

    monkeypatch.setattr(P, "remote", fake_remote)
    rels = ["data/producer/registry.json", "data/producer/runs/v2/registry.json", "data/producer/runs/missing/registry.json"]
    got = P.mirror_fetch("gpu33", rels)
    assert len(calls) == 1 and calls[0][0] == "gpu33" and "tar cf - -T -" in calls[0][1]
    assert calls[0][2].decode() == "\n".join(rels) + "\n"
    assert got["data/producer/registry.json"] == b'{"a":1}' and got["data/producer/runs/v2/registry.json"] == b"[1]"
    assert "data/producer/runs/missing/registry.json" not in got and got["_rc"] == 0
    # 失败：只有 _rc
    monkeypatch.setattr(P, "remote", lambda *a, **k: subprocess.CompletedProcess(["x"], 255, b"", b"down"))
    assert P.mirror_fetch("gpu36", rels) == {"_rc": 255}
    assert P.mirror_fetch("gpu36", []) == {"_rc": 0}


# ================================================================ ④ resident_restart.sh night-only 只换 night（干跑）
def _rr_env(tmp: Path) -> dict:
    off = tmp / "off"
    (off / "run").mkdir(parents=True)
    (off / "venv/bin").mkdir(parents=True)
    (off / "venv/bin/python").write_text("#!/bin/sh\necho series10_v2\n", encoding="utf-8", newline="\n")
    os.chmod(off / "venv/bin/python", 0o755)
    (off / "repo/config/pipeline").mkdir(parents=True)
    (off / "repo/config/pipeline/runs.json").write_text('{"primary": "series10_v2"}', encoding="utf-8")
    proc = tmp / "proc"
    for pid, name, cmd in ((111, "night", "python -u tools/series10_video/night.py --run series10_v2"),
                           (222, "producer", "python -u tools/autopilot/producer.py serve --run series10_v2"),
                           (333, "fwd", "python -u fwd.py")):
        (off / "run" / f"{name}.pid").write_text(str(pid), encoding="utf-8")
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "cmdline").write_text(cmd, encoding="utf-8")
    return {**os.environ, "NS_RR_DRY": "1", "NS_RR_OFF": _posix(off), "NS_RR_PROC": _posix(proc), "PYTHONIOENCODING": "utf-8"}


def _rr(tmp: Path, mode: str):
    env = _rr_env(tmp)
    r = subprocess.run([BASH, "ops/offline/resident_restart.sh", "gpu36", mode], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=120)
    return r, tmp / "proc"


@pytest.mark.skipif(not BASH, reason="需要 bash")
def test_resident_restart_night_only_keeps_producer(tmp_path):
    """PS-MASTER 11-06 18:2x：night-only 以前连 producer 一起停、又只起 night → gpu36 出图停 25 min。现在只停 / 只起 night"""
    r, proc = _rr(tmp_path, "night-only")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "stopped night 111" in out and "stopped producer" not in out, out
    assert (proc / "222").is_dir() and not (proc / "111").exists()                  # producer 进程没被碰
    logs = tmp_path / "off/logs"                                                     # 起进程的命令 stdout 进 logs/<n>.out（干跑打印在那里）
    assert "night.py --run series10_v2" in (logs / "night.out").read_text(encoding="utf-8")
    assert not (logs / "producer.out").exists() and "producer.py serve" not in out   # 只起 night（fwd 活着不重起）
    assert "producer untouched" in out and "ensure_runs.sh" not in out               # night-only 不碰第二季 producer


@pytest.mark.skipif(not BASH, reason="需要 bash")
def test_resident_restart_all_stops_both_and_calls_start(tmp_path):
    r, proc = _rr(tmp_path, "all")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "stopped night 111" in out and "stopped producer 222" in out
    assert not (proc / "111").exists() and not (proc / "222").exists() and (proc / "333").is_dir()
    assert "start.sh gpu36" in out and "ensure_runs.sh gpu36 stop" in out and out.rstrip().endswith("ensure_runs.sh gpu36")


def test_restart_queue_records_done_once_restart_was_sent(tmp_path, monkeypatch):
    """FIX-NIGHT2 17:5x：重启命令已发出 → 记 done（即使 resume 抛错），同一请求绝不第二次杀刚起的 night；
    pause / 排空阶段就失败（重启没发出）→ 不记 done，下一拍重试"""
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import restart_queue as RQ
    monkeypatch.setattr(RQ, "REQ", tmp_path / "req.jsonl")
    monkeypatch.setattr(RQ, "DONE", tmp_path / "done.jsonl")
    state = tmp_path / "state.json"
    calls = []

    class _RS:
        STATE, R, PY, RESTART_MIN_GAP_S = state, "/r", {"gpu36": "py"}, 1800

        @staticmethod
        def jl(p, d=None):
            try:
                return json.loads(Path(p).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return d

        @staticmethod
        def js(p, d):
            Path(p).write_text(json.dumps(d), encoding="utf-8")

        @staticmethod
        def ssh(host, cmd, **kw):
            calls.append(cmd)
            if "resume" in cmd:
                raise RuntimeError("resume boom")
            return b""

        @staticmethod
        def restart(host, mode):
            calls.append(f"RESTART {mode}")
            return "night pid 1 alive"

        @staticmethod
        def log(*a):
            pass

    monkeypatch.setattr(RQ, "pre_paused", lambda host, rs: None)
    monkeypatch.setattr(RQ, "drain", lambda host, rs, **k: {"drained": True, "drain_mode": "full", "drain_s": 0.0})
    RQ.request("gpu36", "test", by="T", mode="night")
    rec = RQ.process("gpu36", rs=_RS, now=1_800_000_000.0)
    assert rec and rec["mode"] == "night-only" and rec["restart_executed"] and rec["ok"] is False and "resume boom" in rec["error"]
    assert RQ.pending("gpu36") == []                                   # 已记 done：不会再重跑
    assert calls.count("RESTART night-only") == 1
    assert RQ.process("gpu36", rs=_RS, now=1_800_000_000.0 + 10) is None
    # 排空前就失败（pause 抛错）→ 不记 done、请求留着
    RQ.request("gpu36", "again", by="T", mode="night", urgent=True)
    monkeypatch.setattr(_RS, "ssh", staticmethod(lambda host, cmd, **kw: (_ for _ in ()).throw(RuntimeError("pause boom"))))
    rec2 = RQ.process("gpu36", rs=_RS, now=1_800_000_000.0 + 20)
    assert rec2 and rec2["ok"] is False and not rec2.get("restart_executed")
    assert len(RQ.pending("gpu36")) == 1
