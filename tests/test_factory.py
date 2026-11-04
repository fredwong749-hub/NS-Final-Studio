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
    assert RS._FULL.index('/measure"') < RS._FULL.index('subprocess.run([CPY, os.path.join(SRC, "tools/gen_contract/clip_srv.py")')   # K-OPS-F18
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
    assert d.index("decision_file_problems(self.p.run_id)") < d.index("backlog = len(self.scoring)")
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
    calls = re.findall(r'subprocess\.run\(\[(?:IDM|HAND|CPY), os\.path\.join\(SRC, "[\w/]+(?:score_remote|hands_remote|clip_srv)\.py"\)[^\n]*\n?[^\n]*', src)   # K-OPS-F18 仓库目录
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



def test_k_ops_f18_no_bypass_script_dirs():
    """K-OPS-F18（总调度 11-02 16:5x）：服务器上生产调用的脚本只许来自仓库部署目录——arch_scan bypass_script 能抓三种写法，
    remote_score / clip 常驻全仓 0 处（imggen/score_remote.py 旁路拷贝让 sv-13 的补边修复没生效）"""
    sys.path.insert(0, str(ROOT / "tools/qa"))
    import arch_scan as A
    src = ('import subprocess\nsubprocess.run([IDM, "score_remote.py", "-"], cwd=R, timeout=5)\n'
           'p = "/root/work/fredw/imggen/score_remote.py"\nok = "/root/work/fredw/offline_20261101/repo/tools/a.py"\n'
           'S = """\nsubprocess.run([HAND, "hands_remote.py"], cwd=R)\nos.system("cd {R} && {IDM} score_remote.py -")\n"""\n')
    assert A.scan_source("tools/x.py", src)["bypass_script"] == 4
    for f in ("tools/gen_contract/remote_score.py", "tools/gen_contract/clip_srv.py", "tools/series10_imggen/server_deploy.py"):
        assert A.scan_source(f, (ROOT / f).read_text(encoding="utf-8"))["bypass_script"] == 0, f
    sh = (ROOT / "ops/factory/clip_resident.sh").read_text(encoding="utf-8")
    assert "cp -a" not in sh and "$PROD/tools/gen_contract/clip_srv.py --serve" in sh
    svc = (ROOT / "ops/factory/systemd/ns-clip-resident.service").read_text(encoding="utf-8")
    assert "/bin/cp" not in svc and "repo/tools/gen_contract/clip_srv.py --serve" in svc
    import remote_score as RS
    assert RS.srv_repo("gpu33").endswith("/repo") and RS.srv_repo("gpu36").endswith("/repo")


def test_k_ops_f20_pause_single_source_runs_json(tmp_path, monkeypatch):
    """K-OPS-F20（总调度 11-02 17:0x）：暂停状态只有一个来源 = runs.json status。
    producer 每拍按它判（control 被改回 paused=false 也不派）；dispatch 对暂停中的 run 把 control 写成 paused + owner"""
    import json as _j
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    sys.path.insert(0, str(ROOT / "tools/netfix"))
    import producer as P
    import dispatch as D
    (tmp_path / "config/pipeline").mkdir(parents=True)
    runs = {"primary": "series10_v1", "runs": {"series10_v1": {"status": "producing"}, "series10_s2": {"status": "paused"}}}
    (tmp_path / "config/pipeline/runs.json").write_text(_j.dumps(runs), encoding="utf-8")
    assert P.run_status(tmp_path, "series10_s2") == "paused" and P.run_status(tmp_path, "series10_v1") == "producing"
    assert P.run_status(tmp_path / "nope", "series10_s2") is None
    ctl = tmp_path / "data/producer/runs/series10_s2/control.json"
    ctl.parent.mkdir(parents=True)
    ctl.write_text(_j.dumps({"paused": False, "only": ["ep02-S1"]}), encoding="utf-8")
    monkeypatch.setattr(D, "RUNS", tmp_path / "config/pipeline/runs.json")
    monkeypatch.setattr(D, "ROOT", tmp_path)
    assert D.paused_runs() == ["series10_s2"]
    new = D.pause_run_control("series10_s2")
    assert new["paused"] is True and new["reason_kind"] == "owner" and new["only"] == ["ep02-S1"]
    assert D.pause_run_control("series10_s2") is None                     # 已是 owner 暂停：不重复写
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert "st = run_status(self.p.root, self.p.run_id)" in src.split("def ctrl(self) -> dict:")[1].split("def ledger")[0]


def test_alignment_step2_prompt_sha_compared():
    """ALIGNMENT 第 2 步：同一镜不管在哪台编译，提示词 sha 都相同；verify 比对出不一致的镜"""
    import deps as DP
    assert DP.prompt_sha({"prompt": "a"}) == _sha(b"a")[:16]
    lap = {"ep01-S1": {"prompt_sha": "aa"}, "ep01-S2": {"prompt_sha": "bb"}, "ep01-S3": {}}
    srv = {"ep01-S1": {"prompt_sha": "aa"}, "ep01-S2": {"prompt_sha": "cc"}, "ep01-S3": {"prompt_sha": "dd"}}
    assert SY.prompt_mismatch(lap, srv) == {"ep01-S2": {"laptop": "bb", "server": "cc"}}


def test_dispatch_push_carries_no_code():
    """K-OPS-F18：push_server_control 只推派单输入数据，不推 .py（代码只经 deploy）"""
    sys.path.insert(0, str(ROOT / "tools/netfix"))
    import dispatch as D
    assert not [f for f in D.PUSH_FILES if f.endswith(".py")]


def test_k_ops_f21_video_hosts_generated_from_partition(tmp_path, monkeypatch):
    """K-OPS-F21：video/hosts.json 由 partition.json video 分区生成；分区没有的集不派（不再 pick_host）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("night_t", ROOT / "tools/series10_video/night.py")
    N = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(N)
    monkeypatch.setattr(N, "VID", tmp_path)
    monkeypatch.setattr(N, "LOG", tmp_path / "night.log")
    (tmp_path / "hosts.json").write_text('{"7": "gpu36", "10": "gpu36"}', encoding="utf-8")
    part = {"video": {"gpu33": [1, 7], "gpu36": [10]}}
    assert N.sync_hosts_from_partition(part) == {"1": "gpu33", "7": "gpu33", "10": "gpu36"}
    import json as _j
    assert _j.loads((tmp_path / "hosts.json").read_text(encoding="utf-8"))["7"] == "gpu33"
    src = (ROOT / "tools/series10_video/night.py").read_text(encoding="utf-8")
    assert "else pick_host(st)" not in src and "sync_hosts_from_partition()" in src.split("def loop_once")[1][:200]


def test_repart_refuses_move_to_host_without_takes():
    """K-OPS-F21 / E25（总调度 17:3x）：改分区必须先过 repart_check——集搬到本机没有当前版本的机器就拒绝（16:31 ep02/04/06 → gpu33 重出 94 次）"""
    import repart as RP
    old = {"images": {"gpu33": [1, 3], "gpu36": [2, 4]}, "video": {"gpu33": [1, 3], "gpu36": [2, 4]}}
    bad = {"images": {"gpu33": [1, 2, 3, 4], "gpu36": []}, "video": {"gpu33": [1, 2, 3, 4], "gpu36": []}}
    assert RP.moved(old["images"], bad["images"]) == {"gpu33": [2, 4]}

    class R:
        def __init__(self, have):
            self.have = have

        def __call__(self, h, cmd, **k):
            import types
            return types.SimpleNamespace(stdout=json.dumps(sorted(self.have[h])))
    run = R({"gpu33": {1, 3}, "gpu36": {2, 4}})
    assert RP.check(old, bad, run=run)                                   # gpu33 没有 ep02/04 → 拒绝
    ok = {"images": {"gpu33": [1, 3], "gpu36": [2, 4]}, "video": {"gpu33": [1, 3], "gpu36": [2, 4]}}
    assert RP.check(old, ok, run=run) == []
    assert RP.check(old, bad, run=R({"gpu33": {1, 2, 3, 4}, "gpu36": {2, 4}})) == []   # 两边都有 → 放行


def test_k_ops_f22_compile_only_released_code():
    """K-OPS-F22（总调度 17:4x）：cut 冻结中 / 工作树编译代码与最新发版 tag 不同 → episode_pipeline 不重编 first_frame_jobs.json；
    服务器部署树（无 git）放行；冻结解除后会重试（compile_frozen 在重试状态里）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ep_pipe_t", ROOT / "tools/autopilot/episode_pipeline.py")
    EP = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    spec.loader.exec_module(EP)

    class SV:
        def __init__(self, locked=None, drift=(), tags=("sv-20261102-13",), boom=False):
            self.locked, self.drift, self.tags, self.boom = locked, list(drift), list(tags), boom

        def cut_locked(self):
            if self.boom:
                raise RuntimeError("no git")
            return self.locked

        def sv_tags(self):
            return self.tags

        def drift_files(self, tag, dirs):
            assert "services/agent/ns_agent" in dirs and "tools/pipeline" in dirs
            return self.drift
    assert "冻结" in EP.compile_gate(SV(locked={"active": True}))
    assert "不同" in EP.compile_gate(SV(drift=["services/agent/ns_agent/frame_job.py"]))
    assert EP.compile_gate(SV()) is None
    assert EP.compile_gate(SV(boom=True)) is None
    src = (ROOT / "tools/autopilot/episode_pipeline.py").read_text(encoding="utf-8")
    assert '"compile_frozen"))' in src and src.count("why = compile_gate()") == 2


def test_k_ops_f24_only_legacy_run_uses_unprefixed_paths(tmp_path):
    """K-OPS-F24（总调度 18:4x）：primary 切到 series10_v2 后，只有 legacy_unprefixed_run（series10_v1）用不带前缀的旧路径，
    V2 一律 data/renders/<run>/、data/import/runs/<run>/、带前缀对象 id——不会写进 V1 的目录"""
    import json as _j
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import runs as RN
    import producer as P
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(_j.dumps({
        "primary": "series10_v2", "legacy_unprefixed_run": "series10_v1",
        "runs": {"series10_v1": {"status": "frozen"}, "series10_v2": {"status": "preparing"}}}), encoding="utf-8")
    assert RN.legacy_run(tmp_path) == "series10_v1" and RN.is_legacy("series10_v1", tmp_path) and not RN.is_legacy(None, tmp_path)
    assert RN.import_path(None, tmp_path) == tmp_path / "data/import/runs/series10_v2/script_v2.json"
    assert RN.import_path("series10_v1", tmp_path) == tmp_path / "data/import/script_v2.json"
    assert RN.obj_id(None, "first", "ep01-S1", tmp_path) == "series10_v2/first:ep01-S1"
    assert RN.ready_paths("series10_v2", tmp_path) == [tmp_path / "data/autopilot/runs/series10_v2/ready_episodes.json"]
    pv2 = P.Paths(root=tmp_path, run_id="series10_v2")
    assert pv2.renders == tmp_path / "data/renders/series10_v2" and not pv2.primary
    assert P.Paths(root=tmp_path, run_id="series10_v1").renders == tmp_path / "data/renders"
    assert P.run_env("series10_v2", tmp_path)["NS_RENDERS_DIR"].endswith("series10_v2")
    assert P.run_env("series10_v1", tmp_path) == {}


def test_run_path_entries(tmp_path):
    """AUDIT-M I-14 / I-15：按剧取路径的唯一入口——script_path / renders_dir / looks_path / asset_manifest（V2 不读 V1 树）"""
    import json as _j
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import runs as RN
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(_j.dumps({
        "primary": "series10_v2", "legacy_unprefixed_run": "series10_v1",
        "runs": {"series10_v1": {"status": "archived"}, "series10_v2": {"status": "preparing", "assets_manifest": "assets_v2/manifest.json"}}}),
        encoding="utf-8")
    assert RN.renders_dir(root=tmp_path) == tmp_path / "data/renders/series10_v2"
    assert RN.renders_dir("series10_v1", tmp_path) == tmp_path / "data/renders"
    assert RN.script_path(root=tmp_path) == tmp_path / "data/import/runs/series10_v2/script_v2.json"
    assert RN.looks_path(root=tmp_path) == tmp_path / "data/pipeline/runs/series10_v2/looks"
    assert RN.looks_path("series10_v1", tmp_path) == tmp_path / "data/looks"
    assert RN.asset_manifest(root=tmp_path) == tmp_path / "assets_v2/manifest.json" and RN.asset_manifest("series10_v1", tmp_path) is None


def test_k_ops_f23_v2_manifest_only_and_no_server_derived(tmp_path, monkeypatch):
    """L-125 / L-126（C10 / C1 / C7）：资产包模式下 face_of / sheet_of / scene_ref / item_image 只读清单（sha 对上才算），
    清单空 = 返回无（preflight 挡住出图）；清单外参考 I11 挡；服务器上派生参考图只用现成的、没有就挡，不本地生成"""
    import hashlib
    import json as _j
    sys.path.insert(0, str(ROOT / "services/agent"))
    from ns_agent import asset_refs as AR
    face = tmp_path / "assets_v2/characters/f/face.png"
    face.parent.mkdir(parents=True)
    face.write_bytes(b"png-face")
    man = {"characters": {}, "scenes": {}}
    (tmp_path / "assets_v2/manifest.json").write_text(_j.dumps(man), encoding="utf-8")
    cfg = {"projects": {"v2": {"assets_manifest": "assets_v2/manifest.json", "crop_dir": "data/pipeline/runs/v2/images/refcrops",
                               "board_dir": "data/pipeline/runs/v2/images/refboards"}}}
    (tmp_path / "asset_refs.json").write_text(_j.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(AR, "ROOT", tmp_path)
    monkeypatch.setattr(AR, "CFG", tmp_path / "asset_refs.json")
    assert AR.face_of("v2", "f") is None                                         # 空清单：项目方挑定前没有身份脸
    man["characters"]["f"] = {"face": {"file": "assets_v2/characters/f/face.png", "sha256": hashlib.sha256(b"png-face").hexdigest()},
                              "looks": {"A": {"sheet": {"file": "assets_v2/characters/f/sheet.png", "sha256": "bad"}}}}
    (tmp_path / "assets_v2/manifest.json").write_text(_j.dumps(man), encoding="utf-8")
    assert AR.face_of("v2", "f") == "assets_v2/characters/f/face.png"
    assert AR.sheet_of("v2", "f", "A") is None                                   # sha 不符 = 不算
    bd = tmp_path / "data/pipeline/runs/v2/images/refboards"      # PROMPTFIX 20:3x：派生图须在 sha 账本里（_derived_index.json）
    bd.mkdir(parents=True)
    (bd / "b.png").write_bytes(b"board")
    AR.record_derived(bd / "b.png")
    assert AR.manifest_violations("v2", ["assets_v2/characters/f/face.png", "data/pipeline/runs/v2/images/refboards/b.png"]) == []
    (bd / "b.png").write_bytes(b"changed")
    assert AR.manifest_violations("v2", ["data/pipeline/runs/v2/images/refboards/b.png"])   # 字节不是账本那张 → 挡
    assert AR.manifest_violations("v2", ["assets/characters/lin_wan/old.png"])   # V1 资产 → 挡
    assert AR.manifest_violations("nomanifest", ["anything.png"]) == []           # 没配清单的项目不受影响
    (tmp_path / "assets_v2/manifest.json").write_text("{broken", encoding="utf-8")
    assert AR.manifest_violations("v2", ["x.png"])                                # 清单读坏 = 失败关闭
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    import pytest
    with pytest.raises(AR.DerivedRefMissing):
        AR._derived_on_server(tmp_path / "data/pipeline/runs/v2/images/refcrops/x.png")
    out = tmp_path / "data/pipeline/runs/v2/images/refcrops/y.png"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"y")
    AR.record_derived(out)                                                    # 账本登记过的（笔记本那张）才用
    assert AR._derived_on_server(out) == "data/pipeline/runs/v2/images/refcrops/y.png"
    monkeypatch.delenv("OFFLINE_SELF")
    monkeypatch.delenv("NS_FACTORY_HOST", raising=False)
    assert AR._derived_on_server(tmp_path / "nope.png") is None                   # 笔记本：照常生成
    src = (ROOT / "services/agent/ns_agent/gen_contract/preflight.py").read_text(encoding="utf-8")
    assert '"I11"' in src and "manifest_violations" in src


def test_v2_identity_face_fail_closed_no_v1_fallback():
    """VQAGATE / 总调度 19:0x：V2 没登记的角色，身份脸一律“无”——不回退 config faces / face_overrides / V1 资产（真实配置）"""
    sys.path.insert(0, str(ROOT / "services/agent"))
    sys.path.insert(0, str(ROOT / "tools/gen_contract"))
    from ns_agent import asset_refs as AR
    import remote_score as RS
    assert AR.manifest_rel("series10_v2") == "assets_v2/manifest.json"
    assert AR.face_of("series10_v2", "lin_wan") is None and AR.face_of("series10_v2", "gu_chen") is None
    assert "lin_wan" not in RS.local_faces("series10_v2")
    assert not (AR.project_cfg("series10_v2").get("faces") or {}) and not AR.project_cfg("series10_v2").get("inherits")
    src = (ROOT / "services/api/ns_api/character_hub.py").read_text(encoding="utf-8")
    assert "manifest_mode = bool(R.manifest_rel(project))" in src


def test_decisions_guard_manifest_mode(tmp_path):
    """L-125：资产包模式的剧（runs.json assets_manifest）只要求清单 + 资产配置，不要求 V1 的 data/looks 覆盖文件；清单坏 = 拦"""
    import json as _j
    import decisions_guard as DG
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/recipes").mkdir(parents=True)
    (tmp_path / "config/recipes/asset_refs.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config/pipeline/runs.json").write_text(_j.dumps({"primary": "v2", "runs": {"v2": {"assets_manifest": "assets_v2/manifest.json"}}}),
                                                        encoding="utf-8")
    assert DG.problems(tmp_path, server=False, run="v2") == ["缺必需的决策文件 assets_v2/manifest.json"]
    (tmp_path / "assets_v2").mkdir()
    (tmp_path / "assets_v2/manifest.json").write_text("{bad", encoding="utf-8")
    assert "读不出" in DG.problems(tmp_path, server=False, run="v2")[0]
    (tmp_path / "assets_v2/manifest.json").write_text("{}", encoding="utf-8")
    assert DG.problems(tmp_path, server=False, run="v2") == []
    assert any("data/looks" in x for x in DG.problems(tmp_path, server=False, run="v1"))   # 旧剧照旧要求


def test_tests_never_read_real_primary():
    """总调度 19:1x：测试不许依赖真实当前剧（primary 会切换）——conftest 钉 NS_PRIMARY_RUN；测试代码里不许直接读真实 runs.json 的 primary"""
    import re
    assert 'os.environ.setdefault("NS_PRIMARY_RUN"' in (ROOT / "tests/conftest.py").read_text(encoding="utf-8")
    pat = re.compile(r'(?:ROOT|REPO)\s*/\s*"config"\s*/\s*"pipeline"\s*/\s*"runs\.json"\)\.read_text\([^)]*\)\)\.get\("primary"\)')
    bad = [p.name for p in (ROOT / "tests").glob("test_*.py") if pat.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert not bad, bad


def test_l128_owner_controlled_lanes_and_adult_wait(tmp_path):
    """L-128（项目方 19:1x）：local_only = 项目方自有机器（笔记本 + gpu33 + gpu36）都可以；不认识的机器 / 没指定道挡（失败关闭）。
    不变项：成人镜系统 / agent 不自动派，只有项目方在界面触发（owner_triggers.json）才派"""
    import json as _j
    import hosts as H
    assert H.owner_lane("gpu33:0") and H.owner_lane("gpu36:1") and H.owner_lane("laptop:0")
    assert not H.owner_lane("other:0") and not H.owner_lane("")
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import producer as P

    class Sh:
        def __init__(self, i, adult):
            self.id, self.adult = i, adult

    class Ep:
        def __init__(self, shots):
            self.shots = shots

    class Sc:
        episodes = [Ep([Sh("ep01-S1", True), Sh("ep01-S2", False)])]
    assert P.adult_shot_ids(Sc()) == {"ep01-S1"}
    p = P.Paths(root=tmp_path, run_id="v2x")
    assert P.owner_trigger_ids(p) == set()                                    # 没有触发记录 = 一个都不放
    p.pd.mkdir(parents=True)
    (p.pd / "owner_triggers.json").write_text(_j.dumps({"objects": ["first:ep01-S1"]}), encoding="utf-8")
    assert P.owner_trigger_ids(p) == {"first:ep01-S1"}
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert 'o["shot"] in adult_shots and o["id"] not in owner_triggers' in src
    assert 'job.get("route") == "local_only" and not owner_lane(lane)' in src
    hj = _j.loads((ROOT / "config/factory/hosts.json").read_text(encoding="utf-8"))
    assert all(hj["hosts"][h].get("owner_controlled") is True for h in ("gpu33", "gpu36", "laptop"))


def test_arch_scan_hard_import_path_metric():
    """AUDIT-M I-14 / 总调度 19:2x：写死导入稿 / data/looks / data/renders 根目录计入 hard_import_path（基线只许减）；入口文件除外"""
    sys.path.insert(0, str(ROOT / "tools/qa"))
    import arch_scan as A
    src = 'a = "data/import/script_v2.json"\nb = "data/looks/wardrobe.json"\nc = "data/renders"\nd = "data/renders/ep01/S1"\nok = "data/renders/series10_v2"\n'
    assert A.scan_source("tools/x.py", src)["hard_import_path"] == 4
    assert A.scan_source("tools/autopilot/runs.py", src).get("hard_import_path", 0) == 0
    import json as _j
    base = _j.loads((ROOT / "data/sysarch/baseline.json").read_text(encoding="utf-8"))
    assert "hard_import_path" in base.get("totals", {})


def test_a05_vqa_config_broken_fails_closed(tmp_path, monkeypatch):
    """A-05：config/vqa.json 读不出 / 读坏 → 闸门仍执行、Q9 直接判不过（以前 {} = 闸门放行）"""
    sys.path.insert(0, str(ROOT / "services/agent"))
    from ns_agent import vqa as VQ
    from ns_agent.gen_contract import postflight as PF
    bad = tmp_path / "vqa.json"
    bad.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(VQ, "CFG", bad)
    c = VQ.cfg()
    assert c.get("_config_error") and c["gate"]["enforce"] is True
    st, d, _ = PF._q9_item(VQ, ("untested", "没有结果", {}))
    assert st == "fail" and "失败关闭" in d
    monkeypatch.setattr(VQ, "CFG", tmp_path / "missing.json")
    assert VQ.cfg().get("_config_error")


def test_a08_importer_no_default_old_docs():
    """A-08：导入器不再默认导入 / 并入第一季文档；输出默认 = 当前剧导入稿；非 V1 输出引用第一季文档目录 → 拒绝"""
    import importlib.util as _u
    sp = _u.spec_from_file_location("import_script_t", ROOT / "tools/import_script.py")
    IS = _u.module_from_spec(sp)
    sp.loader.exec_module(IS)
    src = (ROOT / "tools/import_script.py").read_text(encoding="utf-8")
    assert '"--script", type=Path, required=True' in src and '"--image-doc", type=Path, default=None' in src
    v2_out = ROOT / "data/import/runs/series10_v2/script_v2.json"
    assert IS.old_doc_refs(v2_out, [ROOT / "script play lib" / "x.md"])                 # V2 引用旧剧文档 → 拒绝
    assert IS.old_doc_refs(v2_out, [ROOT / "data/inbox/new.md"]) == []
    assert IS.old_doc_refs(ROOT / "data/import/script_v2.json", [ROOT / "script play lib" / "x.md"]) == []   # V1 自己照旧


def test_a03_single_postflight_field():
    """A-03：契约结果只认 pf_of（take.postflight 唯一字段，旧数据退到 contract.postflight）；写回同时写唯一字段；已有结果不重复打分"""
    sys.path.insert(0, str(ROOT / "services/render_router"))
    from ns_render import unified_frame as UF
    assert UF.pf_of({"postflight": {"ok": True, "items": []}}) == {"ok": True, "items": []}
    assert UF.pf_of({"contract": {"postflight": {"status": "done", "ok": False}}})["status"] == "done"
    assert UF.pf_of({"contract": {"ok": True}}) == {"ok": True}
    assert UF.pf_of({}) == {} and UF.pf_of(None) == {}
    assert UF._pf_done(UF.pf_of({"postflight": {"ok": True, "items": [1]}}))          # 只在 take.postflight 的结果也算算过
    src = (ROOT / "services/render_router/ns_render/unified_frame.py").read_text(encoding="utf-8")
    assert 't["postflight"] = pf' in src and "cur = pf_of(t)" in src


def test_comfy_tag_known_client_prefixes():
    """总调度 19:3x：client_id 前缀能对上已知 agent（例 stylev2-*）就直接标 agent 名，不显示“未标记”"""
    sys.path.insert(0, str(ROOT / "services/agent"))
    from ns_agent import comfy_tag as CT
    assert CT.infer({}, {"client_id": "stylev2-ab12"})["agent"] == "STYLE-V2"
    assert CT.infer({}, {"client_id": "zzz-unknown"})["agent"] == "未标记"


def test_a07_no_in_place_source_patching(monkeypatch):
    """A-07：服务器上不再就地改源码——night / sync 原生认 OFFLINE_SELF，CLIP 解释器按 hosts.json comfy_python；resident_prep 不调 patch_*"""
    import importlib.util as _u
    src = (ROOT / "ops/offline/resident_prep.py").read_text(encoding="utf-8")
    main = src.split('if __name__ == "__main__":')[1]
    assert "patch_night()" not in main and "patch_sync_and_score()" not in main
    for rel in ("tools/series10_video/night.py", "tools/series10_video/sync.py"):
        sp = _u.spec_from_file_location("hh_" + rel.replace("/", "_"), ROOT / rel)
        m = _u.module_from_spec(sp)
        sp.loader.exec_module(m)
        monkeypatch.setenv("OFFLINE_SELF", "gpu36")
        assert m._hosts_here() == ("gpu36",)
        monkeypatch.delenv("OFFLINE_SELF")
        assert m._hosts_here() == ("gpu33", "gpu36")
    sys.path.insert(0, str(ROOT / "tools/gen_contract"))
    import remote_score as RS
    assert RS.comfy_py("gpu36") == "/root/work/fredw/venv/bin/python" and "comfy" in RS.comfy_py("gpu33")


def test_pause_state_real_layout(tmp_path):
    """OVERSIGHT-F P1-3：用真实目录结构判“已被别人暂停”——legacy 剧读 data/producer/control.json，其它剧读 runs/<run>/control.json；
    runs.json status 不是 producing 也算暂停（F20）；登记表坏 = 当作已暂停"""
    import json as _j
    import subprocess
    import pause_state as PS

    def run_snip(root):
        env = {k: v for k, v in __import__("os").environ.items() if k not in ("NS_PRIMARY_RUN", "NS_RUN")}
        r = subprocess.run([sys.executable, "-c", PS.PAUSE_PY, str(root)], capture_output=True, text=True, timeout=60, env=env)
        return PS.parse(r.stdout)
    import shutil
    (tmp_path / "tools/autopilot").mkdir(parents=True)
    (tmp_path / "tools/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tools/autopilot/__init__.py").write_text("", encoding="utf-8")
    shutil.copy(ROOT / "tools/autopilot/runs.py", tmp_path / "tools/autopilot/runs.py")
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "data/producer/runs/v2").mkdir(parents=True)
    w = lambda p, d: (tmp_path / p).write_text(_j.dumps(d), encoding="utf-8")
    w("config/pipeline/runs.json", {"primary": "v2", "legacy_unprefixed_run": "v1", "runs": {"v1": {"status": "archived"}, "v2": {"status": "producing"}}})
    w("config/pipeline/run.json", {"run_id": "v2"})
    w("data/producer/control.json", {"paused": True, "paused_by": "V1 的暂停"})            # V1 的 control 不能拿来判 V2
    w("data/producer/runs/v2/control.json", {"paused": False})
    assert run_snip(tmp_path) is None
    w("data/producer/runs/v2/control.json", {"paused": True, "paused_by": "项目方"})
    assert run_snip(tmp_path) == "项目方"
    w("data/producer/runs/v2/control.json", {"paused": False})
    w("config/pipeline/runs.json", {"primary": "v2", "legacy_unprefixed_run": "v1", "runs": {"v2": {"status": "paused"}}})
    assert "status=paused" in run_snip(tmp_path)
    (tmp_path / "config/pipeline/runs.json").write_text("{bad", encoding="utf-8")
    assert run_snip(tmp_path).startswith("unknown")


def test_oversight_p2_items(monkeypatch):
    """OVERSIGHT-F P2：NS_RUN / NS_PRIMARY_RUN 统一（runs.current_run）；lead_f 造型只从 manifest 读；出图作业没写项目 I11–I13 失败关闭"""
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import runs as RN
    monkeypatch.setenv("NS_RUN", "series10_v2")
    assert RN.current_run() == "series10_v2"
    monkeypatch.delenv("NS_RUN")
    assert RN.current_run() == RN.primary_run()
    sys.path.insert(0, str(ROOT / "tools/script_rsi"))
    import looks_table as LT
    allk, adult, daily, shoes = LT.lead_manifest()
    assert set(allk) == set(adult) | set(daily) and shoes and "LEAD_LOOKS = (" not in (ROOT / "tools/script_rsi/looks_table.py").read_text(encoding="utf-8")
    sys.path.insert(0, str(ROOT / "services/agent"))
    from ns_agent.gen_contract import preflight as PF
    r = PF.check({"kind": "image", "model": "qwen_image_2.1", "asset_refs": {"slots": []}, "prompt": "x", "cast": []})
    st = {i.id: i.status for i in r.items}
    assert st.get("I11") == "fail" and st.get("I12") == "fail"
    import producer as P
    assert P.run_env("series10_v2")["NS_RUN"] == "series10_v2"


def test_autoflow_resident_single_instance_and_status_filter(tmp_path, monkeypatch):
    """写作推进常驻服务：单实例锁；只推进 preparing / active / producing 的剧（paused / frozen / archived 不碰）；不写 control（不清暂停）"""
    import json as _j
    import autoflow_resident as AR
    lock = tmp_path / "x.lock"
    assert AR.acquire_lock(lock) is True
    assert AR.acquire_lock(lock) is False                                    # 本进程还活着 → 第二份起不来
    AR.release_lock(lock)
    lock.write_text(_j.dumps({"pid": 999999}), encoding="utf-8")
    assert AR.acquire_lock(lock) is True                                     # 陈旧锁 → 接管
    AR.release_lock(lock)
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(_j.dumps({"runs": {
        "v1": {"status": "archived"}, "s2": {"status": "paused"}, "v2": {"status": "preparing"}, "x": {"status": "frozen"}}}), encoding="utf-8")
    assert AR.advance_runs(tmp_path) == ["v2"]
    monkeypatch.setattr(AR, "advance_runs", lambda root=None: ["v2"])
    rd = tmp_path / "data/pipeline/runs/v2"
    rd.mkdir(parents=True)

    class AF:
        @staticmethod
        def pending_done(d):
            return [1]

    class RN:
        @staticmethod
        def run_dir(run, root):
            return rd
    spawned = []

    class Pr:
        def poll(self):
            return None
    # W13 CUTB-PREP 11-03（REVIEW-G6）：tick 后来又挂了 asset_tick / dispatch_tick / hollywood_tick 三相，本用例只测写作推进；
    # 不打桩它们会写真实 data/factory/*（real-data-guard 记 6 次 → pytest 退出码 1）。同 tests/test_epchain_o.py:90 的打法，断言不变
    for ph in ("asset_tick", "dispatch_tick", "hollywood_tick", "watchdog_tick"):   # W19：看门狗同理
        monkeypatch.setattr(AR, ph, lambda *a, **k: {}, raising=False)
    r = AR.tick({}, af=AF, runs_mod=RN, spawn=lambda d, ep: spawned.append((d, ep)) or Pr())
    assert r["started"] == ["v2 ep01"] and spawned == [(rd, 1)]
    procs = {("v2", 1): Pr()}
    assert AR.tick(procs, af=AF, runs_mod=RN, spawn=lambda d, ep: spawned.append(1))["started"] == []   # 同一集还在跑：不重复起
    src = (ROOT / "tools/factory/autoflow_resident.py").read_text(encoding="utf-8")
    assert "control.json" not in src.split('"""', 2)[2]                     # 代码里不碰 control（不清别人的暂停）


def test_expected_table_only_live_runs(tmp_path, monkeypatch):
    """总调度 20:1x：期望参考表只给在做的剧建（preparing / active / producing），归档 / 冻结 / 暂停的剧跳过"""
    import json as _j
    monkeypatch.delenv("NS_PRIMARY_RUN", raising=False)     # runs.py 拷进临时仓库后它的 ROOT 就是临时目录：不钉剧，读临时登记表
    import shutil
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "tools/autopilot").mkdir(parents=True)
    shutil.copy(ROOT / "tools/autopilot/runs.py", tmp_path / "tools/autopilot/runs.py")
    (tmp_path / "config/pipeline/runs.json").write_text(_j.dumps({"primary": "v2", "legacy_unprefixed_run": "v1", "runs": {
        "v1": {"status": "archived"}, "s2": {"status": "paused"}, "v2": {"status": "preparing"}}}), encoding="utf-8")
    for p in ("data/import/script_v2.json", "data/import/runs/s2/script_v2.json", "data/import/runs/v2/script_v2.json"):
        (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / p).write_text("{}", encoding="utf-8")
    assert IB._runs(tmp_path) == ("v2", ["v2"])


def test_assemble_compose_reads_run_script():
    """OVERSIGHT-F P1-4c：compose 按剧取导入稿（V2 run 下读不到 V1 剧本），plan 同口径"""
    src = (ROOT / "tools/assemble_series.py").read_text(encoding="utf-8")
    assert ('load_episode(RUNS.script_path(run or RUN_ID, ROOT), ep)' in src
            or ("run = run or RUN_ID" in src and 'load_episode(RUNS.script_path(run, ROOT), ep)' in src))   # P1-13a 后改成先归一 run
    assert "run: str | None = None) -> tuple[dict, int]" in src
    assert 'ROOT / "data/import/script_v2.json"' not in src
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import runs as RN
    assert RN.script_path("series10_v2") == ROOT / "data/import/runs/series10_v2/script_v2.json"


def test_k_ops_f30_no_mass_kill_by_name_or_port():
    """W-34 / K-OPS-F30（总调度 20:2x）：agent 只能停自己记下 pid 的进程；不许按端口 / 进程名批量杀（taskkill /IM、pkill -f、killall、
    Stop-Process -Name、fuser -k）。共享服务重启一律走 ops/restart_*.ps1（它们是唯一允许按命令行匹配的地方），并先通知总调度"""
    import re
    pat = re.compile(r"taskkill\s+(?:/F\s+)?/IM|pkill\s+-f|killall\b|Stop-Process\s+-Name|fuser\s+-k", re.I)
    legacy = {"ops/gpu0_relay.sh"}                          # 10-30 旧中继脚本（已停用），只许减不许增
    bad = []
    for top in ("tools", "ops", "services"):
        for p in (ROOT / top).rglob("*"):
            if p.suffix not in (".py", ".sh", ".ps1", ".mjs", ".js") or "node_modules" in p.parts or "_quarantine" in p.parts:
                continue
            rel = p.relative_to(ROOT).as_posix()
            if rel.startswith("ops/restart_") or rel in legacy or rel == "tests/test_factory.py":
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if pat.search(txt):
                bad.append(rel)
    assert not bad, bad


def test_anomaly_resident_script():
    """检测器常驻服务：只在 gpu36、GPU 走 ANOMALY_GPU（默认 1，W40 11-04：给 2 = 坏卡红线直接拒绝）、单实例 pid 文件、
    只听 127.0.0.1:8893、内网 lan_proxy 只放行 gpu33；不按名字批量杀（K-OPS-F30）"""
    t = (ROOT / "ops/factory/anomaly_resident.sh").read_text(encoding="utf-8")
    assert "GPU=${ANOMALY_GPU:-1}" in t and "CUDA_VISIBLE_DEVICES=$GPU" in t and "CUDA_VISIBLE_DEVICES=2" not in t
    assert '[ "$GPU" = 2 ] &&' in t and "exit 3" in t
    assert '[ "$SELF" = gpu36 ]' in t and "ANOMALY_PORT=$PORT" in t and "PORT=8893" in t
    assert "--allow 10.0.0.33" in t and "--bind 10.0.0.36" in t and "alive $PIDF" in t
    assert "pkill -f" not in t and "rm -" not in t


def test_infra_status_hm_invalid_timestamp():
    """/api/infra/status 500（OSError Errno 22）：_hm 收到非法时间戳（负数 / 超范围）时返回 None，不让整个接口出错"""
    sys.path.insert(0, str(ROOT / "services/api"))
    from ns_api import infra_status as IS
    assert IS._hm(None) is None and IS._hm(-1e12) is None and IS._hm(1e20) is None and IS._hm("x") is None
    assert IS._hm(1793616000) and len(IS._hm(1793616000)) == 8


def test_api_watchdog_and_restart_caller(tmp_path):
    """总调度 20:5x：restart_api.ps1 记调用方（-By / 父进程链 → data/ops/restart_events.jsonl）、经看门狗起 uvicorn；
    看门狗记 started / exited（强制结束也能看到退出码和时间）；app 启动 / 关闭各记一行"""
    import json as _j
    import api_watchdog as W

    class P_:
        pid = 4242

        def wait(self):
            return 1
    log = tmp_path / "lc.jsonl"
    orig = W.LOG
    W.LOG = log
    try:
        assert W.run(["-m", "x"], "TEST", popen=lambda *a, **k: P_()) == 1
    finally:
        W.LOG = orig
    ev = [_j.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in ev] == ["started", "exited"] and ev[1]["rc"] == 1 and ev[0]["by"] == "TEST"
    ps1 = (ROOT / "ops/restart_api.ps1").read_text(encoding="utf-8-sig")
    assert "restart_events.jsonl" in ps1 and "parent_chain" in ps1 and "tools/factory/api_watchdog.py" in ps1 and "[string]$By" in ps1
    app_src = (ROOT / "services/api/ns_api/app.py").read_text(encoding="utf-8")
    assert '_lifecycle("api_shutdown")' in app_src and '_lifecycle("api_startup")' in app_src


def test_k_ops_f33_non_comfy_must_hold_and_idle_sweep_checks_gpu(tmp_path):
    """K-OPS-F33（总调度 21:1x，gpu33:1 SeedVR2 撞金样首帧爆显存）：不走 ComfyUI 的 GPU 任务不许 lend（必须 hold）；
    空闲回收前先查卡上有没有非 ComfyUI 进程占显存，有就不回收并记 idle_release_blocked"""
    import json as _j
    import importlib.util as _u
    sp = _u.spec_from_file_location("debug_lanes_t", ROOT / "tools/debug/lanes.py")
    L = _u.module_from_spec(sp)
    sp.loader.exec_module(L)
    part = tmp_path / "partition.json"
    part.write_text(_j.dumps({"retired_lanes": [], "_lent_lanes": {}, "_temp_holds": {}}), encoding="utf-8")
    import pytest
    with pytest.raises(L.LendRefused):
        L.lend("gpu33:1", "STYLE-V2", 30, "stylev2-", "STYLE-V2", part=part, job_kind="seedvr2")
    L.lend("gpu33:1", "PROMPTFIX", 30, "promptfix-", "PROMPTFIX", part=part, now=1000.0)
    idle = lambda lane: {"ok": True, "busy": False, "last_end": None}
    busy_gpu = lambda lane: {"ok": True, "procs": [{"pid": 7, "mib": 9000, "cmd": "python seedvr2.py"}]}
    assert L.idle_sweep(10, probe=idle, part=part, now=1000.0 + 3600, gpu_probe=busy_gpu) == []      # 卡上有人 → 不回收
    assert "idle_release_blocked" in (tmp_path / "lane_loans.jsonl").read_text(encoding="utf-8")
    assert L.idle_sweep(10, probe=idle, part=part, now=1000.0 + 3600, gpu_probe=lambda lane: {"ok": False, "procs": []}) == []  # 探测失败也不收
    assert L.idle_sweep(10, probe=idle, part=part, now=1000.0 + 3600, gpu_probe=lambda lane: {"ok": True, "procs": []}) == ["gpu33:1"]


def test_a12_atomic_sync_writes(tmp_path):
    """A-12：推送解包后逐个 mv（原子替换），不再 cp -a 原地覆盖；merge_pull 共享账本原子写。用真 bash 验 mv 安装"""
    import shutil
    import subprocess
    src = (ROOT / "tools/autopilot/resident_sync.py").read_text(encoding="utf-8")
    assert "cp -a $T/. {R}/" not in src and src.count("atomic_install_cmd(R)") >= 4 and "cp -a" not in src.replace("以前 cp -a 原地覆盖", "")
    mp = (ROOT / "ops/offline/merge_pull.py").read_text(encoding="utf-8")
    assert "def _atomic_json(" in mp and mp.count("_atomic_json(") >= 4
    # W13 CUTB-PREP 11-03：环境口径，与 tests/test_system_version.py::test_verified_install_refuses_truncated_stdin 同一条（A-G1 第 22 轮 #4）：
    # Windows 上用 Git bash；PATH 里的 System32 / WindowsApps bash.exe 是 WSL 入口，收到 C:/… 路径找不到目录，`while read` 卡住
    # → 60 s TimeoutExpired（W13 实测，真实工作树）。只有 WSL 入口时 skip 并写明原因；有 Git bash 照常真跑，断言不变。
    import os
    git_bash = r"C:\Program Files\Git\bin\bash.exe"
    bash = git_bash if os.name == "nt" and os.path.isfile(git_bash) else shutil.which("bash")
    if not bash:
        return
    low = bash.replace("/", "\\").lower()
    if os.name == "nt" and ("\\system32\\" in low or "\\windowsapps\\" in low):
        import pytest
        pytest.skip(f"只有 WSL 入口 bash（{bash}），它读不到 Windows 临时目录；装 Git for Windows 后本测试会真跑")
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import importlib.util as _u
    sp = _u.spec_from_file_location("rsync_t", ROOT / "tools/autopilot/resident_sync.py")
    RS = _u.module_from_spec(sp)
    try:
        sp.loader.exec_module(RS)
    except Exception:  # noqa: BLE001  导入期依赖网络 / 配置时只做静态检查
        return
    T = tmp_path / "T"
    (T / "data/renders/ep01/S1").mkdir(parents=True)
    (T / "data/renders/ep01/S1/takes.json").write_text("new", encoding="utf-8")
    dest = tmp_path / "repo"
    (dest / "data/renders/ep01/S1").mkdir(parents=True)
    (dest / "data/renders/ep01/S1/takes.json").write_text("old", encoding="utf-8")
    cmd = f"T={T.as_posix()}; " + RS.atomic_install_cmd(dest.as_posix())
    subprocess.run([bash, "-c", cmd], check=True, timeout=60)
    assert (dest / "data/renders/ep01/S1/takes.json").read_text(encoding="utf-8") == "new" and not T.exists()


def test_a12_owner_decisions_laptop_wins():
    """A-12：takes.json 合并时项目方的决定（locked / master_gate）以笔记本为准，服务器的旧值不能盖掉；active 仍按服务器"""
    import importlib.util as _u
    sp = _u.spec_from_file_location("merge_pull_t", ROOT / "ops/offline/merge_pull.py")
    MP = _u.module_from_spec(sp)
    sp.loader.exec_module(MP)
    takes = [{"stage": "image", "n": 1, "file": "a.png"}, {"stage": "image", "n": 2, "file": "b.png"}]
    local = {"takes": takes, "active": {"image": 1}, "locked": {"image": 2}, "master_gate": {"image": "approved"}}
    remote = {"takes": takes, "active": {"image": 2}, "locked": {"image": 1}, "master_gate": {"image": "pending"}}
    out, *_ = MP.merge_takes_docs(remote, local, None, None)
    assert out["locked"] == {"image": 2} and out["master_gate"] == {"image": "approved"} and out["active"] == {"image": 2}


def test_i16_require_run_and_parity_uses_current_run(monkeypatch):
    """I-16：离线工具必须显式 --run（或 NS_RUN），不再默认第一季；data_parity 按当前剧比较"""
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import runs as RN
    import pytest
    monkeypatch.delenv("NS_RUN", raising=False)
    with pytest.raises(RN.RunNotGiven):
        RN.require_run([])
    assert RN.require_run(["--run", "series10_v2"]) == "series10_v2" and RN.require_run(["--run=x"]) == "x"
    monkeypatch.setenv("NS_RUN", "y")
    assert RN.require_run([]) == "y"
    dp = (ROOT / "tools/qa/data_parity.py").read_text(encoding="utf-8")
    assert "series10_v1" not in dp and "_runs().script_path(RUN, ROOT)" in dp


def test_p2_lifecycle_not_written_by_tests_or_preflight(monkeypatch, tmp_path):
    """OVERSIGHT-F 第 12 轮 P2-1：TestClient 也触发 startup/shutdown → pytest 在跑、P.DATA 被换掉、重启预检实例都不写真实 api_lifecycle.jsonl"""
    from ns_api import app as A
    assert A._lifecycle_should_log() is False                       # PYTEST_CURRENT_TEST 在
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("NS_API_PREFLIGHT", raising=False)
    monkeypatch.setattr(A.P, "DATA", tmp_path / "data")
    assert A._lifecycle_should_log() is False                       # 数据目录不是仓库 data/
    monkeypatch.setattr(A.P, "DATA", A.P.ROOT / "data")
    assert A._lifecycle_should_log() is True                        # 真服务才记（只判断，不写）
    monkeypatch.setenv("NS_API_PREFLIGHT", "1")
    assert A._lifecycle_should_log() is False
    calls = []
    monkeypatch.setattr("builtins.open", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("不该写")))
    A._lifecycle("api_startup")
    assert not calls


def test_k_ops_f35_release_only_own_and_lend_respects_hold(tmp_path):
    """K-OPS-F35（STYLE-V2 11-02 20:53/20:55）：release 只清调用方自己的那条；lend 碰到有效 hold 拒绝并报 why；hold 进审计；idle 收回不碰 hold"""
    sys.path.insert(0, str(ROOT / "tools" / "debug"))
    import pytest
    import lanes as LN
    part = tmp_path / "partition.json"
    part.write_text(json.dumps({"retired_lanes": []}), encoding="utf-8")
    t0 = 1_800_000_000.0
    LN.hold("gpu33:0", 60, "SeedVR2 4K", part=part, now=t0, by="STYLE-V2")
    with pytest.raises(LN.LendRefused, match="STYLE-V2.*SeedVR2"):
        LN.lend("gpu33:0", "PROMPTFIX", 30, "pf", "PROMPTFIX", part=part, now=t0 + 60)
    LN.lend("gpu33:0", "PROMPTFIX", 30, "pf", "PROMPTFIX", part=part, now=t0 + 61 * 60)   # hold 过期后可以借
    d = json.loads(part.read_text(encoding="utf-8"))
    assert "gpu33:0" in d["_lent_lanes"] and "gpu33:0" in d["_temp_holds"]               # 过期的 hold 还在（等 sweep 清），借道也在
    # 同一条道：STYLE-V2 hold（新）+ PROMPTFIX 借道 → PROMPTFIX release 只清自己的借道
    LN.hold("gpu36:1", 60, "SeedVR2", part=part, now=t0, by="STYLE-V2")
    d = json.loads(part.read_text(encoding="utf-8"))
    d["_lent_lanes"]["gpu36:1"] = {"to": "PROMPTFIX", "by": "PROMPTFIX", "client_prefix": "pf", "at": "2027-01-15T08:00:00"}
    part.write_text(json.dumps(d), encoding="utf-8")
    LN.release("gpu36:1", part=part, by="PROMPTFIX")
    d = json.loads(part.read_text(encoding="utf-8"))
    assert "gpu36:1" not in d["_lent_lanes"] and d["_temp_holds"]["gpu36:1"]["by"] == "STYLE-V2" and "gpu36:1" in d["retired_lanes"]
    LN.release("gpu36:1", part=part)                                                     # 不带 by 只放借道，别人的 hold 不动
    assert "gpu36:1" in json.loads(part.read_text(encoding="utf-8"))["_temp_holds"]
    LN.release("gpu36:1", part=part, by="STYLE-V2")                                      # 本人放
    d = json.loads(part.read_text(encoding="utf-8"))
    assert "gpu36:1" not in d["_temp_holds"] and "gpu36:1" not in d["retired_lanes"]
    au = [json.loads(x) for x in (tmp_path / "lane_loans.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(a["ev"] == "hold" and a["by"] == "STYLE-V2" and a["why"] == "SeedVR2 4K" for a in au)
    assert any(a["ev"] == "release_noop" and a.get("kept", {}).get("_temp_holds") == "STYLE-V2" for a in au)


I16_LEGACY_TOOLS = ["assetmaster/frames_v2.py", "assetmaster/gen_look_sheets.py", "assetmaster/look_fix.py", "bakeoff/post_local.py",
                    "bakeoff/run.py", "gen_contract/calibrate_imgfix.py", "gen_contract/calibrate_q.py", "gen_contract/look_audit.py",
                    "gen_contract/reflock_page.py", "gen_contract/reflock_v9.py", "gen_contract/reflock_validate.py",
                    "series10_imggen/imgfix_ab.py", "qa/defect_hunt.py", "script_rsi/rubric_audit.py", "voice10/voice10.py",
                    "imgfix/lookA_adopt.py"]


def test_i16_legacy_tools_gated_and_no_hard_run():
    """I-16：第一季专用历史离线工具一律走 runs.gate_legacy_tool（必须显式 --run，只认 legacy run），源码字符串里不再写死剧名"""
    import ast
    for rel in I16_LEGACY_TOOLS + ["script_rsi/hollywood_r5.py"]:
        src = (ROOT / "tools" / rel).read_text(encoding="utf-8")
        strs = [n.value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert not any("series10_v1" in s for s in strs), rel
        if rel in I16_LEGACY_TOOLS:
            assert src.count("RUNS.gate_legacy_tool(") == 1, rel          # 只调一次（第二次会因 --run 已剥掉而误报）


def test_i16_gate_legacy_tool(monkeypatch, tmp_path):
    import pytest
    sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
    import runs as RUNS
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({"primary": "v2", "legacy_unprefixed_run": "v1", "runs": {"v1": {}, "v2": {}}}), encoding="utf-8")
    monkeypatch.delenv("NS_RUN", raising=False)
    with pytest.raises(RUNS.RunNotGiven, match="--run"):
        RUNS.gate_legacy_tool(["page"], "x.py", root=tmp_path)                       # 不给 → 退出
    with pytest.raises(RUNS.RunNotGiven, match="第一季.*v2"):
        RUNS.gate_legacy_tool(["--run", "v2", "page"], "x.py", root=tmp_path)        # 给的不是 legacy → 退出
    assert RUNS.gate_legacy_tool(["--run", "v1", "page", "--by", "Z"], "x.py", root=tmp_path) == ["page", "--by", "Z"]
    assert RUNS.gate_legacy_tool(["--run=v1", "a"], "x.py", root=tmp_path) == ["a"]
    monkeypatch.setenv("NS_RUN", "v1")
    monkeypatch.setattr(sys, "argv", ["x.py", "plan"])
    assert RUNS.gate_legacy_tool(None, "x.py", root=tmp_path) == ["plan"] and sys.argv == ["x.py", "plan"]


def test_restartfix_lanes_cli_release_without_by_warns(monkeypatch, capsys):
    """RESTARTFIX-S P2-3：release 不带 --by 而道上有别人的 hold → CLI 提示“没有清理任何 hold，请加 --by”；带 --by 不提示"""
    import importlib
    sys_path = str(Path(__file__).resolve().parents[1] / "tools" / "debug")
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    L = importlib.import_module("lanes")
    seen = []
    monkeypatch.setattr(L, "release", lambda lane, part=None, by=None, kind=None: seen.append(by) or {"_temp_holds": {lane: {"by": "STYLE-V2"}}})
    assert L.main(["release", "gpu3"]) == 0
    assert "没有清理任何 hold，请加 --by" in capsys.readouterr().out
    assert L.main(["release", "gpu3", "--by", "STYLE-V2"]) == 0
    assert "没有清理任何 hold" not in capsys.readouterr().out
    monkeypatch.setattr(L, "release", lambda lane, part=None, by=None, kind=None: {"_lent_lanes": {}})
    L.main(["release", "gpu3"])
    assert "没有清理任何 hold" not in capsys.readouterr().out


def test_producer_postflight_gives_local_file_when_host_path_remote(tmp_path, monkeypatch):
    """W41（11-04）：笔记本上跑 producer 时 host_path 是 gpu33 路径 → 作业同时带本机交付图 file（G1 / Q9 读得到图）；
    host_path 在本机（服务器上）→ 不加 file，行为不变"""
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import producer as PR
    sys.path.insert(0, str(ROOT / "tools" / "gen_contract"))
    import remote_score as RS
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    seen = []

    def fake_full(host, jobs, label=None):
        seen.append(dict(jobs[0]))
        return {"x": {"ok": True, "items": [], "reasons": []}}
    monkeypatch.setattr(RS, "postflight_full", fake_full)
    monkeypatch.setattr(PR, "vqa_gate", lambda *a, **k: None)
    monkeypatch.setattr(PR, "shared_accept", lambda p, script, sid, f, job, pf: pf)
    monkeypatch.setattr(PR, "vqa_record", lambda *a, **k: None)
    monkeypatch.setattr(PR, "outbox_emit", lambda *a, **k: None)
    monkeypatch.setattr(UF, "preset_id", lambda: "x")
    from ns_render import image_params as IP
    monkeypatch.setattr(IP, "resolve", lambda *a, **k: {})
    monkeypatch.setattr(RS, "post_of", lambda *a, **k: None)
    fx = PR.FrameExec.__new__(PR.FrameExec)
    fx.p, fx.script = PR.Paths(pd=tmp_path / "pd", run_id="series10_v2"), None
    fx._postflight("ep01-S10", "last", 1, "renders/series10_v2/ep01/S10/takes/last.png", {}, "gpu33",
                   "/root/nowhere/gpu1/ns_final/x.png")
    assert seen[-1]["file"] == str(P.DATA / "renders/series10_v2/ep01/S10/takes/last.png")
    here = tmp_path / "raw.png"
    here.write_bytes(b"x")
    fx._postflight("ep01-S10", "last", 1, "renders/series10_v2/ep01/S10/takes/last.png", {}, "gpu33", str(here))
    assert "file" not in seen[-1] and seen[-1]["host_path"] == str(here)
