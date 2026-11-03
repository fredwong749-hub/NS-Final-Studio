"""MIGRATE-O 11-03（L-141）：H3 镜内 At → 自然语言分拍的确定性迁移器 + autoflow_agent 接线。
夹具 tests/fixtures/l141/ep01_v2_shots.md = V2 第 1 集 P4_ep01.final.md 的真实镜头（镜 1 已是新写法；镜 6 / 9 / 10 镜内 At），
每条用例复制到 tmp_path 再跑，不写真实数据。"""
import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/recipes", "tools/script_rsi"):
    sys.path.insert(0, str(ROOT / p))

import l141_migrate as M  # noqa: E402
from ns_recipes import lint as L  # noqa: E402
from ns_recipes.spec_import import parse_beats  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "l141" / "ep01_v2_shots.md"


@pytest.fixture
def run(tmp_path, monkeypatch):
    rd = tmp_path / "series10_v2"
    (rd / "writer_out").mkdir(parents=True)
    p = rd / "writer_out" / "P4_ep01_a9.md"
    shutil.copy(FIX, p)
    monkeypatch.setenv("NSFS_L141_QUARANTINE", str(tmp_path / "q"))
    return SimpleNamespace(dir=rd, p=p, q=tmp_path / "q", orig=FIX.read_text(encoding="utf-8"))


def blocks(text):
    return {int(re.match(r"\*\*镜(\d+)", b).group(1)): b for b in M.SHOT_SPLIT.split(text)[1:]}


def h3(b):
    return M.H3_LINE.search(b).group(2)


def beats(b):
    return parse_beats(M.BEATS_LINE.search(b).group(1))


def test_migrate_ep01_real_shots(run):
    res = M.apply_file(run.p, run.dir, by="test")
    assert res["changed"] and res["migrated"] == [9, 10] and res["needs_llm"] == [6]
    new = run.p.read_text(encoding="utf-8")
    ob, nb = blocks(run.orig), blocks(new)
    assert ob[1] == nb[1] and ob[6] == nb[6]                       # 已是新写法的镜 / 拍数对不上的镜一个字节不动
    for n in (9, 10):
        body, bt = h3(nb[n]), beats(nb[n])
        # 迁移后 lint RL-T8 / RL-T9 通过（lint 原函数，spec 只带 **分拍**）
        sp = SimpleNamespace(motion=SimpleNamespace(beats=bt), duration_s=bt[-1].t1)
        iss = L.timeline_alignment("integrated_multimodal_description: " + body, sp, strict=True)
        assert [i for i in iss if i["level"] == "error"] == [], iss
        assert not L.in_shot_timecodes(body)
        # 拍数、拍序和 **分拍** 一致
        marks = L.nl_beats(body)
        assert len(marks) == len(bt) - 1
        assert [m[2] for m in marks] == [float(int(b.t0)) for b in bt[1:]]
        assert body.index("In the first two seconds, ") < marks[0][0]
        # 台词一字不改、去掉时间标记后正文一字不改
        assert M.D_RE.findall(body) == M.D_RE.findall(h3(ob[n]))
        assert M.strip_marks(body) == M.strip_marks(h3(ob[n]))
        # H3 行以外一个字节不动
        assert M.H3_LINE.sub("", nb[n]) == M.H3_LINE.sub("", ob[n])
    assert M.D_RE.findall(new) == M.D_RE.findall(run.orig)


def test_backup_and_audit(run):
    res = M.apply_file(run.p, run.dir, by="test")
    bak = Path(res["backup"])
    assert bak.is_relative_to(run.q) and bak.read_text(encoding="utf-8") == run.orig    # 原稿先隔离备份
    rec = [json.loads(x) for x in (run.dir / M.AUDIT).read_text(encoding="utf-8").splitlines()]
    assert len(rec) == 1 and rec[0]["migrated"] == [9, 10] and rec[0]["backup"] == str(bak)
    assert {r["shot"]: r["status"] for r in rec[0]["shots"]} == {6: "needs_llm", 9: "migrated", 10: "migrated"}
    assert all(r["lint_before"] for r in rec[0]["shots"])          # 迁移前 lint 对比留在审计里
    again = M.apply_file(run.p, run.dir, by="test")                # 幂等：再跑不改、不再备份
    assert not again["changed"] and len(list(run.q.rglob("*.orig"))) == 1


def test_dry_run_writes_nothing(run):
    res = M.apply_file(run.p, run.dir, write=False)
    assert res["migrated"] == [9, 10] and run.p.read_text(encoding="utf-8") == run.orig
    assert not run.q.exists() and not (run.dir / M.AUDIT).exists()


def test_cut_at_kept_and_increasing():
    b9 = blocks(FIX.read_text(encoding="utf-8"))[9]
    body, bt = h3(b9), beats(b9)
    multi = body.rstrip() + " [Shot 2] At 00:05.000, the camera cuts to a close-up of her face, her eyes on the ring light, her lips closed."
    new, why = M.migrate_body(multi, bt)
    assert new is not None, why
    assert "[Shot 2] At 00:05.000, the camera cuts" in new           # 切镜 At 保留
    assert not L.in_shot_timecodes(new) and L.cut_issues(new, "error") == []
    cuts = [m.group(0) for m in L.CUT_RE.finditer(new)]
    assert cuts == ["[Shot 2] At 00:05.000,"]
    bad = multi + " [Shot 3] At 00:04.000, the camera cuts back."
    new2, why2 = M.migrate_body(bad, bt)
    assert new2 is None and "严格递增" in why2                      # 切镜不递增 → 不迁，交补丁环


def test_beat_count_mismatch_left_for_llm():
    b6 = blocks(FIX.read_text(encoding="utf-8"))[6]
    new, why = M.migrate_body(h3(b6), beats(b6))
    assert new is None and "拍数对不上" in why


def test_autoflow_agent_hook(run, monkeypatch):
    AG = M_load_agent()
    st = SimpleNamespace(d={}, save=lambda: None)
    assert AG.l141_fix(run.dir, run.p, st, "test") is None          # 不是 V2 完全切割 run：不动
    (run.dir / "CLEAN_CUT.json").write_text("{}", encoding="utf-8")
    assert AG.l141_fix(run.dir, run.p, st, "test", need_done=True) is None   # 没 .done：写手还在写，不动
    run.p.with_name(run.p.name + ".done").write_text("ok", encoding="utf-8")
    res = AG.l141_fix(run.dir, run.p, st, "intake_full_p4", need_done=True)
    assert res["changed"] and res["migrated"] == [9, 10]
    assert st.d["agent_history"][-1]["by"] == "l141_migrate"
    assert not L.in_shot_timecodes(h3(blocks(run.p.read_text(encoding="utf-8"))[9]))


def M_load_agent():
    import importlib.util as u
    spec = u.spec_from_file_location("autoflow_agent_l141", ROOT / "tools" / "script_rsi" / "autoflow_agent.py")
    m = u.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
