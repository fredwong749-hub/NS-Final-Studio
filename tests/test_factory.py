"""FACTORY（L-099b，docs/master/FRAMEWORK_REFRAME.md）：deps / inbox / sync 的离线测试（不连服务器）。
K-OPS-F02 交还闸门、K-OPS-F03 派单前 refs sha 校验。"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/factory"))

import inbox as IB  # noqa: E402
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("factory_sync", ROOT / "tools/factory/sync.py")   # 名字 sync 与 series10_video/sync.py 重名（script_name_guard）
SY = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(SY)


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
    """11-02 01:24 事故：服务器缺 face_overrides → 身份脸解析成旧 ref2va；身份脸不在本镜期望里必须拒派"""
    d = tmp_path / "data/assets/identity_refs/lin_wan"
    d.mkdir(parents=True)
    (d / "hd.png").write_bytes(b"hd")
    (d / "old.png").write_bytes(b"old")
    hd, old = "data/assets/identity_refs/lin_wan/hd.png", "data/assets/identity_refs/lin_wan/old.png"
    exp = {"shots": {"ep02-S1": [{"rel": hd, "sha": _sha(b"hd")}]}}
    probs = IB.check_refs("ep02-S1", [old], expected=exp, root=tmp_path)
    assert probs and "身份脸不对" in probs[0]
    assert IB.check_refs("ep02-S1", [hd, "data/x/crop.png"], expected=exp, root=tmp_path) == []   # 变体多挂的非身份图不拦


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


def test_clip_resident_script_per_host():
    """gpu36 CPU 常驻（GPU2 给看图）；gpu33 钉 GPU1、8 线程、绑 80-95 核（总调度 11-02 15:4x，K-OPS-F17）；nohup 脚本和 systemd env 同参数"""
    t = (ROOT / "ops/factory/clip_resident.sh").read_text(encoding="utf-8")
    assert "8872" in t and "rm -" not in t                                       # 不删文件
    assert 'gpu36) GPU=""; DEV=cpu; TH=16' in t
    assert "gpu33) GPU=1; DEV=cuda; TH=8; NICE=10; CPUS=80-95" in t and "GPU=2" not in t   # gpu33 GPU2 坏卡永不用
    e33 = (ROOT / "ops/factory/systemd/env/gpu33.env").read_text(encoding="utf-8")
    e36 = (ROOT / "ops/factory/systemd/env/gpu36.env").read_text(encoding="utf-8")
    assert "CLIP_GPU=1" in e33 and "CLIP_DEV=cuda" in e33 and "taskset -c 80-95" in e33
    assert "CLIP_GPU=" + chr(10) in e36 and "CLIP_DEV=cpu" in e36
    svc = (ROOT / "ops/factory/systemd/ns-clip-resident.service").read_text(encoding="utf-8")
    assert "$CLIP_PY" in svc and "$CLIP_GPU" in svc


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
    (tmp_path / "config/pipeline").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/pipeline/run.json").write_text('{"run_id": "run_x"}', encoding="utf-8")   # 兼容期旧位置也认
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


def test_check_refs_per_run_tables(tmp_path):
    """多剧：第二季镜号和第一季重名，按 run 分表查（K-OPS-F03 修订）"""
    d = tmp_path / "data/assets/identity_refs/x"
    d.mkdir(parents=True)
    (d / "a.png").write_bytes(b"A")
    (d / "b.png").write_bytes(b"B")
    a, b = "data/assets/identity_refs/x/a.png", "data/assets/identity_refs/x/b.png"
    exp = {"primary": "series10_v1", "shots": {"ep01-S1": [{"rel": a, "sha": _sha(b"A")}]},
           "runs": {"series10_s2": {"ep01-S1": [{"rel": b, "sha": _sha(b"B")}]}}}
    assert IB.check_refs("ep01-S1", [a], expected=exp, root=tmp_path, run="series10_v1") == []
    assert IB.check_refs("ep01-S1", [b], expected=exp, root=tmp_path, run="series10_s2") == []
    assert IB.check_refs("ep01-S1", [a], expected=exp, root=tmp_path, run="series10_s2")     # 拿第一季的脸出第二季 → 拒派
    assert IB.check_refs("ep01-S1", [b], expected=exp, root=tmp_path, run="series10_s9")     # 表里没这部剧 → 拒派


def test_deploy_pushes_expected_table_built_from_snapshot():
    s = (ROOT / "tools/qa/system_version.py").read_text(encoding="utf-8")
    assert "def build_expected(" in s and "SNAP_BASE / sv" in s
    d = s[s.index("def deploy_host("):s.index("def deploy(sv")]
    assert d.index("expected_refs.json") < d.index("server_deps.py") < d.index("decisions_guard.py")


def test_state_paths_compat_read_and_atomic_write(tmp_path):
    """§10：先读新位置；只有旧 → 读旧 + legacy_reads 事件（不静默）；写只落新位置；都不在 → raise"""
    import state_paths as SP
    old = tmp_path / "config/netfix/partition.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"images": {"gpu33": [1]}}', encoding="utf-8")
    assert SP.read_state("netfix/partition", root=tmp_path)["images"]["gpu33"] == [1]
    ev = (tmp_path / "data/state/legacy_reads.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(ev[-1])["name"] == "netfix/partition" and json.loads(ev[-1])["old_path"] == "config/netfix/partition.json"
    SP.write_state("netfix/partition", {"images": {"gpu33": [2]}}, root=tmp_path)
    assert SP.read_state("netfix/partition", root=tmp_path)["images"]["gpu33"] == [2]            # 新的优先
    assert len((tmp_path / "data/state/legacy_reads.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 1
    import pytest
    with pytest.raises(SP.StateError):
        SP.read_state("pipeline/runs", root=tmp_path)
    with pytest.raises(SP.StateError):
        SP.state_path("nope/x", root=tmp_path)


def test_k_ops_f17_scoring_subprocesses_are_throttled():
    """K-OPS-F17（总调度 11-02 15:2x）：gpu33 load 300、score_remote 412 线程 1452% CPU 饿死 sshd。
    出图机器上的打分子进程（score_remote / hands_remote / clip_srv 单次）必须限线程 + nice + 绑核。"""
    import re
    src = (ROOT / "tools/gen_contract/remote_score.py").read_text(encoding="utf-8")
    calls = re.findall(r'subprocess\.run\(\[(?:IDM|HAND|CPY), "(?:score_remote|hands_remote|clip_srv)\.py"[^\n]*\n?[^\n]*', src)
    assert calls, "没找到打分子进程调用"
    for c in calls:
        assert "preexec_fn=_lim" in c and "SENV" in c, c
    assert src.count("def _lim():") >= 2 and "os.nice(10)" in src and "sched_setaffinity" in src


def test_clip_resident_only_restarts_for_deployed_code(tmp_path, monkeypatch):
    """常驻 CLIP：本目录代码被笔记本未发版代码覆盖 → 不退出（当次 409 走单次子进程）；等于部署仓库那份 → 退出按新版重启"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("clip_srv_t", ROOT / "tools/gen_contract/clip_srv.py")
    CS = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CS)
    src = tmp_path / "repo"
    (src / "services/agent/ns_agent/gen_contract").mkdir(parents=True)
    (src / "tools/gen_contract").mkdir(parents=True)
    (src / "services/agent/ns_agent/gen_contract/metrics.py").write_text("m2", encoding="utf-8")
    (src / "tools/gen_contract/clip_srv.py").write_text("c2", encoding="utf-8")
    import hashlib
    h = lambda b: hashlib.sha256(b).hexdigest()
    assert CS.code_matches_src({"metrics.py": h(b"m2"), "clip_srv.py": h(b"c2")}, str(src))
    assert not CS.code_matches_src({"metrics.py": h(b"laptop"), "clip_srv.py": h(b"c2")}, str(src))
    assert CS.code_matches_src({"metrics.py": "x", "clip_srv.py": "y"}, "")          # 没配部署仓库：旧行为
    sh = (ROOT / "ops/factory/clip_resident.sh").read_text(encoding="utf-8")
    assert "NS_CLIP_CODE_SRC=$PROD" in sh


def test_sync_auto_repushes_when_remote_table_differs(monkeypatch, tmp_path):
    """11-02 16:02：gpu36 期望表被写成 0 字节，推送记录却是成功 → auto 不能只看记录，要核服务器上的 sha，不一致就重推"""
    import json as _j
    exp = tmp_path / "expected_refs.json"
    exp.write_bytes(b'{"shots": {}}')
    monkeypatch.setattr(IB, "build", lambda *a, **k: {"shots": {}, "counts": {}})
    monkeypatch.setattr(IB, "EXPECTED", exp)
    monkeypatch.setattr(SY, "ROOT", tmp_path)
    monkeypatch.setattr(SY, "_save", lambda *a, **k: None)
    key = SY._table_key({"shots": {}, "counts": {}})
    (tmp_path / "data/factory").mkdir(parents=True)
    (tmp_path / "data/factory/expected_pushed.json").write_text(
        _j.dumps({"gpu36": key, "gpu36:sha": _sha(b'{"shots": {}}')}), encoding="utf-8")
    pushed = []
    monkeypatch.setattr(SY, "push", lambda h, *a, **k: pushed.append(h) or {"sent": 0})
    remote = {"sha": _sha(b"")}
    monkeypatch.setattr(SY, "rrun", lambda h, cmd, **k: remote["sha"] + "  x")
    SY.auto(hosts=("gpu36",))
    assert pushed == ["gpu36"]                                     # 服务器上是空文件 → 重推
    remote["sha"] = _sha(b'{"shots": {}}')
    SY.auto(hosts=("gpu36",))
    assert pushed == ["gpu36"]                                     # 一致 → 不动
    assert "sha256sum -c" in SY.verified_install("/x/e.json", b"{}")
