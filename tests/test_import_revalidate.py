"""W-GATE 11-06：导入稿按现行规则复验（tools/master/import_revalidate.py + sop_gate 导入闸门接线）。夹具全在临时根目录，不跑真实校验器。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SG = _load("sop_gate_reval_t", "tools/master/sop_gate.py")
RV = SG._reval_mod()
RUN = "drama_x"
LINTS_V1 = 'WRITER_LINT_LEVEL = "warn"\nRULES = {"QW-W1": ("warn", "a")}\nL201_LEVEL = "block"\n'


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _root(tmp_path, mode="report", shots=(1, 2)):
    r = tmp_path
    _w(r / "config/pipeline/runs.json", {"primary": RUN, "legacy_unprefixed_run": "old_v1", "runs": {RUN: {"status": "preparing"}}})
    _w(r / "config/pipeline/sop_gate.json", {"enabled": True, "observe_stages": [], "whole_episode_prompts": False,
                                              "whole_episode_assets": False, "import_revalidate": {"mode": mode}})
    _w(r / "tools/qa/writer_lints.py", LINTS_V1)
    md = r / f"data/pipeline/runs/{RUN}/staging/P4_ep01.fix.md"
    _w(md, "## ep1《x》\n镜1\n")
    sha = RV._sha_file(md)
    _w(r / "data/import/runs" / RUN / "script_v2.json",
       {"sources": [{"path": str(md), "sha256": sha, "episodes": [1]}],
        "episodes": [{"number": 1, "shots": [{"index": n} for n in shots]}]})
    _w(r / f"data/pipeline/runs/{RUN}/P4_ep01.md", "# P4\n")
    _w(r / f"data/pipeline/runs/{RUN}/autoflow_ep01.json",
       {"stages": [{"id": "gate", "status": "ok"}, {"id": "import", "status": "imported", "sha256": sha}, {"id": "code", "fails": 0}]})
    _w(r / f"data/pipeline/asset_jobs/{RUN}/_ready_ep01.json", {"ready": True, "gaps": 0, "at": "t"})
    ev = {"fingerprint": SG.prompt_fingerprint(r, RUN, 1), "at": "t", "shots": {str(n): {"ok": True} for n in shots}}
    _w(r / f"data/pipeline/sop_gate/{RUN}/ep01_prompts.json", ev)
    return r


class Runner:
    def __init__(self, blocking):
        self.blocking, self.calls = blocking, 0

    def __call__(self, root, path, ep, timeout_s):
        self.calls += 1
        n = self.blocking
        return {"blocking": n, "episodes_found": 1, "counts": ({"QW-L14|block": n, "QW-W1|warn": 2} if n else {"QW-W1|warn": 2})}


def _use(monkeypatch, runner):
    RV._MEMO.clear()
    monkeypatch.setattr(RV, "RUNNER", runner)


def test_fingerprint_changes_when_rule_added(tmp_path):
    _w(tmp_path / "tools/qa/writer_lints.py", LINTS_V1)
    RV._MEMO.clear()
    a = RV.ruleset_fingerprint(tmp_path)
    assert ["QW-W1", "warn"] in [list(x) for x in a["rules"]]
    _w(tmp_path / "tools/qa/writer_lints.py", LINTS_V1 + 'RULES["QW-L14"] = ("block", "首尾帧")\n')
    b = RV.ruleset_fingerprint(tmp_path)
    assert a["fp"] != b["fp"] and ("QW-L14", "block") in b["rules"]
    _w(tmp_path / "tools/qa/writer_lints.py", LINTS_V1 + 'RULES["QW-L14"] = ("warn", "首尾帧")\n')
    assert RV.ruleset_fingerprint(tmp_path)["fp"] not in (a["fp"], b["fp"])      # 只改级别也变


def test_report_mode_never_blocks(tmp_path, monkeypatch):
    r = _root(tmp_path, "report")
    _use(monkeypatch, Runner(11))
    j = SG.judge(RUN, 1, "出图", root=r)
    assert j["ok"], j["missing"]
    assert j["import_revalidate"]["blocking"] == 11 and j["import_revalidate"]["mode"] == "report"
    assert SG.judge(RUN, 1, "出图", shot=1, root=r)["ok"]
    SG.require(RUN, 1, "出图", shot=1, root=r)                  # 不抛
    row = SG.status(RUN, r)[0]
    assert "导入闸门" in row["passed"] and "block 11（QW-L14×11）" in row["rows"][1]["why"]
    assert row["import_revalidate"]["by_rule"] == {"QW-L14": 11}
    # 新结果：遥测一行 + 一条卡点（同一稿同一组计数只开一次）
    tl = (r / "data/pipeline/sop_gate/import_revalidate.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(tl) == 1 and json.loads(tl[0])["blocking"] == 11
    iss = (r / "data/pipeline/issues.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(iss) == 1 and "QW-L14×11" in json.loads(iss[0])["what"] and json.loads(iss[0])["blocking"] is False
    RV._MEMO.clear()
    SG.status(RUN, r)                                                          # 缓存命中：不再写遥测 / 卡点
    assert len((r / "data/pipeline/issues.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_report_mode_validator_error_does_not_block(tmp_path, monkeypatch):
    r = _root(tmp_path, "report")

    def boom(*a, **k):
        raise RuntimeError("validator crashed")
    _use(monkeypatch, boom)
    j = SG.judge(RUN, 1, "出图", root=r)
    assert j["ok"] and "没跑成" in SG.status(RUN, r)[0]["rows"][1]["why"]


def test_enforce_blocks_when_block_gt0(tmp_path, monkeypatch):
    r = _root(tmp_path, "enforce")
    _use(monkeypatch, Runner(9))
    j = SG.judge(RUN, 1, "出图", root=r)
    assert not j["ok"] and any(m.startswith("导入闸门复验") and "block 9" in m for m in j["missing"])
    assert not SG.judge(RUN, 1, "出图", shot=1, root=r)["ok"]
    assert SG.judge(RUN, 1, "提示词", root=r)["ok"]                 # 出图之前的阶段不挡（只挡进出图）
    assert not SG.promote_check(RUN, r)["promote"]
    import pytest
    with pytest.raises(SG.SopGateError):
        SG.require(RUN, 1, "出图", shot=1, root=r)


def test_enforce_passes_block0(tmp_path, monkeypatch):
    r = _root(tmp_path, "enforce")
    _use(monkeypatch, Runner(0))
    j = SG.judge(RUN, 1, "出图", root=r)
    assert j["ok"], j["missing"]
    assert j["import_revalidate"]["blocking"] == 0
    assert SG.promote_check(RUN, r)["promote"]
    assert not (r / "data/pipeline/issues.jsonl").exists()


def test_off_mode_does_not_run(tmp_path, monkeypatch):
    r = _root(tmp_path, "off")
    rn = Runner(5)
    _use(monkeypatch, rn)
    assert SG.judge(RUN, 1, "出图", root=r)["ok"] and rn.calls == 0
    assert SG.status(RUN, r)[0]["import_revalidate"] is None


def test_cache_hit_avoids_rerun(tmp_path, monkeypatch):
    r = _root(tmp_path, "report")
    rn = Runner(3)
    _use(monkeypatch, rn)
    SG.status(RUN, r)
    SG.judge(RUN, 1, "出图", root=r)
    assert rn.calls == 1
    RV._MEMO.clear()                                   # 新进程：只剩文件缓存
    res = RV.revalidate(RUN, 1, r, import_doc=json.loads((r / f"data/import/runs/{RUN}/script_v2.json").read_text(encoding="utf-8")),
                        cfg=RV.DEFAULT, runner=rn)
    assert rn.calls == 1 and res["cached"] and res["blocking"] == 3
    # 规则集变了 → 指纹变 → 重跑
    _w(r / "tools/qa/writer_lints.py", LINTS_V1 + 'RULES["QW-L15"] = ("block", "x")\n')
    RV._MEMO.clear()
    SG.status(RUN, r)
    assert rn.calls == 2
    # 导入稿变了（重新导入）→ 重跑
    md = r / f"data/pipeline/runs/{RUN}/staging/P4_ep01.fix.md"
    _w(md, "## ep1《x》\n镜1 改\n")
    doc = json.loads((r / f"data/import/runs/{RUN}/script_v2.json").read_text(encoding="utf-8"))
    doc["sources"].append({"path": str(md), "sha256": RV._sha_file(md), "episodes": [1]})
    _w(r / f"data/import/runs/{RUN}/script_v2.json", doc)
    SG.status(RUN, r)
    assert rn.calls == 3


def test_imported_source_falls_back_to_autoflow_sha(tmp_path):
    d = tmp_path / f"data/pipeline/runs/{RUN}"
    _w(d / "P4_ep02.final.md", "a")
    _w(d / "P4_ep02.md", "b")
    sha = RV._sha_file(d / "P4_ep02.final.md")
    src = RV.imported_source(RUN, 2, tmp_path, import_doc={"sources": []},
                             autoflow={"stages": [{"id": "import", "sha256": sha}]})
    assert src["path"].name == "P4_ep02.final.md" and src["note"] == ""
    assert RV.imported_source(RUN, 2, tmp_path, import_doc={}, autoflow={"stages": [{"id": "import", "sha256": "nope"}]}) is None
    # 记录的文件导入后被改过：按 sha 在候选里找回原稿
    _w(d / "P4_ep02.v1.md", "a")
    _w(d / "P4_ep02.final.md", "a2")
    src = RV.imported_source(RUN, 2, tmp_path, import_doc={"sources": [{"path": str(d / "P4_ep02.final.md"), "sha256": sha, "episodes": [2]}]})
    assert src["path"].name == "P4_ep02.v1.md" and src["sha"] == sha and "按 sha" in src["note"]


def test_bad_mode_falls_back_to_report():
    assert RV.cfg_of({"import_revalidate": {"mode": "weird"}})["mode"] == "report"
    assert RV.cfg_of({})["mode"] == "report"


# ---- Fable 复审 A1–A5（11-06）
def test_error_result_memoized_runner_called_once(tmp_path, monkeypatch):
    r = _root(tmp_path, "report")
    calls = []

    def boom(*a, **k):
        calls.append(a[3])
        raise RuntimeError("validator timeout")
    _use(monkeypatch, boom)
    for _ in range(5):
        assert SG.judge(RUN, 1, "出图", shot=1, root=r)["ok"]
    assert len(calls) == 1 and calls[0] == RV.DEFAULT["timeout_s"] == 30
    # episodes_found=0 也一样只跑一次
    rn = Runner(0)
    rn_calls = []
    _use(monkeypatch, lambda *a, **k: (rn_calls.append(1), {"blocking": 0, "episodes_found": 0, "counts": {}})[1])
    for _ in range(5):
        SG.judge(RUN, 1, "出图", root=r)
    assert len(rn_calls) == 1
    # TTL 过了重试
    for k, v in list(RV._MEMO.items()):
        if k[0] == "err":
            RV._MEMO[k] = (v[0] - RV.ERR_TTL_S - 1, v[1])
    SG.judge(RUN, 1, "出图", root=r)
    assert len(rn_calls) == 2


def test_persistence_error_does_not_raise(tmp_path, monkeypatch):
    r = _root(tmp_path, "report")
    _use(monkeypatch, Runner(4))

    def locked(*a, **k):
        raise PermissionError("WinError 5 file locked")
    monkeypatch.setattr(RV, "_write_json", locked)
    monkeypatch.setattr(RV, "_append", locked)
    j = SG.judge(RUN, 1, "出图", root=r)
    assert j["ok"] and j["import_revalidate"]["blocking"] == 4


def test_broken_module_treated_as_off(tmp_path, monkeypatch):
    sg = _load("sop_gate_reval_broken_t", "tools/master/sop_gate.py")
    bad = tmp_path / "mod"
    _w(bad / "import_revalidate.py", "def x(:\n")
    _w(bad / "sop_gate.py", "")
    monkeypatch.setattr(sg, "__file__", str(bad / "sop_gate.py"))
    assert sg._reval_mod() is None
    assert sg._reval_mod() is None                     # 60 s 内不重试，也不抛
    r = _root(tmp_path / "root", "enforce")
    rv, rc = sg.import_revalidate(r, RUN, 1)
    assert rv is None and rc["mode"] == "off"
    assert sg.judge(RUN, 1, "出图", root=r)["ok"]


def test_windows_path_resolves_on_posix(tmp_path):
    f = tmp_path / f"data/pipeline/runs/{RUN}/staging/P4_ep01.x.md"
    _w(f, "x")
    got = RV._abs(tmp_path, chr(92).join(["D:", "NS-Final Studio", "data", "pipeline", "runs", RUN, "staging", "P4_ep01.x.md"]))
    assert got == tmp_path / "data/pipeline" / "runs" / RUN / "staging" / "P4_ep01.x.md" and got.is_file()
    assert RV._abs(tmp_path, f"/root/work/ns/data/pipeline/runs/{RUN}/staging/P4_ep01.x.md").is_file()
    assert RV._abs(tmp_path, f"data/pipeline/runs/{RUN}/staging/P4_ep01.x.md").is_file()
    assert RV._abs(tmp_path, str(f)) == f


def test_import_doc_cached_by_stat(tmp_path, monkeypatch):
    r = _root(tmp_path, "report")
    n = []
    real = SG._j
    monkeypatch.setattr(SG, "_j", lambda p, d=None: (n.append(str(p)) if str(p).endswith("script_v2.json") else None, real(p, d))[1])
    SG._import_doc(r, RUN)
    SG._import_doc(r, RUN)
    assert len(n) == 1
