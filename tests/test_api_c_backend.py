"""后端 C：Qwen 信箱代理（假信箱）、T21 gpu3_takes、T22 时长/舞台提示、T44 ComfyUI 锁、桥只读快速失败。"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from ns_api import qwen_mailbox as QM
from ns_api import readiness as RD
from ns_render import pipeline as P

from test_readiness import PNG, env, ep1, gpu3_shot, script  # noqa: F401  复用夹具


# ---------------------------------------------------------------- 假 Qwen 信箱

class FakeMailbox:
    def __init__(self):
        self.tasks: dict[str, dict] = {}
        self.posts: list[dict] = []
        self.files: dict[str, dict[str, bytes]] = {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
                outer.posts.append(body)
                tid = f"t{len(outer.posts)}"
                outer.tasks[tid] = {"id": tid, "status": "queued", "created_at": "2026-10-30T00:00:00Z"}
                self._send(201, {"id": tid})

            def do_GET(self):
                if self.path.startswith("/files/"):
                    tid, _, rel = self.path[len("/files/"):].partition("/")
                    files = outer.files.get(tid, {})
                    if not rel:
                        return self._send(200, {"task_id": tid, "files": sorted(files)})
                    if rel not in files:
                        return self._send(404, {"detail": "no file"})
                    self.send_response(200)
                    self.send_header("Content-Type", "text/markdown; charset=utf-8")
                    self.send_header("Content-Length", str(len(files[rel])))
                    self.end_headers()
                    return self.wfile.write(files[rel])
                if self.path == "/health":
                    return self._send(200, {"ok": True, "model": "qwen"})
                tid = self.path.rsplit("/", 1)[-1]
                if tid not in outer.tasks:
                    return self._send(404, {"detail": "no such task"})
                self._send(200, outer.tasks[tid])

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture()
def qwen(tmp_path, monkeypatch):
    from ns_api import app as app_mod
    fake = FakeMailbox()
    monkeypatch.setattr(QM, "MAILBOX_URL", fake.url)
    monkeypatch.setattr(QM, "INDEX", tmp_path / "qwen_tasks.jsonl")
    yield TestClient(app_mod.app), fake
    fake.close()


TEXT = "  请按 G3 重写 ep01-S2 的 img 提示词。\n原文：她（低声）……  "   # 带首尾空白：必须原样转发


def test_qwen_task_roundtrip_verbatim(qwen):
    c, fake = qwen
    meta = {"project": "weita", "episode": 1, "shot": "ep01-S2", "kind": "script"}
    r = c.post("/api/qwen/tasks", json={"text": TEXT, "meta": meta})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert fake.posts == [{"from": "canvas", "text": TEXT, "meta": meta}]       # 不读不改
    assert r.json()["status"] == "queued"

    out = "**img**: 她低头……\n（原样，不做任何处理）  "
    fake.tasks[tid].update(status="done", result={"output": out, "extra": [1, 2]}, finished_at="2026-10-30T00:01:00Z")
    g = c.get(f"/api/qwen/tasks/{tid}").json()
    assert g["status"] == "done" and g["output"] == out and g["result"]["extra"] == [1, 2]
    assert g["reachable"] is True and g["meta"] == meta and g["text"] == TEXT

    lst = c.get("/api/qwen/tasks", params={"shot": "ep01-S2"}).json()
    assert [t["id"] for t in lst["tasks"]] == [tid] and lst["tasks"][0]["output"] == out
    assert c.get("/api/qwen/tasks", params={"shot": "ep01-S9"}).json()["tasks"] == []
    # 索引是只追加 jsonl，最后一行 = 最新快照
    lines = QM.index_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[-1])["output"] == out


def test_qwen_list_refreshes_pending(qwen):
    c, fake = qwen
    tid = c.post("/api/qwen/tasks", json={"text": "x", "meta": {"shot": "ep01-S1", "kind": "other"}}).json()["id"]
    fake.tasks[tid].update(status="failed", error="oom")
    t = c.get("/api/qwen/tasks", params={"shot": "ep01-S1", "kind": "other"}).json()["tasks"][0]
    assert t["status"] == "failed" and t["error"] == "oom"
    assert c.get("/api/qwen/tasks/nope").status_code == 404
    assert c.get("/api/qwen/health").json()["reachable"] is True


def test_qwen_tunnel_down(qwen, monkeypatch):
    c, fake = qwen
    tid = c.post("/api/qwen/tasks", json={"text": "x", "meta": {"shot": "ep01-S1", "kind": "other"}}).json()["id"]
    fake.close()
    r = c.post("/api/qwen/tasks", json={"text": "y", "meta": {"kind": "other"}})
    assert r.status_code == 502 and "18099" in r.json()["detail"]
    g = c.get(f"/api/qwen/tasks/{tid}").json()                     # 本地记录 + 不可达提示
    assert g["reachable"] is False and g["status"] == "queued" and "隧道" in g["hint"]
    lst = c.get("/api/qwen/tasks", params={"shot": "ep01-S1"}).json()
    assert lst["reachable"] is False and len(lst["tasks"]) == 1
    h = c.get("/api/qwen/health").json()
    assert h["reachable"] is False and "隧道" in h["hint"]
    assert c.post("/api/qwen/tasks", json={"text": "  ", "meta": {"kind": "other"}}).status_code == 400


def test_qwen_kind_required(qwen):
    c, fake = qwen
    assert c.post("/api/qwen/tasks", json={"text": "x", "meta": {}}).status_code == 400
    assert c.post("/api/qwen/tasks", json={"text": "x", "meta": {"kind": "g3"}}).status_code == 400
    assert c.post("/api/qwen/tasks", json={"text": "x", "meta": {"kind": "image_request"}}).status_code == 501
    for k in ("script", "lora", "blender", "crawl", "other"):
        assert c.post("/api/qwen/tasks", json={"text": "x", "meta": {"kind": k}}).status_code == 201
    assert len(fake.posts) == 5


def test_qwen_files_proxy(qwen):
    c, fake = qwen
    tid = c.post("/api/qwen/tasks", json={"text": "x", "meta": {"kind": "blender"}}).json()["id"]
    raw = "## ep1《雾》\n原样字节\r\n".encode("utf-8")
    fake.files[tid] = {"script.md": raw, "result.json": b'{"status":"done"}'}
    assert c.get(f"/api/qwen/tasks/{tid}/files").json() == {"task_id": tid, "files": ["result.json", "script.md"]}
    r = c.get(f"/api/qwen/tasks/{tid}/files/script.md")
    assert r.status_code == 200 and r.content == raw and r.headers["content-type"].startswith("text/markdown")
    assert c.get(f"/api/qwen/tasks/{tid}/files/nope.md").status_code == 404


# ---------------------------------------------------------------- kind=script：取回 → 校验 → 返修 / 确认导入

FIX_SCRIPT = Path(__file__).parent / "fixtures" / "t42" / "雾港来信（剧本和镜头）.md"


@pytest.fixture()
def qproj(qwen, tmp_path, monkeypatch):
    from ns_api import project_ctx as PC
    monkeypatch.setenv("NS_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("NS_ORCH_BACKGROUND", "0")
    ctx = PC.create_project("雾港来信", "wugang")
    c, fake = qwen
    tid = c.post("/api/qwen/tasks", json={"text": "写剧本", "meta": {"kind": "script", "project": "wugang"}}).json()["id"]
    fake.files[tid] = {"script.md": FIX_SCRIPT.read_bytes()}
    return c, fake, ctx, tid


def test_script_fetch_validate_repair(qproj):
    c, fake, ctx, tid = qproj
    assert c.post(f"/api/qwen/tasks/{tid}/script/repair").status_code == 409        # 还没取回
    r = c.post(f"/api/qwen/tasks/{tid}/script/fetch").json()
    assert (ctx.root / r["path"]).read_bytes() == FIX_SCRIPT.read_bytes()            # 原样落盘
    v = r["validation"]
    assert v["ok"] is False and v["blocking"] > 0 and v["repair_text"]              # 夹具剧本是 v2 格式，校验不过
    assert c.post(f"/api/qwen/tasks/{tid}/script/import", json={"confirm": True, "by": "owner"}).status_code == 409
    n = c.post(f"/api/qwen/tasks/{tid}/script/repair")
    assert n.status_code == 201
    assert fake.posts[-1] == {"from": "canvas", "text": v["repair_text"],
                              "meta": {"kind": "script", "project": "wugang", "parent": tid}}
    assert c.get(f"/api/qwen/tasks/{tid}", params={}).json()["repair_task"] == n.json()["id"]


def test_script_import_needs_owner_confirm(qproj, monkeypatch):
    c, fake, ctx, tid = qproj
    ok = {"ok": True, "exit_code": 0, "blocking": 0, "warnings": 0, "episodes_found": 2, "repair_text": "",
          "report": None, "stderr": ""}
    monkeypatch.setattr(QM, "run_validator", lambda path, ctx: dict(ok))
    assert c.post(f"/api/qwen/tasks/{tid}/script/import", json={"confirm": True, "by": "owner"}).status_code == 409   # 未取回
    c.post(f"/api/qwen/tasks/{tid}/script/fetch")
    assert c.post(f"/api/qwen/tasks/{tid}/script/import", json={}).status_code == 403
    assert not ctx.script_json.exists()
    r = c.post(f"/api/qwen/tasks/{tid}/script/import", json={"confirm": True, "by": "owner"})
    assert r.status_code == 200, r.text
    data = json.loads(ctx.script_json.read_text(encoding="utf-8"))
    assert len(data["episodes"]) >= 1
    assert ctx.settings()["script_files"]["script"] == f"data/qwen/{tid}/script.md"
    # 文件被改过 → 拒绝导入
    (ctx.root / "data" / "qwen" / tid / "script.md").write_text("changed", encoding="utf-8")
    assert c.post(f"/api/qwen/tasks/{tid}/script/import", json={"confirm": True, "by": "owner"}).status_code == 409


def test_script_import_refuses_default_project(qwen, monkeypatch):
    c, fake = qwen
    tid = c.post("/api/qwen/tasks", json={"text": "x", "meta": {"kind": "script", "project": "weita"}}).json()["id"]
    fake.files[tid] = {"script.md": b"## ep1\n"}
    monkeypatch.setattr(QM, "run_validator", lambda path, ctx: {"ok": True, "repair_text": ""})
    monkeypatch.setattr(QM, "_ctx_for", lambda rec, project: type("C", (), {
        "is_default": True, "slug": "weita", "root": Path("."), "data_dir": Path(".") / "_nope",
        "rel": staticmethod(lambda p: "x")})())
    QM._append({**QM.load_index()[tid], "script": {"project": "weita", "path": "x", "sha256": "0"}})
    assert c.post(f"/api/qwen/tasks/{tid}/script/import", json={"confirm": True, "by": "owner"}).status_code == 409


# ---------------------------------------------------------------- T21 gpu3_takes

def test_gpu3_takes_mirrored_and_bridge(env):
    c, data, _ = env
    gpu3_shot(data, "ep01-S1", video=True, mirror_image=False)
    t = RD.gpu3_takes("ep01-S1", "weita")
    img = next(x for x in t["takes"] if x["stage"] == "image")
    vid = next(x for x in t["takes"] if x["stage"] == "video")
    assert img["url"] == "/api/gpu3-media/renders_gpu3/ep01/S1/takes/image_001.png"   # 镜像没有 → 经桥
    assert vid["url"].startswith("/files/renders_gpu3/ep01/S1/takes/video_001.mp4?v=")  # 镜像有 → /files
    assert vid["last_url"].startswith("/files/renders_gpu3/ep01/S1/takes/video_001_last.png")
    assert all(x["source"] == "gpu3" for x in t["takes"]) and t["active"] == {"image": 1, "video": 1}
    d = c.get("/api/shots/ep01-S1").json()
    assert [x["n"] for x in d["gpu3_takes"]["takes"]] == [1, 1]
    assert RD.gpu3_takes("ep01-S2", "weita") == {"takes": [], "active": {}}


# ---------------------------------------------------------------- T22 时长 + 对白舞台提示

def test_summary_has_duration_and_dialogue_stage(env):
    c, _, _ = env
    s = ep1(c)["shots"][0]
    assert s["duration"] == {"seconds": 8, "source": "script"}
    for d in s["dialogue"]:
        assert set(d) >= {"speaker_note", "text", "stage"}


# ---------------------------------------------------------------- 桥只读快速失败

def test_media_proxy_fails_fast_when_bridge_down(env, monkeypatch):
    c, _, _ = env
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(RD.urllib.request, "urlopen", boom)
    monkeypatch.setattr(RD, "_bridge_down_until", 0.0)
    assert c.get("/api/gpu3-media/renders_gpu3/ep01/S7/x.png").status_code == 502
    assert c.get("/api/gpu3-media/renders_gpu3/ep01/S8/x.png").status_code == 502
    assert len(calls) == 1 and RD.bridge_down()                  # 第二次没再连
    RD.mark_bridge(True)


# ---------------------------------------------------------------- T44 ComfyUI 锁

def test_comfy_lock_mutex(tmp_path, monkeypatch):
    from ns_orch import comfy_lock as CL
    monkeypatch.setattr(CL, "LOCK_PATH", tmp_path / "comfy.lock")
    assert CL.is_free() and CL.holder() is None
    fh = CL.acquire("orchestrator", "demo ep01 image", timeout=0)
    try:
        assert not CL.is_free() and CL.holder()["who"] == "orchestrator"
        with pytest.raises(CL.Busy) as ei:
            CL.acquire("canvas", "x", timeout=0)
        assert "orchestrator" in str(ei.value)
        seen = []
        threading.Timer(0.3, lambda: CL.release(fh)).start()
        with CL.hold("canvas", "ep01-S1 image", timeout=5, poll=0.05, on_wait=seen.append):
            assert CL.holder()["who"] == "canvas"
        assert seen and seen[0]["who"] == "orchestrator"
    finally:
        try:
            CL.release(fh)
        except Exception:  # noqa: BLE001
            pass
    assert CL.is_free()


def test_orchestrator_waits_when_canvas_holds(tmp_path, monkeypatch):
    from ns_orch import comfy_lock as CL
    from ns_orch import executors as EX
    monkeypatch.setattr(CL, "LOCK_PATH", tmp_path / "comfy.lock")
    monkeypatch.setattr(EX, "comfy_status", lambda url: {"reachable": True})

    class Ctx:
        slug, is_default = "demo", False
    with CL.hold("canvas", "ep01-S1 image"):
        with pytest.raises(EX.Waiting, match="canvas"):
            EX.RealExecutor().render_frames(Ctx(), 1, "image")
    ran = []
    monkeypatch.setattr(EX.RealExecutor, "_run", lambda self, ctx, args, name: ran.append(CL.holder()) or {})
    EX.RealExecutor().render_frames(Ctx(), 1, "image")
    assert ran[0]["who"] == "orchestrator" and CL.is_free()


def test_comfy_lock_endpoint(qwen, tmp_path, monkeypatch):
    from ns_orch import comfy_lock as CL
    monkeypatch.setattr(CL, "LOCK_PATH", tmp_path / "comfy.lock")
    c, _ = qwen
    assert c.get("/api/comfy-lock").json()["free"] is True
    with CL.hold("orchestrator", "demo ep02 last"):
        j = c.get("/api/comfy-lock").json()
        assert j["free"] is False and j["holder"]["what"] == "demo ep02 last"


# ---------------------------------------------------------------- 「请 gpu3 重出」请求进度 + request_id

def _jl(p, rows):
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def test_gpu3_requests_from_mirror(env, monkeypatch):
    from ns_api import gpu3_requests as GR
    c, data, _ = env
    monkeypatch.setattr(GR, "from_bridge", lambda limit=500: (_ for _ in ()).throw(urllib.error.URLError("down")))
    g3 = data / "renders_gpu3"
    _jl(g3 / "rerender_queue.jsonl", [
        {"id": "a", "op": "render", "shot": "ep1-S1", "stage": "both", "at": "2026-10-30T01:00:00Z"},
        {"id": "b", "op": "render", "shot": "ep01-S2", "stage": "image", "at": "2026-10-30T02:00:00Z"},
        {"id": "c", "op": "render", "shot": "ep01-S1", "stage": "video", "at": "2026-10-30T03:00:00Z"},
        {"id": "z", "op": "render", "project": "other", "shot": "ep01-S1", "stage": "video", "at": "2026-10-30T04:00:00Z"},
        {"op": "cancel", "target_id": "c", "at": "2026-10-30T03:01:00Z"}])
    _jl(g3 / "rerender_events.jsonl", [
        {"id": "a", "state": "started", "at": "2026-10-30T01:01:00Z"},
        {"id": "a", "state": "image_done", "take": {"stage": "image", "n": 4}, "at": "2026-10-30T01:05:00Z"},
        {"id": "b", "state": "failed", "error": "CUDA OOM", "at": "2026-10-30T02:03:00Z"}])
    r = c.get("/api/gpu3/requests", params={"shots": "ep01-S1"}).json()
    assert [(x["id"], x["state"]) for x in r] == [("c", "cancelled"), ("a", "image_done")]
    assert r[1]["takes"] == [{"stage": "image", "n": 4}] and r[0]["source"] == "mirror"
    r2 = c.get("/api/gpu3/requests", params={"shots": "ep01-S1,ep01-S2"}).json()
    b = next(x for x in r2 if x["id"] == "b")
    assert b["state"] == "failed" and b["error"] == "CUDA OOM"


def test_gpu3_requests_from_bridge(env, monkeypatch):
    from ns_api import gpu3_requests as GR

    class R:
        def __init__(self, b):
            self.b = b

        def read(self):
            return self.b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    items = [{"id": "x", "shot": "ep01-S3", "stage": "both", "state": "rendering", "requested_at": "t1",
              "updated_at": "t2", "error": None, "takes": [{"stage": "image", "n": 2}]},
             {"id": "y", "shot": "ep01-S3", "stage": "video", "state": "queued", "requested_at": "t0",
              "updated_at": "t0", "error": None, "takes": []}]
    seen = {}

    def fake(url, timeout):
        seen["timeout"] = timeout
        return R(json.dumps(items).encode())
    monkeypatch.setattr(GR.urllib.request, "urlopen", fake)
    monkeypatch.setattr(RD, "_bridge_down_until", 0.0)
    c, _, _ = env
    r = c.get("/api/gpu3/requests", params={"shots": "ep01-S3"}).json()
    assert [(x["id"], x["state"], x["source"]) for x in r] == [("x", "image_done", "bridge"), ("y", "queued", "bridge")]
    assert seen["timeout"] <= 5


def test_gpu3_rerender_returns_request_id(env, monkeypatch):
    c, _, _ = env
    monkeypatch.setattr(RD, "post_rerender", lambda req: {"requests": [{"id": "rq1"}], "errors": []})
    j = c.post("/api/shots/ep01-S2/gpu3-rerender", json={"stage": "image"}).json()
    assert j["request_id"] == "rq1" and j["request"]["id"] == "rq1"
