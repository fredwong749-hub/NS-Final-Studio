"""EPCHAIN-O 11-03（项目方 02:1x：ep01 做完做 ep02，按集流水，最终 100% 全自动）。
① 第 N 集导入后系统自动开第 N+1 集（resident → autoflow.pending_done → run），到 P1_storyline 最后一集为止；
② 派人请求一请求一文件（inbox/requests/），多集不互相覆盖；写手 Fable、评审 Sonnet；pending_requests 只读列出；
③ 每段一行计量 <run>/metrics/epNN.jsonl（docs/master/METRICS_SPEC.md）；
④ dry-run：临时目录里 ep01 imported → ep02 P2 自动开写 → 请求写出 → .done → P3（不写真实数据）。"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "data/pipeline/runs/series10_v2"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def AF():
    return _load("autoflow_epchain", "tools/script_rsi/autoflow.py")


@pytest.fixture(scope="module")
def AG():
    return _load("autoflow_agent_epchain", "tools/script_rsi/autoflow_agent.py")


@pytest.fixture(scope="module")
def PR():
    return _load("pending_requests_epchain", "tools/master/pending_requests.py")


def _season(rd: Path, n_eps: int, verdicts: dict[int, str]) -> None:
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "P1_storyline.json").write_text(json.dumps({"episodes": [{"episode": i} for i in range(1, n_eps + 1)]}), encoding="utf-8")
    for ep, v in verdicts.items():
        (rd / f"autoflow_ep{ep:02d}.json").write_text(json.dumps({"episode": ep, "verdict": v}), encoding="utf-8")


# ------------------------------------------------------------------ ① 按集流水

def test_next_episode_opens_after_import(AF, tmp_path):
    rd = tmp_path / "r"
    _season(rd, 3, {1: "imported"})
    assert AF.next_episodes(rd) == [2]
    assert 2 in AF.pending_done(rd)                     # 常驻服务每拍调的就是 pending_done（单一推进入口不变）


def test_next_episode_not_before_import(AF, tmp_path):
    rd = tmp_path / "r"
    _season(rd, 3, {1: "awaiting_writer"})
    assert AF.next_episodes(rd) == [] and AF.pending_done(rd) == []


def test_next_episode_once_and_stops_at_last(AF, tmp_path):
    rd = tmp_path / "r"
    _season(rd, 3, {1: "imported", 2: "awaiting_writer"})
    assert AF.next_episodes(rd) == []                   # ep02 已开：不重复开
    _season(rd, 3, {1: "imported", 2: "imported", 3: "imported"})
    assert AF.next_episodes(rd) == []                   # 最后一集导入后不再开 ep04
    (rd / "autoflow_ep03.json").unlink()
    _season(rd, 3, {1: "imported", 2: "imported"})
    assert AF.next_episodes(rd) == [3]


def test_last_episode_falls_back_to_brief(AF, tmp_path):
    rd = tmp_path / "r"
    rd.mkdir()
    assert AF.season_last_episode(rd) == 0              # 都读不到 = 不开新集（失败关闭）
    (rd / "P0_brief.json").write_text(json.dumps({"episodes": {"from": 1, "to": 4}}), encoding="utf-8")
    assert AF.season_last_episode(rd) == 4


def test_resident_spawns_next_episode(AF, tmp_path, monkeypatch):
    """resident.tick 用 af.pending_done 起 autoflow run：ep01 imported → 起 ep02"""
    RES = _load("autoflow_resident_epchain", "tools/factory/autoflow_resident.py")
    rd = tmp_path / "series_x"
    _season(rd, 10, {1: "imported"})
    monkeypatch.setattr(RES, "advance_runs", lambda root=None: ["series_x"])
    monkeypatch.setattr(RES, "asset_tick", lambda runs=None: {})
    # REVIEW-G2 P1-1：不许写真实 data/factory（派单器 state / hollywood 锁）
    monkeypatch.setattr(RES, "dispatch_tick", lambda *a, **k: {}, raising=False)
    monkeypatch.setattr(RES, "hollywood_tick", lambda *a, **k: {}, raising=False)
    spawned = []

    class P:
        def poll(self):
            return None
    r = RES.tick({}, af=AF, runs_mod=type("M", (), {"run_dir": staticmethod(lambda run, root: rd)}),
                 spawn=lambda d, ep: spawned.append((d, ep)) or P())
    assert spawned == [(rd, 2)] and r["started"] == ["series_x ep02"]


# ------------------------------------------------------------------ ② 派人请求

def test_requests_one_file_each_no_overwrite(AG, AF, PR, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    monkeypatch.setenv("NSFS_INBOX_DIR", str(inbox))
    rd = tmp_path / "r"
    (rd / "writer_tasks").mkdir(parents=True)
    paths = []
    for ep, step, role in ((2, "P2_ep02", "writer"), (3, "facts_ep03", "reviewer")):
        pk = {"step": step, "attempt": 1, "role": role, "episode": ep, "link": "x",
              "output": {"path": str(rd / "writer_out" / f"{step}_a1.json"), "done_marker": str(rd / "writer_out" / f"{step}_a1.json.done")}}
        pp = rd / "writer_tasks" / f"{step}_a1.json"
        pp.write_text(json.dumps({**pk, "status": "open"}), encoding="utf-8")
        paths.append(AG.packet_request(rd, pk, pp))
    files = sorted(p.name for p in (inbox / "requests").glob("*.json"))
    assert files == ["r__P2_ep02_a1.json", "r__facts_ep03_a1.json"]
    w = json.loads(paths[0].read_text(encoding="utf-8"))
    v = json.loads(paths[1].read_text(encoding="utf-8"))
    assert (w["episode"], w["step"], w["kind"], w["suggested_model"]) == (2, "P2_ep02", "writer", "fable")
    assert (v["kind"], v["suggested_model"], v["must_differ_from"]) == ("reviewer", "sonnet", "fable")
    assert w["packet"] and w["output"] and v["packet"] and v["output"]
    assert AF.MODEL_PLAN["writer"] not in AF.MODEL_PLAN["judges"] and AF.MODEL_PLAN["writer"] != AF.MODEL_PLAN["reviewer"]
    assert [r["step"] for r in PR.list_requests(inbox)] == ["P2_ep02", "facts_ep03"]
    (rd / "writer_out").mkdir()
    (rd / "writer_out" / "P2_ep02_a1.json.done").write_text("", encoding="utf-8")
    assert [r["step"] for r in PR.list_requests(inbox)] == ["facts_ep03"]          # 交了稿的不再列
    (rd / "writer_tasks" / "facts_ep03_a1.json").unlink()                           # 包被作废移走 → 不再列
    assert PR.list_requests(inbox) == []
    assert {r["state"] for r in PR.list_requests(inbox, include_all=True)} == {"done", "voided"}


# ------------------------------------------------------------------ ③ 计量

def test_metrics_one_line_per_stage_result(AF, tmp_path):
    rd = tmp_path / "r"
    (rd / "writer_tasks").mkdir(parents=True)
    st = AF.Status(rd, 2, 0.0)
    st.set(writer_backend="claude_agent")
    st.stage("P1", "故事线", "reused", "code")
    st.stage("P2", "分集大纲", "awaiting_writer", "api_model", step="P2_ep02", attempt=1)
    (rd / "writer_tasks" / "P2_ep02_a1.json").write_text("{}", encoding="utf-8")
    (rd / "writer_tasks" / "P2_ep02_a2.json").write_text("{}", encoding="utf-8")
    st.stage("P2", "分集大纲", "ok", "api_model", attempt=2)
    st.stage("P2", "分集大纲", "ok", "api_model", attempt=2)          # 同一结果再报一次：不重复出行
    st.stage("gate", "导入闸门", "ok", "code")
    (rd / "writer_tasks" / "P3_ep02_a1.json").write_text("{}", encoding="utf-8")
    (rd / "writer_out").mkdir()
    (rd / "writer_out" / "P3_ep02_a1.json.done").write_text("SCRIPTWRITER\nmodel: claude-fable-5-1\n", encoding="utf-8")
    st.stage("P3", "单集剧本", "ok", "api_model", attempt=1)
    rows = [json.loads(x) for x in (rd / "metrics" / "ep02.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["stage"] for r in rows] == ["P1", "P2", "gate", "P3"]
    p1, p2, gate, p3 = rows
    assert p1["carried"] is True and p1["by"] == "code" and p1["attempts"] == 0
    assert p2["by"] == "agent:fable" and p2["model_source"] == "suggested" and p2["attempts"] == 2 and p2["result"] == "ok" and p2["ok"] is True
    assert p3["by"] == "agent:claude-fable-5-1" and p3["model_source"] == "done"          # METRICS-F：实际模型取 .done 第 2 行
    assert gate["by"] == "code" and gate["attempts"] == 1
    for r in rows:
        assert set(r) >= {"schema", "run", "episode", "stage", "started_at", "ended_at", "duration_s", "by", "attempts", "result"}


def test_metrics_spec_documents_fields():
    spec = (ROOT / "docs/master/METRICS_SPEC.md").read_text(encoding="utf-8")
    for k in ("nsfs.metrics.stage/1", "started_at", "ended_at", "by", "attempts", "result", "carried"):
        assert k in spec


# ------------------------------------------------------------------ ④ dry-run（临时目录，真实 series10_v2 只读）

SEED = ["P0_brief.json", "P1_storyline.json", "P1_storyline.json.report.json", "P1_looks.json", "owner_gates.json", "CLEAN_CUT.json",
        "judge_p1/STATE.json", "autoflow_ep01.json"]


@pytest.mark.skipif(not (REAL / "P1_storyline.json").exists(), reason="没有 series10_v2 种子")
def test_dry_run_ep01_imported_to_ep02_p3(AF, AG, PR, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    monkeypatch.setenv("NSFS_INBOX_DIR", str(inbox))
    rd = tmp_path / "series10_v2"
    for rel in SEED:
        (rd / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REAL / rel, rd / rel)
    # TIMELINE-O 11-03：真实 ep01 会被新闸门（时间轴 TL-）重开补丁环；本用例只测“ep01 已导入 → 开 ep02”，夹具里固定成已导入
    _st = json.loads((rd / "autoflow_ep01.json").read_text(encoding="utf-8"))
    _st.update(verdict="imported", awaiting=None)
    (rd / "autoflow_ep01.json").write_text(json.dumps(_st, ensure_ascii=False), encoding="utf-8")

    assert json.loads((rd / "autoflow_ep01.json").read_text(encoding="utf-8"))["verdict"] == "imported"
    # 一拍：ep01 已导入 → 开 ep02
    assert AF.pending_done(rd) == [2]
    d = AG.run(rd, 2, "dry")
    assert d["awaiting"]["step"] == "P2_ep02" and d["verdict"] == "awaiting_writer"
    reqs = PR.list_requests(inbox)
    assert [(r["episode"], r["step"], r["kind"], r["suggested_model"]) for r in reqs] == [(2, "P2_ep02", "writer", "fable")]
    assert AF.pending_done(rd) == []                    # 等写手：不空转
    # 写手交稿（夹具：ep02 大纲由 ep01 大纲改集号 + P1 第 2 集 logline）→ .done → 下一拍推进到 P3
    sl = json.loads((rd / "P1_storyline.json").read_text(encoding="utf-8"))
    e2 = next(e for e in sl["episodes"] if int(e["episode"]) == 2)
    o = json.loads((REAL / "P2_ep01_outline.json").read_text(encoding="utf-8"))
    o.update(episode=2, title=e2.get("title") or o["title"], logline=e2.get("logline") or o["logline"],
             characters=e2["characters"], scenes=e2["scenes"])
    ren = {"江予白": e2["characters"][1], "卓琳": e2["characters"][-1], "唐瑶": e2["characters"][-1]}   # 人物 / 场景换成 P1 第 2 集的（LK12-02）
    for b in o["beats"]:
        b["scene_id"] = e2["scenes"][0]
        b["characters"] = list(dict.fromkeys(ren.get(c, c) for c in b["characters"]))
        for a_, z_ in ren.items():
            b["summary"] = b["summary"].replace(a_, z_)
    out = Path(reqs[0]["output"])
    out = out if out.is_absolute() else ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
    Path(str(out) + ".done").write_text("", encoding="utf-8")
    assert AF.pending_done(rd) == [2]
    d = AG.run(rd, 2, "dry")
    assert (rd / "P2_ep02_outline.json").exists(), d.get("stages")
    assert d["awaiting"]["step"] == "P3_ep02"
    assert [r["step"] for r in PR.list_requests(inbox)] == ["P3_ep02"]
    rows = [json.loads(x) for x in (rd / "metrics" / "ep02.jsonl").read_text(encoding="utf-8").splitlines()]
    p2 = next(r for r in rows if r["stage"] == "P2")
    assert p2["by"].startswith("agent:") and p2["result"] == "ok"
    # 真实数据不写：进程内写 data/ 由 conftest real-data-guard 当场报错；这里再核对产物全落在临时目录
    assert str(tmp_path) in str(out) and (rd / "metrics" / "ep02.jsonl").exists()
    assert all(tmp_path.as_posix() in Path(json.loads(f.read_text(encoding="utf-8"))["packet"]).as_posix() for f in (inbox / "requests").glob("*.json"))
