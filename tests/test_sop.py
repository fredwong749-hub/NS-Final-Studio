"""SOP 阶段 S1–S5 / 关口 G1–G5（/api/sop/status、/api/sop/episode/{n}，ns_api.sop，tools/sop_owner.py）。
全部在临时目录里：假的 state_timeline.json / scenes.json / schedule.json / renders_gpu3；剧本只留前两集。"""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_api import app as app_mod
from ns_api import readiness as RD
from ns_api import sop as SOP
from ns_render import pipeline as P
from ns_schema.script import ScriptImport

# 固定测试数据（与 t06 金标准同一份 60 集 v2 剧本）：data/import 里导入了什么都不影响这些测试
PINNED_SCRIPT = Path(__file__).resolve().parent / "fixtures" / "t06_golden" / "data" / "import" / "script_v2.json"

REPO = Path(__file__).resolve().parents[1]
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _tool(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def script() -> ScriptImport:
    sc = ScriptImport.model_validate_json(PINNED_SCRIPT.read_text(encoding="utf-8"))
    sc = sc.model_copy(deep=True)
    sc.episodes = sc.episodes[:2]
    ep = sc.episodes[0]                       # ep01 补齐 v3 要素；ep02 保持 v2
    ep.music_bgm = "Sparse piano, slow tempo."
    for s in ep.shots:
        s.sound = s.sound or "环境声"
        s.sound_h3 = "Quiet room tone."
        s.sound_intimate = "soft breathing"
        s.music_cue = "进入，强度1"
        s.duration, s.duration_source = 8, "script"
        s.h3_prompt = _h3_prompt(s)            # v3 每镜带 **H3提示词**（S1-W7；通过 §9A 机检）
    return sc


def _h3_prompt(s) -> str:
    from ns_agent.h3_prompt import assemble
    from ns_schema.h3_lint import frames_for_seconds
    # 项目方 2026-10-30：普通对话镜每镜只让一个人说话（H3-D7 block）→ 夹具的台词都归同一个说话人 (S1)
    lines = " ".join(f"The speaker (S1) says: <d>[Chinese] {d.text}</d>" for d in s.dialogue)
    body = ("Live-action, cinematic, shallow depth of field, a medium shot begins in the position, framing and lighting "
            f"established by Picture 1. She lifts her gaze slowly. {lines} She settles into the pose and composition "
            "established by Picture 2 at the end of the shot.").replace("  ", " ")
    return assemble(frames_for_seconds(s.duration), body, "Quiet room tone.")


def _shots(script):
    return [(e.number, s.id, s.index) for e in script.episodes for s in e.shots]


def write_timeline(root: Path, script, *, provisional=True, s2=None, g3=False, version="v3", drop_s2_fields=False,
                   look_confirmed=False):
    """s2: shot_id → s2_blockers 列表（缺省 = 就绪）"""
    s2 = s2 or {}
    shots = []
    for ep, sid, idx in _shots(script):
        b = s2.get(sid, [])
        row = {"shot_id": sid, "episode": ep, "index": idx, "scene_id": "sk_elevator",
               "characters": {"lin_wan": {"present": True}}, "required_loras": [], "future_field": {"x": 1}}
        if not drop_s2_fields:
            row.update(s2_ready=not b, s2_blockers=(["s1_gate_not_passed"] if provisional else []) + b)
        shots.append(row)
    tl = {"format": "ns.state_timeline/1", "source": {"script": version}, "provisional": provisional,
          "s1_gate": {"validator_errors": 0 if not provisional else None, "g3_accepted": g3, "g3_ref": "好" if g3 else ""},
          "episodes": {str(e.number): {"look_confirmed": look_confirmed} for e in script.episodes}, "shots": shots}
    d = root / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state_timeline.json").write_text(json.dumps(tl, ensure_ascii=False), encoding="utf-8")
    (d / "scenes.json").write_text(json.dumps({"provisional": provisional, "scenes": [
        {"scene_id": "sk_elevator", "place": "电梯", "shots": [s[1] for s in _shots(script)],
         "plate": "assets/scenes/sk_elevator/plate.png",
         "plate_status": "missing" if drop_s2_fields else "candidate"}]}, ensure_ascii=False), encoding="utf-8")
    (d / "looks").mkdir(exist_ok=True)
    (d / "looks" / "schedule.json").write_text(json.dumps({"episodes": {
        str(e.number): {"lin_wan": {"owner_confirmed_at": "x" if look_confirmed else None,
                                    "owner_confirmed_ref": "项目方：造型可以" if look_confirmed else None}}
        for e in script.episodes}}),
        encoding="utf-8")


def gpu3_shot(data: Path, shot: str, *, video=True, continuity="pass"):
    ep, sn = shot.split("-")
    d = data / "renders_gpu3" / ep / sn
    (d / "takes").mkdir(parents=True, exist_ok=True)
    img = f"renders_gpu3/{ep}/{sn}/takes/image_001.png"
    (data / img).write_bytes(PNG)
    takes, active = [{"stage": "image", "n": 1, "file": img, "created_at": "2026-10-29T02:00:00Z"}], {"image": 1}
    if video:
        v = f"renders_gpu3/{ep}/{sn}/takes/video_001.mp4"
        (data / v).write_bytes(b"mp4")
        takes.append({"stage": "video", "n": 1, "file": v, "created_at": "2026-10-29T03:00:00Z"})
        active["video"] = 1
    (d / "last.png").write_bytes(PNG)
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": active}), encoding="utf-8")
    (d / "status.json").write_text(json.dumps({"status": "ok", "owner": "gpu3", "continuity": continuity}), encoding="utf-8")


@pytest.fixture()
def env(tmp_path, script, monkeypatch):
    root = tmp_path / "proj"
    data = root / "data"
    (data / "renders").mkdir(parents=True)
    (data / "renders_gpu3").mkdir()
    own = tmp_path / "shot_ownership.json"
    own.write_text(json.dumps({"projects": {"weita": {"owner": "gpu3"}}}), encoding="utf-8")
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    monkeypatch.setattr(RD, "GPU3_ROOT", data / "renders_gpu3")
    monkeypatch.setattr(RD, "OWNERSHIP_FILE", own)
    monkeypatch.setattr(app_mod, "_script", script)
    monkeypatch.setattr(app_mod, "SOP_ROOT", root)
    monkeypatch.setattr(app_mod.PJC, "list_projects", lambda: [])
    yield TestClient(app_mod.app), root, data


def proj(c) -> dict:
    r = c.get("/api/sop/status")
    assert r.status_code == 200, r.text
    return r.json()["projects"][0]


def gate(p, gid):
    return next(g for g in p["gates"] if g["id"] == gid)


def test_no_endpoint_accepts_for_owner():
    for r in app_mod.app.routes:
        if getattr(r, "path", "").startswith("/api/sop"):
            assert r.methods == {"GET"}, r.path


def test_s1_blocked_shows_owner_cli(env, script):
    c, root, _ = env
    write_timeline(root, script, version="v2")
    p = proj(c)
    assert p["stage"] == "S1" and p["stages"][0]["shots_here"] == len(_shots(script))
    g3 = gate(p, "G3")
    assert g3["status"] == "blocked"
    b = g3["blockers"][0]
    assert b["actor"] == "owner" and b["cli"] == 'uv run python tools/s1_gate.py --accept "<项目方原话>"'
    codes = {x["code"]: x["actor"] for x in p["s1"]["blockers"]}
    assert codes == {"script_not_v3": "gpu3", "validator_unrecorded": "laptop", "g3_not_accepted": "owner"}
    act = next(a for a in p["owner_actions"] if a["gate"] == "G3")
    assert act["actionable"] is False and act["waiting_on"]        # v3 还没来，先别采纳
    assert p["gpu_priority"]["next"] == "S1"
    e = c.get("/api/sop/episode/1").json()
    s = e["shots"][0]
    assert s["stage"] == "S1" and {"g3_not_accepted", "script_not_v3"} <= {x["code"] for x in s["blockers"]}
    # ep02 是 v2：剧本要素（时长等）也列为 S1
    e2 = c.get("/api/sop/episode/2").json()
    assert any(x["code"].startswith("element:") for x in e2["shots"][0]["blockers"])
    assert c.get("/api/sop/episode/99").status_code == 404


def test_s2_blockers_actor_and_cli(env, script):
    c, root, _ = env
    first = _shots(script)[0][1]
    write_timeline(root, script, provisional=False, g3=True, s2={
        first: ["lora:hh12clear:missing", "plate:sk_elevator:candidate", "look_unconfirmed:ep01",
                "missing_ref:assets/x.png", "something_new:abc"]})
    e = c.get("/api/sop/episode/1").json()
    s = e["shots"][0]
    assert s["stage"] == "S2"
    by = {b["code"]: b for b in s["blockers"]}
    assert by["lora:hh12clear:missing"]["actor"] == "gpu3"
    assert by["plate:sk_elevator:candidate"]["actor"] == "owner"
    assert by["plate:sk_elevator:candidate"]["cli"] == 'uv run python tools/sop_owner.py plate sk_elevator "<项目方原话>"'
    assert by["look_unconfirmed:ep01"]["cli"] == 'uv run python -m ns_agent.looks confirm 1 lin_wan "<项目方原话>"'
    assert by["missing_ref:assets/x.png"]["actor"] == "laptop"
    assert by["something_new:abc"]["actor"] == "laptop"              # 不认识的阻塞照实列出
    p = proj(c)
    gates = {a["gate"] for a in p["owner_actions"]}
    assert {"look", "plate"} <= gates and "G3" not in gates
    look = next(a for a in p["owner_actions"] if a["gate"] == "look")
    assert look["cli_all"] == 'uv run python -m ns_agent.looks confirm 1-2 lin_wan "<项目方原话>"'
    assert p["gpu_priority"]["lora_queue"] == [{"trigger": "hh12clear", "shots": 1}]


def test_tolerates_missing_fields(env, script):
    c, root, _ = env
    write_timeline(root, script, provisional=False, g3=True, drop_s2_fields=True)
    s = c.get("/api/sop/episode/1").json()["shots"][0]
    assert s["stage"] == "S2"
    codes = {b["code"] for b in s["blockers"]}
    assert "plate:sk_elevator:missing" in codes and "look_unconfirmed:ep01" in codes
    (root / "data" / "state_timeline.json").unlink()
    p = proj(c)
    assert p["stage"] == "S1" and p["s1"]["blockers"][0]["code"] == "timeline_missing"
    assert p["s1"]["blockers"][0]["cli"] == "uv run python tools/build_state_timeline.py"


def test_full_path_g4_g5(env, script):
    c, root, data = env
    write_timeline(root, script, provisional=False, g3=True, look_confirmed=True)
    ep1 = [s for s in script.episodes[0].shots]
    for s in ep1:
        gpu3_shot(data, s.id)
    # 有视频、没 qa.json → S4，等 gpu3
    e = c.get("/api/sop/episode/1").json()
    assert {s["stage"] for s in e["shots"]} == {"S4"}, [s["blockers"] for s in e["shots"]]
    assert e["shots"][0]["blockers"][0]["code"] == "qa_not_pass"
    assert gate(proj(c), "G4")["status"] == "pending"
    vsha = hashlib.sha256(b"mp4").hexdigest()                     # gpu3_shot 写的视频内容
    qa = {"verdict": "pass", "shots": {f"S{s.index}": {"verdict": "pass", "video_sha256": vsha} for s in ep1}}
    (data / "renders_gpu3" / "ep01" / "qa.json").write_text(json.dumps(qa), encoding="utf-8")
    e = c.get("/api/sop/episode/1").json()
    assert {s["stage"] for s in e["shots"]} == {"S5"} and e["s4_done"]
    assert any(b["code"] == "final_missing" and b["actor"] == "gpu3" for b in e["episode_blockers"])
    p = proj(c)
    g4 = gate(p, "G4")
    assert g4["status"] == "blocked" and g4["blockers"][0]["actionable"] is True
    assert g4["blockers"][0]["cli"] == 'uv run python tools/sop_owner.py g4 --episode 1 "<项目方原话>"'
    # G4 没锁：第 2 集出了帧也停在 S3（若上游过了）——这里第 2 集剧本是 v2，停在 S1，但 S3 关卡里列了 G4
    e2 = c.get("/api/sop/episode/2").json()
    assert any(b["code"] == "g4_not_locked" for b in e2["shots"][0]["stages"]["S3"]["blockers"])
    # 项目方跑命令后才算锁定
    tool = _tool("sop_owner")
    tool.g4(root, data / "renders_gpu3", 1, "样片可以", False)
    assert gate(proj(c), "G4")["status"] == "passed"
    e2 = c.get("/api/sop/episode/2").json()
    assert not any(b["code"] == "g4_not_locked" for b in e2["shots"][0]["stages"]["S3"]["blockers"])
    # 成片 → G5 待项目方
    (data / "renders_gpu3" / "ep01" / "ep01_final.mp4").write_bytes(b"mp4")
    e = c.get("/api/sop/episode/1").json()
    b = next(b for b in e["episode_blockers"] if b["code"] == "g5_pending")
    assert b["actor"] == "owner" and b["cli"] == 'uv run python tools/sop_owner.py g5 1 "<项目方原话>"'
    assert any(a["gate"] == "G5" for a in e["owner_actions"])
    tool.g5(root, data / "renders_gpu3", 1, "发布", False)
    e = c.get("/api/sop/episode/1").json()
    assert e["stage"] == "S3" and e["episode_blockers"][0]["code"] == "continuity_sheet_missing"
    (data / "renders_gpu3" / "ep01" / "continuity_sheet.jpg").write_bytes(b"jpg")
    e = c.get("/api/sop/episode/1").json()
    assert e["stage"] == "done" and not e["episode_blockers"]


def test_continuity_fail_blocks_s3(env, script):
    c, root, data = env
    write_timeline(root, script, provisional=False, g3=True, look_confirmed=True)
    sh = script.episodes[0].shots
    gpu3_shot(data, sh[0].id)
    gpu3_shot(data, sh[1].id, continuity={"verdict": "fail", "reasons": ["换衣服了"]})
    s = c.get("/api/sop/episode/1").json()["shots"][1]
    assert s["stage"] == "S3"
    assert any(b["code"] == "frame:continuity" and "换衣服了" in b["text"] and b["actor"] == "gpu3" for b in s["blockers"])


def test_owner_tool_refuses(tmp_path):
    tool = _tool("sop_owner")
    root = tmp_path
    (root / "data").mkdir()
    (root / "data" / "scenes.json").write_text(json.dumps({"provisional": True}), encoding="utf-8")
    with pytest.raises(SystemExit):
        tool.plate(root, "sk_x", "", False, False)                 # 没有原话
    with pytest.raises(SystemExit):
        tool.plate(root, "sk_x", "确认", False, False)             # 临时分组
    (root / "data" / "scenes.json").write_text(json.dumps({"provisional": False}), encoding="utf-8")
    with pytest.raises(SystemExit):
        tool.plate(root, "sk_x", "确认", False, False)             # 没有图
    d = root / "assets" / "scenes" / "sk_x"
    d.mkdir(parents=True)
    (d / "plate.png").write_bytes(PNG)
    man = tool.plate(root, "sk_x", "确认", False, False)
    assert man["owner_confirmed_ref"] == "确认" and len(man["plate_sha256"]) == 64
    with pytest.raises(SystemExit):
        tool.g4(root, root / "data" / "renders_gpu3", 1, "锁", False)   # 没有 qa.json
    with pytest.raises(SystemExit):
        tool.g5(root, root / "data" / "renders_gpu3", 1, "发布", False)  # 没有成片


def test_ep_ranges():
    assert SOP.ep_ranges([5, 1, 2, 3, 7, 8]) == "1-3,5,7-8"
