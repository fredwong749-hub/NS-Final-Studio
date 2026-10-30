"""封板修复（docs/release/debug_api.md）：API 各模块的边界 / 错误路径。全部临时目录 + monkeypatch，不碰生产数据、
不发 gpu3 / Qwen 真实写请求。"""
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ns_api import app as app_mod
from ns_api import episodes_fast as EF
from ns_api import qwen_mailbox as QM
from ns_api import readiness as RD
from ns_api import script_ab as SAB
from ns_api import script_inbox as SI
from ns_render import pipeline as P

REPO = Path(__file__).resolve().parents[1]
c = TestClient(app_mod.app)


# ---------------------------------------------------------------- /api/gpu3-media 路径穿越

@pytest.mark.parametrize("rel", ["renders_gpu3/..%5C..%5Cconfig%5Cscript_mainline.json",
                                 "renders_gpu3/ep01/..%5C..%5C..%5Cconfig%5Cx.json",
                                 "renders_gpu3/C:%5Cwindows%5Cwin.ini", "other/x.png"])
def test_gpu3_media_rejects_traversal(rel, monkeypatch):
    monkeypatch.setattr(RD, "fetch_media", lambda *a, **k: pytest.fail("不该请求桥"))
    assert c.get(f"/api/gpu3-media/{rel}").status_code == 400


def test_gpu3_media_serves_local_mirror(tmp_path, monkeypatch):
    f = tmp_path / "renders_gpu3" / "ep01" / "S1" / "frame.png"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"png")
    monkeypatch.setattr(P, "DATA", tmp_path)
    r = c.get("/api/gpu3-media/renders_gpu3/ep01/S1/frame.png")
    assert r.status_code == 200 and r.content == b"png"


# ---------------------------------------------------------------- 剧本导入收件箱：导入 / 回滚 / 边界

@pytest.fixture()
def inbox(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "import").mkdir(parents=True)
    (data / "staging_input").mkdir()
    cand = data / "staging_input" / "稿 v3.md"
    cand.write_bytes("## ep01\n".encode())
    imp = data / "import" / "script_v2.json"
    imp.write_text('{"old": true}', encoding="utf-8")
    for k, v in {"REPO": tmp_path, "DATA": data, "IMPORT_JSON": imp, "LOG": data / "import" / "import_log.jsonl",
                 "CACHE": data / "import" / "script_inbox_cache.json",
                 "MAINLINE_CFG": tmp_path / "config" / "script_mainline.json"}.items():
        monkeypatch.setattr(SI, k, v)
    st = {"validator": {"blocking": 0, "warnings": 1, "episodes_found": 1, "counts": {"r": 1}}, "import_rc": 0,
          "calls": []}

    def fake_run(cmd, **kw):
        st["calls"].append([str(x) for x in cmd])
        if "validate_qwen_script.py" in str(cmd[1]):
            v = st["validator"]
            return SimpleNamespace(returncode=0 if v else 1, stdout=json.dumps(v).encode() if v else b"",
                                   stderr=b"" if v else b"Traceback: boom")
        if st["import_rc"] == 0:
            imp.write_text('{"new": true}', encoding="utf-8")
        else:
            imp.write_text("half-written", encoding="utf-8")
        return SimpleNamespace(returncode=st["import_rc"], stdout="导入完成".encode(), stderr=b"err")
    monkeypatch.setattr(SI.subprocess, "run", fake_run)
    st.update(cand=cand, imp=imp, rel="data/staging_input/稿 v3.md")
    return st


def _body(st, **kw):
    return {"path": st["rel"], "sha256": SI._sha(st["cand"]), "by": "owner", "confirm": True, **kw}


def test_import_merge_default_backup_and_log(inbox):
    r = c.post("/api/script-inbox/import", json=_body(inbox))
    assert r.status_code == 200, r.text
    assert inbox["imp"].read_text(encoding="utf-8") == '{"new": true}'
    backup = SI.REPO / r.json()["backup"]
    assert backup.read_text(encoding="utf-8") == '{"old": true}'
    cmd = inbox["calls"][-1]
    assert cmd[cmd.index("--merge-base") + 1] == str(backup)            # 默认以导入前的剧本为底合并
    row = json.loads(SI.LOG.read_text(encoding="utf-8").splitlines()[-1])
    assert row["mode"] == "merge" and row["rc"] == 0 and row["by"] == "owner"
    assert c.get("/api/script-inbox").json()["current"]["last_import"]["rc"] == 0


def test_import_failure_rolls_back(inbox):
    inbox["import_rc"] = 1
    r = c.post("/api/script-inbox/import", json=_body(inbox))
    assert r.status_code == 500 and "已恢复原剧本" in r.json()["detail"]
    assert inbox["imp"].read_text(encoding="utf-8") == '{"old": true}'


def test_import_replace_has_no_merge_base_and_bad_mode_rejected(inbox):
    assert c.post("/api/script-inbox/import", json=_body(inbox, mode="replace")).status_code == 200
    assert "--merge-base" not in inbox["calls"][-1]
    n = len(inbox["calls"])
    assert c.post("/api/script-inbox/import", json=_body(inbox, mode="mrege")).status_code == 422
    assert len(inbox["calls"]) == n


def test_import_missing_merge_base_is_422_without_touching_script(inbox):
    r = c.post("/api/script-inbox/import", json=_body(inbox, merge_base="data/import/backups/nope.json"))
    assert r.status_code == 422 and inbox["imp"].read_text(encoding="utf-8") == '{"old": true}'
    assert not (SI.IMPORT_JSON.parent / "backups").exists()


def test_two_imports_same_second_keep_both_backups(inbox, monkeypatch):
    real = time.strftime
    monkeypatch.setattr(SI.time, "strftime", lambda fmt, *a: "20261030-120000" if fmt == "%Y%m%d-%H%M%S"
                        else real(fmt, *a))
    b1 = c.post("/api/script-inbox/import", json=_body(inbox)).json()["backup"]
    b2 = c.post("/api/script-inbox/import", json=_body(inbox)).json()["backup"]
    assert b1 != b2 and (SI.REPO / b1).read_text(encoding="utf-8") == '{"old": true}'


def test_concurrent_import_refused(inbox):
    assert SI._import_lock.acquire(blocking=False)
    try:
        r = c.post("/api/script-inbox/import", json=_body(inbox))
        assert r.status_code == 409 and "正在进行" in r.json()["detail"]
    finally:
        SI._import_lock.release()


def test_validator_crash_not_cached(inbox):
    inbox["validator"] = None
    v = c.post("/api/script-inbox/validate", json={"path": inbox["rel"]}).json()
    assert v["ok"] is False and "boom" in v["error"]
    assert not SI.CACHE.exists() or SI._sha(inbox["cand"]) not in json.loads(SI.CACHE.read_text(encoding="utf-8"))
    r = c.post("/api/script-inbox/import", json=_body(inbox))
    assert r.status_code == 409 and "没跑成" in r.json()["detail"]
    inbox["validator"] = {"blocking": 0, "warnings": 0, "episodes_found": 1, "counts": {}}
    assert c.post("/api/script-inbox/validate", json={"path": inbox["rel"]}).json()["ok"] is True   # 重新校验能恢复


def test_corrupt_import_log_line_does_not_break_list(inbox):
    SI.LOG.write_text('{"rc": 0, "at": "x"}\n{"rc": 1, "at\n', encoding="utf-8")
    r = c.get("/api/script-inbox")
    assert r.status_code == 200 and r.json()["current"]["last_import"]["rc"] == 0


def test_download_traversal_and_noncandidate(inbox):
    assert c.get("/api/script-inbox/download", params={"path": "../x.md"}).status_code == 404
    assert c.get("/api/script-inbox/download", params={"path": "data/import/script_v2.json"}).status_code == 404
    r = c.get("/api/script-inbox/download", params={"path": inbox["rel"]})
    assert r.status_code == 200 and r.content == "## ep01\n".encode()


# ---------------------------------------------------------------- 剧本 A/B 选择记录

def test_ab_choices_skip_corrupt_lines(tmp_path, monkeypatch):
    f = tmp_path / "ab.jsonl"
    f.write_text('{"ep": 1, "pick": "A"}\n{"ep": 2, "pi\n[1]\n{"ep": 2, "pick": "B"}\n', encoding="utf-8")
    monkeypatch.setattr(SAB, "CHOICES", f)
    assert [r["pick"] for r in c.get("/api/script-ab/choices").json()] == ["A", "B"]
    assert [r["pick"] for r in c.get("/api/script-ab/choices", params={"ep": 2}).json()] == ["B"]


# ---------------------------------------------------------------- 按集渲染：桥返回非对象 JSON 错误

def test_owner_run_bridge_error_non_object_detail(monkeypatch):
    import io
    import urllib.error

    from ns_api import owner_run as OR
    monkeypatch.setattr(OR, "_require_episode", lambda ep: None)

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 409, "x", {}, io.BytesIO(b'["busy"]'))
    monkeypatch.setattr(OR, "_post", boom)
    r = c.post("/api/gpu3/episodes/2/run", json={"gpu": 3, "steps": ["frames"], "note": "x", "by": "owner"})
    assert r.status_code == 409 and "busy" in r.json()["detail"]


# ---------------------------------------------------------------- gpu3 takes / 链：格式坏的 takes.json

@pytest.mark.parametrize("body", ['[]', '"x"', '{"takes": null, "active": null}', '{"takes": [1, null], "active": []}'])
def test_gpu3_takes_and_chain_tolerate_malformed(body, tmp_path, monkeypatch):
    d = tmp_path / "ep01" / "S1"
    d.mkdir(parents=True)
    (d / "takes.json").write_text(body, encoding="utf-8")
    monkeypatch.setattr(RD, "gpu3_root", lambda slug: tmp_path)
    assert RD.gpu3_takes("ep01-S1", "x") == {"takes": [], "active": {}}
    ch = RD.gpu3_chain("ep01-S1", "x")
    assert ch["image_take"] is None and ch["takes_count"] == {"image": 0, "video": 0}


# ---------------------------------------------------------------- Qwen 信箱任务列表：并行刷新 + 节流

def test_qwen_list_refreshes_in_parallel_and_throttles(tmp_path, monkeypatch):
    idx = tmp_path / "q.jsonl"
    idx.write_text("".join(json.dumps({"id": f"t{i}", "meta": {"kind": "other"}, "status": "running",
                                       "created_at": f"2026-10-30T00:00:0{i}Z"}) + "\n" for i in range(6)),
                   encoding="utf-8")
    monkeypatch.setattr(QM, "INDEX", idx)
    monkeypatch.setattr(QM, "_refreshed_at", {})
    calls = []

    def fake_call(method, path, body=None, timeout=5.0):
        calls.append(path)
        time.sleep(0.3)
        return {"status": "done" if path.endswith("t0") else "running"}
    monkeypatch.setattr(QM, "_call", fake_call)
    t = time.perf_counter()
    r = c.get("/api/qwen/tasks").json()
    assert time.perf_counter() - t < 1.2                     # 6 个并行（串行要 ≥1.8 s）
    assert len(calls) == 6 and r["reachable"] is True
    assert next(x for x in r["tasks"] if x["id"] == "t0")["status"] == "done"
    r2 = c.get("/api/qwen/tasks").json()                     # 5 s 内不再问上游
    assert len(calls) == 6 and r2["reachable"] is True


def test_qwen_list_unreachable(tmp_path, monkeypatch):
    idx = tmp_path / "q.jsonl"
    idx.write_text(json.dumps({"id": "u1", "meta": {}, "status": "queued"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(QM, "INDEX", idx)
    monkeypatch.setattr(QM, "_refreshed_at", {})

    def down(*a, **k):
        raise QM.MailboxError("不可达")
    monkeypatch.setattr(QM, "_call", down)
    r = c.get("/api/qwen/tasks").json()
    assert r["reachable"] is False and "hint" in r and r["tasks"][0]["status"] == "queued"


def test_qwen_files_path_rejects_dotdot():
    with pytest.raises(Exception):
        QM._files_path("t1", "a/../../etc")
    assert QM._files_path("t 1", "a b/c.md") == "/files/t%201/a%20b/c.md"


# ---------------------------------------------------------------- 慢接口缓存（A-2）

def test_keyed_cache_sig_and_stale_while_revalidate():
    kc = EF.KeyedCache(ttl_s=0.05)
    n = []
    f = lambda: n.append(1) or len(n)          # noqa: E731
    assert kc.get("a", 1, f) == 1 and kc.get("a", 1, f) == 1 and len(n) == 1
    assert kc.get("a", 2, f) == 2                              # 签名变了 → 同步重算
    time.sleep(0.08)
    assert kc.get("a", 2, f) == 2                              # 过期 → 先回旧值
    for _ in range(50):
        if len(n) == 3:
            break
        time.sleep(0.02)
    assert kc.get("a", 2, f) == 3


def test_readiness_endpoint_cached_and_invalidated_by_sig(monkeypatch):
    app_mod._slow_cache.clear()
    calls = []
    sig = [1]
    monkeypatch.setattr(app_mod, "_readiness_report", lambda ep: calls.append(ep) or [{"ep": ep}])
    monkeypatch.setattr(app_mod, "_inputs_sig", lambda root=None: tuple(sig))
    assert c.get("/api/readiness", params={"ep": 1}).json() == [{"ep": 1}]
    c.get("/api/readiness", params={"ep": 1})
    assert calls == [1]
    sig[0] = 2                                                 # 剧本 / 状态表变了
    c.get("/api/readiness", params={"ep": 1})
    assert calls == [1, 1]
    app_mod._slow_cache.clear()


# ---------------------------------------------------------------- tools/s2_waiver.py（项目方本人运行；这里只在临时文件上测）

def _waiver_mod():
    spec = importlib.util.spec_from_file_location("s2_waiver_t", REPO / "tools" / "s2_waiver.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_s2_waiver_tool_tolerates_missing_key_and_rejects_bad_episode(tmp_path, monkeypatch):
    from ns_agent import state_timeline as T
    m = _waiver_mod()
    cfg = tmp_path / "s2_waivers.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(m, "CFG", cfg)
    monkeypatch.setattr(T, "write", lambda root: None)
    monkeypatch.setattr(sys, "argv", ["s2_waiver", "--episode", "2", "--revoke"])
    assert m.main() == 0 and json.loads(cfg.read_text(encoding="utf-8")) == {"waivers": []}
    monkeypatch.setattr(sys, "argv", ["s2_waiver", "--episode", "2", "--skip", "plate", "--quote", "原话"])
    assert m.main() == 0
    w = json.loads(cfg.read_text(encoding="utf-8"))["waivers"]
    assert len(w) == 1 and w[0]["by"] == "owner" and w[0]["skip"] == ["plate"]
    assert T.waived(tmp_path.parent, 2, "plate") is None      # 别的根不受影响
    for argv in (["--episode", "0", "--skip", "plate", "--quote", "x"], ["--episode", "2", "--skip", "plate"]):
        monkeypatch.setattr(sys, "argv", ["s2_waiver", *argv])
        with pytest.raises(SystemExit):
            m.main()
    assert len(json.loads(cfg.read_text(encoding="utf-8"))["waivers"]) == 1
