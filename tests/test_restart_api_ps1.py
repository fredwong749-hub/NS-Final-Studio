"""ops/restart_api.ps1 + api_restart_guard 重启安全（总调度 11-02 22:0x：今晚三次自动重启把 :8800 弄挂，K-OPS-F34）。

真跑 restart_api.ps1，但全部用假端口 / 假 app / 临时 data 目录 / 只匹配本测试标记的“旧进程”——不碰真 :8800、不写真实 data/。
覆盖：新代码起不来 → 旧进程不杀；端口被别的进程一直占着 → 旧进程不杀；两种都写 restart_failed(old_kept=true) + 告警。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PS1 = ROOT / "ops" / "restart_api.ps1"
PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(os.name != "nt" or not PWSH, reason="restart_api.ps1 只在 Windows + pwsh 上跑")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _spawn(code: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _listener(port: int, mark: str = "") -> subprocess.Popen:
    p = _spawn(f"import socket,time  # {mark}\ns=socket.socket(); s.bind(('127.0.0.1',{port})); s.listen(); time.sleep(120)")
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return p
        except OSError:
            time.sleep(0.1)
    p.kill()
    raise RuntimeError("listener did not come up")


def _cmd(tmp_path: Path, port: int, mark: str, app: str, extra: list[str] | None, preport: int | None, prewait: int, freewait: int) -> list[str]:
    return [PWSH, "-NoProfile", "-File", str(PS1), "-Force", "-By", "pytest",
            "-Port", str(port), "-PrePort", str(preport or _free_port()), "-App", app, "-AppDir", str(tmp_path),
            "-KillMatch", mark, "-DataDir", str(tmp_path / "data"), "-LogDir", str(tmp_path / "logs"),
            "-PreWaitS", str(prewait), "-FreeWaitS", str(freewait), "-UpWaitS", "10", "-Probe", "/", *(extra or [])]


def _read(tmp_path: Path) -> tuple[list[dict], list[dict]]:
    rd = lambda f: [json.loads(x) for x in f.read_text(encoding="utf-8-sig").splitlines() if x.strip()] if f.exists() else []
    return rd(tmp_path / "data" / "ops" / "restart_events.jsonl"), rd(tmp_path / "data" / "qa" / "alerts.jsonl")


def _run(tmp_path: Path, port: int, mark: str, app: str, timeout: int = 240, extra: list[str] | None = None,
         preport: int | None = None, prewait: int = 20, freewait: int = 5) -> tuple[int, list[dict], list[dict]]:
    # 输出写文件、不接管道：起来的新服务会继承 pwsh 的句柄，接管道会一直等不到 EOF（守护 21:45 / 20:07 卡满 360 s 就是这个）
    with open(tmp_path / "ps1.out", "ab") as out:
        r = subprocess.run(_cmd(tmp_path, port, mark, app, extra, preport, prewait, freewait),
                           stdout=out, stderr=subprocess.STDOUT, timeout=timeout, stdin=subprocess.DEVNULL)
    ev, al = _read(tmp_path)
    return r.returncode, ev, al


def _born(pid: int) -> str:
    """与 ps1 的 Born 同口径：Win32_Process.CreationDate 的 UTC Ticks"""
    r = subprocess.run([PWSH, "-NoProfile", "-Command",
                        f"[string]([datetime](Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CreationDate).ToUniversalTime().Ticks"],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def _port_free(port: int) -> bool:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _kill_started(tmp_path: Path, port: int) -> None:
    """只停本测试里 ps1 起的那份（pid 记在临时 data/ops/api_<port>.pid.json，K-OPS-F30）"""
    f = tmp_path / "data" / "ops" / f"api_{port}.pid.json"
    if f.exists():
        subprocess.run(["taskkill", "/PID", str(json.loads(f.read_text(encoding="utf-8-sig"))["pid"]), "/T", "/F"], capture_output=True, timeout=30)


@pytest.fixture
def fake_app(tmp_path):
    (tmp_path / "fake_asgi.py").write_text(
        "async def app(scope, receive, send):\n"
        "    if scope['type'] != 'http':\n"
        "        return\n"
        "    await send({'type': 'http.response.start', 'status': 200, 'headers': []})\n"
        "    await send({'type': 'http.response.body', 'body': b'ok'})\n", encoding="utf-8")
    return "fake_asgi:app"


def test_preflight_fail_keeps_old_process(tmp_path):
    """新代码起不来（模块导入失败）→ 不杀旧进程，exit 4，restart_failed(stage=preflight, old_kept=true) + warn 告警"""
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    old = _spawn(f"import time  # {mark}\ntime.sleep(120)")
    try:
        rc, ev, al = _run(tmp_path, _free_port(), mark, "no_such_module_xyz:app")
        assert rc == 4
        assert old.poll() is None, "预检失败时旧进程被杀了"
        f = [e for e in ev if e.get("event") == "restart_failed"]
        assert f and f[-1]["stage"] == "preflight" and f[-1]["old_kept"] is True
        assert not [e for e in ev if e.get("event") == "restart_done"]
        assert al and al[-1]["id"] == "A-API-RESTART-FAIL" and al[-1]["level"] == "warn"
        assert not (tmp_path / "data" / "ops" / "api_restart.lock").exists(), "退出后锁没释放"
        assert not (tmp_path / "data" / "ops" / "api_preflight.pid").exists()
    finally:
        old.kill()


def test_port_held_by_other_process_keeps_old_process(tmp_path, fake_app):
    """端口一直被别的进程占着（新进程拿不到端口）→ 旧进程一个都不杀，exit 4，restart_failed(stage=port_foreign, old_kept=true)"""
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    old = _spawn(f"import time  # {mark}\ntime.sleep(120)")
    squatter = _listener(port, "squatter-not-matching")
    try:
        rc, ev, al = _run(tmp_path, port, mark, fake_app)
        assert rc == 4, ev
        assert old.poll() is None, "端口被占时旧进程被杀了"
        assert squatter.poll() is None
        f = [e for e in ev if e.get("event") == "restart_failed"]
        assert f and f[-1]["stage"] == "port_foreign" and f[-1]["old_kept"] is True
        assert al and al[-1]["level"] == "warn"
    finally:
        old.kill()
        squatter.kill()


def test_success_path_switches_old_to_new(tmp_path, fake_app, monkeypatch):
    """正常路径：备用端口预检过 → 停旧（声明 --port P 的标记进程）→ 等端口空 → 看门狗起新 → 探针 200 → restart_done + 标记文件"""
    import urllib.request
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    old = _spawn(f"import socket,time  # {mark} --port {port}\n"
                 f"s=socket.socket(); s.bind(('127.0.0.1',{port})); s.listen(); time.sleep(120)")
    time.sleep(1.0)
    life = tmp_path / "lifecycle.jsonl"
    monkeypatch.setenv("NS_API_LIFECYCLE_LOG", str(life))      # 看门狗不写真实 data/ops/api_lifecycle.jsonl
    try:
        rc, ev, al = _run(tmp_path, port, mark, fake_app)
        assert rc == 0, ev
        assert old.poll() is not None, "旧进程没停"
        assert [e for e in ev if e.get("event") == "restart_done" and e.get("up_at")]
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).status == 200
        assert json.loads((tmp_path / "data" / "qa" / "api_restart.json").read_text(encoding="utf-8-sig"))["up_at"]
        assert not al
    finally:
        old.kill()
        for ln in (life.read_text(encoding="utf-8").splitlines() if life.exists() else []):
            wd = json.loads(ln).get("watchdog_pid")
            if wd:      # 只停本测试起的那份（看门狗 pid 记在临时留痕里，K-OPS-F30）
                subprocess.run(["taskkill", "/PID", str(wd), "/T", "/F"], capture_output=True, timeout=30)


def _http_server(port: int, mark: str, delay: float = 0.0) -> subprocess.Popen:
    """假“健康 API”：延迟 delay 秒后在 port 上对任何 GET 回 200；命令行带 mark + --port（被脚本当作“旧进程”）"""
    return _spawn(f"import time  # {mark} --port {port}\ntime.sleep({delay})\n"
                  "import http.server\n"
                  "class H(http.server.BaseHTTPRequestHandler):\n"
                  "    def do_GET(self):\n"
                  "        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
                  "    def log_message(self, *a): pass\n"
                  f"http.server.ThreadingHTTPServer(('127.0.0.1',{port}),H).serve_forever()")


def _wait_http(port: int, secs: float = 10) -> None:
    import urllib.request
    end = time.time() + secs
    while time.time() < end:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1).close()
            return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("fake api not up")


def test_lock_busy_exit5_touches_nothing(tmp_path, fake_app):
    """RESTARTFIX-S P1-2：锁被活着的别的进程持有 -> exit 5，什么都不做（旧进程不杀、不预检），锁文件原样保留"""
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    old = _spawn(f"import time  # {mark} --port {port}\ntime.sleep(120)")
    holder = _spawn("import time\ntime.sleep(120)")
    lock = tmp_path / "data" / "ops" / "api_restart.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": holder.pid, "at": "2026-11-02T23:00:00", "by": "someone"}), encoding="utf-8")
    try:
        rc, ev, al = _run(tmp_path, port, mark, fake_app)
        assert rc == 5, ev
        assert old.poll() is None
        assert lock.exists() and json.loads(lock.read_text(encoding="utf-8"))["pid"] == holder.pid
        assert [e for e in ev if e.get("event") == "restart_skipped" and e.get("stage") == "lock_busy"]
        assert not [e for e in ev if e.get("event") in ("restart_failed", "restart_done")]
        assert not al and not (tmp_path / "logs" / "api_preflight.err.log").exists(), "没拿到锁却起了预检"
    finally:
        old.kill()
        holder.kill()


def test_stale_lock_is_taken_over(tmp_path):
    """持有者进程已死的锁可接管：脚本继续往下走（这里预检失败 exit 4），退出后锁已释放"""
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    dead = _spawn("pass")
    dead.wait(timeout=30)
    lock = tmp_path / "data" / "ops" / "api_restart.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": dead.pid, "at": "2026-11-02T20:00:00", "by": "ghost"}), encoding="utf-8")
    old = _spawn(f"import time  # {mark}\ntime.sleep(120)")
    try:
        rc, ev, _ = _run(tmp_path, _free_port(), mark, "no_such_module_xyz:app")
        assert rc == 4, ev
        assert not lock.exists()
    finally:
        old.kill()


def test_revive_already_healthy_never_kills_api(tmp_path, fake_app):
    """RESTARTFIX-S P1-2：-Force -Revive 时 :Port 已健康 -> exit 0，不停旧（健康的）进程、不预检"""
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    api = _http_server(port, mark)
    try:
        _wait_http(port)
        rc, ev, al = _run(tmp_path, port, mark, fake_app, extra=["-Revive"])
        assert rc == 0, ev
        assert api.poll() is None, "健康的 API 被杀了"
        assert [e for e in ev if e.get("event") == "restart_skipped" and e.get("stage") == "already_healthy"]
        assert not [e for e in ev if e.get("event") in ("restart_failed", "restart_done")] and not al
    finally:
        api.kill()


def test_revive_api_started_by_someone_during_preflight_is_not_killed(tmp_path):
    """模拟补起预检期间（慢 app 约 30 s）别人把 API 拉起来了：停旧进程之前的再测一次发现健康 -> exit 0，不杀它

    W13 CUTB-PREP 11-03（REVIEW-G5/G6）：时序放宽，断言不变。原参数（假 API 6 s 后起、慢 app 10 s、PreWaitS 30）在本机串行也红：
    pwsh 冷启动 + 拿锁比假 API 的 6 s 还慢（实测 restart_requested→跳过 3 s），假 API 已在“拿到锁后”那次探针被看到（why=“补起前（拿到锁后）…”），走不到要测的“停旧进程之前”。
    改成 15 s / 30 s / 50 s：拿锁探针（≤ ~9 s）一定还没人，预检结束（≥ 拿锁 + 30 s）前一定已起来。"""
    (tmp_path / "slow_asgi.py").write_text(
        "import time\ntime.sleep(30)\n"
        "async def app(scope, receive, send):\n"
        "    if scope['type'] != 'http':\n        return\n"
        "    await send({'type': 'http.response.start', 'status': 200, 'headers': []})\n"
        "    await send({'type': 'http.response.body', 'body': b'ok'})\n", encoding="utf-8")
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    api = _http_server(port, mark, delay=15.0)       # 脚本拿锁后的第一次探针（≤ ~9 s）还没人，预检结束（>30 s）前它起来了
    try:
        rc, ev, al = _run(tmp_path, port, mark, "slow_asgi:app", extra=["-Revive"], prewait=50)
        assert rc == 0, ev
        assert api.poll() is None, "预检期间被别人拉起的健康 API 被杀了"
        sk = [e for e in ev if e.get("event") == "restart_skipped" and e.get("stage") == "already_healthy"]
        assert sk and "停旧进程之前" in sk[-1]["why"], ev
        assert not [e for e in ev if e.get("event") in ("restart_failed", "restart_done")]
        assert not (tmp_path / "data" / "ops" / "api_restart.lock").exists()
    finally:
        api.kill()


def test_leftover_preflight_from_killed_run_is_cleaned(tmp_path):
    """RESTARTFIX-S P2-1：上次脚本被硬杀留下的预检（pid 文件 + 命令行 --port 对得上）下一次启动先清掉，不会永久 preflight_port"""
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    pre = _free_port()
    left = _listener(pre, f"leftover --port {pre}")
    ops = tmp_path / "data" / "ops"
    ops.mkdir(parents=True)
    (ops / "api_preflight.pid").write_text(str(left.pid), encoding="ascii")
    old = _spawn(f"import time  # {mark}\ntime.sleep(120)")
    try:
        rc, ev, _ = _run(tmp_path, _free_port(), mark, "no_such_module_xyz:app", preport=pre)
        f = [e for e in ev if e.get("event") == "restart_failed"]
        assert f and f[-1]["stage"] == "preflight", ev          # 不是 preflight_port：残留已清
        assert left.poll() is not None
        assert old.poll() is None
    finally:
        old.kill()
        left.kill()


def test_ps1_static_contract():
    """BOM 保留；预检放 try/finally；UpWaitS 默认 180；FreeWaitS 默认 240（RESTARTFIX-O）；-Revive 是开关（默认关）；停旧用 taskkill /T"""
    raw = PS1.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"
    t = raw.decode("utf-8-sig")
    assert "[int]$UpWaitS = 180" in t and "[switch]$Revive" in t and "} finally {" in t
    assert "[int]$FreeWaitS = 240" in t and "Stop-Ids" in t and "Tree-Of $all $liveIds" in t
    assert "/T /F" not in t.split("function Kill-Recorded")[1].split("function Read-Killed")[0], "补停不许用 taskkill /T（不核创建时间）"
    assert "--detach" in t and "WaitForExit(60000)" in t, "看门狗经 api_watchdog.py --detach 起"
    assert "Stop-Process -Id $_.ProcessId" not in t, "不再按命令行逐个 Stop-Process 旧进程（要停整棵树）"


# ---------------------------------------------------------------- RESTARTFIX-O（OVERSIGHT 第 17 轮 P1-1 / P2）
def _inherit_server(port: int, mark: str) -> subprocess.Popen:
    """“旧 API”：命令行带 mark + --port；监听套接字设成可继承，再起一个子进程（close_fds=False）——子进程继承监听句柄，
    只杀父进程时端口仍被子进程占着（复现 11-02 21:58 / 11-03 00:09 的“旧进程死了端口还在听”）"""
    code = (f"import socket,subprocess,sys,time  # {mark} --port {port}\n"
            f"s=socket.socket(); s.bind(('127.0.0.1',{port})); s.listen(); s.set_inheritable(True)\n"
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'], close_fds=False)\n"
            "time.sleep(120)")
    p = _spawn(code)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return p
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("inherit server not up")


def _children(pid: int) -> list[int]:
    r = subprocess.run([PWSH, "-NoProfile", "-Command",
                        f"Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}' | ForEach-Object {{ $_.ProcessId }}"],
                       capture_output=True, text=True, timeout=60)
    return [int(x) for x in r.stdout.split() if x.strip().isdigit()]


def _alive(pid: int) -> bool:
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=30)
    return str(pid) in r.stdout


def test_old_tree_with_child_holding_listener_is_freed(tmp_path, fake_app, monkeypatch):
    """P1-1“旧监听未释放”：旧 API 的子进程继承了监听句柄 → 停旧用 taskkill /T 连子进程一起停，端口马上空、新进程起来（不是 port_busy）"""
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    old = _inherit_server(port, mark)
    time.sleep(1.5)
    kids = [k for c in _children(old.pid) for k in [c, *_children(c)]]
    assert kids, "旧进程没起子进程"
    monkeypatch.setenv("NS_API_LIFECYCLE_LOG", str(tmp_path / "lifecycle.jsonl"))
    try:
        rc, ev, al = _run(tmp_path, port, mark, fake_app)
        assert rc == 0, ev
        st = [e for e in ev if e.get("event") == "stopping_old"]
        assert st and st[-1]["source"] == "claim"
        assert not [k for k in kids if _alive(k)], "旧进程的子进程（占着监听句柄）没被停"
        done = [e for e in ev if e.get("event") == "restart_done"][-1]
        stp = [e for e in ev if e.get("event") == "old_stopped"][-1]
        assert stp["listen_after_1s"] is False and not stp["still_alive"], stp      # 停完 1 秒端口已空（只停父进程时子进程会一直占着）
        assert done["port_freed_s"] < 8, done        # 一次“端口空”判定本机约 4 s（Get-NetTCPConnection 慢），不含残留等待
        assert not al
    finally:
        old.kill()
        for k in kids:
            subprocess.run(["taskkill", "/PID", str(k), "/F"], capture_output=True, timeout=30)
        _kill_started(tmp_path, port)


def test_pid_file_is_used_on_next_restart(tmp_path, fake_app, monkeypatch):
    """第二次重启只认第一次记下的看门狗 pid（pid + 创建时间），整棵树停掉；成功后 killed.json 作废"""
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    old = _http_server(port, mark)
    monkeypatch.setenv("NS_API_LIFECYCLE_LOG", str(tmp_path / "lifecycle.jsonl"))
    try:
        _wait_http(port)
        rc, ev, _ = _run(tmp_path, port, mark, fake_app)
        assert rc == 0, ev
        pf = json.loads((tmp_path / "data" / "ops" / f"api_{port}.pid.json").read_text(encoding="utf-8-sig"))
        assert pf["pid"] and pf["born"] and pf["port"] == port
        first_tree = [pf["pid"], *_children(pf["pid"])]
        rc, ev, _ = _run(tmp_path, port, "NO-MATCH-" + mark, fake_app)      # KillMatch 对不上：只能靠 pid 文件认旧
        assert rc == 0, ev
        st = [e for e in ev if e.get("event") == "stopping_old"]
        assert st[-1]["source"] == "pid_file" and st[-1]["roots"] == [pf["pid"]], st[-1]
        assert not [p for p in first_tree if _alive(p)]
        assert not (tmp_path / "data" / "ops" / f"api_{port}.killed.json").exists()
    finally:
        old.kill()
        _kill_started(tmp_path, port)


def test_revive_residual_port_waits_instead_of_port_foreign(tmp_path, fake_app, monkeypatch):
    """P1-1“残留端口 + -Revive”：没有旧进程、看不到属主、端口还在听（几秒后自己放）→ 按残留等 FreeWaitS 再起，不是 port_foreign；
    没有 killed.json 时不动任何进程"""
    port = _free_port()
    resid = _spawn(f"import socket,time  # residual-not-matching\ns=socket.socket(); s.bind(('127.0.0.1',{port})); s.listen(); time.sleep(40)")
    time.sleep(1.0)
    monkeypatch.setenv("NS_API_LIFECYCLE_LOG", str(tmp_path / "lifecycle.jsonl"))
    try:
        rc, ev, al = _run(tmp_path, port, f"NSOLD-{uuid.uuid4().hex[:8]}", fake_app, extra=["-Revive"], freewait=90)
        assert rc == 0, ev
        assert not [e for e in ev if e.get("stage") == "port_foreign"]
        pr = [e for e in ev if e.get("event") == "port_residual"]
        assert pr and pr[-1]["recorded"] is False
        done = [e for e in ev if e.get("event") == "restart_done"][-1]
        assert done["residual"] is True and done["port_freed_s"] >= 2, done
        assert resid.returncode == 0 or resid.wait(timeout=5) == 0, "残留进程是自己退出的，不该被脚本杀"
    finally:
        resid.kill()
        _kill_started(tmp_path, port)


def test_residual_after_own_stop_kills_only_recorded_survivor(tmp_path, fake_app, monkeypatch):
    """P1-1“残留端口（上次停旧后）”：不带 -Revive 的手动重启，30 分钟内 killed.json 记过的进程还活着占着端口 → 只补停它，端口空了再起"""
    port = _free_port()
    orphan = _listener(port, "orphan-of-old-api")
    bystander = _spawn("import time\ntime.sleep(120)")
    ops = tmp_path / "data" / "ops"
    ops.mkdir(parents=True)
    (ops / f"api_{port}.killed.json").write_text(json.dumps({
        "at": "2026-11-03T00:09:38", "port": port, "source": "pid_file", "roots": [1],
        "pids": [{"pid": orphan.pid, "born": _born(orphan.pid), "parent": 1, "name": "python.exe"},
                 {"pid": bystander.pid, "born": "1", "parent": 1, "name": "python.exe"}]}), encoding="utf-8")   # 创建时间对不上 = pid 复用，不许动
    monkeypatch.setenv("NS_API_LIFECYCLE_LOG", str(tmp_path / "lifecycle.jsonl"))
    try:
        rc, ev, al = _run(tmp_path, port, f"NSOLD-{uuid.uuid4().hex[:8]}", fake_app, freewait=20)
        assert rc == 0, ev
        assert orphan.wait(timeout=10) is not None
        assert bystander.poll() is None, "创建时间对不上的 pid（复用）被杀了"
        pr = [e for e in ev if e.get("event") == "port_residual"]
        assert pr and pr[-1]["recorded"] is True
    finally:
        orphan.kill()
        bystander.kill()
        _kill_started(tmp_path, port)


def test_revive_squatter_is_never_killed(tmp_path, fake_app):
    """-Revive 下真有别的程序一直占着端口（不在 killed.json 里）→ 等 FreeWaitS 后 exit 2（port_residual），一个进程都不杀"""
    port = _free_port()
    squatter = _listener(port, "squatter-not-matching")
    try:
        rc, ev, al = _run(tmp_path, port, f"NSOLD-{uuid.uuid4().hex[:8]}", fake_app, extra=["-Revive"], freewait=6)
        assert rc == 2, ev
        f = [e for e in ev if e.get("event") == "restart_failed"]
        assert f[-1]["stage"] == "port_residual" and f[-1]["old_kept"] is False
        assert squatter.poll() is None
    finally:
        squatter.kill()


def test_revive_fresh_instance_started_by_someone_is_not_killed(tmp_path):
    """P2-5：补起开始之后别人手起的实例（创建时间晚于脚本开始）不当旧进程；停旧前还没健康也不杀，等它健康后 exit 0"""
    (tmp_path / "slow_asgi.py").write_text(
        "import time\ntime.sleep(8)\n"
        "async def app(scope, receive, send):\n"
        "    if scope['type'] != 'http':\n        return\n"
        "    await send({'type': 'http.response.start', 'status': 200, 'headers': []})\n"
        "    await send({'type': 'http.response.body', 'body': b'ok'})\n", encoding="utf-8")
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    with open(tmp_path / "ps1.out", "ab") as out:
        p = subprocess.Popen(_cmd(tmp_path, port, mark, "slow_asgi:app", ["-Revive"], None, 30, 5),
                             stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    api = None
    try:
        time.sleep(5)                                   # 脚本已开始、预检在跑
        api = _http_server(port, mark, delay=14.0)      # 别人手起：预检结束（~10 s）时还没健康
        rc = p.wait(timeout=120)
        ev, _ = _read(tmp_path)
        assert rc == 0, ev
        assert api.poll() is None, "别人刚起的实例被当旧进程杀了"
        sk = [e for e in ev if e.get("event") == "restart_skipped" and e.get("stage") == "already_healthy"]
        assert sk, ev
        assert not [e for e in ev if e.get("event") in ("stopping_old", "restart_failed", "restart_done")]
    finally:
        p.kill()
        if api:
            api.kill()


def test_lock_held_open_by_live_holder_is_not_taken_over(tmp_path, fake_app):
    """P2-2：锁内容里的 pid 已死，但文件句柄被活着的进程开着（真持有者）→ 删不掉 → exit 5，不会两把锁并行"""
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    dead = _spawn("pass")
    dead.wait(timeout=30)
    lock = tmp_path / "data" / "ops" / "api_restart.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": dead.pid, "at": "2026-11-02T20:00:00", "by": "ghost"}), encoding="utf-8")
    holder = _spawn(f"import time\nf=open(r'{lock}','rb')\ntime.sleep(120)")
    time.sleep(1.0)
    try:
        rc, ev, _ = _run(tmp_path, _free_port(), mark, fake_app)
        assert rc == 5, ev
        assert lock.exists()
    finally:
        holder.kill()


def test_lock_pid_reused_is_taken_over(tmp_path):
    """P2-2：锁里的 pid 活着但创建时间对不上（pid 被别的进程复用）→ 不白等 20 分钟，直接接管"""
    holder = _spawn("import time\ntime.sleep(120)")
    lock = tmp_path / "data" / "ops" / "api_restart.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": holder.pid, "born": "1", "at": "2026-11-03T00:00:00", "by": "ghost"}), encoding="utf-8")
    try:
        rc, ev, _ = _run(tmp_path, _free_port(), f"NSOLD-{uuid.uuid4().hex[:8]}", "no_such_module_xyz:app")
        assert rc == 4, ev
        assert not lock.exists() and holder.poll() is None
    finally:
        holder.kill()


def test_caller_holding_pipes_returns_and_watchdog_is_detached(tmp_path, fake_app, monkeypatch):
    """RESTARTFIX-O（01:48 受控重启后 P1）：调用方用管道接 ps1 输出（capture_output）时 ps1 必须按时返回——
    看门狗经 api_watchdog.py --detach 起，不继承调用方管道句柄；父进程不是本脚本的 pwsh（DETACHED + 新进程组 + 尽量脱离作业对象）"""
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    old = _http_server(port, mark)
    life = tmp_path / "lifecycle.jsonl"
    monkeypatch.setenv("NS_API_LIFECYCLE_LOG", str(life))
    try:
        _wait_http(port)
        t0 = time.time()
        r = subprocess.run(_cmd(tmp_path, port, mark, fake_app, None, None, 20, 5), capture_output=True, timeout=150,
                           stdin=subprocess.DEVNULL)          # 管道：旧写法这里会一直等到 API 退出
        assert r.returncode == 0, r.stdout.decode("utf-8", "replace")[-500:]
        assert time.time() - t0 < 150
        pf = json.loads((tmp_path / "data" / "ops" / f"api_{port}.pid.json").read_text(encoding="utf-8-sig"))
        ev = [json.loads(x) for x in life.read_text(encoding="utf-8").splitlines() if x.strip()]
        det = [e for e in ev if e.get("event") == "detached"]
        assert det and det[-1]["watchdog_pid"] == pf["pid"] and "breakaway" in det[-1]
        assert pf.get("breakaway") is not None
        import urllib.request
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).status == 200     # ps1 退出后 API 仍在
    finally:
        old.kill()
        _kill_started(tmp_path, port)


def test_port_served_by_foreign_ns_api_is_not_stopped(tmp_path, fake_app):
    """ISS-1103-014614-9db2(2)：看不到端口属主时问 /api/_instance；回的 pid 不在旧进程树里 → port_foreign，旧进程一个都不杀"""
    mark = f"NSOLD-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    srv = _spawn(f"import time  # {mark} --port {port}\n"
                 "import http.server, json\n"
                 "class H(http.server.BaseHTTPRequestHandler):\n"
                 "    def do_GET(self):\n"
                 "        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()\n"
                 "        self.wfile.write(json.dumps({'pid': 4}).encode())\n"
                 "    def log_message(self, *a): pass\n"
                 f"http.server.ThreadingHTTPServer(('127.0.0.1',{port}),H).serve_forever()")
    try:
        _wait_http(port)
        rc, ev, al = _run(tmp_path, port, mark, fake_app)
        assert rc == 4, ev
        f = [e for e in ev if e.get("event") == "restart_failed"]
        assert f[-1]["stage"] == "port_foreign" and "pid 4" in f[-1]["why"] and f[-1]["old_kept"] is True
        assert srv.poll() is None and not [e for e in ev if e.get("event") == "stopping_old"]
    finally:
        srv.kill()
