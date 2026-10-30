"""2026-10-30 全站走查（fredw-92 debug agent）回归测试：见 docs/qa_laptop.md QA30-xx。"""
from __future__ import annotations

import json
import urllib.error
from pathlib import Path

from fastapi.testclient import TestClient

from ns_api import qwen_mailbox as QM
from ns_api import readiness as RD
from ns_render import pipeline as P


# ---------------------------------------------------------------- QA30-01 已取消的 Qwen 任务不再每次问上游

def test_qwen_list_skips_cancelled(tmp_path, monkeypatch):
    from ns_api import app as app_mod
    idx = tmp_path / "qwen_tasks.jsonl"
    recs = [{"id": f"t{i}", "meta": {"kind": "script"}, "status": "queued", "created_at": f"2026-10-30T00:0{i}:00Z"}
            for i in range(5)]
    recs += [{"id": f"t{i}", "status": "cancelled", "note": "x"} for i in range(5)]
    idx.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    monkeypatch.setattr(QM, "INDEX", idx)
    calls = []

    def fake_call(method, path, body=None, timeout=QM.TIMEOUT_S):
        calls.append(path)
        raise QM.MailboxError("Qwen 信箱返回 404：gone", 404)
    monkeypatch.setattr(QM, "_call", fake_call)
    out = TestClient(app_mod.app).get("/api/qwen/tasks").json()
    assert len(out["tasks"]) == 5 and all(t["status"] == "cancelled" for t in out["tasks"])
    assert calls == []                                    # 之前：5 个已取消任务各问一次上游（真实环境 ~12 s）


# ---------------------------------------------------------------- QA30-02 gpu3 版本图取过一次就走本地缓存

class _Resp:
    def __init__(self, data: bytes):
        self.data, self.status = data, 200
        self.headers = {"content-type": "image/png", "content-length": str(len(data))}
        self._sent = False

    def read(self, n=-1):
        if self._sent:
            return b""
        self._sent = True
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_gpu3_media_takes_cached(tmp_path, monkeypatch):
    from ns_api import app as app_mod
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(app_mod, "GPU3_MEDIA_CACHE", tmp_path / "cache")
    calls = []

    def fetch(rel, rng, timeout=5.0):
        calls.append(rel)
        if len(calls) > 2:
            raise urllib.error.URLError("bridge slow")
        return _Resp(b"PNGDATA-" + rel.encode())
    monkeypatch.setattr(RD, "fetch_media", fetch)
    c = TestClient(app_mod.app)
    rel = "renders_gpu3/ep01/S1/takes/image_008.png"
    r1 = c.get(f"/api/gpu3-media/{rel}")
    assert r1.status_code == 200 and r1.content == b"PNGDATA-" + rel.encode()
    assert (tmp_path / "cache" / rel).read_bytes() == r1.content
    assert not list((tmp_path / "cache").rglob("*.part"))
    r2 = c.get(f"/api/gpu3-media/{rel}")                  # 第二次不再经桥
    assert r2.status_code == 200 and r2.content == r1.content and calls == [rel]
    # 非 takes/（frame.png / last.png 会被 gpu3 覆盖）不缓存
    c.get("/api/gpu3-media/renders_gpu3/ep01/S1/last.png")
    assert not (tmp_path / "cache" / "renders_gpu3/ep01/S1/last.png").exists()
    # 桥不可达时，已缓存的仍可读；未缓存的照旧 502
    assert c.get(f"/api/gpu3-media/{rel}").status_code == 200
    assert c.get("/api/gpu3-media/renders_gpu3/ep01/S1/takes/image_009.png").status_code == 502
    RD.mark_bridge(True)


# ---------------------------------------------------------------- QA30-03 _rel 缓存不改变结果

def test_rel_cached_matches_resolve(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "renders_gpu3" / "ep01" / "S1").mkdir(parents=True)
    monkeypatch.setattr(P, "DATA", data)
    p = data / "renders_gpu3" / "ep01" / "S1" / "frame.png"
    assert RD._rel(p) == "renders_gpu3/ep01/S1/frame.png"
    assert RD._rel(p) == "renders_gpu3/ep01/S1/frame.png"
    assert RD._rel(tmp_path / "elsewhere.png") is None
    other = tmp_path / "data2"                            # P.DATA 换了 → 用新根
    (other / "x").mkdir(parents=True)
    monkeypatch.setattr(P, "DATA", other)
    assert RD._rel(other / "x" / "a.png") == "x/a.png" and RD._rel(p) is None
