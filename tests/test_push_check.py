"""K-OPS-C03 / K-OPS-C04：推送前本地模拟 resident_sync push（tools/qa/push_check.py，CODE-RSI 2026-11-01）。
临时目录当“服务器”，原样调用 resident_sync 的清单计算 + 打包；不连服务器、不写真实 data/。"""
import importlib.util
import io
import json
import os
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


PC = _load("ns_push_check_t", "tools/qa/push_check.py")


def _fake_rs(tmp_path, monkeypatch):
    RS = _load("ns_resident_sync_t", "tools/autopilot/resident_sync.py")
    src = tmp_path / "laptop"
    monkeypatch.setattr(RS, "ROOT", src)
    monkeypatch.setattr(RS, "required_data", lambda: set())
    return RS, src


def _w(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def test_tar_bytes_member_matches_bytes_even_if_stat_is_stale(tmp_path, monkeypatch):
    """K-OPS-C04：stat 之后、读之前文件被截短（别的 loop 正在重写）。旧 tf.add 写坏整包：a.json 变成原文 + 下一个成员的头，
    b.json 丢失。现在按实际读到的字节写成员，包永远自洽。"""
    RS, src = _fake_rs(tmp_path, monkeypatch)
    _w(src / "data/a.json", '{"x": "' + "1" * 1000 + '"}')
    _w(src / "data/b.json", '{"ok": 1}')
    real_stat, real_lstat = os.stat, os.lstat

    def stale(fn):
        def inner(path, *a, **k):
            st = fn(path, *a, **k)
            if str(path).endswith("a.json"):
                return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid, st.st_gid,
                                       st.st_size + 500, int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))
            return st
        return inner
    monkeypatch.setattr(os, "stat", stale(real_stat))
    monkeypatch.setattr(os, "lstat", stale(real_lstat))
    blob = RS.tar_bytes(["data/a.json", "data/b.json", "data/gone.json"])
    monkeypatch.setattr(os, "stat", real_stat)
    monkeypatch.setattr(os, "lstat", real_lstat)
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        got = {m.name: tf.extractfile(m).read() for m in tf.getmembers()}
    assert set(got) == {"data/a.json", "data/b.json"}
    assert got["data/a.json"] == (src / "data/a.json").read_bytes() and json.loads(got["data/b.json"]) == {"ok": 1}


def test_simulated_push_flags_truncation_weights_and_skips_junk(tmp_path, monkeypatch):
    RS, src = _fake_rs(tmp_path, monkeypatch)
    _w(src / "tools/x.py", "print('ok')\n")
    _w(src / "config/a.json", '{"a": 1}')
    _w(src / "tools/__init__.py", "")
    _w(src / "data/renders/ep01/S1/takes.json", '{"takes": [')                 # 截断的 JSON
    _w(src / "data/producer/log.jsonl", '{"a": 1}\n{"b": ')                       # 末行写一半
    _w(src / "tools/m.safetensors", b"\0" * (6 * 1024 * 1024))                    # 模型权重进了代码目录
    _w(src / "data/review_pages/x/index.html", "<html>")                          # resident_sync 本来就跳过
    _w(src / "tools/node_modules/z.js", "x")
    rep = PC.run(code_only=False, freeze=0, server=tmp_path / "srv", rs=RS, skip_guard=True)
    kinds = {(p["kind"], p["file"]) for p in rep["problems"]}
    assert ("P2", "data/renders/ep01/S1/takes.json") in kinds
    assert ("P2", "data/producer/log.jsonl") in kinds
    assert ("P4", "tools/m.safetensors") in kinds
    assert rep["verdict"] == "FAIL"
    srv = tmp_path / "srv/repo"
    assert (srv / "tools/x.py").read_text() == "print('ok')\n" and (srv / "tools/__init__.py").exists()
    assert not (srv / "data/review_pages").exists() and not (srv / "tools/node_modules").exists()
    assert rep["stats"]["rounds"][-1] == 0 or len(rep["stats"]["rounds"]) == 1 or rep["stats"]["rounds"][1] == 0


def test_simulated_push_converges_and_server_has_latest(tmp_path, monkeypatch):
    RS, src = _fake_rs(tmp_path, monkeypatch)
    _w(src / "services/a/m.py", "X = 1\n")
    _w(src / "knowledge/rules/r.yaml", "rules: []\n")
    rep = PC.run(code_only=True, server=tmp_path / "srv", rs=RS, skip_guard=True)
    assert rep["verdict"] == "PASS", rep["problems"]
    _w(src / "services/a/m.py", "X = 22\n")                  # 本地改了 → 再推一次只发这一份，服务器 = 最新
    os.utime(src / "services/a/m.py", (os.path.getmtime(src / "services/a/m.py") + 10,) * 2)
    rep2 = PC.run(code_only=True, server=tmp_path / "srv", rs=RS, skip_guard=True)
    assert rep2["verdict"] == "PASS" and rep2["stats"]["files_sent"] == 1
    assert (tmp_path / "srv/repo/services/a/m.py").read_text() == "X = 22\n"


def test_real_repo_code_push_is_clean():
    """真实仓库的代码目录（resident_sync.CODE_DIRS）推到全新空“服务器”：全部到达、字节相同、能解码、无权重 / 垃圾目录"""
    rep = PC.run(code_only=True, skip_guard=True)
    assert rep["stats"]["code_files"] > 300
    assert rep["verdict"] == "PASS", rep["problems"][:10]


def test_push_is_gated_by_push_check(tmp_path, monkeypatch):
    """K-OPS-C03（总调度 11-01）：push 先过 push_gate；不过 → PushGateFailed，一个字节都不发；recover 整个停下"""
    RS = _load("ns_resident_sync_gate_t", "tools/autopilot/resident_sync.py")
    monkeypatch.delenv("NS_PUSH_GATE", raising=False)
    monkeypatch.setattr(RS, "LOG", tmp_path / "log.txt")
    calls = []

    class R:
        returncode, stdout, stderr = 1, "[P2] x.json：读不全\npush_check FAIL", ""
    monkeypatch.setattr(RS.subprocess, "run", lambda cmd, **k: (calls.append(cmd) or R()))
    monkeypatch.setattr(RS, "ssh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("闸门没过却连了服务器")))
    import pytest
    with pytest.raises(RS.PushGateFailed):
        RS.push("gpu33", tier=1, yes=True)
    assert any("push_check.py" in str(x) for x in calls[0]) and "1" in calls[0]
    RS.recover(["gpu33"])                                  # 闸门不过：不推、不重启、不冒烟、不起 loop（ssh 一调就断言失败）
    d1, r1 = RS.push_dirs(tier=1)
    d2, r2 = RS.push_dirs(tier=2)
    assert "data" in d1 and "data" not in r1 and "data/import" in r1 and "data" in r2
