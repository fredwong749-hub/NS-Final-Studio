"""剧本导入收件箱：只有候选文件可校验 / 导入；导入必须项目方确认；sha 不符拒绝（不触发真实导入）"""
from fastapi.testclient import TestClient

from ns_api import script_inbox as SI
from ns_api.app import app

c = TestClient(app)


def test_list_shape():
    r = c.get("/api/script-inbox").json()
    assert "candidates" in r and "current" in r
    for x in r["candidates"]:
        assert {"path", "sha256", "source", "validation"} <= set(x)


def test_non_candidate_rejected():
    assert c.post("/api/script-inbox/validate", json={"path": "docs/REQUIREMENTS.md"}).status_code == 404


def test_download_utf8_filename(monkeypatch, tmp_path):
    p = tmp_path / "为他而骚 v3.1.md"
    p.write_bytes("## ep01\n".encode())
    monkeypatch.setattr(SI, "_allowed", lambda path: p)
    r = c.get("/api/script-inbox/download", params={"path": "x"})
    assert r.status_code == 200 and r.content == "## ep01\n".encode()
    assert "filename*=UTF-8''%E4%B8%BA" in r.headers["content-disposition"]


def test_default_source_version(monkeypatch, tmp_path):
    """封板修复 P1：Qwen script.md（文件名无版本）经画布导入默认 v3；文件名有 vN 的交给导入工具；草稿不猜"""
    monkeypatch.setattr(SI, "REPO", tmp_path)
    for rel, want in (("data/script_chat/abc/script.md", "v3"), ("data/qwen/t1/script.md", "v3"),
                      ("data/staging_v3/为他而骚 v3.1.md", None), ("data/staging_input/草稿.md", None)):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        assert SI.default_source_version(p) == want, rel


def test_import_requires_owner_confirm():
    body = {"path": "x.md", "sha256": "0", "by": "someone", "confirm": True}
    assert c.post("/api/script-inbox/import", json=body).status_code == 403
    body.update(by="owner", confirm=False)
    assert c.post("/api/script-inbox/import", json=body).status_code == 403


def test_import_sha_mismatch(monkeypatch, tmp_path):
    p = tmp_path / "cand.md"
    p.write_text("x", encoding="utf-8")
    monkeypatch.setattr(SI, "_allowed", lambda path: p)
    called = []
    monkeypatch.setattr(SI.subprocess, "run", lambda *a, **k: called.append(a))
    r = c.post("/api/script-inbox/import", json={"path": "cand.md", "sha256": "bad", "by": "owner", "confirm": True})
    assert r.status_code == 409 and not called


def test_script_input_draft_roundtrip(monkeypatch, tmp_path):
    """剧本输入：保存草稿 → 成为导入候选（source=input）→ 删除移到 .trash"""
    from ns_api import script_input as SIN
    monkeypatch.setattr(SI, "REPO", tmp_path)
    monkeypatch.setattr(SI, "DATA", tmp_path / "data")
    d = tmp_path / "data" / "staging_input"
    r = c.post("/api/script-input", json={"name": "测试稿", "text": "## ep01\r\nx\r\n"})
    assert r.status_code == 200 and r.json()["name"] == "测试稿.md"
    assert (d / "测试稿.md").read_bytes() == "## ep01\nx\n".encode()
    assert c.post("/api/script-input", json={"name": "测试稿", "text": "y"}).status_code == 409
    assert any(p.name == "测试稿.md" for p in SI.candidates())
    assert c.delete("/api/script-input/测试稿").json()["ok"]
    assert not (d / "测试稿.md").exists()
    assert SIN.drafts_dir() == d
