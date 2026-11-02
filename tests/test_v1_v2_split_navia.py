"""NAVIA：V1 / V2 分开显示——V2 页面不给 V1 的文件；V1 只在只读视频库里。
判断依据 = 被发放的 data 根旁边的 config/pipeline/runs.json（和 run_paths._ctx 同一个口径）。
测试用临时 data 根 + 自己的 runs.json + 两种布局的真实文件，用 TestClient 真打 /files，让中间件这条路真跑起来（不 patch 成 True）。"""
import json

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from ns_api import v1_guard as G
from ns_api import v1_library as L
from ns_api import video_index as VI
from ns_render import pipeline as P

MSG = "这部剧里没有这个文件"
V1_PNG = "renders/ep01/S1/takes/image_001.png"                    # V1 legacy 布局（不带剧前缀）
V2_PNG = "renders/series10_v2/ep01/S1/takes/image_001.png"
V1_GPU3 = "cache/gpu3_media/renders_gpu3/ep01/S1/takes/image_001.png"   # 本地 gpu3 缓存里的 V1 首帧
V2_GPU3 = "renders_gpu3/series10_v2/ep01/S1/takes/image_001.png"
V1_GPU3_DIRECT = "renders_gpu3/ep01/S1/takes/image_001.png"


def _sandbox(tmp_path, primary):
    """tmp/config/pipeline/runs.json（primary 可选；None = 不写 runs.json）+ tmp/data 下两种布局的文件"""
    data = tmp_path / "data"
    for rel in (V1_PNG, V2_PNG, V1_GPU3, V2_GPU3, V1_GPU3_DIRECT):
        f = data / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"\x89PNG-fake")
    if primary:
        c = tmp_path / "config" / "pipeline"
        c.mkdir(parents=True)
        (c / "runs.json").write_text(json.dumps({"primary": primary, "legacy_unprefixed_run": "series10_v1", "runs": {}}), encoding="utf-8")
    return data


def _client(monkeypatch, data):
    """自己的 app：同一个中间件函数 + /files 静态目录指向临时 data 根；P.DATA 指过去（中间件按 P.DATA 找 runs.json）"""
    from ns_api import app as A
    monkeypatch.setattr(P, "DATA", data)
    app = FastAPI()
    app.middleware("http")(A._v1_v2_split)
    app.mount("/files", StaticFiles(directory=data), name="files")
    return TestClient(app)


# ---------------------------------------------------------------- 中间件真跑（TestClient 真打 /files）
def test_v2_primary_blocks_v1_layouts_and_serves_v2(tmp_path, monkeypatch):
    c = _client(monkeypatch, _sandbox(tmp_path, "series10_v2"))
    for rel in (V1_PNG, V1_GPU3, V1_GPU3_DIRECT):
        r = c.get("/files/" + rel)
        assert r.status_code == 404 and MSG in r.text, rel
    for rel in (V2_PNG, V2_GPU3):
        assert c.get("/files/" + rel).status_code == 200, rel


def test_v2_primary_blocks_case_encoding_backslash_dotdot_variants(tmp_path, monkeypatch):
    """OVERSIGHT-F 第 7 轮：NTFS 不分大小写，/files/Renders/ep01/… 不能放行；编码、反斜杠、../ 同理"""
    c = _client(monkeypatch, _sandbox(tmp_path, "series10_v2"))
    bad = [
        "/files/Renders/ep01/S1/takes/image_001.png", "/files/RENDERS/ep01/S1/takes/image_001.png", "/files/rEnDeRs/EP01/S1/takes/image_001.png",
        "/files/renders%2Fep01%2FS1%2Ftakes%2Fimage_001.png", "/files/renders%252Fep01/S1/takes/image_001.png",
        "/files/%52enders/ep01/S1/takes/image_001.png",
        "/files/renders%5Cep01%5CS1%5Ctakes%5Cimage_001.png",
        "/files/renders//ep01/S1/takes/image_001.png", "/files//renders/ep01/S1/takes/image_001.png",
        "/files/renders/./ep01/S1/takes/image_001.png",
        "/files/renders/series10_v2/../ep01/S1/takes/image_001.png",
        "/files/Cache/GPU3_Media/Renders_GPU3/ep01/S1/takes/image_001.png",
    ]
    for p in bad:
        r = c.get(p)
        assert r.status_code == 404 and MSG in r.text, p
    assert c.get("/files/Renders/Series10_V2/ep01/S1/takes/image_001.png").status_code == 200    # 当前剧目录大小写不同仍放行


def test_legacy_primary_serves_v1_layout(tmp_path, monkeypatch):
    c = _client(monkeypatch, _sandbox(tmp_path, "series10_v1"))
    assert c.get("/files/" + V1_PNG).status_code == 200
    assert c.get("/files/" + V1_GPU3).status_code == 200


def test_sandbox_without_runs_json_is_not_blocked(tmp_path, monkeypatch):
    """沙箱 / 临时目录：旁边没有 runs.json 就不拦（NS_PROJECT_ROOT 之类也一样，只看被发放的 data 根旁边）"""
    c = _client(monkeypatch, _sandbox(tmp_path, None))
    assert c.get("/files/" + V1_PNG).status_code == 200


def test_broken_runs_json_is_fail_closed(tmp_path, monkeypatch):
    data = _sandbox(tmp_path, "series10_v2")
    (tmp_path / "config" / "pipeline" / "runs.json").write_text("{坏的", encoding="utf-8")
    c = _client(monkeypatch, data)
    r = c.get("/files/" + V1_PNG)
    assert r.status_code == 404 and MSG in r.text


def test_repo_data_without_runs_json_is_fail_closed(tmp_path, monkeypatch):
    """仓库自己的 data 下读不到 runs.json → 拒绝（不是放行）"""
    monkeypatch.setattr(G, "_runs_file", lambda d=None: tmp_path / "nope" / "runs.json")
    assert G.deny("/files/" + V1_PNG, "", G.ROOT / "data")


def test_cache_follows_each_data_root(tmp_path):
    """缓存键按 data 根：先后给两个不同 data 根发放，各用各的 runs.json"""
    da = _sandbox(tmp_path / "a", "series10_v2")
    db = _sandbox(tmp_path / "b", "series10_v1")
    assert G.deny("/files/" + V1_PNG, "", da) is True
    assert G.deny("/files/" + V1_PNG, "", db) is False
    assert G.deny("/files/" + V1_PNG, "", da) is True


# ---------------------------------------------------------------- 真实 app：gpu3-media 路由自己的检查在前（400）
def test_app_gpu3_media_proxy_and_cache_exits(tmp_path, monkeypatch):
    """P1-9a：gpu3-media 代理，V1 legacy 布局必须拒；路径穿越 / 不在 renders_gpu3 下仍是路由自己的 400"""
    from ns_api import app as A
    data = _sandbox(tmp_path, "series10_v2")
    monkeypatch.setattr(P, "DATA", data)
    c = TestClient(A.app)
    r = c.get("/api/gpu3-media/renders_gpu3/ep01/S1/takes/image_001.png")
    assert r.status_code == 404 and MSG in r.text
    assert c.get("/api/gpu3-media/Renders_GPU3/ep01/S1/takes/image_001.png").status_code == 400   # 大小写变体：路由自己的检查先拒（不是 renders_gpu3/ 开头）
    assert c.get("/api/gpu3-media/renders/ep01/S1/x.png").status_code == 400            # 路由自己的检查在前
    assert c.get("/api/gpu3-media/renders_gpu3/%2e%2e/%2e%2e/config/x").status_code == 400
    assert c.get("/api/gpu3-media/" + V2_GPU3).status_code == 200                        # 当前剧的路径：不被拦


def test_app_v1_files_only_serves_videos(tmp_path, monkeypatch):
    from ns_api import app as A
    monkeypatch.setattr(P, "DATA", _sandbox(tmp_path, "series10_v2"))
    c = TestClient(A.app)
    assert c.get("/v1-files/renders/ep01/S1/takes/image_001.png").status_code == 404
    assert c.get("/v1-files/config/pipeline/runs.json").status_code == 404


# ---------------------------------------------------------------- 纯函数
def test_scoped_follows_data_root(tmp_path):
    d2 = _sandbox(tmp_path / "x", "series10_v2")
    d1 = _sandbox(tmp_path / "y", "series10_v1")
    assert G.scoped(V1_PNG, data_dir=d2) is None
    assert G.scoped("data/" + V1_PNG, data_dir=d2) is None
    assert G.scoped(V2_PNG, data_dir=d2) == V2_PNG
    assert G.scoped(V1_PNG, data_dir=d1) == V1_PNG
    assert G.scoped(None, data_dir=d2) is None


def test_video_index_url_blocks_v1(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DATA", _sandbox(tmp_path, "series10_v2"))
    assert VI._url("renders/ep01/S1/takes/video_001.mp4") is None
    assert VI._url("renders/series10_v2/ep01/S1/takes/video_001.mp4") == "/files/renders/series10_v2/ep01/S1/takes/video_001.mp4"


def test_v1_library_lists_only_existing_videos(tmp_path, monkeypatch):
    data = tmp_path / "data"
    r = data / "renders"
    d = r / "ep01" / "S1"
    (d / "takes").mkdir(parents=True)
    (data / "renders" / "ep01" / "S1" / "takes" / "video_001.mp4").write_bytes(b"x")
    (d / "takes.json").write_text(json.dumps({"active": {"video": 1}, "takes": [{"stage": "video", "n": 1, "file": "renders/ep01/S1/takes/video_001.mp4"}]}), encoding="utf-8")
    d2 = r / "ep01" / "S2"
    d2.mkdir(parents=True)
    (d2 / "takes.json").write_text(json.dumps({"active": {"video": 1}, "takes": [{"stage": "video", "n": 1, "file": "renders/ep01/S2/takes/gone.mp4"}]}), encoding="utf-8")
    monkeypatch.setattr(G, "ROOT", tmp_path)
    monkeypatch.setattr(G, "_runs", lambda *a: {"primary": "series10_v2", "legacy_unprefixed_run": "series10_v1", "runs": {"series10_v1": {"frozen_at": "t"}}})
    out = L.build(renders=r)
    assert out["readonly"] is True and out["run"] == "series10_v1" and out["total"] == 1
    assert out["episodes"][0]["shots"][0]["id"] == "ep01-S1" and out["episodes"][0]["shots"][0]["video_url"].startswith("/v1-files/renders/ep01/")
