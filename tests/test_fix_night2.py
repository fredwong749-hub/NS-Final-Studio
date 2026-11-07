"""FIX-NIGHT2（11-06，AUDIT-NIGHT 查出的视频调度缺陷）——全部临时目录 / 打桩，不连服务器、不起进程、不写真实 data/。

#1 L-203：成对尾帧挂进 spec.keyframes["last"] → FL2VA（@last_frame + Picture 2 对齐句）；没成对尾帧 = no_last_frame（不再悄悄编成 I2VA）；
   兜底 I2VA / Ref2VA / 逐镜 I2VA 不送尾帧；账本硬上限 / last_unavailable 也算兜底
#2 finalize 放后台子进程（night_state 记 pid + sig，主循环收尾并回）；同签名不重跑；REOPEN 去抖（≥5 min、≤N/h）
#3 register / trim 只在定下的镜变了才跑；passed_frames 每轮一次；build_jobs 按镜指纹缓存；push 只补服务器缺的输入图；poll 15 s
#4 变体按（配方, 种子, 输入, 提示词）去重；next_variant 跳过同签名；MAX_RENDERS 按不同片数
#5 身份模型缺 → score_infra（不判身份偏离、不吃阶梯）；deploy 大声报缺模型
#6 验收 na：挂满补跑一次，仍 na 按待复核放行；producer 尾帧硬上限 → 写 last_frame_fallback
#7 night 单实例锁（--once 常驻在跑时只读）；shard_relay 临时目录 + mv 原子落位；OFFLINE_ALIASES 不让 night / deploy 把另一台当本机
#8 道轮换起点；失败镜重试按年龄放行；孤儿修复也管 pending / blocked
PS-MASTER 17:5x：restart_queue 重启已执行就记 done；night 心跳文件；lifecycle night 宽限 ≥ 20 min
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("tools/series10_video", "tools/pipeline", "tools/autopilot", "services/recipes", "packages/schema", "services/agent",
          "services/render_router", "packages/qc", "services/post", "tools", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import build_jobs as B  # noqa: E402
import vidgen as VG  # noqa: E402

V2 = "series10_v2"


# ------------------------------------------------------------------ #1 尾帧进视频模型（L-203）
class _Reg:
    def __init__(self, rc):
        self.rc = rc

    def resolve(self, rid):
        return self.rc


def _fake_compile(seen):
    def fn(spec, reg, **kw):
        seen.append({"last": getattr(spec.keyframes.get("last"), "path", None) if isinstance(getattr(spec, "keyframes", None), dict) else None,
                     "ov": kw["overrides"].get("keyframes.last_frame_mode")})
        return {"status": "needs_writer", "reason": "stop"}
    return fn


def test_attach_last_gate(monkeypatch):
    seen = []
    monkeypatch.setattr(B.C, "compile_shot", _fake_compile(seen))
    monkeypatch.setattr(B, "_no_last", lambda spec: False)
    monkeypatch.setattr(B, "LAST_FALLBACK", {})
    reg = _Reg({"keyframes": {"last_frame_mode": "use"}})
    spec = SimpleNamespace(id="ep01-S3", keyframes={})
    ff = {"ep01-S3": {"file": "data/x.jpg", "created_at": "2026-11-06T10:00:00", "take": 2}}
    # 成对尾帧 → 挂进 keyframes["last"]（编译器据此走 FL2VA）
    monkeypatch.setattr(B, "LASTS_OF", {"ep01-S3": {"file": "data/renders/series10_v2/ep01/S3/last_005.png", "created_at": "2026-11-06T11:00:00", "take": 5}})
    B.compile_variant(spec, reg, "r", 1, "v1", ff)
    assert seen[-1] == {"last": "data/renders/series10_v2/ep01/S3/last_005.png", "ov": None}
    assert spec.keyframes["last"].version == "last#5"
    # 尾帧比首帧旧 → 不成对：等（不编）
    monkeypatch.setattr(B, "LASTS_OF", {"ep01-S3": {"file": "data/old.png", "created_at": "2026-11-06T09:00:00", "take": 4}})
    assert B.compile_variant(spec, reg, "r", 1, "v1", ff)["status"] == "no_last_frame:stale_pair" and len(seen) == 1
    assert "last" not in spec.keyframes                                     # 旧尾帧不残留在 spec 上
    monkeypatch.setattr(B, "LASTS_OF", {})
    assert B.compile_variant(spec, reg, "r", 1, "v1", ff)["status"] == "no_last_frame"
    assert B.compile_variant(spec, reg, "r", 1, "v1", {})["status"] == "no_first_frame"
    # 兜底 I2VA（takes.json last_frame_fallback）→ 照编、不送尾帧
    monkeypatch.setattr(B, "LAST_FALLBACK", {"ep01-S3": "i2va"})
    B.compile_variant(spec, reg, "r", 1, "v1", ff)
    assert seen[-1] == {"last": None, "ov": "none"}
    monkeypatch.setattr(B, "LAST_FALLBACK", {})
    # Ref2VA 配方 / 配方不用尾帧 → 不要求尾帧
    B.compile_variant(spec, _Reg({"mode": "ref2va", "keyframes": {"last_frame_mode": "use"}}), "r", 1, "v1", ff)
    B.compile_variant(spec, _Reg({"keyframes": {"last_frame_mode": "none"}}), "r", 1, "v1", ff)
    assert [s["last"] for s in seen[-2:]] == [None, None]
    # 测试替身 spec（没有 keyframes）/ reg=None 不炸（test_video_fixvid2 同一用法）
    assert B.compile_variant(SimpleNamespace(id="ep01-S9"), None, "r", 1, "v1", {})["status"] == "needs_writer"


def test_compile_real_ep01_shot_fl2va_with_paired_last(monkeypatch):
    """真编译：ep01 一镜 + 成对尾帧 → mode fl2va、图里 @last_frame 映射到尾帧、提示词带 Picture 2 对齐句（修前：15/16 镜 I2VA）"""
    B.set_run(V2)
    from ns_recipes import registry as R
    reg = R.load()
    rid = B.recipe_choice()["face_default"]
    specs = B.load_specs()
    monkeypatch.setenv("NS_VIDEO_MODE", "fl2va")
    monkeypatch.setattr(B, "LAST_FALLBACK", {})
    spec = next(s for s in specs.values() if s.id.startswith("ep01-")).model_copy(deep=True)
    spec.keyframes = {}
    ff = {spec.id: {"file": "x.png", "created_at": "2026-11-05 00:00:00", "take": 1}}
    monkeypatch.setattr(B, "LASTS_OF", {spec.id: {"file": "y.png", "created_at": "2026-11-05 01:00:00", "take": 2}})
    out = B.compile_variant(spec, reg, rid, 1, "v1", ff)
    assert out.get("status") == "ready", out.get("status")
    assert out["mode"] == "fl2va" and out["inputs"].get("@last_frame") == "y.png" and out["last_frame"] == "y.png"
    assert "Picture 2" in out["prompt"]
    # 没有成对尾帧：不再悄悄编成 I2VA，而是等
    monkeypatch.setattr(B, "LASTS_OF", {})
    assert B.compile_variant(spec, reg, rid, 1, "v1", ff)["status"] == "no_last_frame"


def test_passed_lasts_carries_take_and_ledger_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "ROOT", tmp_path)
    monkeypatch.setattr(B, "RENDERS", Path("data/renders"))
    monkeypatch.setattr(B, "RUN_ID", "tv")
    d = tmp_path / "data/renders/ep01/S1"
    d.mkdir(parents=True)
    (d / "last_007.png").write_bytes(b"x")
    (d / "takes.json").write_text(json.dumps({"active": {"last": 7}, "takes": [
        {"stage": "last", "n": 7, "file": "renders/ep01/S1/last_007.png", "created_at": "2026-11-06T01:00:00", "postflight": {"ok": True}}]}),
        encoding="utf-8")
    assert B.passed_lasts()["ep01-S1"]["take"] == 7
    # 账本：尾帧硬上限（新鲜、没 uncap）/ last_unavailable → 兜底；uncap 之后 / 过期 / first: 不算
    pd = tmp_path / "pd"
    pd.mkdir()
    now = time.time()
    (pd / "attempts.json").write_text(json.dumps({
        "last:ep01-S1": {"hard_capped": {"t": now - 60, "n": 30, "lim": 30}},
        "last:ep01-S2": {"hard_capped": {"t": now - 60, "n": 30, "lim": 30}, "cap_extra": {"t": now - 10, "n": 3}},
        "last:ep01-S3": {"last_unavailable": True},
        "last:ep01-S4": {"hard_capped": {"t": now - 25 * 3600, "n": 30, "lim": 30}},
        "first:ep01-S5": {"hard_capped": {"t": now - 60, "n": 30, "lim": 30}}}), encoding="utf-8")
    monkeypatch.setitem(sys.modules, "runs", SimpleNamespace(producer_dir=lambda run, root: pd))
    got = B.ledger_last_fallbacks(now)
    assert set(got) == {"ep01-S1", "ep01-S3"} and got["ep01-S1"].startswith("ledger:hard_capped")
    assert B.last_frame_fallbacks() == {"ep01-S1": "i2va", "ep01-S3": "i2va"}


# ------------------------------------------------------------------ #4 变体去重 / #3 按镜缓存
def _var(recipe, seed, prompt="p", inputs=None, status="ready"):
    return {"status": status, "recipe": recipe, "seed": seed, "prompt": prompt, "inputs": inputs or {"@first_frame": "f.jpg"},
            "preflight": {"ok": True}}


def test_dedupe_variants():
    vs = {"v1": _var("pika", 1), "s2": _var("pika", 2), "mot": _var("pika", 2, prompt="p+motion"), "r24": _var("pika", 1),
          "alt": _var("pika", 2), "bad": _var("pika", 1, status="no_last_frame")}
    out, dups = B.dedupe_variants(vs)
    assert list(out) == ["v1", "s2", "mot", "bad"] and dups == {"r24": "v1", "alt": "s2"}


def test_cache_key_and_cached_variants(monkeypatch):
    spec = SimpleNamespace(id="ep01-S1", spec_hash=lambda: "H")
    reg = SimpleNamespace(source_hash="RH")
    ff = {"file": "inputs/ep01-S1_ab.jpg", "take": 3}
    k1 = B.shot_cache_key(spec, ff, None, None, None, False, {"face_default": "pika"}, reg, {})
    assert k1 == B.shot_cache_key(spec, ff, None, None, None, False, {"face_default": "pika"}, reg, {})
    assert k1 != B.shot_cache_key(spec, {**ff, "take": 4}, None, None, None, False, {"face_default": "pika"}, reg, {})
    assert k1 != B.shot_cache_key(spec, ff, None, "i2va", None, False, {"face_default": "pika"}, reg, {})
    prev = {"cache_key": k1, "variants": {"v1": _var("pika", 1)}}
    assert B._cached_variants(prev, k1) == prev["variants"]
    assert B._cached_variants(prev, "other") is None
    assert B._cached_variants({"cache_key": k1, "variants": {}}, k1) is None
    assert B._cached_variants({"cache_key": k1, "variants": {"v1": {**_var("pika", 1), "preflight": {"ok": False}}}}, k1) is None
    monkeypatch.setenv("NS_BUILD_NOCACHE", "1")
    assert B._cached_variants(prev, k1) is None


# ------------------------------------------------------------------ #6 验收 na
def test_na_resolve_recheck_once_then_waive(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "VID", tmp_path / "video")
    launched = []
    monkeypatch.setattr(B, "NA_RECHECK_FN", lambda sid, f: launched.append(sid) or True)
    t0 = 1e9
    assert B.na_resolve("ep01-S2", "data/renders/ep01/S2/image_003.png", now=t0) is False and not launched
    assert B.na_resolve("ep01-S2", "data/renders/ep01/S2/image_003.png", now=t0 + B.NA_RECHECK_S - 1) is False and not launched
    assert B.na_resolve("ep01-S2", "data/renders/ep01/S2/image_003.png", now=t0 + B.NA_RECHECK_S) is False and launched == ["ep01-S2"]
    assert B.na_resolve("ep01-S2", "data/renders/ep01/S2/image_003.png", now=t0 + B.NA_RECHECK_S + 10) is False and len(launched) == 1
    assert B.na_resolve("ep01-S2", "data/renders/ep01/S2/image_003.png", now=t0 + B.NA_RECHECK_S + B.NA_GRACE_S) is True
    assert B.na_resolve("ep01-S2", "data/renders/ep01/S2/image_003.png", now=t0 + 99999) is True and len(launched) == 1
    assert B.na_resolve("ep01-S2", "data/renders/ep01/S2/image_004.png", now=t0 + 99999) is False     # 换了版本：重新计时
    assert B.NA_STATES == (None, "na", "untested")


def test_producer_last_hard_cap_writes_fallback(monkeypatch):
    import producer as PR
    from ns_render import pipeline as P
    muts, leds, logs = [], [], []
    monkeypatch.setattr(P, "mutate_takes", lambda sid, fn, **kw: muts.append(sid))
    fake = SimpleNamespace(led_update=lambda oid, **kw: leds.append((oid, kw)), logf=lambda ev, **kw: logs.append(ev))
    td = {"active": {"image": 3}, "takes": [{"stage": "image", "n": 3}]}
    flag = PR.Producer.last_capped_fallback(fake, "ep01-S4", td, 30, 30)
    assert flag["mode"] == "i2va" and flag["first_n"] == 3 and muts == ["ep01-S4"]
    assert leds[0][0] == "last:ep01-S4" and leds[0][1]["last_unavailable"] is True and "last_unavailable" in logs
    assert PR.Producer.last_capped_fallback(fake, "ep01-S4", {**td, "last_frame_fallback": "i2va"}, 30, 30) is None
    assert PR.Producer.last_capped_fallback(fake, "ep01-S4", {"takes": []}, 30, 30) is None


# ------------------------------------------------------------------ #4 / #8 vidgen
def test_next_variant_skips_same_recipe_seed_and_counts_distinct(monkeypatch):
    monkeypatch.setattr(VG, "policy_ok", lambda var: True)
    shot = {"variants": {"v1": _var("pika", 1), "s2": _var("pika", 2), "s3": _var("pika", 3), "s4": _var("pika", 4),
                         "r24": _var("pika", 1), "alt": _var("pika", 2)}, "ladder_order": ["v1", "s2", "s3", "s4", "r24", "alt"]}
    fail = lambda v, s: {"variant": v, "recipe": "pika", "seed": s, "state": "scored", "score": {"gate": {"pass": False, "fails": ["出片失败"]}}}  # noqa: E731
    rec = {"renders": [fail("v1", 1)]}
    assert VG.next_variant(shot, rec) == "s2"
    rec["renders"].append(fail("s2", 2))
    assert VG.next_variant(shot, rec) == "s3"                                  # r24 / alt 与 v1 / s2 同（配方, 种子）→ 跳过
    rec["renders"] += [fail("s3", 3), fail("s4", 4)]
    assert VG.next_variant(shot, rec) is None and VG.distinct_renders(rec) == 4
    dup = {"renders": [fail("v1", 1), fail("r24", 1), fail("s2", 2), fail("alt", 2)]}      # 旧状态：4 条但只有 2 条不同的片
    assert VG.distinct_renders(dup) == 2 and VG.next_variant(shot, dup) == "s3"
    assert VG.render_sig({"variant": "v1"}) == ("variant", "v1")             # 旧记录没种子：按变体名


def test_lane_order_rotates():
    lanes = {"gpu36:0": 0, "gpu36:1": 1, "gpu36:2": 2}
    assert [n for n, _ in VG.lane_order(lanes, 0)] == ["gpu36:0", "gpu36:1", "gpu36:2"]
    assert [n for n, _ in VG.lane_order(lanes, 2)] == ["gpu36:2", "gpu36:0", "gpu36:1"]
    assert VG.lane_order({}, 5) == []
    assert "lane_order(self.lanes, self.rr_next())" in VG.Runner.submit_round.__code__.co_consts.__repr__() or True
    src = (ROOT / "tools/series10_video/vidgen.py").read_text(encoding="utf-8")
    assert "for name, lane in lane_order(self.lanes, self.rr_next())" in src


def test_first_take_first_releases_aged_retries():
    shots = {s: {"variants": {"v1": {}, "s2": {}}} for s in ("ep01-S1", "ep01-S2", "ep01-S3")}
    now = 1e9
    recs = {"ep01-S1": {"status": "pending", "renders": []},
            "ep01-S2": {"status": "retry", "renders": [{"variant": "v1", "state": "scored", "t_done": now - VG.RETRY_AGE_S - 1}]},
            "ep01-S3": {"status": "retry", "renders": [{"variant": "v1", "state": "scored", "t_done": now - 60}]}}
    todo = [("ep01-S1", "v1"), ("ep01-S2", "s2"), ("ep01-S3", "s2")]
    assert VG.first_take_first(todo, shots, recs, {"_now": now}) == [("ep01-S1", "v1"), ("ep01-S2", "s2")]   # S2 等够久 → 放行；S3 仍等
    assert VG.retry_age({"renders": [{"variant": "v1"}]}, now) == 0.0        # 没记时间的不算等很久


def _runner(monkeypatch):
    ev, logs = [], []
    monkeypatch.setattr(VG, "log", lambda host, *a: logs.append(" ".join(str(x) for x in a)))
    R = SimpleNamespace(lock=threading.Lock(), host="gpu36", st={"shots": {}, "events": []})
    R.event = lambda k, **kw: ev.append((k, kw))
    return R, ev, logs


def test_repair_orphans_handles_pending_and_blocked(monkeypatch):
    R, ev, logs = _runner(monkeypatch)
    R.st["shots"] = {"ep01-S1": {"status": "blocked", "block_kind": "undispatchable", "block_reason": "x", "renders": [], "chosen": None},
                     "ep01-S2": {"status": "pending", "renders": []},
                     "ep01-S3": {"status": "done", "chosen": "v1", "renders": []}}
    VG.Runner.repair_orphans(R, {})
    s1, s2 = R.st["shots"]["ep01-S1"], R.st["shots"]["ep01-S2"]
    assert s1["status"] == "pending" and "block_reason" not in s1 and s1["orphan"] is True
    assert s2["orphan"] is True and R.st["shots"]["ep01-S3"].get("orphan") is None
    n = len(logs)
    VG.Runner.repair_orphans(R, {})
    assert len(logs) == n                                                   # 已标孤儿的不重复记
    VG.Runner.repair_orphans(R, {"ep01-S1": {}})
    assert "orphan" not in s1 and s2.get("orphan") is True                 # 回到本机作业 → 撤标记


# ------------------------------------------------------------------ #5 身份模型缺 → score_infra
def test_score_clip_gate_score_infra_skips_identity():
    import score_clip as SC
    base = {"mean": 1.0, "cheek_red_max": 0.0, "cuts": [], "identity": {}}
    g = SC.gate({**base, "score_infra": "models_cache/vision 无 YuNet/SFace"}, {"林晚": "ref.png"})
    assert "身份偏离" not in g["fails"] and any("score_infra" in s for s in g["soft"]) and g["pass"]
    g2 = SC.gate(base, {"林晚": "ref.png"})
    assert "身份偏离" in g2["fails"]
    src = (ROOT / "tools/series10_video/score_clip.py").read_text(encoding="utf-8")
    assert '"score_infra": str(ir["error"])' in src and '"review_needed": True' in src


# ------------------------------------------------------------------ #3 / #5 / #7 deploy
@pytest.fixture
def deploy_mod(monkeypatch):
    monkeypatch.setenv("NS_RUN", V2)
    import deploy as D
    return importlib.reload(D)


def test_deploy_other_host_ignores_aliases(deploy_mod, monkeypatch):
    D = deploy_mod
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    monkeypatch.setenv("OFFLINE_ALIASES", "gpu33")
    assert D.other_host("gpu33") is True and D.other_host("gpu36") is False and D.other_host("root@gpu36") is False
    monkeypatch.setattr(D, "thread_guard_ok", lambda: (_ for _ in ()).throw(AssertionError("不该走到 ssh")))
    assert D.push("gpu33") is False                                          # gpu36 上不推 gpu33（修前：推到自己目录并报 PUSH_OK）
    monkeypatch.delenv("OFFLINE_SELF")
    assert D.other_host("gpu33") is False                                    # 笔记本：两台都管


def test_deploy_push_only_missing_inputs_and_vision_loud(deploy_mod, monkeypatch, capsys):
    D = deploy_mod
    cmds, tars = [], []

    def ssh(host, cmd, data=None, timeout=900):
        cmds.append(cmd)
        if "wc -l" in cmd:
            return SimpleNamespace(stdout=b"1\n", stderr=b"", returncode=0)
        if "__END__" in cmd:
            return SimpleNamespace(stdout=b"in/ep01-S1_aa.jpg\n__END__\n", stderr=b"", returncode=0)
        return SimpleNamespace(stdout=b"PUSH_OK\n", stderr=b"", returncode=0)
    monkeypatch.setattr(D, "ssh", ssh)
    monkeypatch.setattr(D, "thread_guard_ok", lambda: True)
    monkeypatch.setattr(D, "inputs_for", lambda host, jf: ["in/ep01-S1_aa.jpg", "in/ep01-S2_bb.jpg"])
    monkeypatch.setattr(D, "push_plan", lambda host, files, managed=None: (files, []))
    monkeypatch.setattr(D, "build_tar", lambda files, dirs: tars.append(list(files)) or b"tar")
    monkeypatch.setattr(D, "VISION", ["models_cache/vision/__missing__.onnx", D.VISION[1]])
    assert D.push("gpu36") is True
    files = tars[0]
    assert "in/ep01-S2_bb.jpg" in files and "in/ep01-S1_aa.jpg" not in files    # 服务器已有的不再推
    assert D.VISION[1] in files and "models_cache/vision/__missing__.onnx" not in files
    out = capsys.readouterr().out
    assert "VISION_MODELS_MISSING" in out and "输入图增量" in out
    assert D.remote_have("gpu36", []) == set()
    monkeypatch.setattr(D, "ssh", lambda *a, **k: SimpleNamespace(stdout=b"", stderr=b"", returncode=255))
    assert D.remote_have("gpu36", ["x"]) is None                              # 探测不通 → 全推


def test_shard_relay_atomic_unpack():
    import shard_relay as SR
    cmd = SR.relay_cmd("/srv/repo")
    assert "mktemp -d" in cmd and 'mv -f "$tmp/$f" "$f"' in cmd and "tar xf - -C" in cmd and "RELAY_OK" in cmd
    assert "cd /srv/repo && tar xf - &&" not in cmd                            # 不再直接覆盖活文件


# ------------------------------------------------------------------ night（#2 / #3 / #7 / 心跳）
@pytest.fixture
def night_v2(monkeypatch, tmp_path):
    orig = os.environ.get("NS_RUN")
    import night as N
    os.environ["NS_RUN"] = V2
    N = importlib.reload(N)
    vid = tmp_path / "run" / V2 / "video"
    vid.mkdir(parents=True)
    monkeypatch.setattr(N, "VID", vid)
    monkeypatch.setattr(N, "VID_REL", "run/video")
    monkeypatch.setattr(N, "LOG", vid / "night.log")
    monkeypatch.setattr(N, "STATE", vid / "night_state.json")
    monkeypatch.setattr(N, "EPS_OUT", tmp_path / "episodes" / V2)
    N.FINALIZE_PROCS.clear()
    try:
        yield N
    finally:
        monkeypatch.undo()
        if orig is None:
            os.environ.pop("NS_RUN", None)
        else:
            os.environ["NS_RUN"] = orig
        importlib.reload(N)


def test_finalize_background_spawn_reap_and_same_sig_guard(night_v2, monkeypatch):
    N = night_v2
    monkeypatch.setattr(N, "ep_sig", lambda ep, host: "SIG1")
    spawned = []
    spawn = lambda args: spawned.append(args) or 424242   # noqa: E731
    st = {"eps": {"1": {"host": "gpu36", "status": "rendering", "assembled_n": 2}}, "pending_shots": {}}
    assert N.start_finalize(1, "gpu36", st, {}, spawn=spawn) is True
    x = st["eps"]["1"]
    assert x["status"] == "finalizing" and x["finalize_job"]["pid"] == 424242 and x["finalize_job"]["sig"] == "SIG1"
    assert spawned[0][1:4] == ["tools/series10_video/night.py", "--finalize", "1"] and "--job" in spawned[0]
    monkeypatch.setattr(N, "pid_alive", lambda pid: True)
    assert N.reap_finalize("1", x, st) is False                             # 还在跑
    monkeypatch.setattr(N, "pid_alive", lambda pid: False)
    N.js(N.VID / "finalize_ep01.result.json", {"id": x["finalize_job"]["id"], "ep": 1, "err": None,
                                               "x": {"status": "assembled", "final": "f.mp4", "resolved_sig": "SIG1", "assembled_n": 3}})
    assert N.reap_finalize("1", x, st) is True
    x = st["eps"]["1"]
    assert x["status"] == "assembled" and x["host"] == "gpu36" and x["finalize_done_sig"] == "SIG1" and "finalize_job" not in x
    # 同签名回到 rendering（没有显式放行）→ 不再起 finalize；force_finalize → 起
    x["status"] = "rendering"
    assert N.start_finalize(1, "gpu36", st, {}, spawn=spawn) is False and len(spawned) == 1
    assert N.start_finalize(1, "gpu36", st, {}, spawn=spawn) is False and len(spawned) == 1
    x["force_finalize"] = True
    assert N.start_finalize(1, "gpu36", st, {}, spawn=spawn) is True and len(spawned) == 2 and "force_finalize" not in x
    # 子进程没结果 → 合成失败（retry_assembly 走 20 min 重试）
    N.js(N.VID / "finalize_ep01.result.json", {"id": "stale"})
    assert N.reap_finalize("1", x, st) is True and st["eps"]["1"]["status"] == "assemble_failed"
    # “等原片”收尾 → 回 rendering，但 FINALIZE_WAIT_S 内不再起
    st["eps"]["1"].update(status="rendering", force_finalize=True)
    N.start_finalize(1, "gpu36", st, {}, spawn=spawn)
    N.js(N.VID / "finalize_ep01.result.json", {"id": st["eps"]["1"]["finalize_job"]["id"], "x": {"status": "rendering", "wait_msg": "等原片 2 条"}})
    assert N.reap_finalize("1", st["eps"]["1"], st) is True and st["eps"]["1"]["status"] == "rendering"
    assert N.start_finalize(1, "gpu36", st, {}, spawn=spawn) is False and len(spawned) == 3


def test_finalize_sync_mode_calls_inline(night_v2, monkeypatch):
    N = night_v2
    calls = []
    monkeypatch.setattr(N, "partition_hosts", lambda part=None: {"1": "gpu33"})   # 11-07 §2c：只有本集视频机才合成；本测试的前提 = gpu33 是 ep01 视频机
    monkeypatch.setattr(N, "finalize", lambda ep, host, st, ctrl: calls.append(ep) or st["eps"][str(ep)].update(status="assembled", resolved_sig="S"))
    st = {"eps": {"1": {"host": "gpu33", "status": "rendering"}}}
    assert N.start_finalize(1, "gpu33", st, {"finalize_sync": True}) is True and calls == [1]
    assert st["eps"]["1"]["finalize_done_sig"] == "S"


def test_finalize_child_writes_result(night_v2, monkeypatch):
    N = night_v2
    N.js(N.STATE, {"eps": {"2": {"host": "gpu33", "status": "finalizing", "finalize_job": {"id": "j"}, "assembled_n": 1}}})
    seen = {}
    monkeypatch.setattr(N, "finalize", lambda ep, host, st, ctrl: seen.update(ep=ep, host=host) or st["eps"][str(ep)].update(status="assembled", final="x.mp4"))
    assert N.finalize_child(2, "j") == 0
    res = N.jl(N.VID / "finalize_ep02.result.json")
    assert res["id"] == "j" and res["x"]["status"] == "assembled" and res["x"]["assembled_n"] == 1 and seen == {"ep": 2, "host": "gpu33"}
    monkeypatch.setattr(N, "finalize", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert N.finalize_child(2, "k") == 1 and "boom" in N.jl(N.VID / "finalize_ep02.result.json")["err"]


def test_loop_once_reaps_and_starts_background_finalize(night_v2, monkeypatch):
    """主循环：finalizing 的集收尾；rendering 且落定的集起后台 finalize（不再同步调 finalize）"""
    N = night_v2
    for name in ("sync_hosts_from_partition", "apply_lane_policy", "write_status"):
        monkeypatch.setattr(N, name, lambda *a, **k: None)
    monkeypatch.setattr(N, "expire_holds", lambda c: c)
    monkeypatch.setattr(N, "specs_by_ep", lambda: {})
    monkeypatch.setattr(N, "_B", lambda: SimpleNamespace(passed_frames=lambda: {}, passed_lasts=lambda: {}, FRAMES_OK=N.VID / "no.json"))
    monkeypatch.setattr(N, "regen_holds_now", lambda eps: {})
    monkeypatch.setattr(N, "roles_for_host", lambda *a, **k: None)
    monkeypatch.setattr(N, "run", lambda args, timeout=3600: (0, '"changed": []'))
    monkeypatch.setattr(N, "register_due", lambda st: False)
    monkeypatch.setattr(N, "retry_assembly", lambda st: None)
    monkeypatch.setattr(N, "reopen_changed", lambda st, now=None: None)
    monkeypatch.setattr(N, "ep_resolved", lambda ep, host: (True, {"ep01-S1": {"status": "done"}}))
    monkeypatch.setattr(N, "ep_sig", lambda ep, host: "S")
    monkeypatch.setattr(N, "finalize", lambda *a: (_ for _ in ()).throw(AssertionError("不该同步 finalize")))
    started = []
    monkeypatch.setattr(N, "start_finalize", lambda ep, host, st, ctrl, spawn=None: started.append(ep) or True)
    reaped = []
    monkeypatch.setattr(N, "reap_finalize", lambda e, x, st: reaped.append(e) or False)
    st = {"eps": {"1": {"host": "gpu36", "status": "rendering"}, "2": {"host": "gpu36", "status": "finalizing", "finalize_job": {}}},
          "pending_shots": {}}
    N.loop_once(st)
    assert started == [1] and reaped == ["2"]
    assert (N.VID / "night_heartbeat.json").is_file() and N.jl(N.STATE)["eps"]["1"]["status"] == "rendering"


def test_reopen_debounce(night_v2, monkeypatch):
    N = night_v2
    monkeypatch.setattr(N, "log", lambda *a: None)
    monkeypatch.setattr(N, "ep_sig", lambda ep, host: "NEW")
    now = 1e9
    st = {"eps": {"1": {"host": "gpu36", "status": "assembled", "resolved_sig": "OLD", "finalized": now - 100}}}
    N.reopen_changed(st, now)
    x = st["eps"]["1"]
    assert x["status"] == "assembled" and x["reopen_pending"] == "NEW"       # 合成完不到 5 min：先不重开
    N.reopen_changed(st, now + 300)
    assert x["status"] == "rendering" and x["force_finalize"] is True and "reopen_pending" not in x and len(x["reopen_hist"]) == 1
    x.update(status="assembled", finalized=now, reopen_hist=[now - 10, now - 20, now - 30, now - 40])
    N.reopen_changed(st, now + 3000)
    assert x["status"] == "assembled"                                        # 1 h 内已重开 4 次：不再重开
    x["reopen_hist"] = [now - 3700]
    N.reopen_changed(st, now + 3000)
    assert x["status"] == "rendering"
    assert N.REOPEN_MIN_S == 300 and N.REOPEN_MAX_PER_H == 4


def test_register_due_only_on_new_settled(night_v2, monkeypatch):
    N = night_v2
    shots = {"ep01-S1": {"status": "done", "chosen": "v1", "renders": [{"variant": "v1", "file": "nope.mp4"}]}}
    monkeypatch.setattr(N, "ep_shots", lambda ep, host: shots)
    st = {"eps": {"1": {"host": "gpu36", "status": "rendering"}}}
    assert N.register_due(st, now=1e9) is True
    assert N.register_due(st, now=1e9 + 60) is False                        # 没有新定下的镜：不跑
    shots["ep01-S2"] = {"status": "best_effort", "chosen": "s2", "renders": []}
    assert N.register_due(st, now=1e9 + 120) is True
    assert N.register_due(st, now=1e9 + 120 + N.REGISTER_EVERY_S) is True   # 兜底：到点照跑一次
    src = (ROOT / "tools/series10_video/night.py").read_text(encoding="utf-8")
    body = src.split("def loop_once", 1)[1].split("\ndef ", 1)[0]
    assert "if register_due(st):" in body and body.count("passed_frames()") == 1    # passed_frames 每轮只算一次


def test_single_instance_lock_and_once_readonly(night_v2, monkeypatch):
    N = night_v2
    assert N.pid_alive(os.getpid()) is True
    dead = subprocess.run([sys.executable, "-c", "pass"], capture_output=True, timeout=60)
    assert dead.returncode == 0
    monkeypatch.setattr(N, "log", lambda *a: None)
    N.js(N.VID / "night.pid", {"pid": os.getpid()})
    monkeypatch.setattr(N, "loop_once", lambda st: (_ for _ in ()).throw(AssertionError("常驻在跑时 --once 不该写")))
    assert N.main(["--once"]) == 0                                           # 只读：没碰 loop_once
    assert N.acquire_lock() is True                                          # 自己的 pid = 自己
    N.js(N.VID / "night.pid", {"pid": 2 ** 22 + 12345})
    assert N.resident_pid() is None and N.acquire_lock() is True and N.jl(N.VID / "night.pid")["pid"] == os.getpid()
    # --finalize 入口不进主循环
    monkeypatch.setattr(N, "finalize_child", lambda ep, job: 7)
    assert N.main(["--finalize", "3", "--job", "j"]) == 7


def test_host_is_other_ignores_aliases(night_v2, monkeypatch):
    N = night_v2
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    monkeypatch.setenv("OFFLINE_ALIASES", "gpu33")
    assert N._host_is_other("gpu33") is True and N._host_is_other("gpu36") is False
    monkeypatch.delenv("OFFLINE_SELF")
    assert N._host_is_other("gpu33") is False
    src = (ROOT / "tools/series10_video/night.py").read_text(encoding="utf-8")
    assert "_local_self" not in src.split("def dispatch_hosts", 1)[1].split("\ndef ", 1)[0]


def test_heartbeat_written_by_run_and_poll_default(night_v2, monkeypatch):
    N = night_v2
    monkeypatch.setattr(N.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    N.run([N.PY, "tools/series10_video/sync.py"])
    hb = N.jl(N.VID / "night_heartbeat.json")
    assert hb["step"] == "run:sync.py" and hb["pid"] == os.getpid() and time.time() - hb["t"] < 5
    assert N.poll_seconds({}) == 15.0
    assert N.retry_assembly.__code__.co_consts.__repr__().count("force_finalize") >= 1


# ------------------------------------------------------------------ PS-MASTER 17:5x：restart_queue / lifecycle
def test_restart_queue_records_done_once_restart_executed(monkeypatch, tmp_path):
    import resident_sync as RS
    import restart_queue as RQ
    monkeypatch.setattr(RQ, "REQ", tmp_path / "req.jsonl")
    monkeypatch.setattr(RQ, "DONE", tmp_path / "done.jsonl")
    monkeypatch.setattr(RS, "STATE", tmp_path / "st.json")
    monkeypatch.setattr(RS, "log", lambda *a: None)
    calls = []

    def ssh(h, cmd, **k):
        calls.append(cmd)
        if "resume" in cmd:
            raise RuntimeError("resume 超时")
        return b'{"0": [0, 0], "1": [0, 0]}' if cmd == "python3 -" else b'{"paused_by": null}' if 'base64 -d)" ' in cmd else b"ok"
    monkeypatch.setattr(RS, "ssh", ssh)
    monkeypatch.setattr(RS, "restart", lambda h, mode=None: calls.append("RESTART") or "started")
    RQ.request("gpu36", "lifecycle night", "resident_sync.lifecycle")
    r = RQ.process("gpu36")
    assert r["ok"] is False and r["restart_executed"] is True and "resume" in r["error"] and calls.count("RESTART") == 1
    assert RQ.pending("gpu36") == []                                         # 重启已执行 → 记 done，不再重跑（修前：每拍再杀一次 night）
    assert RQ.process("gpu36") is None and calls.count("RESTART") == 1
    # 排空阶段就失败（重启没发出）→ 留着重试
    monkeypatch.setattr(RQ, "drain", lambda h, rs, **k: (_ for _ in ()).throw(RuntimeError("排空出错")))
    monkeypatch.setattr(RS, "RESTART_MIN_GAP_S", 0)
    RQ.request("gpu36", "再来", "X")
    r2 = RQ.process("gpu36")
    assert r2["ok"] is False and not r2.get("restart_executed") and len(RQ.pending("gpu36")) == 1


def test_lifecycle_night_grace_20min(tmp_path):
    import resident_sync as RS
    assert RS.lc_grace_min({"grace_min": 10}, "night") == 20 and RS.lc_grace_min({"grace_min": 10}, "producer") == 10
    assert RS.lc_grace_min({"grace_min": 25}, "night") == 25 and RS.LC_DEFAULT["night_grace_min"] == 20
    assert "night_heartbeat.json" in RS.REMOTE_HEALTH
    from test_producer_lifecycle import Rec, _root, _stage, _w
    root = _root(tmp_path)
    _w(root / "config/netfix/partition.json", {"images": {"gpu36": [1], "laptop": []}, "video": {"gpu33": [1]}})
    r, st, t = Rec(), _stage((1, "尾帧")), 1e9
    out = RS.lifecycle_tick(root, stage_fn=st, now=t, **r.kw(hbs={"laptop:producer": 0.1}))
    assert out["actions"]["gpu33:night"]["action"] == "requested" and out["actions"]["gpu36:producer"]["action"] == "requested"
    out = RS.lifecycle_tick(root, stage_fn=st, now=t + 15 * 60, **r.kw(hbs={"laptop:producer": 0.1}))
    assert out["actions"]["gpu36:producer"]["attempts"] == 1                 # producer：10 min 宽限已过 → 计一次
    assert out["actions"]["gpu33:night"]["action"] == "waiting" and out["actions"]["gpu33:night"]["attempts"] == 0   # night：20 min 内等
    out = RS.lifecycle_tick(root, stage_fn=st, now=t + 21 * 60, **r.kw(hbs={"laptop:producer": 0.1}))
    assert out["actions"]["gpu33:night"]["attempts"] == 1
