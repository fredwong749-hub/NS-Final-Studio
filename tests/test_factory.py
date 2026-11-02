"""FACTORY（L-099b，docs/master/FRAMEWORK_REFRAME.md）：deps / inbox / sync 的离线测试（不连服务器）。
K-OPS-F02 交还闸门、K-OPS-F03 派单前 refs sha 校验。"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/factory"))

import inbox as IB  # noqa: E402
import sync as SY  # noqa: E402


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_check_refs_no_table_does_not_block(tmp_path):
    assert IB.check_refs("ep01-S1", ["a.png"], expected={}, root=tmp_path) is None
    assert IB.check_refs("ep01-S1", ["a.png"], expected={"shots": {}}, root=tmp_path)      # K-OPS-F09：有表但没这镜 → 拒派


def test_check_refs_ok_and_sha_mismatch(tmp_path):
    f = tmp_path / "data/assets/identity_refs/lin_wan/face.png"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"A")
    exp = {"shots": {"ep01-S1": [{"rel": "data/assets/identity_refs/lin_wan/face.png", "sha": _sha(b"A")}]}}
    assert IB.check_refs("ep01-S1", ["data/assets/identity_refs/lin_wan/face.png"], expected=exp, root=tmp_path) == []
    f.write_bytes(b"B")                    # 同路径、内容变了（例：设定图被换掉）→ 拒派
    probs = IB.check_refs("ep01-S1", ["data/assets/identity_refs/lin_wan/face.png"], expected=exp, root=tmp_path)
    assert probs and "sha 不一致" in probs[0]


def test_check_refs_wrong_face_path_blocks(tmp_path):
    """11-02 01:24 事故：服务器缺 face_overrides → 身份脸解析成旧 ref2va；路径不同必须拒派"""
    for n in ("hd.png", "old.png"):
        (tmp_path / n).write_bytes(n.encode())
    exp = {"shots": {"ep02-S1": [{"rel": "hd.png", "sha": _sha(b"hd.png")}]}}
    probs = IB.check_refs("ep02-S1", ["old.png"], expected=exp, root=tmp_path)
    assert probs and "路径不一致" in probs[0]


def test_ready_requires_zero_block_and_refs_match(tmp_path):
    p = tmp_path / "assets_ready.json"
    p.write_text(json.dumps({"gpu36": {"pushed": True, "ready": False}}), encoding="utf-8")
    r = SY.write_ready_flag("gpu36", {"total": 50, "server_blocked": 0, "refs_mismatch": 3, "ok": False, "at": "t"}, path=p)
    assert r["ready"] is False and r["preflight_dryrun_ok"] is False and r["pushed"] is True
    r = SY.write_ready_flag("gpu36", {"total": 50, "server_blocked": 1, "refs_mismatch": 0, "ok": False, "at": "t"}, path=p)
    assert r["ready"] is False and r["preflight_dryrun_ok"] is False
    r = SY.write_ready_flag("gpu36", {"total": 50, "server_blocked": 0, "refs_mismatch": 0, "ok": True, "at": "t"}, path=p)
    assert r["ready"] is True and r["preflight_dryrun_ok"] is True and r["refs_match"] is True


def test_deps_rel_of_skips_runtime_dirs():
    import deps
    assert deps.rel_of(deps.ROOT / "data/looks/face_overrides.json") == "data/looks/face_overrides.json"
    assert deps.rel_of(deps.ROOT / "data/producer/attempts.json") is None
    assert deps.rel_of(deps.ROOT / "tools/x.py") is None


def test_producer_render_calls_refs_guard_before_submit():
    """K-OPS-F03 静态检查：FrameExec.render 里 refs_guard 在 UF._run（提交）之前"""
    s = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    body = s[s.index("class FrameExec"):s.index("class FakeFrameExec")]
    assert "refs_guard(self.p, sid, job)" in body
    assert body.index("refs_guard(self.p, sid, job)") < body.index("UF._run(client")


def test_factory_has_no_tunnel_ports():
    """K-OPS-F01：工厂代码不许出现隧道端口 / 跨机 ssh 打分"""
    for f in (ROOT / "tools/factory").glob("*.py"):
        t = f.read_text(encoding="utf-8")
        for port in ("18188", "18189", "18191", "18288", "18289", "18290", "18388"):
            assert port not in t, f"{f.name} 含隧道端口 {port}"


def test_full_score_tries_resident_clip_first():
    """K-OPS-F04：服务器 full_score 先走本机常驻 CLIP（127.0.0.1:8872），不在才退单次子进程；常驻服务比对代码 sha"""
    import ast
    sys.path.insert(0, str(ROOT / "tools/gen_contract"))
    import remote_score as RS
    ast.parse(RS._FULL)
    assert RS._FULL.index('/measure"') < RS._FULL.index('subprocess.run([CPY, "clip_srv.py"')
    s = (ROOT / "tools/gen_contract/clip_srv.py").read_text(encoding="utf-8")
    assert "def serve(" in s and '"--serve"' in s and "boot_sha" in s and '"127.0.0.1"' in s
    assert "OMP_NUM_THREADS" in s.split("def ")[0]      # K-OPS-V13：模块头先限线程


def test_clip_resident_script_pins_gpu2_on_gpu36_only():
    t = (ROOT / "ops/factory/clip_resident.sh").read_text(encoding="utf-8")
    assert "NS_CLIP_DEVICE=cpu" in t and "8872" in t        # 07:5x 起 CPU 常驻，不占 GPU2
    assert "rm -" not in t                               # 不删文件


def test_outbox_format_matches_netfix(tmp_path):
    """K-OPS-F05：每个结果一个目录 + manifest.json（sha / size / prio）+ .done 最后写；图片带 512px 缩略图（prio 1）"""
    import outbox as OB
    from PIL import Image
    root = tmp_path / "repo"
    (root / "data/renders/ep02/S9/takes").mkdir(parents=True)
    Image.new("RGB", (1024, 768), (10, 20, 30)).save(root / "data/renders/ep02/S9/takes/v7.png")
    (root / "data/renders/ep02/S9/takes.json").write_text("{}", encoding="utf-8")
    box = tmp_path / "outbox"
    d = OB.write("first:ep02-S9", "take", ["data/renders/ep02/S9/takes.json", "data/renders/ep02/S9/takes/v7.png"],
                 host="gpu36", box=box, root=root)
    assert d.name.endswith("_000001_first_ep02-S9_take") and (d / ".done").exists()
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert m["host"] == "gpu36" and m["obj"] == "first:ep02-S9" and m["event"] == "take" and "+09:00" in m["created"]
    pr = {f["rel"]: f["prio"] for f in m["files"]}
    assert pr == {"data/renders/ep02/S9/takes.json": 0, "data/renders/ep02/S9/takes/v7.png": 2,
                  "data/renders/ep02/S9/takes/v7.png.thumb.jpg": 1}
    for f in m["files"]:
        assert hashlib.sha256((d / "files" / f["rel"]).read_bytes()).hexdigest() == f["sha256"]
    assert not list(box.glob("*.part"))
    (d / ".acked").write_bytes(b"")
    assert OB.archive_acked(box, keep_hours=-1) == 1 and (box / "_acked").is_dir()   # 归档不删


def test_producer_emits_outbox_after_postflight():
    s = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    body = s[s.index("    def _postflight("):s.index("    def activate(")]
    assert "outbox_emit(sid, stage, n, file_rel)" in body
    fn = s[s.index("def outbox_emit("):s.index("def refs_guard(")]
    assert "OFFLINE_SELF" in fn and "except Exception" in fn


def test_sync_push_never_sends_code_dirs(monkeypatch):
    """D9 / K-OPS-F06：sync push 只补数据；代码目录（含 config/）的差异只报 code_drift，随 sv deploy 走"""
    monkeypatch.setattr(SY, "laptop_need", lambda h, e: {"files": {"data/a.png": "x", "config/recipes/image_framing.json": "y"}, "blocked": 0})
    monkeypatch.setattr(SY, "remote_diff", lambda h, n: {"absent": ["data/a.png"], "changed": ["config/recipes/image_framing.json"]})
    monkeypatch.setattr(SY, "_save", lambda *a: None)
    r = SY.push("gpu36", dry=True)
    assert r["code_drift"] == ["config/recipes/image_framing.json"]
    s = (ROOT / "tools/factory/sync.py").read_text(encoding="utf-8")
    assert 'todo = [r for r in allx if not r.startswith(CODE_PREFIX)]' in s


def test_library_content_addressed(tmp_path, monkeypatch):
    """D2：按 sha256 存，同内容只存一份，get 取回字节一致"""
    import library as LB
    monkeypatch.setenv("NS_LIBRARY", str(tmp_path / "lib"))
    f = tmp_path / "a.png"
    f.write_bytes(b"abc")
    s = LB.put(f)
    assert s == _sha(b"abc") and LB.has(s) and LB.path_of(s).parent.name == s[:2]
    assert LB.put(f) == s and len(list((tmp_path / "lib/objects").rglob("*"))) == 2   # 目录 + 1 个对象
    assert LB.get(s, tmp_path / "out/b.png").read_bytes() == b"abc"


def _decision_root(tmp_path):
    import decisions_guard as DG
    for r in DG.REQUIRED:
        p = tmp_path / r.format(run="run_x")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    (tmp_path / "config/pipeline/run.json").write_text('{"run_id": "run_x"}', encoding="utf-8")
    return DG


def test_decision_files_fail_closed(tmp_path):
    """K-OPS-F09：必需决策文件缺 / 坏、可选覆盖坏、hold 坏 → 拒派；服务器另须期望 refs 表"""
    DG = _decision_root(tmp_path)
    assert DG.problems(tmp_path, server=False) == []
    assert any("expected_refs" in x for x in DG.problems(tmp_path, server=True))
    (tmp_path / "data/looks/face_overrides.json").unlink()
    assert any("face_overrides" in x for x in DG.problems(tmp_path, server=False))
    (tmp_path / "data/looks/face_overrides.json").write_text("{", encoding="utf-8")       # 截断
    assert any("读不出" in x and "face_overrides" in x for x in DG.problems(tmp_path, server=False))
    (tmp_path / "data/looks/face_overrides.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data/looks/hub_extra_looks.json").write_text("[[", encoding="utf-8")
    assert any("hub_extra_looks" in x for x in DG.problems(tmp_path, server=False))
    (tmp_path / "data/looks/hub_extra_looks.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data/autopilot").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/autopilot/lookA_hold.json").write_text("nope", encoding="utf-8")
    assert any("hold" in x for x in DG.problems(tmp_path, server=False))
    (tmp_path / "data/autopilot/lookA_hold.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config/pipeline/run.json").unlink()
    assert any("run.json" in x for x in DG.problems(tmp_path, server=False))


def test_overlay_doc_raises_on_corrupt_not_silent(tmp_path):
    sys.path.insert(0, str(ROOT / "services/agent"))
    from ns_agent import asset_refs as AR
    assert AR._overlay_doc(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    import pytest
    with pytest.raises(AR.DecisionFileError):
        AR._overlay_doc(bad)


def test_producer_dispatch_checks_decision_files_first():
    s = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    d = s[s.index("    def dispatch_frames("):]
    assert d.index("decision_file_problems()") < d.index("backlog = len(self.scoring)")
    fn = s[s.index("def decision_file_problems("):s.index("def refs_guard(")]
    assert "return [" in fn                       # 校验器自身出错也算问题（失败关闭）


def test_refs_table_missing_shot_blocks(tmp_path):
    assert IB.check_refs("ep09-S9", ["a.png"], expected={"shots": {"ep01-S1": []}}, root=tmp_path)


def test_decisions_guard_checks_code_sv_on_server(tmp_path):
    """K-OPS-X08 接 F09：服务器上本机代码版本低于 min_code_sv / 读不到 → 拒派；笔记本不查"""
    import shutil
    DG = _decision_root(tmp_path)
    (tmp_path / "tools/autopilot").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "tools/autopilot/policy.py", tmp_path / "tools/autopilot/policy.py")
    (tmp_path / "config/policies").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "config/policies/handback.yaml", tmp_path / "config/policies/handback.yaml")
    (tmp_path / "data/factory/inbox").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/factory/inbox/expected_refs.json").write_text("{}", encoding="utf-8")
    assert any("system_version" in x for x in DG.problems(tmp_path, server=True))       # 没有版本文件 → 失败关闭
    (tmp_path / "data/system_version.txt").write_text('{"id": "sv-20000101-01"}', encoding="utf-8")
    assert any("低于" in x for x in DG.problems(tmp_path, server=True))
    (tmp_path / "data/system_version.txt").write_text('{"id": "sv-20991231-99"}', encoding="utf-8")
    assert DG.problems(tmp_path, server=True) == []
    assert DG.problems(tmp_path, server=False) == []


def test_rssh_offline_aliases_are_local(monkeypatch):
    """gpu36 上 OFFLINE_ALIASES=gpu33：full_score("gpu33") 必须当本机执行（11-02 sv-06 P0：漏了 → gpu36 每单 score_infra）"""
    sys.path.insert(0, str(ROOT / "tools/netfix"))
    import rssh
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    monkeypatch.setenv("OFFLINE_ALIASES", "gpu33")
    assert rssh._local_self("gpu33") == "self" and rssh._local_self("root@gpu33") == "self"
    monkeypatch.setenv("OFFLINE_ALIASES", "")
    assert rssh._local_self("gpu33") == "other"
    assert rssh._local_self("gpu36") == "self"
