"""跨机借道（CODER-XH 11-05；默认关，config/pipeline/lane_relay.json enabled=false）。

gpu33 / gpu36 互不信任（K-OPS-Y02），所以 gpu33 的 producer 要用 gpu36:0 出首帧，只能经笔记本：
    笔记本  python tools/autopilot/lane_relay.py serve        # 白名单代理 + ssh -R 挂到 gpu33（断了自动重连）
    笔记本  python tools/autopilot/lane_relay.py status       # 代理 / 上游 / 配置一眼看
    gpu33   producer 启动时读配置：enabled 且 OFFLINE_SELF == consumer_host → self.lanes 多一条 gpu36:0 = http://127.0.0.1:<listen_port>

代理只放行 ComfyUI 出图要用的 method+path（见 ALLOW），别的一律 403；上游只能是配置里写死的隧道口（不接受请求里的地址）。
黑名单道（只剩 gpu33:2 坏卡；L-194 11-05 项目方授权 gpu36:0/1/2 全归 NS，原 gpu36:1 / gpu36:2 黑名单撤销）和非 image 角色的道，配置里写了也拒绝。

阶段交接（出图 → 视频）：借来的道在视频阶段要还给 gpu36 本机视频作业。手动开关 = 文件 data/pipeline/lane_relay_hold.json
{"hold": ["gpu36:1", "gpu36:2"]}（或 "all"）；producer 每轮 probe_lanes 现读，列在里面的借道不再派首帧（在跑的做完）；删文件 / 清空 = 恢复。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "pipeline" / "lane_relay.json"
NEVER = ("gpu33:2",)                                 # 坏卡：永不借（L-194：gpu36:1 / gpu36:2 已归 NS，不再黑名单）
HOLD_FILE = ROOT / "data" / "pipeline" / "lane_relay_hold.json"
ALLOW = [("GET", r"/system_stats"), ("GET", r"/queue"), ("GET", r"/object_info(/[\w.\-]+)?"), ("GET", r"/history(/[\w\-]+)?"),
         ("GET", r"/view"), ("GET", r"/prompt"), ("POST", r"/prompt"), ("POST", r"/upload/image"), ("GET", r"/view_metadata/.+"),
         ("POST", r"/interrupt"), ("POST", r"/free"), ("POST", r"/queue")]
MAX_BODY = 64 * 1024 * 1024


def load_cfg(path: Path = CFG) -> dict:
    """读不到 / 坏 = 关（失败关闭）"""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"enabled": False}
    except (OSError, ValueError):
        return {"enabled": False}


def _image_lane_ok(ln: str) -> bool:
    try:
        if str(ROOT / "tools") not in sys.path:
            sys.path.insert(0, str(ROOT / "tools"))
        from factory import hosts as H
        return ln in H.lanes(role="image", enabled=True)
    except Exception:  # noqa: BLE001  arch-ok: 读不到车道表 = 不借（失败关闭）
        return False


def valid_lanes(cfg: dict, lane_ok=_image_lane_ok) -> dict:
    """配置里合格的借道：道名不在 NEVER、listen_port / upstream 齐全（上游只许本机回环）、该道 hosts.json 角色含 image 且已启用"""
    out = {}
    for ln, rec in (cfg.get("lanes") or {}).items():
        if ln in NEVER or not isinstance(rec, dict) or not rec.get("listen_port") or not rec.get("upstream"):
            continue
        if not str(rec["upstream"]).startswith("http://127.0.0.1:"):
            continue
        if lane_ok(ln):
            out[ln] = rec
    return out


def consumer_lanes(cfg: dict | None = None, host: str | None = None, lane_ok=_image_lane_ok) -> dict:
    """producer 用：enabled 且本进程在 consumer_host → {道: 本机代理地址}；否则 {}"""
    cfg = load_cfg() if cfg is None else cfg
    host = host if host is not None else (os.environ.get("NS_FACTORY_HOST") or os.environ.get("OFFLINE_SELF"))
    if not cfg.get("enabled") or not host or host != cfg.get("consumer_host"):
        return {}
    return {ln: f"http://127.0.0.1:{int(rec['listen_port'])}" for ln, rec in valid_lanes(cfg, lane_ok).items()}


def runtime_hold(lanes, path: Path | None = None) -> set:
    """阶段交接开关（现读，读不到 / 坏 = 不挡）：{"hold": ["gpu36:1", ...]} 或 {"hold": "all"} → 这些借道本轮不派首帧"""
    try:
        d = json.loads(Path(path or HOLD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 开关文件没有 / 坏 = 不挡（默认继续借）
        return set()
    h = d.get("hold") if isinstance(d, dict) else None
    if h == "all":
        return set(lanes)
    return {str(x) for x in h if str(x) in set(lanes)} if isinstance(h, list) else set()


def allowed(method: str, path: str) -> bool:
    p = path.split("?", 1)[0]
    return any(method == m and re.fullmatch(rx, p) for m, rx in ALLOW)


def make_handler(upstream: str, state: dict):
    sem = threading.BoundedSemaphore(int(state.get("max_inflight") or 4))

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _do(self, method: str):
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n) if 0 < n <= MAX_BODY else None
            if not allowed(method, self.path):
                state["denied"] = state.get("denied", 0) + 1
                return self._send(403, json.dumps({"error": f"lane_relay: {method} {self.path.split('?')[0]} 不在白名单"}).encode())
            if n > MAX_BODY:
                return self._send(413, b'{"error":"too large"}')
            hdr = {k: v for k, v in self.headers.items() if k.lower() == "content-type"}
            req = urllib.request.Request(upstream + self.path, data=data, headers=hdr, method=method)
            with sem:
                try:
                    with urllib.request.urlopen(req, timeout=300) as r:
                        body, code, ct = r.read(), r.status, r.headers.get("Content-Type", "application/octet-stream")
                except urllib.error.HTTPError as e:
                    body, code, ct = e.read(), e.code, e.headers.get("Content-Type", "application/json")
                except Exception as e:  # noqa: BLE001  arch-ok: 上游断 = 502，调用方按基础设施错重试
                    state["errors"] = state.get("errors", 0) + 1
                    return self._send(502, json.dumps({"error": "lane_relay upstream: " + repr(e)[:160]}).encode())
            state["ok"] = state.get("ok", 0) + 1
            state["last"] = time.time()
            self._send(code, body, ct)

        def do_GET(self):
            self._do("GET")

        def do_POST(self):
            self._do("POST")

    return H


def serve_proxy(listen_port: int, upstream: str, state: dict | None = None, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    state = state if state is not None else {}
    srv = ThreadingHTTPServer((host, listen_port), make_handler(upstream, state))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def reverse_cmd(rec: dict, tun: dict | None = None) -> list[str]:
    """ssh -N -R 127.0.0.1:P:127.0.0.1:P <gpu33-t>：只绑服务器回环，不绑 0.0.0.0；ssh 配置 / 选项同监管进程（netfix 隧道配置）"""
    tun = tun or json.loads((ROOT / "config" / "netfix" / ("tunnels" + ".json")).read_text(encoding="utf-8"))
    p = int(rec["listen_port"])
    return [tun["ssh_exe"], "-F", tun.get("ssh_config") or "config/netfix/ssh_config", *tun["ssh_opts"], "-o", "Tag=nsnetfix-lanerelay",
            "-R", f"127.0.0.1:{p}:127.0.0.1:{p}", rec.get("ssh_target") or "gpu33-t"]


def serve(cfg: dict | None = None, stop: threading.Event | None = None, spawn=subprocess.Popen) -> int:
    cfg = load_cfg() if cfg is None else cfg
    if not cfg.get("enabled"):
        print("lane_relay: enabled=false，不启动")
        return 0
    lanes = valid_lanes(cfg)
    if not lanes:
        print("lane_relay: 没有合格的借道（道名在黑名单 / 非 image 角色 / 配置不全）")
        return 2
    stop = stop or threading.Event()
    for ln, rec in lanes.items():
        serve_proxy(int(rec["listen_port"]), rec["upstream"], {"max_inflight": rec.get("max_inflight") or 2})
        print(f"lane_relay: {ln} 代理 127.0.0.1:{rec['listen_port']} -> {rec['upstream']}")
    procs: dict = {}
    while not stop.is_set():
        for ln, rec in lanes.items():
            pr = procs.get(ln)
            if pr is None or pr.poll() is not None:
                if pr is not None:
                    print(f"lane_relay: {ln} 反向隧道退出 rc={pr.returncode}，5 s 后重连")
                    stop.wait(5)
                procs[ln] = spawn(reverse_cmd(rec), cwd=str(ROOT), stdin=subprocess.DEVNULL)
        stop.wait(10)
    for pr in procs.values():
        try:
            pr.terminate()
        except Exception:  # noqa: BLE001  arch-ok: 退出清理
            pass
    return 0


def status() -> int:
    cfg = load_cfg()
    print(json.dumps({"enabled": bool(cfg.get("enabled")), "consumer_host": cfg.get("consumer_host"),
                      "lanes_valid": sorted(valid_lanes(cfg))}, ensure_ascii=False))
    for ln, rec in valid_lanes(cfg).items():
        for nm, u in (("proxy", f"http://127.0.0.1:{rec['listen_port']}"), ("upstream", rec["upstream"])):
            try:
                urllib.request.urlopen(u + "/queue", timeout=5).read()
                print(f"  {ln} {nm} ok")
            except Exception as e:  # noqa: BLE001
                print(f"  {ln} {nm} DOWN {repr(e)[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(serve() if (sys.argv[1:2] == ["serve"]) else status())
