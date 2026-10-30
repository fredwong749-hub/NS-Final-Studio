"""tools/gpu_grab.py：校验、空闲判断、锁协议、队列流转（全部用假的 gpu3 / 笔记本 / 出图）。"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("gpu_grab", Path(__file__).resolve().parent.parent / "tools" / "gpu_grab.py")
G = importlib.util.module_from_spec(_spec)
sys.modules["gpu_grab"] = G
_spec.loader.exec_module(G)

OWN = {"weita": {"owner": "gpu3"}}


def job(**kw):
    j = {"model": "qwen_image_2.1_int8_convrot.safetensors", "steps": 35, "cfg": 3.0, "size": [1024, 1536],
         "prompt": "Full-body identity reference photo of a 34-year-old adult man", "negative": "裸体", "seed": 1,
         "file": "x_s0.png", "out_dir": "assets/characters/x/candidates/"}
    j.update(kw)
    return j


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ROOT", tmp_path)
    for name in ("QUEUE", "RUNNING", "DONE", "FAILED"):
        monkeypatch.setattr(G, name, tmp_path / "data" / "jobs" / name.lower())
    monkeypatch.setattr(G, "LOG", tmp_path / "data" / "logs" / "gpu_grab.log")
    return tmp_path


# ---------------------------------------------------------------- 校验
def test_valid_asset_job_accepted():
    assert G.refuse_reason({}, job(), OWN) is None


def test_sample_job_file_accepted():
    p = Path(__file__).resolve().parent.parent / "data" / "jobs" / "gpu3_char_variety_20261030.json"
    if not p.exists():
        pytest.skip("sample job file missing")
    meta, jobs = G.load_jobs(json.loads(p.read_text(encoding="utf-8")))
    assert jobs and all(G.refuse_reason(meta, j, OWN) is None for j in jobs)


@pytest.mark.parametrize("extra", [{"adult": True}, {"nsfw": True}, {"rating": "Adult"}, {"adult_shot": True}])
def test_adult_jobs_accepted(extra):
    """2026-10-30 取消成人过滤器：gpu_grab 不再按 adult/nsfw 标记拒绝。"""
    assert G.refuse_reason({}, job(**extra), OWN) is None


def test_adult_flag_on_file_meta_accepted():
    assert G.refuse_reason({"adult": True}, job(), OWN) is None


def test_word_adult_in_prompt_is_not_a_flag():
    assert G.refuse_reason({}, job(prompt="a 34-year-old adult man in a black shirt"), OWN) is None


@pytest.mark.parametrize("extra", [{"kind": "first_frame", "project": "weita"}, {"shot_id": "ep01-S3", "project": "weita"},
                                   {"kind": "video", "project": "weita"},
                                   {"out_dir": "data/renders_gpu3/weita/ep01/S1/"}])
def test_weita_shot_jobs_refused_by_ownership(extra):
    r = G.refuse_reason({}, job(**extra), OWN)
    assert r and ("shot_ownership" in r or "assets/candidates only" in r)


def test_weita_frame_cites_ownership():
    assert "shot_ownership" in G.refuse_reason({"project": "weita"}, job(kind="last_frame"), OWN)


def test_other_shot_job_still_refused():
    assert "assets/candidates only" in G.refuse_reason({}, job(kind="video", project="other"), OWN)


def test_gpu2_target_and_bad_paths_refused():
    assert "targets" in G.refuse_reason({}, job(targets=["gpu3:2"]), OWN)
    assert "outside" in G.refuse_reason({}, job(out_dir="../../elsewhere"), OWN)
    assert "bare .png" in G.refuse_reason({}, job(file="../x.png"), OWN)
    assert "missing" in G.refuse_reason({}, job(prompt=""), OWN)


# ---------------------------------------------------------------- 空闲判断
def test_idle_needs_full_window():
    t = G.IdleTracker(window_s=120)
    t.record(0, {1: (300, 0)})
    assert not t.idle(1, 60)
    t.record(60, {1: (300, 2)})
    assert not t.idle(1, 119)
    assert t.idle(1, 120)


def test_idle_resets_on_activity():
    t = G.IdleTracker(window_s=120)
    t.record(0, {1: (300, 0)})
    t.record(100, {1: (300, 40)})       # 有人在跑
    t.record(130, {1: (300, 0)})
    assert not t.idle(1, 200)
    assert t.idle(1, 250)


def test_idle_memory_threshold():
    t = G.IdleTracker(window_s=0)
    t.record(0, {0: (19000, 0), 1: (1023, 4), 3: (1024, 0)})
    assert [g for g in (0, 1, 3) if t.idle(g, 1)] == [1]


def _snap(files=None, smi=None):
    return {"files": files or {}, "smi": smi or {0: (10, 0), 1: (10, 0), 3: (10, 0)}}


def _idle_tracker(snap):
    t = G.IdleTracker(window_s=120)
    t.record(0, snap["smi"])
    return t


def test_gpu3_free_when_idle_and_unlocked():
    s = _snap()
    assert G.gpu3_free(1, s, _idle_tracker(s), 200) is None


@pytest.mark.parametrize("fname", ["gpu.lock.gpu1", "train.lock.gpu1", "train.lock.1", "lend.gpu1", "assign.gpu1.json"])
def test_gpu3_blocked_by_state_files(fname):
    s = _snap({fname: "pid:5 someone"})
    assert G.gpu3_free(1, s, _idle_tracker(s), 200) is not None


def test_gpu2_never():
    s = _snap(smi={2: (0, 0)})
    assert "never" in G.gpu3_free(2, s, _idle_tracker(s), 999)


def test_laptop_free_rules():
    assert G.laptop_free({"queue_running": [], "queue_pending": []}, []) is None
    assert "busy" in G.laptop_free({"queue_running": [["x"]], "queue_pending": []}, [])
    assert "unreachable" in G.laptop_free(None, [])
    assert "busy" in G.laptop_free({"queue_running": [], "queue_pending": []}, ["python.exe#1: render_batch.py"])
    # X-1：本机 ComfyUI 单一锁被画布 / 编排器占着 → 不抢
    held = G.laptop_free({"queue_running": [], "queue_pending": []}, [], {"who": "canvas", "what": "ep01-S1"})
    assert "comfy.lock" in held and "canvas" in held


def test_filter_busy_processes():
    lines = ["10\tpython.exe\tpython tools/render_batch.py --ep 1",
             "11\tpython.exe\tpython D:/x/tools/gen_assets.py run",
             "12\tpython.exe\tpython tools/gpu_grab.py --watch",
             "13\tbash.exe\tbash -c grep render_batch",
             "14\tpython.exe\tpython -m uvicorn ns_api.app:app",
             "15\tpython.exe\tpython run.py training/lin_wan/cfg.toml",
             '16\tpython.exe\t"D:\\NS\\.venv\\python.exe" tools/gen_assets_v2.py run --only plates/id_front',
             "99\tpython.exe\tpython tools/gen_scenes.py"]
    busy = G.filter_busy(lines, own_pid=99)
    assert [b.split(":")[0] for b in busy] == ["python.exe#10", "python.exe#11", "python.exe#15", "python.exe#16"]


def test_lock_text_format():
    assert G.lock_text("q1:gu chen\nx.png") == "fredw-d9 q1:gu_chen_x.png"


# ---------------------------------------------------------------- 队列流转（假 gpu3 / 假出图）
class FakeGpu3:
    def __init__(self, may=True, acquire=True, smi=None, files=None):
        self.may, self.acq = may, acquire
        self.locks: dict[int, str] = {}
        self.events: list[tuple] = []
        self._smi = smi or {0: (10, 0), 1: (10, 0), 3: (10, 0)}
        self.files = files or {}

    def snapshot(self):
        return {"files": dict(self.files), "smi": dict(self._smi), "ages": {}}

    def may_use(self, g):
        ok = self.may(g) if callable(self.may) else self.may
        self.events.append(("may_use", g, ok))
        return ok, "fake"

    def acquire(self, g, text):
        if not self.acq or g in self.locks:
            return False
        self.locks[g] = text
        self.events.append(("lock", g, text))
        return True

    def release(self, g, text):
        if self.locks.get(g) == text:
            del self.locks[g]
            self.events.append(("unlock", g, text))
        return True

    def remove_own_stale(self, snap, ttl=1200):
        pass

    def tunnel(self, g):
        class T:
            def __enter__(s):
                return f"http://fake-gpu3-{g}"

            def __exit__(s, *a):
                pass
        return T()


class FakeLaptop:
    def __init__(self, free=True):
        self.free = free

    def queue(self):
        return {"queue_running": [], "queue_pending": []} if self.free else {"queue_running": [["x"]]}

    def busy_procs(self):
        return []

    def lock_holder(self):
        return None


def make_exec(fail_files=(), timeout_files=(), lock_check=None):
    calls = []

    def ex(job, url, limit, target, job_id):
        if lock_check:
            lock_check(target, job_id)
        calls.append((job["file"], target, limit))
        if job["file"] in fail_files:
            raise G.QCFail("QC v3 nudity hard fail")
        if job["file"] in timeout_files:
            raise G.JobTimeout("over")
        return {"sha256": "abc", "gen_seconds": 1.0, "qc": {"nudity": False}}
    ex.calls = calls
    return ex


def put(env, name, jobs, **meta):
    G.QUEUE.mkdir(parents=True, exist_ok=True)
    p = G.QUEUE / name
    p.write_text(json.dumps({**meta, "jobs": jobs}, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _no_remote(monkeypatch):
    monkeypatch.setattr(G, "_remote_queue_empty", lambda url: True)
    monkeypatch.setattr(G, "_free", lambda url: None)


@pytest.fixture(autouse=True)
def _isolated_comfy_lock(tmp_path, monkeypatch):
    """测试不碰仓库里真实的 data/comfy.lock（画布 / 编排器在用）"""
    from ns_orch import comfy_lock as CL
    monkeypatch.setattr(CL, "LOCK_PATH", tmp_path / "comfy.lock")
    return CL


def test_laptop_run_moves_to_done(env):
    put(env, "a.json", [job(file="a1.png"), job(file="a2.png")])
    ex = make_exec()
    r = G.Runner(gpu3=None, laptop=FakeLaptop(), execute=ex, use_gpu3=False, ownership=OWN)
    assert r.once(sample_s=0) == 1
    assert [c[:2] for c in ex.calls] == [("a1.png", "laptop"), ("a2.png", "laptop")]
    d = json.loads((G.DONE / "a.json").read_text(encoding="utf-8"))
    assert {v["status"] for v in d["_gpu_grab"]["results"].values()} == {"ok"}
    assert not list(G.QUEUE.glob("*.json")) and not list(G.RUNNING.glob("*.json"))


def test_qc_fail_is_hard_and_goes_to_failed(env):
    put(env, "b.json", [job(file="ok.png"), job(file="nude.png")])
    ex = make_exec(fail_files={"nude.png"})
    G.Runner(gpu3=None, laptop=FakeLaptop(), execute=ex, use_gpu3=False, ownership=OWN).once(sample_s=0)
    d = json.loads((G.FAILED / "b.json").read_text(encoding="utf-8"))
    assert d["_gpu_grab"]["results"]["1"]["status"] == "failed"
    assert len(ex.calls) == 2      # 不换种子重试


def test_refused_file_never_runs_but_adult_does(env):
    put(env, "c.json", [job(file="f.png", kind="first_frame")], project="weita")
    put(env, "d.json", [job(file="g.png", adult=True)])
    ex = make_exec()
    G.Runner(gpu3=None, laptop=FakeLaptop(), execute=ex, use_gpu3=False, ownership=OWN).once(sample_s=0)
    assert ex.calls == [("g.png", "laptop", 3600)]
    assert "shot_ownership" in json.loads((G.FAILED / "c.json").read_text(encoding="utf-8"))["_gpu_grab"]["refused"]
    assert (G.DONE / "d.json").exists()


def test_laptop_yields_when_comfy_lock_held(env, _isolated_comfy_lock):
    """X-1：画布 / 编排器拿着 comfy.lock 时，gpu_grab 不往本机 ComfyUI 派活，任务留在队列（不计失败）"""
    CL = _isolated_comfy_lock
    put(env, "h.json", [job(file="h1.png")])
    ex = make_exec()
    fh = CL.acquire("canvas", "ep01-S1", timeout=0)
    try:
        G.Runner(gpu3=None, laptop=FakeLaptop(), execute=ex, use_gpu3=False, ownership=OWN).once(sample_s=0)
    finally:
        CL.release(fh)
    assert ex.calls == [] and (G.QUEUE / "h.json").exists() and not list(G.FAILED.glob("*.json"))
    # 锁放开后照常跑，跑的时候 gpu_grab 自己持锁
    seen = []
    ex2 = make_exec(lock_check=lambda target, job_id: seen.append(CL.holder()))
    G.Runner(gpu3=None, laptop=FakeLaptop(), execute=ex2, use_gpu3=False, ownership=OWN).once(sample_s=0)
    assert [c[0] for c in ex2.calls] == ["h1.png"] and seen[0]["who"] == "gpu_grab"
    assert CL.is_free()


def test_laptop_busy_nothing_runs(env):
    put(env, "e.json", [job()])
    ex = make_exec()
    G.Runner(gpu3=None, laptop=FakeLaptop(free=False), execute=ex, use_gpu3=False, ownership=OWN).once(sample_s=0)
    assert ex.calls == [] and (G.QUEUE / "e.json").exists()


def _gpu3_runner(fake, ex, targets=("gpu3:1",)):
    r = G.Runner(gpu3=fake, laptop=None, execute=ex, use_laptop=False, ownership=OWN,
                 tracker=G.IdleTracker(window_s=0))
    return r


def test_gpu3_lock_per_job_and_released_between(env):
    put(env, "h.json", [job(file="h1.png"), job(file="h2.png")], targets=["gpu3:1"])
    fake = FakeGpu3()
    seen = []
    ex = make_exec(lock_check=lambda t, jid: seen.append(dict(fake.locks)))
    _gpu3_runner(fake, ex).once(sample_s=0)
    assert seen == [{1: "fredw-d9 h:h1.png"}, {1: "fredw-d9 h:h2.png"}]   # 跑的时候持锁
    assert fake.locks == {}                                                # 结束释放
    kinds = [e[0] for e in fake.events]
    assert kinds == ["may_use", "lock", "unlock", "may_use", "lock", "unlock"]   # 每个任务前都问 may-use
    assert all(c[2] == G.GPU3_JOB_LIMIT_S for c in ex.calls)
    assert (G.DONE / "h.json").exists()


def test_gpu3_may_use_refused_between_jobs_requeues(env):
    put(env, "i.json", [job(file="i1.png"), job(file="i2.png")], targets=["gpu3:1"])
    answers = iter([True, False])
    fake = FakeGpu3(may=lambda g: next(answers))
    ex = make_exec()
    _gpu3_runner(fake, ex).once(sample_s=0)
    assert [c[0] for c in ex.calls] == ["i1.png"]
    d = json.loads((G.QUEUE / "i.json").read_text(encoding="utf-8"))     # 放回队列，进度保留
    assert d["_gpu_grab"]["results"]["0"]["status"] == "ok" and "1" not in d["_gpu_grab"]["results"]
    assert fake.locks == {}


def test_gpu3_may_use_refused_never_locks(env):
    put(env, "j.json", [job(file="j.png")], targets=["gpu3:1"])
    fake = FakeGpu3(may=False)
    ex = make_exec()
    _gpu3_runner(fake, ex).once(sample_s=0)
    assert ex.calls == [] and not any(e[0] == "lock" for e in fake.events)
    assert (G.QUEUE / "j.json").exists()


def test_gpu3_lock_race_lost(env):
    put(env, "k.json", [job(file="k.png")], targets=["gpu3:1"])
    fake = FakeGpu3(acquire=False)
    ex = make_exec()
    _gpu3_runner(fake, ex).once(sample_s=0)
    assert ex.calls == [] and (G.QUEUE / "k.json").exists()


def test_gpu3_busy_card_not_grabbed(env):
    put(env, "l.json", [job(file="l.png")])
    fake = FakeGpu3(smi={0: (19000, 90), 1: (17000, 100), 2: (0, 0), 3: (16000, 100)})
    ex = make_exec()
    _gpu3_runner(fake, ex).once(sample_s=0)
    assert ex.calls == [] and fake.events == []


def test_gpu3_foreign_lock_file_blocks(env):
    put(env, "m.json", [job(file="m.png")], targets=["gpu3:1"])
    fake = FakeGpu3(files={"gpu.lock.gpu1": "pid:17209 wardrobe-gen"})
    ex = make_exec()
    _gpu3_runner(fake, ex).once(sample_s=0)
    assert ex.calls == [] and fake.events == []


def test_timeout_requeues_then_fails(env):
    put(env, "n.json", [job(file="n.png")], targets=["gpu3:1"])
    fake = FakeGpu3()
    ex = make_exec(timeout_files={"n.png"})
    r = _gpu3_runner(fake, ex)
    r.once(sample_s=0)
    assert (G.QUEUE / "n.json").exists() and fake.locks == {}
    r.once(sample_s=0)
    d = json.loads((G.FAILED / "n.json").read_text(encoding="utf-8"))
    assert d["_gpu_grab"]["results"]["0"]["timeouts"] == G.MAX_TIMEOUTS


def test_lock_released_even_if_executor_crashes(env):
    put(env, "o.json", [job(file="o.png")], targets=["gpu3:1"])
    fake = FakeGpu3()

    def boom(*a):
        raise KeyboardInterrupt  # 最坏情况：线程里抛出非 Exception
    r = _gpu3_runner(fake, boom)
    with pytest.raises(KeyboardInterrupt):
        r._run_gpu3(G.Claimed(G.QUEUE / "o.json", {}, {}, [job(file="o.png")]), 0, job(file="o.png"), "o:o.png", 1)
    assert fake.locks == {}


def test_recover_moves_running_back(env):
    G.RUNNING.mkdir(parents=True, exist_ok=True)
    (G.RUNNING / "p.json").write_text(json.dumps({"jobs": [job()]}), encoding="utf-8")
    G.Runner(gpu3=None, laptop=FakeLaptop(free=False), execute=make_exec(), use_gpu3=False, ownership=OWN).once(sample_s=0)
    assert (G.QUEUE / "p.json").exists()


def test_acquire_never_writes_lock_outside_state_dir(tmp_path, monkeypatch):
    """回归：状态目录不存在（或 cd 失败）时不能把锁写进当前目录。"""
    import shutil
    import subprocess
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash")
    monkeypatch.setattr(G, "STATE_DIR", "/nonexistent/NS-Studio-test")

    class Local(G.Gpu3):
        def _ssh(self, cmd, timeout=60, inp=None):
            return subprocess.run([bash, "-c", cmd], capture_output=True, text=True, cwd=tmp_path)
    assert Local().acquire(1, "fredw-d9 t:x.png") is False
    assert not list(tmp_path.rglob("gpu.lock.*"))


# ---------------------------------------------------------------- G2 edit 任务 / 场景底板任务
def _g2_job(ref_rel, sha=None, **kw):
    j = job(mode="edit", refs=[ref_rel], file="c_CM_s0.png", out_dir="assets/characters/c/candidates/",
            lora=[["Qwen2.1_Anything2RealCharacters.safetensors", 0.45], ["krea2_film_texture_qwen21.safetensors", 0.4]],
            refine={"scale": 1.5, "steps": 12, "denoise": 0.3}, project="weita", character="c", tier="CM",
            reference={"path": ref_rel, "sha256": sha, "ai_generated_fictional_adult": True})
    j.update(kw)
    return j


def _ref(env):
    from PIL import Image
    p = env / "projects" / "p" / "refs" / "c.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 96), (120, 120, 120)).save(p)
    return "projects/p/refs/c.png", G._sha(p)


def test_g2_edit_job_accepted(env):
    rel, sha = _ref(env)
    meta = {"kind": "g2_master_candidates", "project": "weita", "character": "c"}
    assert G.refuse_reason(meta, _g2_job(rel, sha), OWN) is None


def test_g2_edit_job_ref_problems_refused(env):
    rel, sha = _ref(env)
    assert "sha256 mismatch" in G.refuse_reason({}, _g2_job(rel, "0" * 64), OWN)
    assert "reference missing" in G.refuse_reason({}, _g2_job("projects/p/refs/none.png"), OWN)
    assert "needs refs" in G.refuse_reason({}, _g2_job(rel, sha, refs=[]), OWN)
    assert "mode" in G.refuse_reason({}, _g2_job(rel, sha, mode="i2v"), OWN)


def test_g2_edit_graph_uses_reference_in_both_passes():
    j = _g2_job("x.png")
    wf, refine = G.build_graphs(j, "p", ["ns_final/gpu_grab/ref.png"])
    assert wf["101"]["inputs"]["image"] == "ns_final/gpu_grab/ref.png"
    assert wf["20"]["inputs"]["images.image_1"] == ["101", 0] and wf["20"]["inputs"]["prompt"] == j["prompt"]
    assert "102" not in wf                                         # crop=False（预缩放参考图原样送入）
    wf2 = refine("first.png")
    assert wf2["101"]["inputs"]["image"] == "ns_final/gpu_grab/ref.png"
    assert wf2["40"]["inputs"]["latent_image"] == ["203", 0] and "34" not in wf2
    assert (wf2["202"]["inputs"]["width"], wf2["202"]["inputs"]["height"]) == (1536, 2304)
    assert wf2["37"]["inputs"]["denoise"] == 0.3 and wf2["37"]["inputs"]["steps"] == 12
    with pytest.raises(ValueError):
        G.build_graphs(j, "p", [])


def _plate_job(**kw):
    j = job(kind="scene_plate", mode="t2i", size=[928, 1632], file="plate_raw.png", out_dir="assets/scenes/sk_x/",
            refine={"upscale_to": [1152, 2016], "upscale_method": "lanczos", "scale": 1.2353, "steps": 12, "denoise": 0.3},
            scene_id="sk_x", stem="plate", light={"time": "night"},
            post={"center_crop": [768, 1344], "final": "plate.png", "where": "laptop: tools/gen_scenes.py finalize (CPU)"},
            prompt="电影场景空镜底板（空场，画面中没有任何人物）：客厅，夜晚")
    j.update(kw)
    return j


def test_scene_plate_job_accepted_and_upscale_to_used():
    assert G.refuse_reason({"kind": "scene_plates"}, _plate_job(), OWN) is None
    assert "upscale_to" in G.refuse_reason({}, _plate_job(refine={"upscale_to": [10, 10]}), OWN)
    assert "upscale_method" in G.refuse_reason({}, _plate_job(refine={"upscale_to": [1152, 2016],
                                                                       "upscale_method": "magic"}), OWN)
    wf, refine = G.build_graphs(_plate_job(), "p")
    assert (wf["34"]["inputs"]["width"], wf["34"]["inputs"]["height"]) == (928, 1632)
    wf2 = refine("first.png")
    s = wf2["202"]["inputs"]
    assert (s["width"], s["height"], s["upscale_method"]) == (1152, 2016, "lanczos")
    assert G.clamp_side(_plate_job()) is None            # 底板原尺寸交给 finalize 裁切
    assert G.clamp_side(job()) == 1536 and G.clamp_side(job(max_side=1024)) == 1024


def test_real_gen_scenes_jobs_accepted():
    try:
        sys.path.insert(0, str(Path(G.__file__).parent))
        import gen_scenes
        head, jobs = gen_scenes.scene_jobs(gen_scenes.ROOT, draft=True)
    except BaseException as e:  # noqa: BLE001 — 没有 scenes.json 等
        pytest.skip(f"gen_scenes unavailable: {e}")
    assert jobs and all(G.refuse_reason(head, j, OWN) is None for j in jobs[:20])


def test_dict_manifest_preserved_for_scene_plates(env):
    d = env / "assets" / "scenes" / "sk_x"
    d.mkdir(parents=True)
    orig = {"plate": "plate.png", "scene_id": "sk_x", "queued": {"plate": {"seed": 1, "post": {"final": "plate.png"}}},
            "variants": {}, "owner_confirmed_at": None}
    (d / "manifest.json").write_text(json.dumps(orig), encoding="utf-8")
    G.write_manifest(d, {"file": "plate_raw.png", "seed": 1, "prompt": "p"})
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert man["queued"] == orig["queued"] and man["plate"] == "plate.png" and "owner_confirmed_at" in man
    assert man["renders"]["plate_raw.png"]["seed"] == 1
    (d / "plate_raw.png").write_bytes(b"x")
    assert G.manifest_has({"out_dir": "assets/scenes/sk_x/", "file": "plate_raw.png", "seed": 1, "prompt": "p"})


def test_list_manifest_replace_and_corrupt_not_clobbered(env):
    d = env / "assets" / "c"
    d.mkdir(parents=True)
    G.write_manifest(d, {"file": "a.png", "seed": 1})
    G.write_manifest(d, {"file": "b.png", "seed": 2})
    G.write_manifest(d, {"file": "a.png", "seed": 3})
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert [(e["file"], e["seed"]) for e in man] == [("b.png", 2), ("a.png", 3)]
    (d / "manifest.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError):
        G.write_manifest(d, {"file": "c.png"})
    assert (d / "manifest.json").read_text(encoding="utf-8") == "{broken"
